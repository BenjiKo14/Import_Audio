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
import requests
import json
from urllib.parse import parse_qs, urlparse

# Configuration pour le chemin des ressources
def resource_path(relative_path):
    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
    return os.path.join(base_path, relative_path)

# Détermination du binaire ffmpeg selon l'OS
def get_ffmpeg_cmd():
    if os.name == "nt":
        ffmpeg_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg", "bin")
        os.environ["PATH"] += os.pathsep + ffmpeg_dir
        return os.path.join(ffmpeg_dir, "ffmpeg.exe")
    return "ffmpeg"

FFMPEG_CMD = get_ffmpeg_cmd()

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

def extract_video_id(url):
    """Extrait l'ID de la vidéo depuis l'URL YouTube"""
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'(?:embed\/)([0-9A-Za-z_-]{11})',
        r'(?:watch\?v=)([0-9A-Za-z_-]{11})',
        r'(?:youtu\.be\/)([0-9A-Za-z_-]{11})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def download_with_cobalt_api(video_id, output_dir):
    """Télécharge avec l'API Cobalt (co.wuk.sh)"""
    try:
        api_url = "https://co.wuk.sh/api/json"
        headers = {
            'User-Agent': get_random_user_agent(),
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        }
        
        payload = {
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "vCodec": "mp3",
            "vQuality": "128",
            "aFormat": "mp3",
            "isAudioOnly": True
        }
        
        print("[INFO] Tentative avec Cobalt API...")
        response = requests.post(api_url, json=payload, headers=headers, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'success' and data.get('url'):
                audio_url = data['url']
                return download_file_from_url(audio_url, output_dir, 'audio.mp3')
                
    except Exception as e:
        print(f"[WARN] Cobalt API échouée: {str(e)[:100]}...")
    
    return None

def download_with_invidious_api(video_id, output_dir):
    """Télécharge avec l'API Invidious"""
    invidious_instances = [
        "https://invidious.fdn.fr",
        "https://inv.riverside.rocks",
        "https://invidious.snopyta.org",
        "https://invidious.kavin.rocks",
        "https://vid.puffyan.us"
    ]
    
    for instance in invidious_instances:
        try:
            print(f"[INFO] Tentative avec Invidious: {instance}")
            
            # Obtenir les informations de la vidéo
            api_url = f"{instance}/api/v1/videos/{video_id}"
            headers = {'User-Agent': get_random_user_agent()}
            
            response = requests.get(api_url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                
                # Rechercher le meilleur format audio
                audio_formats = [f for f in data.get('adaptiveFormats', []) if f.get('type', '').startswith('audio/')]
                
                if audio_formats:
                    # Prendre le format avec la meilleure qualité
                    best_audio = max(audio_formats, key=lambda x: x.get('bitrate', 0))
                    audio_url = best_audio['url']
                    
                    return download_file_from_url(audio_url, output_dir, 'audio.mp4')
                    
        except Exception as e:
            print(f"[WARN] Invidious {instance} échoué: {str(e)[:100]}...")
            continue
    
    return None

def download_file_from_url(url, output_dir, filename):
    """Télécharge un fichier depuis une URL"""
    try:
        headers = {
            'User-Agent': get_random_user_agent(),
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }
        
        print(f"[INFO] Téléchargement du fichier audio...")
        
        response = requests.get(url, headers=headers, stream=True, timeout=60)
        response.raise_for_status()
        
        file_path = os.path.join(output_dir, filename)
        
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            print(f"[SUCCESS] Fichier téléchargé: {file_path}")
            return file_path
        
    except Exception as e:
        print(f"[WARN] Téléchargement direct échoué: {str(e)[:100]}...")
    
    return None

def download_with_yt_dlp_fallback(url, output_dir):
    """Méthode de fallback avec yt-dlp (version simplifiée)"""
    try:
        print("[INFO] Tentative avec yt-dlp (fallback)...")
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(output_dir, 'audio.%(ext)s'),
            'progress_hooks': [progress_hook],
            'extract_flat': False,
            'no_warnings': True,
            'extractor_args': {
                'youtube': {
                    'player_client': ['tv_embedded'],
                }
            },
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (SMART-TV; Linux; Tizen 2.4.0) AppleWebKit/538.1',
            },
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # Vérifier si le fichier a été créé
        for f in os.listdir(output_dir):
            if f.startswith('audio.') and os.path.getsize(os.path.join(output_dir, f)) > 0:
                return os.path.join(output_dir, f)
                
    except Exception as e:
        print(f"[WARN] yt-dlp fallback échoué: {str(e)[:100]}...")
    
    return None

def download_youtube_audio(url, output_dir):
    """Télécharge l'audio depuis YouTube en utilisant plusieurs APIs"""
    
    # Extraire l'ID de la vidéo
    video_id = extract_video_id(url)
    if not video_id:
        raise Exception("Impossible d'extraire l'ID de la vidéo depuis l'URL")
    
    print(f"[INFO] ID de la vidéo: {video_id}")
    
    # Essayer différentes méthodes dans l'ordre
    methods = [
        ("Cobalt API", lambda: download_with_cobalt_api(video_id, output_dir)),
        ("Invidious API", lambda: download_with_invidious_api(video_id, output_dir)),
        ("yt-dlp fallback", lambda: download_with_yt_dlp_fallback(url, output_dir)),
    ]
    
    for method_name, method_func in methods:
        try:
            print(f"[INFO] === Essai avec {method_name} ===")
            result = method_func()
            
            if result and os.path.exists(result):
                print(f"[SUCCESS] ✅ {method_name} a réussi!")
                return result
            else:
                print(f"[WARN] ❌ {method_name} n'a pas produit de fichier")
                
        except Exception as e:
            print(f"[WARN] ❌ {method_name} échoué: {str(e)[:100]}...")
        
        # Attendre entre les tentatives
        time.sleep(random.uniform(1, 3))
    
    # Si toutes les méthodes échouent
    raise Exception("Toutes les méthodes de téléchargement ont échoué. Le contenu pourrait être protégé ou temporairement indisponible.")

def cut_audio_ffmpeg(input_path, output_path, start_time, end_time):
    """Découpe l'audio avec ffmpeg"""
    duration = end_time - start_time

    # Commande ffmpeg pour découpage rapide
    cmd = [
        FFMPEG_CMD,
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
            FFMPEG_CMD,
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
