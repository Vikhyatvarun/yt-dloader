from email import header
import os
import json
import threading
import queue
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, END
import customtkinter as ctk
from yt_dlp import YoutubeDL
import ctypes
import winsound
import sys
import requests  
import socket   
from PIL import Image, ImageTk  
import io  
import shutil 
import webbrowser 

APP_TITLE = "YT DLoader - YouTube Video Downloader"
DEFAULT_OUTDIR = os.path.join(os.path.expanduser("~"), "Downloads")
START_SIZE = "920x520"
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

try:
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    DWMWA_USE_IMMERSIVE_DARK_MODE = 20
    DWMWA_CAPTION_COLOR = 35
    DWMWA_TEXT_COLOR = 36

    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                                               ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int))
    white = ctypes.c_int(0x00FFFFFF)
    dark = ctypes.c_int(0x00121212)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_CAPTION_COLOR,
                                               ctypes.byref(dark), ctypes.sizeof(ctypes.c_int))
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_TEXT_COLOR,
                                               ctypes.byref(white), ctypes.sizeof(ctypes.c_int))
except Exception:
    pass

_ffmpeg_warning_shown = False

def setup_ffmpeg():
    """Find FFmpeg: bundled → system PATH → show warning if missing."""
    global _ffmpeg_warning_shown

    if getattr(sys, 'frozen', False):
        app_dir = os.path.dirname(sys.executable)     
    else:
        app_dir = os.path.dirname(os.path.abspath(__file__)) 

    bundled_path = os.path.join(app_dir, "ffmpeg", "ffmpeg.exe")

    if os.path.isfile(bundled_path):
        return bundled_path 

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg  

    if not _ffmpeg_warning_shown:
        messagebox.showwarning(
            "FFmpeg Missing",
            "FFmpeg not found!\n\n"
            "The app may not merge videos or extract audio properly.\n"
            "Please reinstall the app or download FFmpeg manually."
        )
        _ffmpeg_warning_shown = True

    return "ffmpeg"

def human_size(num_bytes):
    try:
        n = float(num_bytes)
    except Exception:
        return "Unknown"
    if n <= 0:
        return "0B"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024.0:
            return f"{n:3.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"

def format_seconds(s):
    try:
        s = int(float(s))
    except Exception:
        return None
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"

