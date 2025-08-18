import os
import re
import sys
import tempfile
import threading
import queue
import shutil
import subprocess
import signal
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import yt_dlp
import platform

# ------------------------------
# Utilitaires
# ------------------------------

ALLOWED_EXTENSIONS = {'mp3', 'wav', 'm4a', 'aac', 'mp4', 'avi', 'mkv'}

def clean_ansi(text):
    import re as _re
    return _re.sub(r'\x1b\[[0-9;]*m', '', text)

def parse_time_to_seconds(t):
    """
    Accepte 'hh:mm:ss', 'mm:ss' ou 'ss' -> secondes (int)
    """
    t = t.strip()
    if not t:
        return 0
    parts = t.split(':')
    try:
        parts = list(map(int, parts))
    except ValueError:
        raise ValueError("Format de temps invalide (hh:mm:ss, mm:ss ou ss).")

    if len(parts) == 1:
        return parts[0]
    elif len(parts) == 2:
        m, s = parts
        if not (0 <= s < 60):
            raise ValueError("Secondes doivent être entre 0 et 59.")
        return m * 60 + s
    elif len(parts) == 3:
        h, m, s = parts
        if not (0 <= m < 60 and 0 <= s < 60):
            raise ValueError("Minutes/secondes doivent être entre 0 et 59.")
        return h * 3600 + m * 60 + s
    else:
        raise ValueError("Format de temps invalide (hh:mm:ss, mm:ss ou ss).")
    
def safe_filename(name, maxlen=120):
    """
    Supprime/ remplace les caractères interdits sous Windows et nettoie la fin.
    """
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', '_', name)  # chars interdits
    name = re.sub(r'\s+', ' ', name).strip()            # espaces multiples
    name = name.rstrip('. ')                            # pas de '.' ou espace final
    return name[:maxlen]


def seconds_to_hhmmss(sec):
    sec = int(sec)
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h}:{m:02d}:{s:02d}"

