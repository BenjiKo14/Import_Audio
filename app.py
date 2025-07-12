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

# Ajouter le chemin vers ffmpeg local au PATH
ffmpeg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg", "bin")
os.environ["PATH"] += os.pathsep + ffmpeg_path


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

@app.route('/extract', methods=['POST'])
def extract():
    global temp_audio_path

    url = request.form['url']
    start = request.form['start']
    end = request.form['end']

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
            # Chemin de sortie temporaire pour yt-dlp
            audio_output_path = os.path.join(temp_dir, "audio.%(ext)s")
            downloaded_file_path = os.path.join(temp_dir, "audio.mp3")

            status_data['step'] = "Récupération du lien et du timing..."

            # Essayer différentes méthodes d'authentification
            browsers_to_try = [
                ('chrome',),
                ('firefox',),
                ('edge',),
                ('safari',),
            ]
            
            downloaded = False
            for browser in browsers_to_try:
                try:
                    ydl_opts = {
                        'format': 'bestaudio/best',
                        'outtmpl': audio_output_path,
                        'progress_hooks': [progress_hook],
                        'prefer_ffmpeg': True,
                        'postprocessor_args': {
                            'ffmpeg': ['-preset', 'ultrafast', '-loglevel', 'info']
                        },
                        'cookiesfrombrowser': browser,
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '128',
                        }]
                    }

                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url])
                    downloaded = True
                    break
                except Exception as e:
                    continue
            
            # Si aucun navigateur ne fonctionne, essayer avec le fichier cookies.txt
            if not downloaded:
                try:
                    ydl_opts = {
                        'format': 'bestaudio/best',
                        'outtmpl': audio_output_path,
                        'progress_hooks': [progress_hook],
                        'prefer_ffmpeg': True,
                        'postprocessor_args': {
                            'ffmpeg': ['-preset', 'ultrafast', '-loglevel', 'info']
                        },
                        'cookiefile': resource_path('cookies.txt'),
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '128',
                        }]
                    }

                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url])
                except Exception as e:
                    # En dernier recours, essayer sans cookies
                    ydl_opts = {
                        'format': 'bestaudio/best',
                        'outtmpl': audio_output_path,
                        'progress_hooks': [progress_hook],
                        'prefer_ffmpeg': True,
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
                        ydl.download([url])

            if not os.path.exists(downloaded_file_path):
                raise Exception("Fichier MP3 non trouvé après le téléchargement.")

            status_data['step'] = "Découpage de l'extrait... ✂️"
            progress_data['percent'] = '0%'

            clip = AudioFileClip(downloaded_file_path).subclip(start_time, end_time)

            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            temp_audio_path = temp_file.name
            temp_file.close()

            clip.write_audiofile(temp_audio_path, codec='libmp3lame', verbose=False, logger=None)
            clip.close()

        status_data['step'] = "Terminé ✅"
        progress_data['percent'] = 'done'
        return jsonify({"success": True})

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
        return send_file(path, as_attachment=True, download_name="extrait_audio.mp3")

    return "Fichier introuvable", 404

def monitor_browser():
    global last_ping
    while True:
        time.sleep(5)
        if time.time() - last_ping > 10:
            print("Navigateur fermé. Arrêt du serveur...")
            os._exit(0)

if __name__ == '__main__':
    threading.Thread(target=monitor_browser, daemon=True).start()
    threading.Timer(1, open_browser).start()
    app.run(debug=False)
