from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import re
import time
import threading
import webbrowser
import glob
import sys
import tempfile
import subprocess
import json

# ---- Utilitaires de chemin (PyInstaller-friendly) ----
def resource_path(relative_path):
    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
    return os.path.join(base_path, relative_path)

def open_browser():
    webbrowser.open_new("http://localhost:5005")

# ---- Initialisation Flask ----
app = Flask(
    __name__,
    template_folder=resource_path('templates'),
    static_folder=resource_path('static')
)

progress_data = {'percent': '0%'}
status_data   = {'step': 'En attente...'}
last_ping     = time.time()
temp_audio_path = None  # fichier temporaire

# ---- Chemins ffmpeg/ffprobe (packagés localement) ----
FFMPEG_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ffmpeg', 'bin')
FFMPEG_PATH  = os.path.join(FFMPEG_DIR, 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
FFPROBE_PATH = os.path.join(FFMPEG_DIR, 'ffprobe.exe' if os.name == 'nt' else 'ffprobe')

def clean_ansi(text):
    return re.sub(r'\x1b\[[0-9;]*m', '', text)

def progress_hook(d):
    if d['status'] == 'downloading':
        raw = d.get('_percent_str', '0.0%')
        progress_data['percent'] = clean_ansi(raw).strip()
        status_data['step'] = "Téléchargement en cours... 📥"
    elif d['status'] == 'finished':
        progress_data['percent'] = 'convert'
        status_data['step'] = "Conversion audio en cours... 🎧"

# ---- Helpers temps/validation ----
def parse_time(t):
    parts = list(map(int, t.strip().split(":")))
    if len(parts) == 1:
        return parts[0]
    elif len(parts) == 2:
        return parts[0] * 60 + parts[1]
    elif len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    else:
        raise ValueError("Format de temps invalide (hh:mm:ss, mm:ss ou ss)")

def probe_duration(input_file):
    """Retourne la durée (float, secondes) via ffprobe."""
    try:
        cmd = [
            FFPROBE_PATH,
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            input_file
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        info = json.loads(result.stdout)
        # priorité au format.duration, fallback stream[0].duration
        if 'format' in info and 'duration' in info['format']:
            return float(info['format']['duration'])
        for s in info.get('streams', []):
            if 'duration' in s:
                return float(s['duration'])
        raise ValueError("Durée introuvable")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffprobe a échoué: {e.stderr or e.stdout}")

def ffmpeg_cut_to_mp3(input_file, start_time, end_time, output_path):
    """Coupe l'audio entre start_time et end_time (en secondes) vers MP3."""
    # -ss avant -i pour seek rapide; -to est relatif au début
    cmd = [
        FFMPEG_PATH,
        "-v", "error",
        "-ss", str(start_time),
        "-to", str(end_time),
        "-i", input_file,
        "-vn",
        "-acodec", "libmp3lame",
        "-b:a", "128k",
        "-y",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError(f"ffmpeg a échoué: {result.stderr or result.stdout}")

# ---- Routes ----
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/progress')
def progress():
    return jsonify(progress_data)

@app.route('/status')
def status():
    return jsonify(status_data)

@app.route('/ping', methods=['POST'])
def ping():
    global last_ping
    last_ping = time.time()
    return '', 204

@app.route('/download-start', methods=['POST'])
def download_start():
    global last_ping
    last_ping = time.time()  # Reset le timer quand le téléchargement commence
    return '', 204

@app.route('/extract', methods=['POST'])
def extract():
    global temp_audio_path

    mode  = request.form['mode']
    start = request.form['start']
    end   = request.form['end']

    ALLOWED_EXTENSIONS = {'mp3', 'wav', 'm4a', 'aac', 'mp4', 'avi', 'mkv'}

    def allowed_file(filename):
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

    start_time = parse_time(start)
    end_time   = parse_time(end)

    if end_time <= start_time:
        return jsonify({"success": False, "error": "L'heure de fin doit être supérieure à l'heure de début."})

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            if mode == 'youtube':
                url = request.form['url']
                audio_output_path    = os.path.join(temp_dir, "audio.%(ext)s")
                downloaded_file_path = os.path.join(temp_dir, "audio.mp3")

                status_data['step'] = "Récupération du lien et du timing..."

                # Options yt-dlp durcies pour contourner SABR/Signature (client Android) + cookies
                cookies_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': audio_output_path,
                    'progress_hooks': [progress_hook],
                    'prefer_ffmpeg': True,
                    'ffmpeg_location': FFMPEG_DIR,
                    'noplaylist': True,
                    'extractor_args': {
                        'youtube': {
                            'player_client': ['android']
                        }
                    },
                    'postprocessor_args': {
                        'ffmpeg': ['-preset', 'ultrafast', '-loglevel', 'info']
                    },
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '128',
                    }]
                }
                if os.path.exists(cookies_path):
                    ydl_opts['cookiefile'] = cookies_path

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    video_title = info.get('title', 'video')
                    video_title = "".join(c for c in video_title if c.isalnum() or c in (' ', '-', '_')).strip()
                    ydl.download([url])

                if not os.path.exists(downloaded_file_path):
                    raise Exception("Fichier MP3 non trouvé après le téléchargement.")
                
                input_file = downloaded_file_path
                output_filename = f"{video_title}_{start}-{end}.mp3"
            else:
                if 'audio-file' not in request.files:
                    raise Exception("Aucun fichier n'a été uploadé")
                
                audio_file = request.files['audio-file']
                if audio_file.filename == '':
                    raise Exception("Aucun fichier sélectionné")
                
                if not allowed_file(audio_file.filename):
                    raise Exception("Format de fichier non supporté. Formats acceptés : MP3, WAV, M4A, AAC, MP4, AVI, MKV")
                
                original_filename = os.path.splitext(audio_file.filename)[0]
                ext = os.path.splitext(audio_file.filename)[1]
                input_file = os.path.join(temp_dir, "uploaded_audio" + ext)
                audio_file.save(input_file)
                status_data['step'] = "Fichier uploadé avec succès"
                output_filename = f"{original_filename}_{start}-{end}.mp3"

            # Validation durée via ffprobe
            status_data['step'] = "Analyse du média... 🔎"
            clip_duration = probe_duration(input_file)

            if start_time >= clip_duration or end_time > clip_duration:
                raise ValueError(
                    f"La durée du fichier est de {int(clip_duration//60)}:{int(clip_duration%60):02d}. "
                    "Veuillez choisir une plage de temps valide."
                )

            # Découpage via ffmpeg
            status_data['step'] = "Découpage de l'extrait... ✂️"
            progress_data['percent'] = '0%'

            # Créer un fichier temporaire invisible côté utilisateur
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            temp_audio_path = temp_file.name
            temp_file.close()

            ffmpeg_cut_to_mp3(input_file, start_time, end_time, temp_audio_path)

        status_data['step'] = "Terminé ✅"
        progress_data['percent'] = 'done'
        return jsonify({"success": True, "filename": output_filename})

    except Exception as e:
        status_data['step'] = f"Erreur : {str(e)}"
        return jsonify({"success": False, "error": str(e)})

@app.route('/download')
def download():
    global temp_audio_path

    if temp_audio_path and os.path.exists(temp_audio_path):
        path = temp_audio_path
        temp_audio_path = None  # Reset avant suppression

        def delete_file_later(p):
            time.sleep(5)
            try:
                os.remove(p)
            except Exception:
                pass

        threading.Thread(target=delete_file_later, args=(path,), daemon=True).start()
        return send_file(path, as_attachment=True, download_name=request.args.get('filename', 'extrait_audio.mp3'))

    return "Fichier introuvable", 404

def monitor_browser():
    global last_ping
    while True:
        time.sleep(5)
        if time.time() - last_ping > 60:
            print("Navigateur fermé. Arrêt du serveur...")
            os._exit(0)

if __name__ == '__main__':
    threading.Thread(target=monitor_browser, daemon=True).start()
    threading.Timer(1, open_browser).start()
    app.run(debug=False)