def has_allowed_extension(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def ffmpeg_default_paths():
    """
    Retourne (ffmpeg_dir, ffmpeg_exe, ffprobe_exe).
    Priorité :
      1) ./ffmpeg/bin/{ffmpeg, ffprobe}
      2) ffmpeg trouvé via PATH (shutil.which)
    """
    import shutil

    base = os.path.abspath(os.path.join(os.getcwd(), "ffmpeg", "bin"))
    is_win = os.name == "nt"
    ff = os.path.join(base, "ffmpeg.exe" if is_win else "ffmpeg")
    fp = os.path.join(base, "ffprobe.exe" if is_win else "ffprobe")

    if os.path.isfile(ff) and os.path.isfile(fp):
        return base, ff, fp

    # sinon, essaie via PATH
    ff_which = shutil.which("ffmpeg")
    fp_which = shutil.which("ffprobe")
    if ff_which and fp_which:
        return os.path.dirname(ff_which), ff_which, fp_which

    # rien trouvé
    return None, None, None

class BigSpinner(ttk.Frame):
    """
    Champ numérique avec gros boutons +/− empilés verticalement (par défaut)
    ou placés horizontalement. get()/set(int) pour lire/écrire la valeur.
    """
    def __init__(self, master, minval=0, maxval=59, step=1, width=3,
                 font=("Segoe UI", 12), initial=0, arrows="vertical", **kwargs):
        super().__init__(master, **kwargs)
        self.minval, self.maxval, self.step = int(minval), int(maxval), int(step)
        self._repeat_job = None

        self.var = tk.StringVar(value=str(int(initial)))
        self.entry = ttk.Entry(self, textvariable=self.var, width=width, justify="center")
        try:
            self.entry.configure(font=font)  # ttk accepte 'font' sur la plupart des themes
        except tk.TclError:
            pass

        self.btn_up = ttk.Button(self, text="▲", width=2)
        self.btn_dn = ttk.Button(self, text="▼", width=2)

        # ---- Layout
        if arrows == "vertical":
            # Empile: + (row=0) / Entry (row=1) / - (row=2)
            self.btn_up.grid(row=0, column=0, pady=(0, 2))
            self.entry.grid(row=1, column=0)
            self.btn_dn.grid(row=2, column=0, pady=(2, 0))
        else:
            # Aligne: - [Entry] +
            self.btn_dn.grid(row=0, column=0, padx=(0, 2))
            self.entry.grid(row=0, column=1)
            self.btn_up.grid(row=0, column=2, padx=(2, 0))

        # ---- Actions
        self.btn_up.configure(command=self.inc_once)
        self.btn_dn.configure(command=self.dec_once)

        # Auto-repeat au maintien
        for btn, fn in [(self.btn_up, self.inc_once), (self.btn_dn, self.dec_once)]:
            btn.bind("<ButtonPress-1>", lambda e, f=fn: self._start_repeat(f))
            btn.bind("<ButtonRelease-1>", lambda e: self._stop_repeat())

        # Molette souris
        self.entry.bind("<MouseWheel>", self._on_wheel)     # Windows / macOS
        self.entry.bind("<Button-4>", self._on_wheel_linux) # Linux up
        self.entry.bind("<Button-5>", self._on_wheel_linux) # Linux down

        # Validation
        vcmd = (self.register(self._validate), "%P")
        self.entry.configure(validate="key", validatecommand=vcmd)

    # ----- API
    def get(self):
        s = (self.var.get() or "0").strip()
        try:
            return max(self.minval, min(self.maxval, int(s)))
        except ValueError:
            return self.minval

    def set(self, val: int):
        self.var.set(str(max(self.minval, min(self.maxval, int(val)))))

    # ----- Internes
    def _validate(self, newval):
        if newval == "":
            return True
        if not newval.isdigit():
            return False
        v = int(newval)
        return self.minval <= v <= self.maxval

    def inc_once(self):
        self.set(self.get() + self.step)

    def dec_once(self):
        self.set(self.get() - self.step)

    def _start_repeat(self, fn):
        self._stop_repeat()
        self._repeat_job = self.after(350, self._repeat, fn, 90)

    def _repeat(self, fn, delay):
        fn()
        self._repeat_job = self.after(delay, self._repeat, fn, delay)

    def _stop_repeat(self):
        if self._repeat_job:
            self.after_cancel(self._repeat_job)
            self._repeat_job = None

    def _on_wheel(self, event):
        if event.delta > 0:
            self.inc_once()
        else:
            self.dec_once()
        return "break"

    def _on_wheel_linux(self, event):
        if event.num == 4:
            self.inc_once()
        elif event.num == 5:
            self.dec_once()
        return "break"


# ------------------------------
# Worker (thread) pour le traitement
# ------------------------------

class ExtractWorker(threading.Thread):
    """
    Workflow:
      - YouTube (yt-dlp) -> récup MP3
      - OU fichier local -> utilise tel quel
      - ffmpeg (subprocess) -> découpe (-ss / -to) vers MP3
    Annulation:
      - Pendant téléchargement : exception dans progress_hook
      - Pendant découpe : kill du process ffmpeg
    """
    def __init__(self, mode, url, local_file, start_str, end_str, event_queue, ffmpeg_dir=None):
        super().__init__(daemon=True)
        self.mode = mode
        self.url = url
        self.local_file = local_file
        self.start_str = start_str
        self.end_str = end_str
        self.event_queue = event_queue
        self.ffmpeg_dir = ffmpeg_dir  # dossier contenant ffmpeg/ffprobe si dispo
        self.temp_out_path = None
        self.output_filename = None
        self._stopped = False
        self._ff_proc = None
        self._tmp_workdir = None
        self._downloaded_input = None

    def stop(self):
        self._stopped = True
        # Stopper ffmpeg en cours
        if self._ff_proc and self._ff_proc.poll() is None:
            try:
                if os.name == 'nt':
                    self._ff_proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    self._ff_proc.terminate()
            except Exception:
                pass

    def _emit(self, type_, **payload):
        self.event_queue.put({"type": type_, **payload})

    def yt_progress_hook(self, d):
        if self._stopped:
            # lever une erreur pour stopper yt-dlp
            raise yt_dlp.utils.DownloadError("Annulé par l'utilisateur")
        if d['status'] == 'downloading':
            raw = d.get('_percent_str', '0.0%')
            percent = clean_ansi(raw).strip()
            self._emit("progress", percent=percent, phase="Téléchargement en cours... 📥")
        elif d['status'] == 'finished':
            self._emit("progress", percent="convert", phase="Conversion audio en cours... 🎧")
    def _run_ffmpeg_cut(self, input_path, start_sec, end_sec, out_path):
        # Utilise le binaire résolu si connu, sinon 'ffmpeg' (PATH)
        ff_bin = self.ffmpeg_exe if self.ffmpeg_exe else "ffmpeg"

        cmd = [
            ff_bin,
            "-y",
            "-hide_banner",
            "-loglevel", "error",
            "-ss", str(start_sec),
            "-to", str(end_sec),
            "-i", input_path,
            "-vn",
            "-acodec", "libmp3lame",
            out_path
        ]

        env = os.environ.copy()
        # s'assure que le dossier contenant ffmpeg est en tête du PATH
        if self.ffmpeg_dir:
            env["PATH"] = self.ffmpeg_dir + os.pathsep + env.get("PATH", "")

        creationflags = 0
        if os.name == "nt":
            # pour permettre CTRL_BREAK_EVENT sur Windows
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        self._ff_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            creationflags=creationflags
        )
        _, err = self._ff_proc.communicate()
        code = self._ff_proc.returncode
        self._ff_proc = None

        if self._stopped:
            raise RuntimeError("Annulé")
        if code != 0:
            raise RuntimeError(err.decode("utf-8", errors="ignore") or "Echec ffmpeg")


    def run(self):
        try:
            # Prépare temps
            start_time = parse_time_to_seconds(self.start_str)
            end_time = parse_time_to_seconds(self.end_str)
            if end_time <= start_time:
                raise ValueError("Le temps de fin doit être supérieur au temps de début.")

            # FFmpeg par défaut : ./ffmpeg/bin si dispo
            ffdir, ffexe, fprobe = ffmpeg_default_paths()
            if ffdir:
                self.ffmpeg_dir = ffdir  # preferred
            # Sinon, on laisse PATH

            # Dossier temporaire de travail
            with tempfile.TemporaryDirectory() as temp_dir:
                self._tmp_workdir = temp_dir
                input_path = None
                video_title = "audio"

                if self._stopped:
                    raise RuntimeError("Annulé")

                if self.mode == "youtube":
                    if not self.url:
                        raise ValueError("Veuillez saisir une URL YouTube.")
                    self._emit("status", text="Récupération du lien et du timing...")

                    audio_output_path = os.path.join(temp_dir, "audio.%(ext)s")
                    downloaded_file_path_mp3 = os.path.join(temp_dir, "audio.mp3")

                    ydl_opts = {
                        'format': 'bestaudio/best',
                        'outtmpl': audio_output_path,
                        'progress_hooks': [self.yt_progress_hook],
                        'prefer_ffmpeg': True,
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '128',
                        }],
                    }
                    # Si on a ./ffmpeg/bin, le fournir à yt-dlp
                    if self.ffmpeg_dir:
                        ydl_opts['ffmpeg_location'] = self.ffmpeg_dir

                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(self.url, download=False)
                        title = info.get('title', 'video')
                        video_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
                        ydl.download([self.url])

                    if not os.path.exists(downloaded_file_path_mp3):
                        raise RuntimeError("Fichier MP3 non trouvé après le téléchargement.")

                    input_path = downloaded_file_path_mp3
                    self._downloaded_input = input_path
                else:
                    # Fichier local
                    if not self.local_file:
                        raise ValueError("Veuillez sélectionner un fichier.")
                    if not os.path.exists(self.local_file):
                        raise ValueError("Fichier introuvable.")
                    if not has_allowed_extension(self.local_file):
                        raise ValueError("Format non supporté. Acceptés : MP3, WAV, M4A, AAC, MP4, AVI, MKV.")

                    self._emit("status", text="Fichier chargé avec succès.")
                    input_path = self.local_file
                    base = os.path.splitext(os.path.basename(self.local_file))[0]
                    video_title = "".join(c for c in base if c.isalnum() or c in (' ', '-', '_')).strip()

                if self._stopped:
                    raise RuntimeError("Annulé")

                # Découpage
                self._emit("progress", percent="cut", phase="Découpage de l'extrait... ✂️")

                # Fichier temporaire de sortie
                temp_fd, temp_path = tempfile.mkstemp(suffix=".mp3")
                os.close(temp_fd)
                self.temp_out_path = temp_path
                start_safe = self.start_str.replace(":", "-")
                end_safe   = self.end_str.replace(":", "-")
                title_safe = safe_filename(video_title)
                self.output_filename = safe_filename(f"{title_safe}_{start_safe}-to-{end_safe}.mp3")



                # Lancer ffmpeg
                self._run_ffmpeg_cut(
                    input_path=input_path,
                    start_sec=start_time,
                    end_sec=end_time,
                    out_path=self.temp_out_path
                )

            # Terminé
            self._emit("done", temp_path=self.temp_out_path, suggested_name=self.output_filename)
            self._emit("status", text="Terminé ✅")

        except yt_dlp.utils.DownloadError as e:
            # Annulation propre pendant le download
            msg = str(e)
            if "Annulé" in msg:
                self._emit("error", message="Annulé")
            else:
                self._emit("error", message=msg or "Erreur yt-dlp")
        except Exception as e:
            self._emit("error", message=str(e))