class YTDLoader(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.config_path = "config.json"
        self.last_folder = self._load_last_folder()

        self.title("YT DLoader")
        self.geometry("1100x650")
        self.resizable(False, False)
        icon_path = os.path.join(sys._MEIPASS, "logo.ico") if hasattr(sys, "_MEIPASS") else "logo.ico"
        try:
            self.iconbitmap(icon_path)
        except Exception:
            pass

        self.queue = queue.Queue()
        self.fetch_thread = None
        self.download_thread = None
        self.available_options = []

        self._cancel_requested = False
        self._marquee_pos = 0.0
        self._error_shown = False

        self.retry_count = 0
        self.max_retries = 10

        self._spinner_running = False
        self._spinner_after_id = None
        self._spinner_chars = ["⠋","⠙","⠸","⠴","⠦","⠇","⠋","⠙","⠸","⠴","⠦","⠇"]
        self._spinner_index = 0

        self._dl_spinner_running = False
        self._dl_spinner_index = 0
        self._dl_spinner_after = None
        self._dl_spinner_chars = ["⠋","⠙","⠸","⠴","⠦","⠇"]

        self._build_ui()
        self.after(100, self._center_window)
        self._periodic_check()

    def _check_internet(self):
        """Check if internet is connected (ping Google)."""
        try:
            response = requests.get("http://www.google.com", timeout=3)
            return response.status_code == 200
        except (requests.RequestException, socket.timeout):
            return False
        except Exception:
            return False

    def _show_no_internet_popup(self):
        """Show popup and stop spinners."""
        self._stop_spinner()
        self._stop_dl_spinner()
        messagebox.showwarning(
            "No Internet Connection",
            "Please check your Internet connection. Will auto-retry when back online."
        )
        self.status_label.configure(text="No Internet — Retrying...")
        self._append_log("No internet detected. Auto-retrying in 5 seconds...")

    def _start_auto_retry(self, action_func):
        """Start timer to check internet & auto-call action_func (fetch or download)."""
        def check_and_retry():
            if self._check_internet():
                self._append_log("Internet back! Resuming...")
                action_func()  
            else:
                self.after(5000, check_and_retry)

        check_and_retry()

    def _load_last_folder(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    data = json.load(f)
                    return data.get("last_folder", "")
            except:
                return ""
        return ""

    def _save_last_folder(self, folder):
        try:
            with open(self.config_path, "w") as f:
                json.dump({"last_folder": folder}, f)
        except:
            pass

    def _add_divider(self, parent, row, columnspan=1, padx=12, pady=(8, 8)):
        divider = ctk.CTkFrame(parent, height=2, fg_color="#DFDFDF")
        divider.grid(row=row, column=0, columnspan=2, sticky="ew", padx=12, pady=(10,10))

    def _build_ui(self):
        pad = 12
        header = ctk.CTkFrame(self, corner_radius=0, fg_color="#313131")
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        title = ctk.CTkLabel(header, text=APP_TITLE,
                             font=ctk.CTkFont(size=18, weight="bold"), text_color="white")
        title.grid(row=0, column=0, sticky="w", padx=(pad, 8), pady=12)

        def open_report_link():
            webbrowser.open("https://vikhyatvarun.github.io/YT-DLoader/")  
        report_link = ctk.CTkLabel(header, text="Report problem here!", 
                           text_color="#4A90E2", 
                           font=ctk.CTkFont(size=12, underline=True),  
                           cursor="hand2") 
        report_link.grid(row=0, column=2, sticky="e", padx=(0, pad), pady=12)

        # Make it clickable
        report_link.bind("<Button-1>", lambda e: open_report_link())
        report_link.bind("<Enter>", lambda e: report_link.configure(text_color="#357ABD"))  
        report_link.bind("<Leave>", lambda e: report_link.configure(text_color="#4A90E2")) 

        main_left = ctk.CTkFrame(self, corner_radius=8)
        main_left.grid(row=1, column=0, sticky="nsew", padx=(pad, 6), pady=pad)
        main_left.grid_columnconfigure(0, weight=1)

        main_right = ctk.CTkFrame(self, corner_radius=8)
        main_right.grid(row=1, column=1, sticky="nsew", padx=(6, pad), pady=pad)

        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(1, weight=1)

        left_row = 0

        heading_frame = ctk.CTkFrame(main_left, fg_color="transparent")
        heading_frame.grid(row=left_row, column=0, sticky="ew", padx=12, pady=(12, 4))

        heading_label = ctk.CTkLabel(
            heading_frame,
            text="Download",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="white"
        )
        heading_label.grid(row=0, column=0, sticky="w")

        left_row += 1
        self._add_divider(main_left, left_row)
        left_row += 1

        # URL Frame
        url_frame = ctk.CTkFrame(main_left, fg_color="transparent")
        url_frame.grid(row=left_row, column=0, sticky="ew", padx=12, pady=(5, 8))
        url_frame.grid_columnconfigure(0, weight=1)
        url_lbl = ctk.CTkLabel(url_frame, text="Paste URL:")
        url_lbl.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.url_var = tk.StringVar()
        self.url_entry = ctk.CTkEntry(url_frame, textvariable=self.url_var,
                                      placeholder_text="Paste YouTube link here")
        self.url_entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))

        self.url_entry.bind("<Return>", self._on_enter)
        self.url_entry.bind("<Control-v>", self._on_ctrl_v_paste)
        self.url_entry.bind("<Control-V>", self._on_ctrl_v_paste)

        paste_btn = ctk.CTkButton(url_frame, text="Paste", width=30,
                          fg_color="#FF3B30", hover_color="#D32F2F",
                          command=self._paste_and_fetch)
        paste_btn.grid(row=1, column=1, padx=(6, 0))

        left_row += 1

        self._add_divider(main_left, left_row)
        left_row += 1

        format_frame = ctk.CTkFrame(main_left, fg_color="transparent")
        format_frame.grid(row=left_row, column=0, sticky="ew", padx=12, pady=(6, 8))

        format_frame.grid_columnconfigure(1, weight=1)
        format_frame.grid_columnconfigure(2, weight=0)

        format_lbl = ctk.CTkLabel(format_frame, text="Format:")
        format_lbl.grid(row=0, column=0, sticky="w", padx=(0, 8))

        self.format_var = tk.StringVar(value="Video")
        mode_frame = ctk.CTkFrame(format_frame, fg_color="transparent")
        mode_frame.grid(row=0, column=1, sticky="w")

        self.video_rb = ctk.CTkRadioButton(mode_frame, text="Video", variable=self.format_var,
                                           value="Video",fg_color="#2979FF", hover_color="#1565C0", command=lambda: self._on_format_change("Video"))
        self.video_rb.grid(row=0, column=0, padx=(0, 8))

        self.audio_rb = ctk.CTkRadioButton(mode_frame, text="Audio", variable=self.format_var,
                                           value="Audio",fg_color="#2979FF", hover_color="#1565C0", command=lambda: self._on_format_change("Audio"))
        self.audio_rb.grid(row=0, column=1)

        res_lbl = ctk.CTkLabel(format_frame, text="Resolution:")
        res_lbl.grid(row=1, column=0, sticky="w", pady=(8, 0), padx=(0, 8))
        self.res_var = tk.StringVar(value="Auto (best)")
        self.res_menu = ctk.CTkOptionMenu(format_frame, values=["Auto (best)"], variable=self.res_var)
        self.res_menu.grid(row=1, column=1, sticky="w", pady=(8, 0))

        # spinner label placed right of resolution
        self.spinner_label = ctk.CTkLabel(format_frame, text="", width=24)
        self.spinner_label.grid(row=1, column=1, sticky="w", padx=(158,0), pady=(8,0))

        left_row += 1
        left_row += 1
        self._add_divider(main_left, left_row)
        left_row += 1

        fname_frame = ctk.CTkFrame(main_left, fg_color="transparent")
        fname_frame.grid(row=left_row, column=0, sticky="ew", padx=12, pady=(6, 8))
        fname_lbl = ctk.CTkLabel(fname_frame, text="Filename template:")
        fname_lbl.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.fname_entry = ctk.CTkEntry(fname_frame)
        self.fname_entry.insert(0, "%(title)s.%(ext)s")
        self.fname_entry.grid(row=1, column=0, sticky="ew", pady=(6, 0))

        left_row += 1
        self._add_divider(main_left, left_row)
        left_row += 1

        out_frame = ctk.CTkFrame(main_left, fg_color="transparent")
        out_frame.grid(row=left_row, column=0, sticky="ew", padx=12, pady=(6, 8))
        out_frame.grid_columnconfigure(0, weight=1)
        out_lbl = ctk.CTkLabel(out_frame, text="Save to:")
        out_lbl.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.out_dir_var = tk.StringVar(value=DEFAULT_OUTDIR)
        self.out_entry = ctk.CTkEntry(out_frame, textvariable=self.out_dir_var)
        self.out_entry.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(6, 0))
        out_btn = ctk.CTkButton(out_frame, text="Browse", width=90, command=self._choose_folder,
                                fg_color="#2979FF", hover_color="#1565C0")
        out_btn.grid(row=1, column=1, sticky="e", padx=(4, 0), pady=(6, 0))

        left_row += 1
        self._add_divider(main_left, left_row)
        left_row += 1

        btns_frame = ctk.CTkFrame(main_left, fg_color="transparent")
        btns_frame.grid(row=left_row, column=0, sticky="w", padx=34, pady=(6, 8))
        self.download_btn = ctk.CTkButton(btns_frame, text="Download", width=140, fg_color="#FF3B30",
                                          hover_color="#D32F2F", command=self._on_download)
        self.download_btn.grid(row=0, column=0, padx=(7, 12))
        self.cancel_btn = ctk.CTkButton(btns_frame, text="Cancel", width=140, command=self._on_cancel, state="disabled",
                                        fg_color="#246BE6", hover_color="#135EB4")
        self.cancel_btn.grid(row=0, column=1)

        left_row += 1

        self.progress = ctk.CTkProgressBar(main_left)
        self.progress.grid(row=left_row, column=0, sticky="ew", padx=12, pady=(6, 4))
        self.progress.configure(mode="determinate")
        self.progress.set(0)
        self.progress.configure(progress_color="#d61a1a", fg_color="#383838")
        left_row += 1
        self.status_label = ctk.CTkLabel(main_left, text="Idle", anchor="w")
        self.status_label.grid(row=left_row, column=0, sticky="w", padx=12, pady=(0, 12))

        main_right.grid_rowconfigure(2, weight=1) 

        preview_frame = ctk.CTkFrame(main_right, fg_color="transparent")
        preview_frame.grid(row=0, column=0, sticky="ew", pady=(10, 5))
        preview_frame.grid_columnconfigure(1, weight=1)
        preview_frame.grid_rowconfigure(0, weight=1)  
        preview_frame.configure(height=160)
        self.thumb_label = ctk.CTkLabel(preview_frame, text="No thumbnail", width=240, height=135, fg_color="#383838", corner_radius=8)
        self.thumb_label.grid(row=0, rowspan=3, column=0, padx=(10, 12), pady=4, sticky="nw")

        self.title_label = ctk.CTkLabel(
            preview_frame, 
            text="No title", 
            font=ctk.CTkFont(size=14, weight="bold"), 
            anchor="nw",  
            justify="left",
            wraplength=410  
        )
        self.title_label.grid(row=0, column=1, sticky="ew", pady=4, padx=(0, 0))

        self.duration_label = ctk.CTkLabel(preview_frame, text="No duration", anchor="w", text_color="gray")
        self.duration_label.grid(row=1, column=1, sticky="w", pady=(0, 2))

        self.uploader_label = ctk.CTkLabel(preview_frame, text="No uploader", anchor="w", text_color="gray")
        self.uploader_label.grid(row=2, column=1, sticky="w", pady=(0, 0))

        log_header_frame = ctk.CTkFrame(main_right, fg_color="transparent")
        log_header_frame.grid(row=1, column=0, sticky="ew", pady=(0, 5))
        log_header_frame.grid_columnconfigure(0, weight=1)
        log_header_frame.grid_columnconfigure(1, weight=0)

        log_label = ctk.CTkLabel(log_header_frame, text="Log:", font=ctk.CTkFont(size=18, weight="bold"), text_color="white")
        log_label.grid(row=0, column=0, sticky="w", padx=10)

        clear_btn = ctk.CTkButton(
            log_header_frame,
            width=28,
            height=28,
            text="🗑",
            fg_color="#FF3B30",
            hover_color="#D32F2F",
            command=self._clear_log,
        )
        clear_btn.grid(row=0, column=1, sticky="e", padx=(0, 26), pady=(5,0))

        # Log Frame
        log_frame = ctk.CTkFrame(main_right, fg_color="transparent")
        log_frame.grid(row=2, column=0, sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_frame,
            wrap="word",
            bg="#0b0b0c",
            fg="#dff8ff",
            font=("Arial", 11)
        )
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        log_scroll = ctk.CTkScrollbar(log_frame, orientation="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)
        if self.last_folder and os.path.isdir(self.last_folder):
            self.out_dir_var.set(self.last_folder)

        self._append_log("Ready. Paste a YouTube URL or click Paste to begin.")

    def _on_enter(self, event):
        """Prevent Enter from triggering a fetch automatically."""
        return "break"

    def _center_window(self):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = int((sw - w) / 2)
        y = int((sh - h) / 4)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _append_log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert(END, text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", END)
        self.log_text.configure(state="disabled")

    def _choose_folder(self):
        folder = filedialog.askdirectory(initialdir=self.out_dir_var.get() or os.path.expanduser("~"))
        if folder:
            self.out_dir_var.set(folder)
            self._save_last_folder(folder)

    def _paste_and_fetch(self):
        try:
            clip = self.clipboard_get().strip()
        except Exception:
            clip = ""
        if clip:
            self.url_var.set(clip)
            self._append_log("Pasted URL from clipboard.")
            self._error_shown = False
            self._fetch_formats(clip)
        else:
            self._append_log("Clipboard empty or no text available.")

    def _on_ctrl_v_paste(self, event=None):
        self._error_shown = False
        self.after(150, lambda: self._fetch_formats(self.url_var.get().strip()))
        return None

    def _on_format_change(self, value):
        self._update_resolution_state()

    def _update_resolution_state(self):
        fmt = self.format_var.get()
        if fmt == "Audio":
            try:
                self.res_menu.configure(values=["Audio only"], state="disabled")
                self.res_var.set("Audio only")
            except Exception:
                pass
        else:
            try:
                labels = [o[0] for o in self.available_options] if self.available_options else ["Auto (recommended)"]
                if "Auto (recommended)" not in labels:
                    labels.insert(0, "Auto (recommended)")
                self.res_menu.configure(values=labels, state="normal")
                self.res_var.set(labels[0])
            except Exception:
                pass

    def _start_spinner(self):
        if self._spinner_running:
            return
        self._spinner_running = True
        self._spinner_index = 0
        self._spinner_step()

    def _spinner_step(self):
        if not self._spinner_running:
            return
        ch = self._spinner_chars[self._spinner_index % len(self._spinner_chars)]
        self.spinner_label.configure(text=ch)
        self._spinner_index += 1
        self._spinner_after_id = self.after(80, self._spinner_step)

    def _stop_spinner(self):
        if not self._spinner_running:
            return
        self._spinner_running = False
        if self._spinner_after_id:
            try:
                self.after_cancel(self._spinner_after_id)
            except Exception:
                pass
            self._spinner_after_id = None
        try:
            self.spinner_label.configure(text="")
        except Exception:
            pass

    def _start_dl_spinner(self):
        if self._dl_spinner_running:
            return
        self._dl_spinner_running = True
        self._dl_spinner_index = 0
        self._dl_spinner_step()

    def _dl_spinner_step(self):
        if not self._dl_spinner_running:
            return
        spin = self._dl_spinner_chars[self._dl_spinner_index]
        self._dl_spinner_index = (self._dl_spinner_index + 1) % len(self._dl_spinner_chars)

        txt = self.status_label.cget("text")
        if txt and txt.strip():
            parts = txt.rsplit(" ", 1)
            if parts[-1] in self._dl_spinner_chars:
                txt = parts[0]
        else:
            txt = ""
        txt = txt.rstrip()
        if txt:
            self.status_label.configure(text=f"{txt} {spin}")
        else:
            self.status_label.configure(text=f"{spin}")
        self._dl_spinner_after = self.after(90, self._dl_spinner_step)

    def _stop_dl_spinner(self):
        self._dl_spinner_running = False
        if self._dl_spinner_after:
            try:
                self.after_cancel(self._dl_spinner_after)
            except:
                pass
        self._dl_spinner_after = None

    def _fetch_formats(self, url):
        if not url:
            return
        if not self._check_internet():
            self._show_no_internet_popup()
            self._start_auto_retry(lambda: self._fetch_formats(url))
            return 
        if self.fetch_thread and self.fetch_thread.is_alive():
            self._append_log("Already fetching formats...")
            return
        try:
            self.res_menu.configure(values=["Fetching..."])
            self.res_var.set("Fetching...")
        except Exception:
            pass
        self._append_log("Fetching formats and size estimates...")
        self._error_shown = False
        self._start_spinner()
        self.fetch_thread = threading.Thread(target=self._fetch_worker, args=(url,), daemon=True)
        self.fetch_thread.start()

    def _fetch_worker(self, url):
        try:
            ydl_opts = {"quiet": True, "no_warnings": True}
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            formats = info.get("formats", []) or []
            heights = {}
            best_audio = None
            for f in formats:
                if (not f.get("vcodec") or f.get("vcodec") == "none") and f.get("acodec") and f.get("acodec") != "none":
                    if best_audio is None or (f.get("abr") or 0) > (best_audio.get("abr") or 0):
                        best_audio = f
                if f.get("vcodec") and f.get("vcodec") != "none":
                    h = f.get("height")
                    if h:
                        current = heights.get(h)
                        score = (f.get("tbr") or 0) + (f.get("width") or 0)/1000.0
                        if current is None or score > current[0]:
                            heights[h] = (score, f)
            heights_list = sorted([h for h in heights.keys() if isinstance(h, int)], reverse=True)

            options = [("Auto (recommended)", None, None)]
            for h in heights_list:
                entry = heights[h][1]
                vsize = entry.get("filesize") or entry.get("filesize_approx") or 0
                a_size = best_audio.get("filesize") or best_audio.get("filesize_approx") or 0 if best_audio else 0
                total = None
                if vsize or a_size:
                    total = (vsize or 0) + (a_size or 0)
                label = f"{h}p"
                label_full = label
                options.append((label_full, h, total))

            self.available_options = options
            labels = [o[0] for o in options]

            video_info = {
                "title": info.get("title", "Unknown"),
                "duration": info.get("duration"),
                "uploader": info.get("uploader", "Unknown"),
                "thumbnail": info.get("thumbnail")
            }
            self.queue.put(("video_info", video_info))

            self.queue.put(("formats_ready", labels))
            self.queue.put(("log", f"Formats fetched: {', '.join(labels[:6])}"))
        except Exception as e:
            err_msg = str(e).lower()
            if not self._check_internet() or any(x in err_msg for x in ["connection", "timeout", "network"]):
                self.queue.put(("no_internet_fetch", None))
            else:
                self.queue.put(("error", {"type": "invalid_url"}))
        finally:
            try:
                self.fetch_thread = None
            except Exception:
                pass

    def _on_download(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("No URL", "Please paste a YouTube URL first.")
            return

        if not self._check_internet():
            self._show_no_internet_popup()
            self._start_auto_retry(self._on_download)  
            return

        self._error_shown = False
        self._start_dl_spinner()

        outdir = os.path.abspath(self.out_dir_var.get() or DEFAULT_OUTDIR)
        self._save_last_folder(outdir)
        os.makedirs(outdir, exist_ok=True)
        fmt_mode = self.format_var.get()
        selected_res = self.res_var.get()

        if fmt_mode == "Audio":
            fmt = "bestaudio/best"
        else:
            if not selected_res or selected_res == "Auto (recommended)" or selected_res == "Fetching...":
                fmt = "bestvideo+bestaudio/best"
            else:
                try:
                    h_part = selected_res.split("p")[0]
                    h = int(h_part.strip())
                    fmt = f"bestvideo[height<={h}]+bestaudio/best"
                except Exception:
                    fmt = "bestvideo+bestaudio/best"

        out_template = os.path.join(outdir, "%(title)s.%(ext)s")
        ydl_opts = {
            "format": fmt,
            "outtmpl": out_template,
            "merge_output_format": "mp4",
            "progress_hooks": [self._progress_hook],
            "noplaylist": False,
            "quiet": True,
            "no_warnings": True,
            "retries": 5,  
            "fragment_retries": 10, 
            "sleep_interval": 1,    
            "max_sleep_interval": 5,
            "ffmpeg_location": setup_ffmpeg(),
        }
        if fmt_mode == "Audio":
            ydl_opts.update({
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            })

        self.retry_count = 0

        self._cancel_requested = False
        self.download_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self._append_log(f"Starting download: format_mode={fmt_mode}, fmt={fmt}")
        self.progress.set(0.0)
        self._marquee_pos = 0.0
        self.status_label.configure(text="Starting download...")

        self.download_thread = threading.Thread(target=self._download_worker, args=(url, ydl_opts), daemon=True)
        self.download_thread.start()

    def _download_worker(self, url, ydl_opts):
        try:
            with YoutubeDL(ydl_opts) as ydl:
                self._current_ydl = ydl
                info = ydl.extract_info(url, download=True)
                final = ydl.prepare_filename(info)
                self.queue.put(("done", final))
        except Exception as e:
            if getattr(self, "_cancel_requested", False):
                self.queue.put(("error", {"type": "cancelled"}))
                return

            err_msg = str(e).lower()
            if not self._check_internet() or any(x in err_msg for x in ["ssl", "decryption", "timeout", "connection", "network", "http"]):
                self.queue.put(("no_internet_download", None))
            else:
                self.queue.put(("error", {"type": "download_failed", "msg": str(e)}))

        finally:
            try:
                delattr(self, "_current_ydl")
            except Exception:
                pass

    def _on_cancel(self):
        if self.download_thread and self.download_thread.is_alive():
            self._append_log("Cancel requested...")
            self._cancel_requested = True
            self.cancel_btn.configure(state="disabled")
        else:
            self._append_log("No active download to cancel.")

    def _progress_hook(self, d):
        try:
            if getattr(self, "_cancel_requested", False):
                raise Exception("User requested cancel")

            st = d.get("status")
            if st == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                if not downloaded:
                    downloaded = d.get("bytes_downloaded") or 0

                pct = None
                if total and total > 0:
                    try:
                        pct = float(downloaded) / float(total)
                        pct = max(0.0, min(1.0, pct))
                    except:
                        pct = None
                sp = d.get("speed") or d.get("download_speed") or None
                eta = d.get("eta") or d.get("estimated_time") or None
                self.queue.put(("progress", {"pct": pct, "eta": eta, "speed": sp, "downloaded": downloaded, "total": total}))

            elif st == "finished":
                self.queue.put(("log", "Finished downloading — post-processing..."))

            elif st == "error":
                if not self._check_internet():
                    self.queue.put(("no_internet_download", None))  
                else:
                    self.queue.put(("log", "Network retrying chunk..."))
                return  

        except Exception:
            raise  

    def _periodic_check(self):
        try:
            while True:
                item = self.queue.get_nowait()
                kind, payload = item[0], item[1]

                if kind == "formats_ready":
                    self._stop_spinner()

                    labels = payload
                    if "Auto (best)" not in labels:
                        labels.insert(0, "Auto (recommended)")
                    try:
                        self.res_menu.configure(values=labels)
                    except Exception:
                        pass
                    self.res_var.set(labels[0] if labels else "Auto (recommended)")
                    self._append_log("Resolutions updated.")
                    self._update_resolution_state()

                elif kind == "video_info":
                    info = payload
                    title = info.get("title", "Unknown")
                    duration = info.get("duration")
                    uploader = info.get("uploader", "Unknown")
                    thumb_url = info.get("thumbnail")

                    self.title_label.configure(text=title)
                    if duration:
                        self.duration_label.configure(text=f"Duration: {format_seconds(duration)}")
                    else:
                        self.duration_label.configure(text="Duration: Unknown")
                    self.uploader_label.configure(text=f"By: {uploader}")

                    if thumb_url:
                        try:
                            response = requests.get(thumb_url, timeout=5)
                            img_data = io.BytesIO(response.content)
                            img = Image.open(img_data).resize((240, 135), Image.Resampling.LANCZOS)
                            photo = ImageTk.PhotoImage(img)
                            self.thumb_label.configure(image=photo, text="")
                            self.thumb_label.image = photo  
                        except Exception as e:
                            self._append_log(f"Failed to load thumbnail: {e}")
                            self.thumb_label.configure(text="Thumbnail failed to load")

                elif kind == "log":
                    self._append_log(payload)

                elif kind == "progress":
                    pct = payload.get("pct", None)
                    sp = payload.get("speed")
                    eta = payload.get("eta")
                    downloaded = payload.get("downloaded", 0)
                    total = payload.get("total", 0)

                    if pct is None:
                        self._marquee_pos = (self._marquee_pos + 0.03) % 1.0
                        try:
                            self.progress.set(self._marquee_pos)
                        except Exception:
                            pass
                        status = f"Downloading — {human_size(downloaded)}"
                        if sp:
                            status += f" — {human_size(sp)}/s"
                        self.status_label.configure(text=status)
                    else:
                        try:
                            self.progress.set(max(0.0, min(1.0, pct)))
                        except Exception:
                            pass
                        status = f"Downloading... {pct*100:5.1f}%"
                        if sp:
                            status += f" — Speed: {human_size(sp)}/s"

                        if eta:
                            nice_eta = format_seconds(eta)
                            if nice_eta:
                                status += f" — Time: {nice_eta}"
                            else:
                                status += f" — Time: {eta}s"
                        else:
                            status += f" — Time: --"

                        self.status_label.configure(text=status)

                elif kind == "done":
                    self._append_log(f"Saved: {payload}")
                    self._spinner_index = 0
                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
                    self.status_label.configure(text="✅ Download Completed! ")
                    try:
                        self.progress.set(1.0)
                    except Exception:
                        pass
                    self._stop_dl_spinner()
                    self.download_btn.configure(state="normal")
                    self.cancel_btn.configure(state="disabled")
                    self._cancel_requested = False

                elif kind == "error":
                    self._stop_dl_spinner()
                    err = payload if isinstance(payload, dict) else {"type": "invalid_url"}
                    etype = err.get("type")

                    if etype == "cancelled":
                        self._append_log("Download cancelled by user.")
                        self.status_label.configure(text="Cancelled")
                    elif etype == "invalid_url":
                        if not self._error_shown:
                            self._error_shown = True
                            messagebox.showerror("Invalid URL", "Please enter a valid YouTube URL.")
                        self.status_label.configure(text="Invalid URL")
                    elif etype == "no_internet":
                        self._append_log("Too many connection failures.")
                        self.status_label.configure(text="No Internet")
                        messagebox.showwarning(
                            "No Internet Connection",
                            "Please check your Internet connection and try again."
                        )
                    else:
                        msg = err.get("msg", "Download failed")
                        self._append_log(f"Download failed: {msg}")
                        self.status_label.configure(text="Failed")

                    self.download_btn.configure(state="normal")
                    self.cancel_btn.configure(state="disabled")
                    self._cancel_requested = False
                    self.progress.set(0)
                    self.retry_count = 0  

                    self._stop_dl_spinner()
                    self.download_btn.configure(state="normal")
                    self.cancel_btn.configure(state="disabled")
                    self._cancel_requested = False

                elif kind == "no_internet_fetch":
                    self._show_no_internet_popup()
                    self._start_auto_retry(lambda: self._fetch_formats(self.url_var.get().strip()))

                elif kind == "no_internet_download":
                    self._show_no_internet_popup()
                    self._start_auto_retry(self._on_download)

        except queue.Empty:
            pass
        self.after(150, self._periodic_check)

if __name__ == "__main__":
    app = YTDLoader()

    app.mainloop()
