from flask import Flask, render_template, request, jsonify, send_file
import yt_dlp
import os
import re
import time
import threading
import webbrowser
import sys
import tempfile
import subprocess
import random
from datetime import datetime

# Configuration pour le chemin des ressources
def resource_path(relative_path):
    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
    return os.path.join(base_path, relative_path)

# Configuration ffmpeg local
ffmpeg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg", "bin")
os.environ["PATH"] += os.pathsep + ffmpeg_path

def open_browser():
    webbrowser.open_new("http://localhost:5000")

app = Flask(
    __name__,
    template_folder=resource_path('templates'),
    static_folder=resource_path('static')
)

# Variables globales pour le suivi
progress_data = {'percent': '0%'}
status_data = {'step': 'En attente...'}
temp_audio_path = None

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

def get_random_user_agent():
    """Génère un User-Agent aléatoire pour éviter la détection"""
    agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ]
    return random.choice(agents)

def download_youtube_audio(url, output_dir):
    """Télécharge l'audio depuis YouTube avec des techniques anti-détection avancées"""
    
    # Méthodes alternatives à essayer
    methods = [
        # Méthode 1: Configuration basique sans postprocessors
        {
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'outtmpl': os.path.join(output_dir, 'audio.%(ext)s'),
            'progress_hooks': [progress_hook],
            'extract_flat': False,
            'writethumbnail': False,
            'writeinfojson': False,
            'http_headers': {
                'User-Agent': get_random_user_agent(),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            },
            'extractor_args': {
                'youtube': {
                    'player_client': ['web'],
                    'skip': ['dash', 'hls'],
                }
            },
            'sleep_interval': random.uniform(1, 3),
        },
        
        # Méthode 2: Client mobile iOS
        {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(output_dir, 'audio.%(ext)s'),
            'progress_hooks': [progress_hook],
            'http_headers': {
                'User-Agent': 'com.google.ios.youtube/19.30.1 (iPhone16,2; U; CPU iOS 17_5_1 like Mac OS X;)',
            },
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios'],
                }
            },
            'sleep_interval': random.uniform(1, 2),
        },
        
        # Méthode 3: Client TV embedded
        {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(output_dir, 'audio.%(ext)s'),
            'progress_hooks': [progress_hook],
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (SMART-TV; Linux; Tizen 2.4.0) AppleWebKit/538.1',
            },
            'extractor_args': {
                'youtube': {
                    'player_client': ['tv_embedded'],
                }
            },
            'sleep_interval': 1,
        },
        
        # Méthode 4: Avec cookies
        {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(output_dir, 'audio.%(ext)s'),
            'progress_hooks': [progress_hook],
            'cookiefile': resource_path('cookies.txt') if os.path.exists(resource_path('cookies.txt')) else None,
            'http_headers': {
                'User-Agent': get_random_user_agent(),
            },
            'extractor_args': {
                'youtube': {
                    'player_client': ['web'],
                }
            },
            'sleep_interval': random.uniform(2, 4),
        }
    ]
    
    for i, ydl_opts in enumerate(methods):
        # Supprimer les options None
        ydl_opts = {k: v for k, v in ydl_opts.items() if v is not None}
        
        try:
            print(f"[INFO] Méthode {i+1}/4: {ydl_opts['extractor_args']['youtube']['player_client'][0]}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            # Vérifier si le fichier a été créé
            downloaded_files = []
            for f in os.listdir(output_dir):
                if f.startswith('audio.') and os.path.getsize(os.path.join(output_dir, f)) > 0:
                    downloaded_files.append(os.path.join(output_dir, f))
            
            if downloaded_files:
                print(f"[SUCCESS] Fichier téléchargé: {downloaded_files[0]}")
                return downloaded_files[0]
            
        except Exception as e:
            print(f"[WARN] Méthode {i+1} échouée: {str(e)[:100]}...")
            # Attendre avant d'essayer la méthode suivante
            time.sleep(random.uniform(1, 3))
            continue
    
    # Si toutes les méthodes échouent
    raise Exception("Impossible de télécharger la vidéo. YouTube bloque temporairement les téléchargements.")

def cut_audio_ffmpeg(input_path, output_path, start_time, end_time):
    """Découpe l'audio avec ffmpeg"""
    duration = end_time - start_time
    
    # Chemin vers ffmpeg
    ffmpeg_exe = os.path.join(ffmpeg_path, "ffmpeg.exe") if os.name == 'nt' else "ffmpeg"
    
    # Commande ffmpeg pour découpage rapide
    cmd = [
        ffmpeg_exe,
        '-i', input_path,
        '-ss', str(start_time),
        '-t', str(duration),
        '-c', 'copy',  # Copie sans réencodage pour plus de vitesse
        '-avoid_negative_ts', 'make_zero',
        '-loglevel', 'quiet',
        '-y',
        output_path
    ]
    
    try:
        subprocess.run(cmd, check=True, timeout=30)
        return True
    except subprocess.TimeoutExpired:
        # Fallback avec réencodage si nécessaire
        cmd_fallback = [
            ffmpeg_exe,
            '-i', input_path,
            '-ss', str(start_time),
            '-t', str(duration),
            '-c:a', 'libmp3lame',
            '-b:a', '128k',
            '-loglevel', 'quiet',
            '-y',
            output_path
        ]
        subprocess.run(cmd_fallback, check=True, timeout=45)
        return True

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/progress')
def progress():
    return jsonify(progress_data)

@app.route('/status')
def status():
    return jsonify(status_data)

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
            raise ValueError("Format de temps invalide")
    
    try:
        start_time = parse_time(start)
        end_time = parse_time(end)
        
        if start_time >= end_time:
            raise ValueError("L'heure de début doit être inférieure à l'heure de fin")
        
        # Réinitialisation des variables
        progress_data['percent'] = '0%'
        status_data['step'] = 'Initialisation...'
        
        with tempfile.TemporaryDirectory() as temp_dir:
            # Téléchargement
            status_data['step'] = 'Téléchargement de la vidéo... 📥'
            
            # Télécharger l'audio
            input_audio = download_youtube_audio(url, temp_dir)
            
            if not input_audio or not os.path.exists(input_audio):
                raise Exception("Échec du téléchargement ou fichier non trouvé")
            
            # Découpage
            status_data['step'] = 'Découpage de l\'extrait... ✂️'
            progress_data['percent'] = 'convert'
            
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
            temp_audio_path = temp_file.name
            temp_file.close()
            
            if not cut_audio_ffmpeg(input_audio, temp_audio_path, start_time, end_time):
                raise Exception("Échec du découpage")
            
            # Finalisation
            status_data['step'] = 'Terminé ✅'
            progress_data['percent'] = 'done'
            
            return jsonify({"success": True})
            
    except Exception as e:
        error_msg = str(e)
        status_data['step'] = f'Erreur: {error_msg}'
        progress_data['percent'] = '0%'
        return jsonify({"success": False, "error": error_msg})

@app.route('/download')
def download():
    global temp_audio_path
    
    if temp_audio_path and os.path.exists(temp_audio_path):
        path = temp_audio_path
        temp_audio_path = None
        
        # Suppression différée du fichier
        def delete_file_later(p):
            time.sleep(10)
            try:
                os.remove(p)
            except:
                pass
        
        threading.Thread(target=delete_file_later, args=(path,), daemon=True).start()
        return send_file(path, as_attachment=True, download_name=f"extrait_audio_{int(time.time())}.mp3")
    
    return "Fichier introuvable", 404

if __name__ == '__main__':
    threading.Timer(1, open_browser).start()
    app.run(debug=False, host='0.0.0.0', port=5000)