# ------------------------------
# UI Tkinter
# ------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Extraction Audio (YouTube / Fichier)")
        # Fenêtre plus grande + redimensionnable
        self.geometry("900x700")
        self.minsize(820, 700)
        self.resizable(True, True)


        self.event_queue = queue.Queue()
        self.worker = None
        self.temp_result_path = None  # pour supprimer si nécessaire

        # --- Détection OS pour polices ---
        if platform.system() == "Darwin":  # macOS
            self.big_font = ("Arial", 12)
        else:  # Windows/Linux
            self.big_font = ("Segoe UI", 12)

        self._build_ui()
        self._poll_events()

    def _browse_ffmpeg(self):
        # Adapte le filtre de fichier en fonction de l'OS
        if platform.system() == "Windows":
            filetypes = [("ffmpeg", "ffmpeg.exe"), ("Tous les fichiers", "*.*")]
        else:
            filetypes = [("ffmpeg", "ffmpeg"), ("Tous les fichiers", "*.*")]
        path = filedialog.askopenfilename(
            title="Sélectionner le binaire ffmpeg",
            filetypes=filetypes
        )
        if path:
            self.ffmpeg_path_var.set(path)


    def _build_ui(self):
        pad = {'padx': 12, 'pady': 8}

        # ---- FFmpeg ----
        frm_ffmpeg = ttk.LabelFrame(self, text="FFmpeg")
        frm_ffmpeg.pack(fill="x", padx=12, pady=8)

        # Adapte le nom de fichier par défaut selon OS
        is_win = os.name == "nt"
        default_ffmpeg = os.path.join(os.getcwd(), "ffmpeg", "bin", "ffmpeg.exe" if is_win else "ffmpeg")
        if os.path.isfile(default_ffmpeg):
            initial_ffmpeg = default_ffmpeg
        else:
            initial_ffmpeg = ""

        self.ffmpeg_path_var = tk.StringVar(value=initial_ffmpeg)
        ttk.Label(frm_ffmpeg, text="Chemin ffmpeg :").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        self.ffmpeg_entry = ttk.Entry(frm_ffmpeg, textvariable=self.ffmpeg_path_var, width=60)
        self.ffmpeg_entry.grid(row=0, column=1, sticky="we", padx=6, pady=6)
        ttk.Button(frm_ffmpeg, text="Parcourir…", command=self._browse_ffmpeg).grid(row=0, column=2, padx=6, pady=6)


        # ---- Source ----
        frm_source = ttk.LabelFrame(self, text="Source")
        frm_source.pack(fill="x", **pad)

        # Ligne des radio boutons (fixe, pas de décalage)
        self.mode_var = tk.StringVar(value="youtube")
        rb_frame = ttk.Frame(frm_source)
        rb_frame.grid(row=0, column=0, columnspan=3, sticky="w")
        rb_y = ttk.Radiobutton(rb_frame, text="Lien YouTube", variable=self.mode_var, value="youtube", command=self._toggle_mode)
        rb_f = ttk.Radiobutton(rb_frame, text="Fichier local", variable=self.mode_var, value="upload", command=self._toggle_mode)
        rb_y.pack(side="left", padx=(0,16))
        rb_f.pack(side="left")

        # Lignes d'entrée (toujours dans la même grille pour stabilité)
        ttk.Label(frm_source, text="URL YouTube :").grid(row=1, column=0, sticky="w", padx=6, pady=6)
        self.url_entry = ttk.Entry(frm_source, width=70)
        self.url_entry.grid(row=1, column=1, sticky="we", padx=6, pady=6, columnspan=2)

        ttk.Label(frm_source, text="Fichier audio/vidéo :").grid(row=2, column=0, sticky="w", padx=6, pady=6)
        self.file_path_var = tk.StringVar()
        self.file_entry = ttk.Entry(frm_source, textvariable=self.file_path_var, width=58)
        self.file_entry.grid(row=2, column=1, sticky="we", padx=6, pady=6)
        ttk.Button(frm_source, text="Parcourir…", command=self._browse_file).grid(row=2, column=2, padx=6, pady=6)

        # Par défaut : mode YouTube => on grise la ligne "fichier"
        self._apply_mode_visibility(initial=True)

        # ---- Timings (2 lignes) ----
        frm_time = ttk.LabelFrame(self, text="Timings")
        frm_time.pack(fill="x", **pad)

        # Début
        start_frame = ttk.Frame(frm_time)
        start_frame.pack(fill="x", padx=6, pady=6)

        ttk.Label(start_frame, text="Début :").grid(row=0, column=0, sticky="w")

        start_inputs = ttk.Frame(start_frame)
        start_inputs.grid(row=0, column=1, sticky="w")

        big_font = self.big_font

        self.start_h = BigSpinner(start_inputs, minval=0, maxval=23, step=1,
                                width=3, font=big_font, initial=0, arrows="vertical")
        self.start_h.grid(row=0, column=0, padx=(0, 4))
        ttk.Label(start_inputs, text="h").grid(row=0, column=1, padx=(0, 8))

        self.start_m = BigSpinner(start_inputs, minval=0, maxval=59, step=1,
                                width=3, font=big_font, initial=0, arrows="vertical")
        self.start_m.grid(row=0, column=2, padx=(0, 4))
        ttk.Label(start_inputs, text="m").grid(row=0, column=3, padx=(0, 8))

        self.start_s = BigSpinner(start_inputs, minval=0, maxval=59, step=1,
                                width=3, font=big_font, initial=0, arrows="vertical")
        self.start_s.grid(row=0, column=4, padx=(0, 4))
        ttk.Label(start_inputs, text="s").grid(row=0, column=5, padx=(0, 8))

        # Raccourcis
        quick_start = ttk.Frame(start_frame)
        for txt, sec in [("0:00",0),("0:30",30),("1:00",60),("5:00",300),("1:15:00",4500)]:
            ttk.Button(quick_start, text=txt, command=lambda s=sec: self._set_quick("start", s)).pack(side="left", padx=2)
        quick_start.grid(row=1, column=1, sticky="w", pady=4)


        # Fin
        end_frame = ttk.Frame(frm_time)
        end_frame.pack(fill="x", padx=6, pady=6)

        ttk.Label(end_frame, text="Fin :").grid(row=0, column=0, sticky="w")

        end_inputs = ttk.Frame(end_frame)
        end_inputs.grid(row=0, column=1, sticky="w")

        self.end_h = BigSpinner(end_inputs, minval=0, maxval=23, step=1,
                                width=3, font=big_font, initial=0, arrows="vertical")
        self.end_h.grid(row=0, column=0, padx=(0, 4))
        ttk.Label(end_inputs, text="h").grid(row=0, column=1, padx=(0, 8))

        self.end_m = BigSpinner(end_inputs, minval=0, maxval=59, step=1,
                                width=3, font=big_font, initial=0, arrows="vertical")
        self.end_m.grid(row=0, column=2, padx=(0, 4))
        ttk.Label(end_inputs, text="m").grid(row=0, column=3, padx=(0, 8))

        self.end_s = BigSpinner(end_inputs, minval=0, maxval=59, step=1,
                                width=3, font=big_font, initial=0, arrows="vertical")
        self.end_s.grid(row=0, column=4, padx=(0, 4))
        ttk.Label(end_inputs, text="s").grid(row=0, column=5, padx=(0, 8))

        # Raccourcis
        quick_end = ttk.Frame(end_frame)
        for txt, sec in [("0:30",30),("1:00",60),("5:00",300),("10:00",600),("1:30:00",5400)]:
            ttk.Button(quick_end, text=txt, command=lambda s=sec: self._set_quick("end", s)).pack(side="left", padx=2)
        quick_end.grid(row=1, column=1, sticky="w", pady=4)





        # ---- Progression / statut ----
        frm_prog = ttk.LabelFrame(self, text="Progression")
        frm_prog.pack(fill="x", **pad)
        self.progress = ttk.Progressbar(frm_prog, orient="horizontal", mode="determinate")
        self.progress["maximum"] = 100
        self.progress.pack(fill="x", padx=8, pady=(8,4))
        self.status_var = tk.StringVar(value="En attente…")
        self.status_label = ttk.Label(frm_prog, textvariable=self.status_var)
        self.status_label.pack(anchor="w", padx=8, pady=(0, 8))

        # ---- Actions ----
        frm_actions = ttk.Frame(self)
        frm_actions.pack(fill="x", **pad)
        self.run_btn = ttk.Button(frm_actions, text="Extraire", command=self._on_run)
        self.run_btn.pack(side="left")
        self.cancel_btn = ttk.Button(frm_actions, text="Annuler", command=self._on_cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=8)

        # ---- Enregistrer (sous la progression, visible seulement après fin) ----
        self.save_frame = ttk.Frame(frm_prog)  # << parent corrigé
        self.save_btn = ttk.Button(self.save_frame, text="Enregistrer le MP3…", command=self._on_save)
        self.save_btn.pack(side="left")
        self.save_frame.pack_forget()  # caché au départ


    # ---------- Mode visibility ----------
    def _apply_mode_visibility(self, initial=False):
        mode = self.mode_var.get()
        # On ne change pas la grille: on active/désactive la ligne correspondante pour éviter toute "danse" de layout
        if mode == "youtube":
            # URL active, fichier grisé
            self.url_entry.configure(state="normal")
            self.file_entry.configure(state="disabled")
        else:
            self.url_entry.configure(state="disabled")
            self.file_entry.configure(state="normal")
        if not initial:
            # Effacer les champs non utilisés pour éviter confusions
            if mode == "youtube":
                self.file_path_var.set("")
            else:
                self.url_entry.delete(0, "end")

    def _toggle_mode(self):
        self._apply_mode_visibility()

    # ---------- Helpers ----------
    def _browse_file(self):
        path = filedialog.askopenfilename(
            title="Sélectionner un fichier audio/vidéo",
            filetypes=[
                ("Audio/Vidéo", "*.mp3 *.wav *.m4a *.aac *.mp4 *.avi *.mkv"),
                ("Tous les fichiers", "*.*")
            ]
        )
        if path:
            self.file_path_var.set(path)

    # Remplace _set_quick
    def _set_quick(self, which, seconds):
        # accepte un int (secondes) ou une string "hh:mm:ss"
        if isinstance(seconds, str) and ":" in seconds:
            total = parse_time_to_seconds(seconds)
        else:
            total = int(seconds)

        h = total // 3600
        m = (total % 3600) // 60
        s = total % 60

        if which == "start":
            self.start_h.set(h); self.start_m.set(m); self.start_s.set(s)
        else:
            self.end_h.set(h); self.end_m.set(m); self.end_s.set(s)

    # Remplace _read_time_fields (si ce n’est pas déjà fait)
    def _read_time_fields(self):
        sh = str(self.start_h.get())
        sm = str(self.start_m.get())
        ss = str(self.start_s.get())
        eh = str(self.end_h.get())
        em = str(self.end_m.get())
        es = str(self.end_s.get())
        return f"{sh}:{sm}:{ss}", f"{eh}:{em}:{es}"


    # ---------- Actions ----------
    def _on_run(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("En cours", "Un traitement est déjà en cours.")
            return

        mode = self.mode_var.get()
        url = self.url_entry.get().strip() if mode == "youtube" else ""
        local_file = self.file_path_var.get().strip() if mode == "upload" else ""

        # Vérifs rapides
        if mode == "youtube" and not url:
            messagebox.showerror("Erreur", "Veuillez entrer une URL YouTube.")
            return
        if mode == "upload" and not local_file:
            messagebox.showerror("Erreur", "Veuillez sélectionner un fichier.")
            return

        start_str, end_str = self._read_time_fields()

        # Reset UI
        self.status_var.set("Préparation…")
        self.progress.config(mode="determinate")
        self.progress["value"] = 0
        self.run_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.save_frame.pack_forget()
        self.temp_result_path = None

        # Lancer le worker
        self.worker = ExtractWorker(
            mode=mode,
            url=url,
            local_file=local_file,
            start_str=start_str,
            end_str=end_str,
            event_queue=self.event_queue,
            ffmpeg_dir=os.path.dirname(self.ffmpeg_path_var.get()) if self.ffmpeg_path_var.get() else None,
        )
        self.worker.ffmpeg_exe = self.ffmpeg_path_var.get() or None

        self.worker.start()

    def _on_save(self):
        if not self.temp_result_path or not os.path.exists(self.temp_result_path):
            messagebox.showerror("Erreur", "Aucun fichier à enregistrer.")
            return

        suggested = getattr(self, "_suggested_name", "extrait_audio.mp3")
        out_path = filedialog.asksaveasfilename(
            title="Enregistrer le MP3",
            defaultextension=".mp3",
            initialfile=suggested,
            filetypes=[("Fichier MP3", "*.mp3")]
        )
        if out_path:
            try:
                shutil.copyfile(self.temp_result_path, out_path)
                messagebox.showinfo("Succès", f"Fichier enregistré :\n{out_path}")
            except Exception as e:
                messagebox.showerror("Erreur", f"Impossible d'enregistrer : {e}")

    def _on_cancel(self):
        if self.worker and self.worker.is_alive():
            self.worker.stop()
            self.status_var.set("Annulation demandée…")
        # On ne réactive les boutons qu’au moment de la réception de l’événement d’erreur/fin

    # ---------- Event loop ----------
    def _poll_events(self):
        try:
            while True:
                msg = self.event_queue.get_nowait()
                typ = msg.get("type")
                if typ == "progress":
                    percent = msg.get("percent", "")
                    phase = msg.get("phase", "")
                    if percent.endswith("%"):
                        try:
                            v = float(percent.strip("%"))
                            if str(self.progress["mode"]) == "indeterminate":
                                self.progress.stop()
                                self.progress.config(mode="determinate")
                            self.progress["value"] = v
                            self.status_var.set(f"{phase} ({percent})")
                        except Exception:
                            self.progress.config(mode="indeterminate")
                            self.progress.start(10)
                            self.status_var.set(phase)
                    else:
                        self.progress.config(mode="indeterminate")
                        self.progress.start(10)
                        self.status_var.set(phase)

                elif typ == "status":
                    self.status_var.set(msg.get("text", ""))

                elif typ == "done":
                    if str(self.progress["mode"]) == "indeterminate":
                        self.progress.stop()
                        self.progress.config(mode="determinate")
                    self.progress["value"] = 100
                    self.status_var.set("✅ Fichier prêt à être enregistré !")
                    self.temp_result_path = msg.get("temp_path")
                    self._suggested_name = msg.get("suggested_name", "extrait_audio.mp3")
                    self.save_frame.pack(pady=(0, 10))   # >> sous la barre de progression
                    self.run_btn.config(state="normal")
                    self.cancel_btn.config(state="disabled")

                elif typ == "error":
                    if str(self.progress["mode"]) == "indeterminate":
                        self.progress.stop()
                        self.progress.config(mode="determinate")
                    self.progress["value"] = 0
                    txt = msg.get('message') or "Erreur inconnue"
                    if txt.strip().lower() == "annulé":
                        self.status_var.set("❌ Annulé")
                    else:
                        self.status_var.set(f"Erreur : {txt}")
                    self.run_btn.config(state="normal")
                    self.cancel_btn.config(state="disabled")
                    self.save_frame.pack_forget()

                self.event_queue.task_done()
        except queue.Empty:
            pass

        self.after(100, self._poll_events)

    def destroy(self):
        try:
            if self.temp_result_path and os.path.exists(self.temp_result_path):
                os.remove(self.temp_result_path)
        except Exception:
            pass
        super().destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
