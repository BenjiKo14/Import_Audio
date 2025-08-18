# 🎵 Extracteur Audio (YouTube / Fichier local)

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS-green.svg)](https://github.com/your-username/Import_Audio)
[![License](https://img.shields.io/badge/License-Libre-brightgreen.svg)](LICENSE)

Application Tkinter permettant d'extraire un extrait audio (MP3) à partir :
- d'un lien YouTube (via `yt-dlp`)
- ou d'un fichier local audio/vidéo (mp3, wav, m4a, aac, mp4, avi, mkv)

Compatible **Windows** et **macOS** ✅

---

## 📋 Table des matières

- [⚙️ Prérequis](#️-prérequis)
- [📦 Installation](#-installation)
- [🎬 Installation de FFmpeg](#-installation-de-ffmpeg)
- [🚀 Lancement de l'application](#-lancement-de-lapplication)
- [🖱️ Utilisation](#️-utilisation)
- [❌ Dépannage](#-dépannage)
- [📂 Structure du projet](#-structure-du-projet)
- [📜 Licence](#-licence)

---

## ⚙️ Prérequis

| Composant | Version | Description |
|-----------|---------|-------------|
| **Python** | 3.9+ | Langage de programmation |
| **FFmpeg** | - | Outil de traitement audio/vidéo |
| **yt-dlp** | 2025.1.1+ | Extractor YouTube |

### Fichier `requirements.txt` minimal

```txt
yt-dlp>=2025.1.1
```

---

## 📦 Installation

### 1️⃣ Récupérer le projet

```powershell
# Option 1 : Télécharger le ZIP
# Option 2 : Cloner le repository
git clone https://https://github.com/BenjiKo14/Import_Audio
cd Import_Audio
```

### 2️⃣ Créer un environnement virtuel


<summary><strong>🔹Windows</strong></summary>

```powershell
python -m venv venv
venv\Scripts\activate
```

</details>


<summary><strong>🔹macOS</strong></summary>

```powershell
python3 -m venv venv
source venv/bin/activate
```

</details>

### 3️⃣ Installer les dépendances Python

```powershell
pip install -r requirements.txt
```

---

## 🎬 Installation de FFmpeg

### 🔹 Windows

1. **Télécharger** une build statique depuis [Gyan.dev](https://www.gyan.dev/ffmpeg/builds/)
2. **Extraire** le dossier `ffmpeg` à la racine du projet :

```
projet/
└── ffmpeg/
    └── bin/
        ├── ffmpeg.exe
        └── ffprobe.exe
```

3. **Vérifier** l'installation :

```powershell
.\ffmpeg\bin\ffmpeg.exe -version
```

### 🔹 macOS


<summary><strong>Avec Homebrew (recommandé)</strong></summary>

```powershell
brew install ffmpeg
ffmpeg -version
```

</details>

<details>
<summary><strong>Sans Homebrew</strong></summary>

Télécharger un binaire signé depuis [evermeet.cx](https://evermeet.cx/ffmpeg/)

</details>

> 💡 **Astuce** : L'application détecte automatiquement `./ffmpeg/bin/ffmpeg` si présent. Sinon, indiquer le chemin dans le champ prévu au lancement.

---

## 🚀 Lancement de l'application


<summary><strong>🔹Windows</strong></summary>

```powershell
python version_tkinter.py
```

</details>


<summary><strong>🔹macOS</strong></summary>

```powershell
python3 version_tkinter.py
```

</details>

---

## 🖱️ Utilisation

### Étapes d'utilisation

1. **Configuration** (optionnel) : Renseigner le chemin de **ffmpeg** si non détecté automatiquement
2. **Source** : Choisir entre :
   - **Lien YouTube** → coller l'URL
   - **Fichier local** → parcourir et sélectionner un fichier audio/vidéo
3. **Découpage** : Régler l'**heure / minute / seconde** de **Début** et **Fin** (boutons +/− verticaux)
4. **Extraction** : Cliquer **Extraire** → progression et statut s'affichent
5. **Sauvegarde** : Cliquer **Enregistrer le MP3…** pour choisir l'emplacement et le nom du fichier

### Formats supportés

| Type | Extensions |
|------|------------|
| **Audio** | mp3, wav, m4a, aac |
| **Vidéo** | mp4, avi, mkv |

---

## ❌ Dépannage

### Problèmes courants

<details>
<summary><strong>"ffmpeg introuvable"</strong></summary>

**Solutions :**
- Vérifier que `ffmpeg` est installé et accessible :
  - Windows : `.\ffmpeg\bin\ffmpeg.exe -version`
  - macOS : `ffmpeg -version`
- Placer le binaire dans `./ffmpeg/bin/` ou indiquer le chemin dans l'application

</details>

<details>
<summary><strong>YouTube : formats HLS / avertissements yt-dlp</strong></summary>

**Explication :**
- C'est normal pour certains contenus, `yt-dlp` gère les flux HLS
- Assurez-vous d'avoir une version récente de `yt-dlp`

</details>


<details>
<summary><strong>Tkinter sur macOS</strong></summary>

**Solution :**
- Préférez Python depuis [python.org](https://www.python.org/downloads/) pour éviter les versions incomplètes

</details>

---

## 📂 Structure du projet

```
projet/
├── version_tkinter.py      # Application principale
├── requirements.txt        # Dépendances Python
├── README.md              # Documentation
├── icone.ico              # Icône de l'application
└── ffmpeg/                # Dossier FFmpeg (optionnel)
    └── bin/
        ├── ffmpeg(.exe)   # Binaire FFmpeg
        └── ffprobe(.exe)  # Binaire FFprobe
```

---

## 📜 Licence

**Projet personnel — utilisation libre.**

---

<div align="center">

⭐ **N'hésitez pas à donner une étoile si ce projet vous a été utile !** ⭐

</div>