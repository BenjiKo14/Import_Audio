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

def download_youtube_audio(url, output_path):
    """Télécharge l'audio depuis YouTube avec des techniques anti-détection avancées"""
    
    # Configuration optimisée avec rotation d'IP simulée
    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': output_path,
        'extractaudio': True,
        'audioformat': 'mp3',
        'audioquality': '128K',
        'no_warnings': True,
        'ignoreerrors': True,
        'progress_hooks': [progress_hook],
        
        # Headers anti-détection
        'http_headers': {
            'User-Agent': get_random_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
        },
        
        # Options anti-détection avancées
        'extractor_args': {
            'youtube': {
                'player_client': ['web', 'android', 'ios'],
                'player_skip': ['configs'],
                'skip': ['dash', 'hls'],
                'lang': ['en'],
            }
        },
        
        # Throttling pour simuler comportement humain
        'sleep_interval': random.uniform(0.5, 2.0),
        'max_sleep_interval': 4,
        'sleep_interval_requests': random.uniform(0.5, 1.5),
        
        # Retry avec backoff
        'retries': 3,
        'fragment_retries': 3,
        'retry_sleep_functions': {'extractor': lambda n: 2 ** n},
    }
    
    print(f"[INFO] Tentative de téléchargement avec User-Agent: {ydl_opts['http_headers']['User-Agent'][:50]}...")
    
    try:
        # Première tentative avec configuration standard
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return True
        
    except Exception as e:
        print(f"[WARN] Méthode standard échouée: {str(e)[:100]}...")
        
        # Tentative avec client mobile uniquement
        try:
            ydl_opts['extractor_args']['youtube']['player_client'] = ['android']
            ydl_opts['http_headers']['User-Agent'] = 'com.google.android.youtube/19.30.1 (Linux; U; Android 13)'
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            return True
            
        except Exception as e2:
            print(f"[WARN] Méthode mobile échouée: {str(e2)[:100]}...")
            
            # Dernière tentative avec cookies si disponibles
            try:
                cookies_file = resource_path('cookies.txt')
                if os.path.exists(cookies_file):
                    ydl_opts['cookiefile'] = cookies_file
                    ydl_opts['extractor_args']['youtube']['player_client'] = ['web']
                    ydl_opts['http_headers']['User-Agent'] = get_random_user_agent()
                    
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url])
                    return True
                else:
                    raise Exception("Toutes les méthodes ont échoué")
                    
            except Exception as e3:
                print(f"[ERROR] Toutes les méthodes échouées: {str(e3)[:100]}...")
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
            temp_audio_file = os.path.join(temp_dir, 'audio.%(ext)s')
            
            if not download_youtube_audio(url, temp_audio_file):
                raise Exception("Échec du téléchargement")
            
            # Recherche du fichier téléchargé
            downloaded_files = []
            for ext in ['mp3', 'm4a', 'webm', 'ogg']:
                pattern = os.path.join(temp_dir, f'audio.{ext}')
                found = [f for f in os.listdir(temp_dir) if f.startswith('audio.')]
                if found:
                    downloaded_files.extend([os.path.join(temp_dir, f) for f in found])
            
            if not downloaded_files:
                raise Exception("Fichier audio non trouvé après téléchargement")
            
            input_audio = downloaded_files[0]
            
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
