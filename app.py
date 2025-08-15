from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import re
import time
import threading
import webbrowser
from moviepy.editor import AudioFileClip
import glob
import sys
import tempfile
import ffmpeg


def resource_path(relative_path):
    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
    return os.path.join(base_path, relative_path)

def open_browser():
    webbrowser.open_new("http://localhost:5000")

app = Flask(
    __name__,
    template_folder=resource_path('templates'),
    static_folder=resource_path('static')
)

progress_data = {'percent': '0%'}
status_data = {'step': 'En attente...'}
last_ping = time.time()
temp_audio_path = None  # fichier temporaire

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

    mode = request.form['mode']
    start = request.form['start']
    end = request.form['end']

    # Liste des extensions autorisées
    ALLOWED_EXTENSIONS = {'mp3', 'wav', 'm4a', 'aac', 'mp4', 'avi', 'mkv'}

    def allowed_file(filename):
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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

    start_time = parse_time(start)
    end_time = parse_time(end)

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            if mode == 'youtube':
                url = request.form['url']
                # Chemin de sortie temporaire pour yt-dlp
                audio_output_path = os.path.join(temp_dir, "audio.%(ext)s")
                downloaded_file_path = os.path.join(temp_dir, "audio.mp3")

                status_data['step'] = "Récupération du lien et du timing..."

                ydl_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': audio_output_path,
                    'progress_hooks': [progress_hook],
                    'prefer_ffmpeg': True,
                    'ffmpeg_location': os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ffmpeg', 'bin', 'ffmpeg.exe'),
                    'postprocessor_args': {
                        'ffmpeg': ['-preset', 'ultrafast', '-loglevel', 'info']
                    },
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '128',
                    }]
                }

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    video_title = info.get('title', 'video')
                    # Nettoyer le titre pour le rendre compatible avec les noms de fichiers
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
                    raise Exception("Format de fichier non supporté. Formats acceptés : MP3, WAV, M4A, AAC")
                
                # Obtenir le nom du fichier sans extension
                original_filename = os.path.splitext(audio_file.filename)[0]
                input_file = os.path.join(temp_dir, "uploaded_audio" + os.path.splitext(audio_file.filename)[1])
                audio_file.save(input_file)
                status_data['step'] = "Fichier uploadé avec succès"
                output_filename = f"{original_filename}_{start}-{end}.mp3"

            status_data['step'] = "Découpage de l'extrait... ✂️"
            progress_data['percent'] = '0%'

            try:
                clip = AudioFileClip(input_file)
                clip_duration = clip.duration
                
                # Vérifier si les timings sont valides
                if start_time >= clip_duration or end_time > clip_duration:
                    clip.close()
                    raise ValueError(f"La durée du fichier est de {int(clip_duration//60)}:{int(clip_duration%60):02d}. Veuillez choisir une plage de temps valide.")
                
                clip = clip.subclip(start_time, end_time)
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
                temp_audio_path = temp_file.name
                temp_file.close()

                clip.write_audiofile(temp_audio_path, codec='libmp3lame', verbose=False, logger=None)
                clip.close()
            except ValueError as e:
                if 'clip' in locals():
                    clip.close()
                raise ValueError(str(e))
            except Exception as e:
                if 'clip' in locals():
                    clip.close()
                if "Accessing time" in str(e):
                    raise ValueError(f"La durée du fichier est de {int(clip_duration//60)}:{int(clip_duration%60):02d}. Veuillez choisir une plage de temps valide.")
                raise e

        status_data['step'] = "Terminé ✅"
        progress_data['percent'] = 'done'
        return jsonify({"success": True, "filename": output_filename})

    except Exception as e:
        status_data['step'] = f"Erreur : {str(e)}"
        return jsonify({"success": False, "error": str(e)})
    finally:
        # S'assurer que tous les fichiers sont fermés
        if 'clip' in locals():
            try:
                clip.close()
            except:
                pass

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
        if time.time() - last_ping > 60:  # Augmenté à 60 secondes
            print("Navigateur fermé. Arrêt du serveur...")
            os._exit(0)

if __name__ == '__main__':
    threading.Thread(target=monitor_browser, daemon=True).start()
    threading.Timer(1, open_browser).start()
    app.run(debug=False)
