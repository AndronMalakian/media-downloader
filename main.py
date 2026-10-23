import json
import os
import re
import sys
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox

import ttkbootstrap as ttkb
from ttkbootstrap.constants import BOTH, BOTTOM, HORIZONTAL, LEFT, RIGHT, VERTICAL, X, Y

try:
    from ttkbootstrap.tooltip import ToolTip
except ImportError:
    from ttkbootstrap import ToolTip


def add_tooltip(widget, text: str, **kwargs):
    try:
        return ToolTip(widget, text=text, **kwargs)
    except TypeError:
        return ToolTip(widget, text, **kwargs)


def resource_path(name: str) -> str:
    """РџСѓС‚СЊ Рє СЂРµСЃСѓСЂСЃСѓ Рё РІ СЂРµР¶РёРјРµ РёСЃС…РѕРґРЅРёРєРѕРІ, Рё РІРЅСѓС‚СЂРё СЃРѕР±СЂР°РЅРЅРѕРіРѕ .exe."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)

from downloader import DownloadProgress, MediaDownloader
from pot import (
    SERVER_HOST,
    SERVER_PORT,
    find_deno,
    install_provider,
    provider_installed,
    server_running,
    start_server,
    stop_server,
)
import pot
from utils import (
    browser_reads_ok,
    check_cookies_file,
    check_youtube_network,
    detect_browsers,
    find_ffmpeg,
    find_ffprobe,
    format_bytes,
    format_duration,
    format_eta,
    get_app_asset_url,
    get_app_version,
    get_default_download_dir,
    get_ffmpeg_download,
    get_installed_ytdlp_version,
    get_latest_app_release,
    get_latest_pypi_version,
    is_browser_running,
    is_newer_app_version,
    is_newer_version,
    looks_like_url,
    ytdlp_update_command,
    download_file,
    create_updater_script,
)

CONFIG_FILE = Path.home() / ".media_downloader_config.json"
LEGACY_CONFIG_FILE = Path.home() / ".yt_downloader_config.json"
FFMPEG_URL = "https://github.com/yt-dlp/FFmpeg-Builds/releases/latest"
RELEASES_URL = "https://github.com/TTsanchez/media-downloader/releases/latest"
DEFAULT_ARCHIVE_FILE = Path.home() / ".media_downloader_archive.txt"

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _run_process(cmd, cwd=None, timeout=1800):
    """Р—Р°РїСѓСЃРєР°РµС‚ РєРѕРјР°РЅРґСѓ Рё РІРѕР·РІСЂР°С‰Р°РµС‚ (РєРѕРґ РІРѕР·РІСЂР°С‚Р°, РІС‹РІРѕРґ)."""
    import subprocess

    try:
        r = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 1, f"РўР°Р№РјР°СѓС‚ РїРѕСЃР»Рµ {timeout} СЃ"
    except Exception as e:
        return 1, str(e)


class VScroll(ttkb.Frame):
    """Р¤СЂРµР№Рј СЃ РІРµСЂС‚РёРєР°Р»СЊРЅРѕР№ РїСЂРѕРєСЂСѓС‚РєРѕР№ (РєРѕР»РµСЃРѕ РјС‹С€Рё + РїРѕР»РѕСЃР° СЃРїСЂР°РІР°)."""

    def __init__(self, master, height=250, bg=None, **kw):
        super().__init__(master, **kw)
        self.canvas = tk.Canvas(self, height=height, highlightthickness=0, bd=0, takefocus=0)
        if bg:
            self.canvas.configure(bg=bg)
        self.canvas.pack(side=LEFT, fill=BOTH, expand=True)

        sb = ttkb.Scrollbar(self, orient=VERTICAL, command=self.canvas.yview, bootstyle="round")
        sb.pack(side=RIGHT, fill=Y)
        self.canvas.configure(yscrollcommand=sb.set)

        self.inner = ttkb.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.canvas.bind_all("<MouseWheel>", self._on_wheel, add="+")

    def _on_inner(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, event):
        self.canvas.itemconfigure(self._win, width=event.width)

    def _on_wheel(self, event):
        # РљСЂСѓС‚РёРј С‚РѕР»СЊРєРѕ РµСЃР»Рё РєСѓСЂСЃРѕСЂ РІРЅСѓС‚СЂРё СЌС‚РѕР№ РѕР±Р»Р°СЃС‚Рё (РёРЅР°С‡Рµ РЅРµ РјРµС€Р°РµРј Р¶СѓСЂРЅР°Р»Сѓ)
        node = event.widget
        while node is not None:
            if node is self.canvas:
                self.canvas.yview_scroll(int(-event.delta / 120), "units")
                return
            node = getattr(node, "master", None)


class YTApp(ttkb.Window):
    def __init__(self):
        super().__init__(title="Media Downloader", size=(1000, 880), minsize=(900, 780))
        self._fit_to_screen()
        try:
            ico = resource_path("icon.ico")
            if os.path.exists(ico):
                self.iconbitmap(ico)
        except Exception:
            pass
        self._set_theme()
        self.downloader = MediaDownloader(progress_callback=self.on_progress)
        self.cookies_path: str | None = None
        self.is_downloading = False
        self.config = self._load_config()

        self._init_vars()
        self._build_ui()
        self._apply_config()
        self._ui_ready = True
        self._save_config()
        self._restore_geometry()
        self._check_ffmpeg()
        self._refresh_browser_list()
        saved = getattr(self, "_saved_browser", "Р±РµР· cookies")
        if saved and saved != "Р±РµР· cookies" and browser_reads_ok(saved):
            for label, key in self._browser_by_label.items():
                    if key == saved:
                        self.cmb_browser.set(label)
                        break
        self._refresh_browser_status()
        self._check_components()
        threading.Thread(target=self._autostart_pot, daemon=True).start()
        self._setup_shortcuts()
        self.bind("<FocusIn>", self._on_focus_in)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._log("Р“РѕС‚РѕРІРѕ. Р’СЃС‚Р°РІСЊС‚Рµ СЃСЃС‹Р»РєСѓ СЃ YouTube Рё РЅР°Р¶РјРёС‚Рµ В«РџРѕР»СѓС‡РёС‚СЊ РёРЅС„РѕСЂРјР°С†РёСЋВ»")
        self._check_updates_async()

    def _fit_to_screen(self):
        """РџРѕРґРіРѕРЅСЏРµС‚ РѕРєРЅРѕ РїРѕРґ СЌРєСЂР°РЅ, С‡С‚РѕР±С‹ РЅРёР¶РЅРёРµ РєРЅРѕРїРєРё РЅРµ СѓРµР·Р¶Р°Р»Рё Р·Р° РєСЂР°Р№."""
        try:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        except Exception:
            return
        w = min(1040, max(900, sw - 60))
        h = min(900, max(620, sh - 70))
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 3)
        self.minsize(900, min(780, h))
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _restore_geometry(self):
        """Р’РѕСЃСЃС‚Р°РЅР°РІР»РёРІР°РµС‚ СЂР°Р·РјРµСЂ Рё РїРѕР»РѕР¶РµРЅРёРµ РѕРєРЅР° РёР· РїСЂРѕС€Р»РѕРіРѕ Р·Р°РїСѓСЃРєР°."""
        geo = (self.config.get("geometry") or "").strip()
        if not geo:
            return
        m = re.match(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", geo)
        if not m:
            return
        try:
            w, h, x, y = (int(m.group(i)) for i in range(1, 5))
            if w < 900 or h < 780:
                return
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            x = max(-w + 120, min(x, sw - 120))
            y = max(0, min(y, sh - 120))
            self.minsize(900, min(780, h))
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def _set_theme(self):
        for name in ("bootstrap-dark", "darkly", "cyborg", "superhero"):
            try:
                self.style.theme_use(name)
                return
            except Exception:
                continue

    # ---------- config ----------

    def _load_config(self) -> dict:
        try:
            path = CONFIG_FILE if CONFIG_FILE.exists() else LEGACY_CONFIG_FILE
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _save_config(self):
        if not getattr(self, "_ui_ready", False):
            return
        try:
            data = {
                "output_dir": self.output_dir_var.get(),
                "audio_format": self.audio_format_var.get(),
                "audio_quality": self.audio_quality_var.get(),
                "restrict_filenames": self.restrict_names_var.get(),
                "skip_downloaded": self.skip_downloaded_var.get(),
                "archive_file": self.archive_var.get().strip(),
                "browser": self._active_browser() or "Р±РµР· cookies",
                "cookies_file": self.cookies_path or "",
                "proxy": self.proxy_var.get().strip(),
                "geometry": self.winfo_geometry(),
            }
            CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _apply_config(self):
        self.output_dir_var.set(self.config.get("output_dir", str(get_default_download_dir())))
        self.audio_format_var.set(self.config.get("audio_format", "mp3"))
        self.audio_quality_var.set(self.config.get("audio_quality", "192"))
        self.restrict_names_var.set(self.config.get("restrict_filenames", True))
        self.skip_downloaded_var.set(bool(self.config.get("skip_downloaded", False)))
        self.archive_var.set(self.config.get("archive_file") or str(DEFAULT_ARCHIVE_FILE))
        self._saved_browser = self.config.get("browser", "Р±РµР· cookies")
        self.proxy_var.set(self.config.get("proxy", ""))

        # Р’РѕСЃСЃС‚Р°РЅР°РІР»РёРІР°РµРј cookies.txt: РґР»СЏ РѕР±С‹С‡РЅС‹С… РїСѓР±Р»РёС‡РЅС‹С… РІРёРґРµРѕ РѕРЅРё РЅРµ РЅСѓР¶РЅС‹
        # (yt-dlp РёРґС‘С‚ Р°РЅРѕРЅРёРјРЅС‹Рј РєР»РёРµРЅС‚РѕРј), РЅРѕ РЅСѓР¶РЅС‹ РґР»СЏ РІРѕР·СЂР°СЃС‚РЅС‹С…/РїСЂРёРІР°С‚РЅС‹С… РІРёРґРµРѕ
        # Рё РґР»СЏ В«РїРѕРґС‚РІРµСЂРґРёС‚Рµ, С‡С‚Рѕ РІС‹ РЅРµ СЂРѕР±РѕС‚В».
        saved_cookies = self.config.get("cookies_file", "")
        if saved_cookies and Path(saved_cookies).is_file():
            self.cookies_path = saved_cookies
            self._apply_cookie_status(saved_cookies)
        else:
            self.cookies_path = None

    def _init_vars(self):
        v = tk.StringVar
        self.url_var = v()
        self.output_dir_var = v()
        self.format_var = v(value="best")
        self.audio_format_var = v(value="mp3")
        self.audio_quality_var = v(value="192")
        self.restrict_names_var = tk.BooleanVar(value=True)
        self.skip_downloaded_var = tk.BooleanVar(value=False)
        self.archive_var = v(value=str(DEFAULT_ARCHIVE_FILE))
        self.browser_var = v(value="Р±РµР· cookies")
        self.proxy_var = v()
        self._browser_by_label: dict[str, str | None] = {"Р±РµР· cookies": None}
        self._detected: list[tuple[str, str]] = []
        self.playlist_all_var = tk.BooleanVar(value=True)
        self.playlist_start_var = tk.IntVar(value=1)
        self.playlist_end_var = tk.IntVar(value=0)
        self.status_var = v(value="Р“РѕС‚РѕРІ Рє СЂР°Р±РѕС‚Рµ")
        self.speed_var = v(value="вЂ”")
        self.eta_var = v(value="вЂ”")
        self.size_var = v(value="вЂ”")
        self._last_clip = ""
        self._ui_ready = False

        # С„РѕСЂРјР°С‚-С‚Р°Р±Р»РёС†Р°
        self._fmt_map: dict[str, tuple[str, str]] = {}
        self._selected_format: str | None = None
        self._selected_audio_only = False
        self._selected_label = ""

        # РѕС‡РµСЂРµРґСЊ
        self.q_parallel_var = tk.IntVar(value=1)
        self.queue_items: list[dict] = []
        self._q_lock = threading.Lock()
        self._q_running = False
        self._q_stop = threading.Event()
        self._q_active: dict[int, MediaDownloader] = {}
        self._q_done_count = 0
        self._q_error_count = 0

    # ---------- ui ----------

    def _build_ui(self):
        try:
            bg = self.style.lookup("TFrame", "background") or "#2b3035"
        except Exception:
            bg = "#2b3035"

        header = ttkb.Frame(self, padding=(20, 10, 20, 8))
        header.pack(fill=X)
        brand = ttkb.Frame(header)
        brand.pack(side=LEFT)
        ttkb.Label(brand, text="Media Downloader", font=("Segoe UI Semibold", 16)).pack(side=LEFT)
        ttkb.Label(brand, text="РІРёРґРµРѕ В· Р°СѓРґРёРѕ В· РїР»РµР№Р»РёСЃС‚С‹", font=("Segoe UI", 9), bootstyle="secondary").pack(
            side=LEFT, padx=(12, 0), pady=(6, 0)
        )
        self.ffmpeg_badge = ttkb.Label(header, text="FFmpeg: РїСЂРѕРІРµСЂРєР°...", font=("Segoe UI", 8), bootstyle="warning")
        self.ffmpeg_badge.pack(side=RIGHT)

        ttkb.Separator(self).pack(fill=X, padx=20)

        url_box = ttkb.LabelFrame(self, text=" РЎСЃС‹Р»РєР° ", padding=(14, 10, 14, 10))
        url_box.pack(fill=X, padx=20, pady=(10, 8))
        row = ttkb.Frame(url_box)
        row.pack(fill=X)
        self.url_entry = ttkb.Entry(row, textvariable=self.url_var, font=("Segoe UI", 10))
        self.url_entry.pack(side=LEFT, fill=X, expand=True, ipady=4)
        self.url_entry.bind("<Return>", lambda e: self._get_info_async())
        ttkb.Button(row, text="Р’СЃС‚Р°РІРёС‚СЊ", width=10, bootstyle="light-outline", command=self._paste_url).pack(side=LEFT, padx=(8, 0))
        ttkb.Button(row, text="РћС‡РёСЃС‚РёС‚СЊ", width=10, bootstyle="light-outline", command=self._clear_url).pack(side=LEFT, padx=(6, 0))
        ttkb.Button(row, text="РџРѕР»СѓС‡РёС‚СЊ РёРЅС„РѕСЂРјР°С†РёСЋ", width=20, bootstyle="primary", command=self._get_info_async).pack(side=LEFT, padx=(6, 0))

        self.title_lbl = ttkb.Label(url_box, text="РќР°Р·РІР°РЅРёРµ: вЂ”", font=("Segoe UI", 9, "bold"), wraplength=860, justify=LEFT)
        self.title_lbl.pack(anchor="w", fill=X, pady=(10, 0))
        self.meta_lbl = ttkb.Label(url_box, text="Р”Р»РёС‚РµР»СЊРЅРѕСЃС‚СЊ: вЂ”    РљР°РЅР°Р»: вЂ”", font=("Segoe UI", 8), bootstyle="secondary", wraplength=860, justify=LEFT)
        self.meta_lbl.pack(anchor="w", fill=X, pady=(2, 0))

        self.nb = nb = ttkb.Notebook(self, padding=(0, 2))
        nb.pack(fill=X, padx=20)

        tab_fmt = ttkb.Frame(nb, padding=(16, 8, 16, 8))
        nb.add(tab_fmt, text="Р¤РѕСЂРјР°С‚")
        fbox = ttkb.LabelFrame(tab_fmt, text=" Р§С‚Рѕ СЃРєР°С‡РёРІР°С‚СЊ ", padding=(14, 8, 14, 8))
        fbox.pack(fill=X)
        self.rb_best = ttkb.Radiobutton(fbox, text="Р›СѓС‡С€РµРµ РєР°С‡РµСЃС‚РІРѕ вЂ” РІРёРґРµРѕ + Р°СѓРґРёРѕ (MP4)", variable=self.format_var, value="best", command=self._on_mode_change)
        self.rb_best.pack(anchor="w", pady=1)
        add_tooltip(self.rb_best, "РЎРєР°С‡Р°РµС‚ Р»СѓС‡С€РµРµ РґРѕСЃС‚СѓРїРЅРѕРµ РІРёРґРµРѕ Рё Р»СѓС‡С€СѓСЋ РґРѕСЂРѕР¶РєСѓ Р·РІСѓРєР°, Р·Р°С‚РµРј СЃРєР»РµРёС‚ РІ РѕРґРёРЅ MP4")
        self.rb_video = ttkb.Radiobutton(fbox, text="РўРѕР»СЊРєРѕ РІРёРґРµРѕ (Р±РµР· Р·РІСѓРєР°)", variable=self.format_var, value="bestvideo", command=self._on_mode_change)
        self.rb_video.pack(anchor="w", pady=1)
        self.rb_audio = ttkb.Radiobutton(fbox, text="РўРѕР»СЊРєРѕ Р°СѓРґРёРѕ", variable=self.format_var, value="bestaudio", command=self._on_mode_change)
        self.rb_audio.pack(anchor="w", pady=1)

        self.audio_box = ttkb.LabelFrame(tab_fmt, text=" РќР°СЃС‚СЂРѕР№РєРё Р°СѓРґРёРѕ ", padding=(14, 6, 14, 6))
        self.audio_box.pack(fill=X, pady=(6, 0))
        arow = ttkb.Frame(self.audio_box)
        arow.pack(fill=X)
        ttkb.Label(arow, text="Р¤РѕСЂРјР°С‚:", width=10).pack(side=LEFT)
        self.cmb_af = ttkb.Combobox(arow, values=["mp3", "m4a", "opus", "wav"], textvariable=self.audio_format_var, state="readonly", width=10)
        self.cmb_af.pack(side=LEFT, padx=(5, 0))
        self.cmb_af.bind("<<ComboboxSelected>>", lambda e: self._save_config())
        ttkb.Label(arow, text="Р‘РёС‚СЂРµР№С‚:", width=12).pack(side=LEFT, padx=(18, 0))
        self.cmb_aq = ttkb.Combobox(arow, values=["128", "160", "192", "256", "320"], textvariable=self.audio_quality_var, state="readonly", width=8)
        self.cmb_aq.pack(side=LEFT, padx=(5, 0))
        self.cmb_aq.bind("<<ComboboxSelected>>", lambda e: self._save_config())
        ttkb.Label(arow, text="kbps", bootstyle="secondary", font=("Segoe UI", 8)).pack(side=LEFT, padx=(6, 0))
        ttkb.Label(self.audio_box, text="mp3 вЂ” СѓРЅРёРІРµСЂСЃР°Р»СЊРЅС‹Р№ В· m4a вЂ” Apple В· opus вЂ” Р»СѓС‡С€РµРµ СЃР¶Р°С‚РёРµ В· wav вЂ” Р±РµР· РїРѕС‚РµСЂСЊ", bootstyle="secondary", font=("Segoe UI", 8)).pack(
            anchor="w", pady=(6, 0)
        )

        tblbox = ttkb.LabelFrame(tab_fmt, text=" РљРѕРЅРєСЂРµС‚РЅС‹Р№ С„РѕСЂРјР°С‚ вЂ” РІС‹Р±РµСЂРёС‚Рµ СЃС‚СЂРѕРєСѓ (РїРѕСЏРІРёС‚СЃСЏ РїРѕСЃР»Рµ В«РџРѕР»СѓС‡РёС‚СЊ РёРЅС„РѕСЂРјР°С†РёСЋВ») ", padding=(10, 6, 10, 6))
        tblbox.pack(fill=BOTH, expand=True, pady=(6, 0))
        cols = ("quality", "type", "codec", "fps", "size", "note")
        self.fmt_tree = ttkb.Treeview(tblbox, columns=cols, show="headings", height=5, bootstyle="light")
        for cid, text, w, anchor in (
            ("quality", "РљР°С‡РµСЃС‚РІРѕ", 110, "w"),
            ("type", "РўРёРї", 110, "w"),
            ("codec", "РљРѕРґРµРє", 150, "w"),
            ("fps", "FPS", 50, "center"),
            ("size", "Р Р°Р·РјРµСЂ", 100, "e"),
            ("note", "РџСЂРёРјРµС‡Р°РЅРёРµ", 240, "w"),
        ):
            self.fmt_tree.heading(cid, text=text)
            self.fmt_tree.column(cid, width=w, anchor=anchor, stretch=(cid == "note"))
        self.fmt_tree.pack(side=LEFT, fill=BOTH, expand=True)
        fsb = ttkb.Scrollbar(tblbox, orient=VERTICAL, command=self.fmt_tree.yview)
        fsb.pack(side=RIGHT, fill=Y)
        self.fmt_tree.configure(yscrollcommand=fsb.set)
        self.fmt_tree.bind("<<TreeviewSelect>>", self._on_format_select)
        self.fmt_lbl = ttkb.Label(tab_fmt, text="Р¤РѕСЂРјР°С‚ РЅРµ РІС‹Р±СЂР°РЅ вЂ” РёСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ РІС‹Р±РѕСЂ РІС‹С€Рµ.", bootstyle="secondary", font=("Segoe UI", 8))
        self.fmt_lbl.pack(anchor="w", pady=(4, 0))

        tab_q = ttkb.Frame(nb, padding=(16, 8, 16, 8))
        nb.add(tab_q, text="РћС‡РµСЂРµРґСЊ")

        qin = ttkb.LabelFrame(tab_q, text=" РЎСЃС‹Р»РєРё вЂ” РїРѕ РѕРґРЅРѕР№ РІ СЃС‚СЂРѕРєРµ ", padding=(12, 8, 12, 8))
        qin.pack(fill=X)
        self.queue_input = tk.Text(
            qin, height=3, wrap="none", font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4",
            insertbackground="white", borderwidth=0, padx=8, pady=6, relief="flat",
        )
        self.queue_input.pack(fill=X)
        qrow = ttkb.Frame(qin)
        qrow.pack(fill=X, pady=(6, 0))
        ttkb.Button(qrow, text="Р”РѕР±Р°РІРёС‚СЊ РІ РѕС‡РµСЂРµРґСЊ", width=20, bootstyle="primary", command=self._queue_add).pack(side=LEFT)
        ttkb.Button(qrow, text="РР· С„Р°Р№Р»Р°...", width=14, bootstyle="light-outline", command=self._queue_add_from_file).pack(side=LEFT, padx=(8, 0))
        ttkb.Button(qrow, text="Р’СЃС‚Р°РІРёС‚СЊ", width=12, bootstyle="light-outline", command=self._queue_paste).pack(side=LEFT, padx=(6, 0))
        ttkb.Label(qrow, text="РџР°СЂР°Р»Р»РµР»СЊРЅРѕ:", bootstyle="secondary", font=("Segoe UI", 8)).pack(side=RIGHT, padx=(0, 6))
        ttkb.Spinbox(qrow, from_=1, to=4, textvariable=self.q_parallel_var, width=4).pack(side=RIGHT)

        qlist = ttkb.LabelFrame(tab_q, text=" РћС‡РµСЂРµРґСЊ ", padding=(10, 6, 10, 6))
        qlist.pack(fill=BOTH, expand=True, pady=(6, 0))
        qcols = ("num", "title", "fmt", "status", "progress")
        self.queue_tree = ttkb.Treeview(qlist, columns=qcols, show="headings", height=5, bootstyle="light")
        for cid, text, w, anchor in (
            ("num", "в„–", 44, "center"),
            ("title", "РЎСЃС‹Р»РєР° / РЅР°Р·РІР°РЅРёРµ", 380, "w"),
            ("fmt", "Р¤РѕСЂРјР°С‚", 150, "w"),
            ("status", "РЎС‚Р°С‚СѓСЃ", 110, "center"),
            ("progress", "РџСЂРѕРіСЂРµСЃСЃ", 90, "center"),
        ):
            self.queue_tree.heading(cid, text=text)
            self.queue_tree.column(cid, width=w, anchor=anchor, stretch=(cid == "title"))
        self.queue_tree.pack(side=LEFT, fill=BOTH, expand=True)
        qsb = ttkb.Scrollbar(qlist, orient=VERTICAL, command=self.queue_tree.yview)
        qsb.pack(side=RIGHT, fill=Y)
        self.queue_tree.configure(yscrollcommand=qsb.set)
        self.queue_tree.tag_configure("done", foreground="#66bb6a")
        self.queue_tree.tag_configure("error", foreground="#ef5350")
        self.queue_tree.tag_configure("working", foreground="#42a5f5")

        qctrl = ttkb.Frame(tab_q)
        qctrl.pack(fill=X, pady=(6, 0))
        self.btn_q_start = ttkb.Button(qctrl, text="РЎРєР°С‡Р°С‚СЊ РІСЃС‘", width=16, bootstyle="success", command=self._queue_start)
        self.btn_q_start.pack(side=LEFT)
        self.btn_q_stop = ttkb.Button(qctrl, text="РћСЃС‚Р°РЅРѕРІРёС‚СЊ", width=14, bootstyle="danger", command=self._queue_stop, state="disabled")
        self.btn_q_stop.pack(side=LEFT, padx=(8, 0))
        ttkb.Button(qctrl, text="РЈРґР°Р»РёС‚СЊ РІС‹Р±СЂР°РЅРЅРѕРµ", width=18, bootstyle="light-outline", command=self._queue_remove_selected).pack(side=LEFT, padx=(8, 0))
        ttkb.Button(qctrl, text="РћС‡РёСЃС‚РёС‚СЊ", width=12, bootstyle="light-outline", command=self._queue_clear).pack(side=LEFT, padx=(8, 0))

        tab_pl = ttkb.Frame(nb, padding=(16, 8, 16, 8))
        nb.add(tab_pl, text="РџР»РµР№Р»РёСЃС‚")
        pbox = ttkb.LabelFrame(tab_pl, text=" Р”РёР°РїР°Р·РѕРЅ ", padding=(14, 8, 14, 8))
        pbox.pack(fill=X)
        ttkb.Radiobutton(pbox, text="Р’РµСЃСЊ РїР»РµР№Р»РёСЃС‚", variable=self.playlist_all_var, value=True, command=self._update_state).pack(anchor="w", pady=1)
        ttkb.Radiobutton(pbox, text="РўРѕР»СЊРєРѕ РІС‹Р±СЂР°РЅРЅС‹Рµ РІРёРґРµРѕ", variable=self.playlist_all_var, value=False, command=self._update_state).pack(anchor="w", pady=1)
        prow = ttkb.Frame(pbox)
        prow.pack(fill=X, pady=(6, 0))
        ttkb.Label(prow, text="РЎ РЅРѕРјРµСЂР°:", width=12).pack(side=LEFT)
        self.sp_start = ttkb.Spinbox(prow, from_=1, to=99999, textvariable=self.playlist_start_var, width=9, state="disabled")
        self.sp_start.pack(side=LEFT, padx=(5, 0))
        ttkb.Label(prow, text="РїРѕ РЅРѕРјРµСЂ:", width=11).pack(side=LEFT, padx=(14, 0))
        self.sp_end = ttkb.Spinbox(prow, from_=0, to=99999, textvariable=self.playlist_end_var, width=9, state="disabled")
        self.sp_end.pack(side=LEFT, padx=(5, 0))
        ttkb.Label(prow, text="(0 вЂ” РґРѕ РєРѕРЅС†Р°)", bootstyle="secondary", font=("Segoe UI", 8)).pack(side=LEFT, padx=(6, 0))
        ttkb.Label(tab_pl, text="Р”Р»СЏ РѕРґРёРЅРѕС‡РЅРѕРіРѕ РІРёРґРµРѕ СЌС‚Рё РЅР°СЃС‚СЂРѕР№РєРё РёРіРЅРѕСЂРёСЂСѓСЋС‚СЃСЏ.", bootstyle="secondary", font=("Segoe UI", 8)).pack(anchor="w", pady=(6, 0))

        tab_set = ttkb.Frame(nb)
        nb.add(tab_set, text="РќР°СЃС‚СЂРѕР№РєРё")
        _settings_scroll = VScroll(tab_set, height=150, bg=bg)
        _settings_scroll.pack(fill=BOTH, expand=True)
        tab_set = ttkb.Frame(_settings_scroll.inner, padding=(14, 10, 14, 10))
        tab_set.pack(fill=BOTH, expand=True)

        obox = ttkb.LabelFrame(tab_set, text="РџР°РїРєР° СЃРѕС…СЂР°РЅРµРЅРёСЏ", padding=(14, 10, 14, 10))
        obox.pack(fill=X)
        orow = ttkb.Frame(obox)
        orow.pack(fill=X)
        ttkb.Entry(orow, textvariable=self.output_dir_var).pack(side=LEFT, fill=X, expand=True, ipady=3)
        ttkb.Button(orow, text="РћР±Р·РѕСЂ...", width=11, bootstyle="light-outline", command=self._browse_dir).pack(side=LEFT, padx=(8, 0))
        ttkb.Button(orow, text="РћС‚РєСЂС‹С‚СЊ", width=11, bootstyle="light-outline", command=self._open_dir).pack(side=LEFT, padx=(6, 0))

        nbox = ttkb.LabelFrame(tab_set, text="РРјРµРЅР° С„Р°Р№Р»РѕРІ", padding=(14, 10, 14, 10))
        nbox.pack(fill=X, pady=(10, 0))
        ttkb.Checkbutton(
            nbox,
            text="РћРіСЂР°РЅРёС‡РёС‚СЊ РЅРµРґРѕРїСѓСЃС‚РёРјС‹Рµ СЃРёРјРІРѕР»С‹ (СЂРµРєРѕРјРµРЅРґСѓРµС‚СЃСЏ)",
            variable=self.restrict_names_var,
            command=self._save_config,
        ).pack(anchor="w")

        dbox = ttkb.LabelFrame(tab_set, text="РђСЂС…РёРІ Р·Р°РіСЂСѓР·РѕРє вЂ” РЅРµ РєР°С‡Р°С‚СЊ РїРѕРІС‚РѕСЂРЅРѕ", padding=(14, 10, 14, 10))
        dbox.pack(fill=X, pady=(10, 0))
        ttkb.Checkbutton(
            dbox,
            text="РџСЂРѕРїСѓСЃРєР°С‚СЊ СѓР¶Рµ СЃРєР°С‡Р°РЅРЅРѕРµ (РІРµРґС‘С‚СЃСЏ СЃРїРёСЃРѕРє СЃРєР°С‡Р°РЅРЅС‹С… СЂРѕР»РёРєРѕРІ)",
            variable=self.skip_downloaded_var,
            command=self._save_config,
        ).pack(anchor="w")
        darow = ttkb.Frame(dbox)
        darow.pack(fill=X, pady=(8, 0))
        ttkb.Entry(darow, textvariable=self.archive_var).pack(side=LEFT, fill=X, expand=True, ipady=3)
        ttkb.Button(darow, text="РћР±Р·РѕСЂ...", width=11, bootstyle="light-outline", command=self._browse_archive).pack(
            side=LEFT, padx=(8, 0)
        )
        ttkb.Label(
            dbox,
            text="РЎРїРёСЃРѕРє С…СЂР°РЅРёС‚СЃСЏ РІ РѕС‚РґРµР»СЊРЅРѕРј С„Р°Р№Р»Рµ. РџРѕРІС‚РѕСЂРЅС‹Р№ Р·Р°РїСѓСЃРє С‚РµС… Р¶Рµ СЃСЃС‹Р»РѕРє РёР»Рё РїР»РµР№Р»РёСЃС‚Р° РЅРµ СЃРєР°С‡Р°РµС‚ РёС… Р·Р°РЅРѕРІРѕ.",
            bootstyle="secondary",
            font=("Segoe UI", 8),
            wraplength=820,
            justify=LEFT,
        ).pack(anchor="w", pady=(8, 0))

        cbox = ttkb.LabelFrame(tab_set, text="Cookies вЂ” РґР»СЏ РІРѕР·СЂР°СЃС‚РЅС‹С… Рё РїСЂРёРІР°С‚РЅС‹С… РІРёРґРµРѕ", padding=(14, 10, 14, 10))
        cbox.pack(fill=X, pady=(10, 0))
        crow = ttkb.Frame(cbox)
        crow.pack(fill=X)
        self.cookie_lbl = ttkb.Label(crow, text="Cookies РЅРµ Р·Р°РіСЂСѓР¶РµРЅС‹", bootstyle="secondary")
        self.cookie_lbl.pack(side=LEFT, fill=X, expand=True)
        ttkb.Button(crow, text="Р—Р°РіСЂСѓР·РёС‚СЊ", width=12, bootstyle="light-outline", command=self._load_cookies).pack(side=LEFT, padx=(6, 0))
        ttkb.Button(crow, text="РЈРґР°Р»РёС‚СЊ", width=12, bootstyle="light-outline", command=self._clear_cookies).pack(side=LEFT, padx=(6, 0))
        ttkb.Label(
            cbox,
            text="Р¤РѕСЂРјР°С‚ Netscape (.txt). Р­РєСЃРїРѕСЂС‚РёСЂСѓРµС‚СЃСЏ СЂР°СЃС€РёСЂРµРЅРёСЏРјРё Cookie-Editor РёР»Рё В«Get cookies.txt LOCALLYВ». Р¤Р°Р№Р» С…СЂР°РЅРёС‚СЃСЏ С‚РѕР»СЊРєРѕ РЅР° СЌС‚РѕРј РєРѕРјРїСЊСЋС‚РµСЂРµ.",
            bootstyle="secondary",
            font=("Segoe UI", 8),
            wraplength=820,
            justify=LEFT,
        ).pack(anchor="w", pady=(8, 0))

        bbox = ttkb.LabelFrame(cbox, text="РР»Рё РІР·СЏС‚СЊ cookies РїСЂСЏРјРѕ РёР· Р±СЂР°СѓР·РµСЂР°", padding=(14, 10, 14, 10))
        bbox.pack(fill=X, pady=(10, 0))
        brow = ttkb.Frame(bbox)
        brow.pack(fill=X)
        ttkb.Label(brow, text="Р‘СЂР°СѓР·РµСЂ:", width=12).pack(side=LEFT)
        self.cmb_browser = ttkb.Combobox(
            brow,
            values=["Р±РµР· cookies"],
            textvariable=self.browser_var,
            state="readonly",
            width=16,
        )
        self.cmb_browser.pack(side=LEFT, padx=(5, 0))
        self.cmb_browser.bind("<<ComboboxSelected>>", lambda e: self._refresh_browser_status())
        ttkb.Button(brow, text="РћР±РЅРѕРІРёС‚СЊ", width=12, bootstyle="light-outline", command=self._refresh_browser_list).pack(side=LEFT, padx=(8, 0))
        ttkb.Button(brow, text="РЎР±СЂРѕСЃРёС‚СЊ", width=12, bootstyle="light-outline", command=self._reset_browser).pack(side=LEFT, padx=(6, 0))
        self.browser_status = ttkb.Label(
            bbox,
            text="",
            bootstyle="warning",
            font=("Segoe UI", 8),
            wraplength=820,
            justify=LEFT,
        )
        self.browser_status.pack(anchor="w", pady=(8, 0))
        ttkb.Label(
            bbox,
            text="Р’Р°Р¶РЅРѕ: Р±СЂР°СѓР·РµСЂ РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ РџРћР›РќРћРЎРўР¬Р® Р·Р°РєСЂС‹С‚, РёРЅР°С‡Рµ С„Р°Р№Р» cookies Р·Р°Р±Р»РѕРєРёСЂРѕРІР°РЅ Рё Р±СѓРґРµС‚ РѕС€РёР±РєР° В«Could not copy cookie databaseВ».",
            bootstyle="secondary",
            font=("Segoe UI", 8),
            wraplength=820,
            justify=LEFT,
        ).pack(anchor="w", pady=(6, 0))

        fbox2 = ttkb.LabelFrame(tab_set, text="FFmpeg", padding=(14, 10, 14, 10))
        fbox2.pack(fill=X, pady=(10, 0))
        self.ffmpeg_lbl = ttkb.Label(fbox2, text="FFmpeg: РїСЂРѕРІРµСЂРєР°...", wraplength=820, justify=LEFT)
        self.ffmpeg_lbl.pack(anchor="w")
        frow = ttkb.Frame(fbox2)
        frow.pack(fill=X, pady=(8, 0))
        ttkb.Button(frow, text="РџСЂРѕРІРµСЂРёС‚СЊ", width=13, bootstyle="light-outline", command=self._check_ffmpeg).pack(side=LEFT)
        ttkb.Button(frow, text="РЎРєР°С‡Р°С‚СЊ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё", width=24, bootstyle="light-outline", command=self._download_ffmpeg_async).pack(side=LEFT, padx=(8, 0))
        ttkb.Label(
            fbox2,
            text="РћР±СЏР·Р°С‚РµР»РµРЅ РґР»СЏ СЃРєР»РµР№РєРё РІРёРґРµРѕ+Р°СѓРґРёРѕ (1080p Рё РІС‹С€Рµ) Рё РєРѕРЅРІРµСЂС‚Р°С†РёРё РІ MP3/M4A/Opus.",
            bootstyle="secondary",
            font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(8, 0))

        kbox = ttkb.LabelFrame(tab_set, text="РљРѕРјРїРѕРЅРµРЅС‚С‹ РґР»СЏ СЂР°Р±РѕС‚С‹ СЃ YouTube", padding=(14, 10, 14, 10))
        kbox.pack(fill=X, pady=(10, 0))
        self.deno_lbl = ttkb.Label(kbox, text="Deno: РїСЂРѕРІРµСЂРєР°...", wraplength=820, justify=LEFT)
        self.deno_lbl.pack(anchor="w")
        self.pot_lbl = ttkb.Label(kbox, text="PO Token: РїСЂРѕРІРµСЂРєР°...", wraplength=820, justify=LEFT)
        self.pot_lbl.pack(anchor="w", pady=(4, 0))
        krow = ttkb.Frame(kbox)
        krow.pack(fill=X, pady=(8, 0))
        ttkb.Button(krow, text="РџСЂРѕРІРµСЂРёС‚СЊ", width=13, bootstyle="light-outline", command=self._check_components).pack(side=LEFT)
        ttkb.Button(krow, text="РЈСЃС‚Р°РЅРѕРІРёС‚СЊ Deno", width=20, bootstyle="light-outline", command=self._install_deno_async).pack(side=LEFT, padx=(8, 0))
        ttkb.Button(krow, text="РЈСЃС‚Р°РЅРѕРІРёС‚СЊ PO Token", width=24, bootstyle="light-outline", command=self._install_pot_async).pack(side=LEFT, padx=(8, 0))
        ttkb.Label(
            kbox,
            text=(
                "YouTube С‚СЂРµР±СѓРµС‚ PO Token Рё JavaScript-С‡РµР»Р»РµРЅРґР¶. Р‘РµР· РЅРёС… вЂ” РѕС€РёР±РєР° В«The page needs to be reloadedВ».\n"
                "Deno СЃС‚Р°РІРёС‚СЃСЏ С‡РµСЂРµР· winget. PO Token вЂ” Р»РѕРєР°Р»СЊРЅС‹Р№ Node.js-СЃРµСЂРІРµСЂ (~165 РњР‘, СЃС‚Р°РІРёС‚СЃСЏ РѕРґРёРЅ СЂР°Р·, РЅСѓР¶РµРЅ Node.js Рё Git).\n"
                "РќСѓР¶РЅС‹ С‚РѕР»СЊРєРѕ РґР»СЏ Р·Р°С‰РёС‰С‘РЅРЅС‹С… РІРёРґРµРѕ; РґР»СЏ РѕС‚РєСЂС‹С‚С‹С… С‡Р°СЃС‚Рѕ СЂР°Р±РѕС‚Р°РµС‚ Рё Р±РµР· РЅРёС…."
            ),
            bootstyle="secondary",
            font=("Segoe UI", 8),
            wraplength=820,
            justify=LEFT,
        ).pack(anchor="w", pady=(8, 0))

        netbox = ttkb.LabelFrame(tab_set, text="РЎРµС‚СЊ Рё РїСЂРѕРєСЃРё вЂ” РѕР±С…РѕРґ Р±Р»РѕРєРёСЂРѕРІРєРё YouTube", padding=(14, 10, 14, 10))
        netbox.pack(fill=X, pady=(10, 0))
        nrow = ttkb.Frame(netbox)
        nrow.pack(fill=X)
        ttkb.Label(nrow, text="РџСЂРѕРєСЃРё:", width=10).pack(side=LEFT)
        ttkb.Entry(nrow, textvariable=self.proxy_var, font=("Segoe UI", 9)).pack(side=LEFT, fill=X, expand=True, ipady=3)
        ttkb.Button(nrow, text="РџСЂРѕРІРµСЂРёС‚СЊ СЃРµС‚СЊ", width=16, bootstyle="light-outline", command=self._check_network_async).pack(
            side=LEFT, padx=(8, 0)
        )
        ttkb.Button(nrow, text="РЎРѕС…СЂР°РЅРёС‚СЊ", width=12, bootstyle="light-outline", command=self._save_config).pack(
            side=LEFT, padx=(6, 0)
        )
        self.net_lbl = ttkb.Label(
            netbox,
            text="РќР°Р¶РјРёС‚Рµ В«РџСЂРѕРІРµСЂРёС‚СЊ СЃРµС‚СЊВ», С‡С‚РѕР±С‹ СѓР·РЅР°С‚СЊ, РґРѕСЃС‚СѓРїРµРЅ Р»Рё YouTube РЅР°РїСЂСЏРјСѓСЋ.",
            bootstyle="secondary",
            font=("Segoe UI", 8),
            wraplength=820,
            justify=LEFT,
        )
        self.net_lbl.pack(anchor="w", pady=(8, 0))
        ttkb.Label(
            netbox,
            text=(
                "Р’ Р РѕСЃСЃРёРё YouTube С‡Р°СЃС‚Рѕ Р±Р»РѕРєРёСЂСѓРµС‚СЃСЏ РїРѕ РёРјРµРЅРё РґРѕРјРµРЅР° (SNI/DPI): СЃР°Р№С‚ РЅРµ РѕС‚РєСЂС‹РІР°РµС‚СЃСЏ, С…РѕС‚СЏ РёРЅС‚РµСЂРЅРµС‚ СЂР°Р±РѕС‚Р°РµС‚.\n"
                "РџСЂРѕРіСЂР°РјРјР° РІ СЌС‚РѕРј СЃР»СѓС‡Р°Рµ РєР°С‡Р°С‚СЊ РЅРµ СЃРјРѕР¶РµС‚ вЂ” РЅРё РѕРґРёРЅ Р»РѕРєР°Р»СЊРЅС‹Р№ Р·Р°РіСЂСѓР·С‡РёРє РЅРµ СЃРјРѕР¶РµС‚. РџРѕРјРѕРіР°РµС‚ VPN РёР»Рё РїСЂРѕРєСЃРё.\n"
                "Р¤РѕСЂРјР°С‚ РїСЂРѕРєСЃРё: http://С…РѕСЃС‚:РїРѕСЂС‚, socks5://С…РѕСЃС‚:РїРѕСЂС‚ РёР»Рё http://Р»РѕРіРёРЅ:РїР°СЂРѕР»СЊ@С…РѕСЃС‚:РїРѕСЂС‚. РџСѓСЃС‚Рѕ вЂ” РїСЂСЏРјРѕРµ РїРѕРґРєР»СЋС‡РµРЅРёРµ."
            ),
            bootstyle="secondary",
            font=("Segoe UI", 8),
            wraplength=820,
            justify=LEFT,
        ).pack(anchor="w", pady=(6, 0))

        ubox = ttkb.LabelFrame(tab_set, text="РћР±РЅРѕРІР»РµРЅРёРµ yt-dlp", padding=(14, 10, 14, 10))
        ubox.pack(fill=X, pady=(10, 0))
        self.ytdlp_lbl2 = ttkb.Label(ubox, text="yt-dlp: РїСЂРѕРІРµСЂРєР°...", wraplength=820, justify=LEFT)
        self.ytdlp_lbl2.pack(anchor="w")
        urow = ttkb.Frame(ubox)
        urow.pack(fill=X, pady=(8, 0))
        ttkb.Button(urow, text="РџСЂРѕРІРµСЂРёС‚СЊ РѕР±РЅРѕРІР»РµРЅРёСЏ", width=20, bootstyle="light-outline", command=self._check_updates_async).pack(
            side=LEFT
        )
        ttkb.Button(urow, text="РћР±РЅРѕРІРёС‚СЊ yt-dlp", width=18, bootstyle="light-outline", command=self._update_ytdlp_async).pack(
            side=LEFT, padx=(8, 0)
        )
        ttkb.Label(
            ubox,
            text=(
                "YouTube С‡Р°СЃС‚Рѕ РјРµРЅСЏРµС‚СЃСЏ, Рё СЃРІРµР¶РёР№ yt-dlp РЅРµСЂРµРґРєРѕ СЂРµС€Р°РµС‚ РѕС€РёР±РєРё Р·Р°РіСЂСѓР·РєРё.\n"
                "Р’ СЃРѕР±СЂР°РЅРЅРѕРј .exe yt-dlp РІС€РёС‚ РІРЅСѓС‚СЂРё вЂ” С‚Р°Рј РѕР±РЅРѕРІР»РµРЅРёРµ РІС‹С…РѕРґРёС‚ РЅРѕРІРѕР№ РІРµСЂСЃРёРµР№ РїСЂРѕРіСЂР°РјРјС‹."
            ),
            bootstyle="secondary",
            font=("Segoe UI", 8),
            wraplength=820,
            justify=LEFT,
        ).pack(anchor="w", pady=(8, 0))

        pbox2 = ttkb.LabelFrame(self, text=" РџСЂРѕРіСЂРµСЃСЃ ", padding=(16, 8, 16, 8))
        pbox2.pack(fill=X, padx=20, pady=(8, 0))
        self.progress_bar = ttkb.Progressbar(pbox2, orient=HORIZONTAL, mode="determinate", maximum=100, value=0)
        self.progress_bar.pack(fill=X)
        irow = ttkb.Frame(pbox2)
        irow.pack(fill=X, pady=(7, 0))
        self.percent_lbl = ttkb.Label(irow, text="0%", font=("Segoe UI", 9, "bold"), width=6)
        self.percent_lbl.pack(side=LEFT)
        ttkb.Label(irow, textvariable=self.speed_var, bootstyle="secondary", font=("Segoe UI", 8)).pack(side=LEFT, padx=(10, 0))
        ttkb.Label(irow, textvariable=self.eta_var, bootstyle="secondary", font=("Segoe UI", 8)).pack(side=LEFT, padx=(10, 0))
        ttkb.Label(irow, textvariable=self.size_var, bootstyle="secondary", font=("Segoe UI", 8)).pack(side=LEFT, padx=(10, 0))
        self.fname_lbl = ttkb.Label(irow, text="вЂ”", bootstyle="secondary", font=("Segoe UI", 8), wraplength=380, justify=RIGHT)
        self.fname_lbl.pack(side=RIGHT, fill=X, expand=True)
        self.status_lbl = ttkb.Label(pbox2, textvariable=self.status_var, bootstyle="info")
        self.status_lbl.pack(anchor="w", pady=(6, 0))

        # РќРёР¶РЅСЏСЏ РїР°РЅРµР»СЊ С†РµРїР»СЏРµС‚СЃСЏ Рє РЅРёР·Сѓ РѕРєРЅР° Рё РЅРёРєРѕРіРґР° РЅРµ СѓРµР·Р¶Р°РµС‚ Р·Р° СЌРєСЂР°РЅ
        arow2 = ttkb.Frame(self, padding=(20, 8, 20, 12))
        arow2.pack(side=BOTTOM, fill=X)
        self.btn_download = ttkb.Button(arow2, text="РЎРєР°С‡Р°С‚СЊ", width=16, bootstyle="success", command=self._download_async)
        self.btn_download.pack(side=LEFT)
        self.btn_stop = ttkb.Button(arow2, text="РћСЃС‚Р°РЅРѕРІРёС‚СЊ", width=16, bootstyle="danger", command=self._stop_download, state="disabled")
        self.btn_stop.pack(side=LEFT, padx=(8, 0))
        ttkb.Button(arow2, text="РћС‡РёСЃС‚РёС‚СЊ Р»РѕРі", width=14, bootstyle="light-outline", command=self._clear_log).pack(side=LEFT, padx=(8, 0))
        ttkb.Button(arow2, text="РџР°РїРєР° Р·Р°РіСЂСѓР·РѕРє", bootstyle="light-outline", command=self._open_dir).pack(side=LEFT, padx=(8, 0))
        self.ytdlp_lbl = ttkb.Label(arow2, text="yt-dlp: ...", bootstyle="secondary", font=("Segoe UI", 8))
        self.ytdlp_lbl.pack(side=RIGHT, padx=(10, 0))

        lbox = ttkb.LabelFrame(self, text=" Р–СѓСЂРЅР°Р» ", padding=(12, 8, 12, 8))
        lbox.pack(fill=BOTH, expand=True, padx=20, pady=(10, 10))
        self.log_text = tk.Text(lbox, height=6, wrap="word", font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4", insertbackground="white", borderwidth=0, padx=10, pady=8, relief="flat")
        self.log_text.pack(side=LEFT, fill=BOTH, expand=True)
        sb = ttkb.Scrollbar(lbox, orient=VERTICAL, command=self.log_text.yview)
        sb.pack(side=RIGHT, fill=Y)
        self.log_text.configure(yscrollcommand=sb.set, state="disabled")

        self._update_state()

    def _update_state(self):
        state = "disabled" if self.playlist_all_var.get() else "normal"
        self.sp_start.configure(state=state)
        self.sp_end.configure(state=state)
        self._save_config()

    # ---------- С„РѕСЂРјР°С‚С‹ ----------

    def _on_mode_change(self):
        self._selected_format = None
        self._selected_audio_only = False
        self._selected_label = ""
        try:
            sel = self.fmt_tree.selection()
            if sel:
                self.fmt_tree.selection_remove(*sel)
        except Exception:
            pass
        try:
            self.fmt_lbl.config(text="Р¤РѕСЂРјР°С‚ РЅРµ РІС‹Р±СЂР°РЅ вЂ” РёСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ РІС‹Р±РѕСЂ РІС‹С€Рµ.", bootstyle="secondary")
        except Exception:
            pass
        self._update_state()

    def _current_mode(self):
        """Р’РѕР·РІСЂР°С‰Р°РµС‚ (mode, custom_format, custom_audio_only) РґР»СЏ Р·Р°РіСЂСѓР·РєРё."""
        if self._selected_format:
            return "custom", self._selected_format, self._selected_audio_only
        mode = {"best": "best", "bestvideo": "video", "bestaudio": "audio"}.get(self.format_var.get(), "best")
        return mode, None, False

    @staticmethod
    def _pick_format_source(info: dict) -> dict | None:
        if info.get("entries"):
            for e in info["entries"]:
                if e and e.get("formats"):
                    return e
            return None
        return info

    def _add_fmt_row(self, quality, typ, codec, fps, size, note, fmt, kind):
        if not fmt:
            return
        iid = self.fmt_tree.insert("", "end", values=(quality, typ, codec, fps, size, note))
        self._fmt_map[iid] = (str(fmt), kind)

    def _populate_formats(self, info: dict):
        for iid in self.fmt_tree.get_children():
            self.fmt_tree.delete(iid)
        self._fmt_map = {}
        self._selected_format = None
        self._selected_audio_only = False
        self._selected_label = ""

        if not info:
            self.fmt_lbl.config(text="Р¤РѕСЂРјР°С‚ РЅРµ РІС‹Р±СЂР°РЅ вЂ” РёСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ РІС‹Р±РѕСЂ РІС‹С€Рµ.", bootstyle="secondary")
            return

        src = self._pick_format_source(info or {})
        fmts = (src or {}).get("formats") or []
        if not fmts:
            self.fmt_lbl.config(text="Р¤РѕСЂРјР°С‚С‹ РЅРµРґРѕСЃС‚СѓРїРЅС‹ РґР»СЏ СЌС‚РѕР№ СЃСЃС‹Р»РєРё.", bootstyle="warning")
            return

        def size_of(f):
            return f.get("filesize") or f.get("filesize_approx") or 0

        video = [f for f in fmts if f.get("vcodec") not in (None, "none")]
        audio_only = [f for f in fmts if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")]
        heights = sorted({f.get("height") for f in video if f.get("height")}, reverse=True)
        best_audio = max(audio_only, key=size_of) if audio_only else None

        self._add_fmt_row("Р›СѓС‡С€РµРµ", "РІРёРґРµРѕ+Р°СѓРґРёРѕ", "Р°РІС‚Рѕ", "", "", "СЃР°РјРѕРµ РІС‹СЃРѕРєРѕРµ РґРѕСЃС‚СѓРїРЅРѕРµ", "bv*+ba/b", "merge")

        for h in heights:
            cands = [f for f in video if f.get("height") == h]
            v = max(cands, key=size_of)
            fps = v.get("fps")
            codec = f'{v.get("ext", "?")} В· {str(v.get("vcodec", "?")).split(".")[0]}'
            total = size_of(v) + (size_of(best_audio) if best_audio else 0)
            self._add_fmt_row(
                f"{h}p", "РІРёРґРµРѕ+Р°СѓРґРёРѕ", codec,
                f"{fps:.0f}" if fps else "",
                format_bytes(total) if total else "",
                "СЃРєР»РµР№РєР° РІ MP4",
                f"bv*[height<={h}]+ba/b[height<={h}]", "merge",
            )

        for f in sorted(video, key=lambda x: (x.get("height") or 0, size_of(x)), reverse=True):
            h = f.get("height")
            codec = f'{f.get("ext", "?")} В· {str(f.get("vcodec", "?")).split(".")[0]}'
            fps = f.get("fps")
            self._add_fmt_row(
                f"{h}p" if h else "РІРёРґРµРѕ", "РІРёРґРµРѕ (Р±РµР· Р·РІСѓРєР°)", codec,
                f"{fps:.0f}" if fps else "",
                format_bytes(size_of(f)) if size_of(f) else "",
                f.get("format_note") or "",
                f.get("format_id"), "video",
            )

        for f in sorted(audio_only, key=size_of, reverse=True)[:12]:
            codec = f'{f.get("ext", "?")} В· {str(f.get("acodec", "?")).split(".")[0]}'
            abr = f.get("abr")
            note = f"{abr:.0f} kbps" if abr else (f.get("format_note") or "")
            self._add_fmt_row(
                "Р°СѓРґРёРѕ", "Р°СѓРґРёРѕ", codec, "",
                format_bytes(size_of(f)) if size_of(f) else "",
                note, f.get("format_id"), "audio",
            )

        self.fmt_lbl.config(
            text=f"Р’РёРґРµРѕ-С„РѕСЂРјР°С‚РѕРІ: {len(video)}, Р°СѓРґРёРѕ: {len(audio_only)}. Р’С‹Р±РµСЂРёС‚Рµ СЃС‚СЂРѕРєСѓ вЂ” РѕРЅР° Р±СѓРґРµС‚ РёСЃРїРѕР»СЊР·РѕРІР°РЅР° РїСЂРё Р·Р°РіСЂСѓР·РєРµ.",
            bootstyle="secondary",
        )

    def _on_format_select(self, _event=None):
        sel = self.fmt_tree.selection()
        if not sel:
            return
        data = self._fmt_map.get(sel[0])
        if not data:
            return
        self._selected_format, kind = data
        self._selected_audio_only = (kind == "audio")
        self._selected_label = self.fmt_tree.set(sel[0], "quality")
        self.fmt_lbl.config(
            text=f"Р’С‹Р±СЂР°РЅ С„РѕСЂРјР°С‚: {self._selected_label} ({kind}). Р‘СѓРґРµС‚ РёСЃРїРѕР»СЊР·РѕРІР°РЅ РїСЂРё Р·Р°РіСЂСѓР·РєРµ.",
            bootstyle="success",
        )
        self._log(f"Р’С‹Р±СЂР°РЅ С„РѕСЂРјР°С‚: {self._selected_label} [{self._selected_format}]")

    # ---------- РѕС‡РµСЂРµРґСЊ ----------

    def _queue_paste(self):
        try:
            text = self.clipboard_get().strip()
        except Exception:
            return
        if not text:
            return
        cur = self.queue_input.get("1.0", "end").strip()
        self.queue_input.insert("end", ("\n" if cur else "") + text)

    def _queue_add(self):
        lines = [l.strip() for l in self.queue_input.get("1.0", "end").splitlines() if l.strip()]
        if not lines:
            messagebox.showinfo("РћС‡РµСЂРµРґСЊ", "Р’СЃС‚Р°РІСЊС‚Рµ С…РѕС‚СЏ Р±С‹ РѕРґРЅСѓ СЃСЃС‹Р»РєСѓ.")
            return
        added = sum(1 for url in lines if self._queue_append(url))
        self.queue_input.delete("1.0", "end")
        if added:
            self._log(f"Р’ РѕС‡РµСЂРµРґСЊ РґРѕР±Р°РІР»РµРЅРѕ СЃСЃС‹Р»РѕРє: {added}")
            self.status_var.set(f"Р’ РѕС‡РµСЂРµРґРё: {len(self.queue_items)}")

    def _queue_add_from_file(self):
        chosen = filedialog.askopenfilename(title="Р¤Р°Р№Р» СЃРѕ СЃСЃС‹Р»РєР°РјРё", filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not chosen:
            return
        try:
            lines = Path(chosen).read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception as e:
            messagebox.showerror("РћС‡РµСЂРµРґСЊ", f"РќРµ СѓРґР°Р»РѕСЃСЊ РїСЂРѕС‡РёС‚Р°С‚СЊ С„Р°Р№Р»:\n{e}")
            return
        added = 0
        for line in lines:
            url = line.strip()
            if url and not url.startswith("#") and self._queue_append(url):
                added += 1
        self._log(f"РР· С„Р°Р№Р»Р° РґРѕР±Р°РІР»РµРЅРѕ СЃСЃС‹Р»РѕРє: {added}")

    def _queue_append(self, url: str) -> bool:
        mode, custom_format, audio_only = self._current_mode()
        if custom_format:
            label = self._selected_label or "С„РѕСЂРјР°С‚"
        else:
            label = {"best": "Р›СѓС‡С€РµРµ", "video": "Р’РёРґРµРѕ", "audio": "РђСѓРґРёРѕ"}.get(mode, mode)
        num = len(self.queue_items) + 1
        iid = self.queue_tree.insert("", "end", values=(num, url[:90], label, "РѕР¶РёРґР°РЅРёРµ", "0%"))
        self.queue_items.append({
            "num": num,
            "url": url,
            "title": url,
            "status": "РѕР¶РёРґР°РЅРёРµ",
            "percent": 0.0,
            "error": "",
            "mode": mode,
            "custom_format": custom_format,
            "audio_only": audio_only,
            "audio_format": self.audio_format_var.get(),
            "audio_quality": self.audio_quality_var.get(),
            "start": max(1, self.playlist_start_var.get() or 1),
            "end": 0 if self.playlist_all_var.get() else max(0, self.playlist_end_var.get() or 0),
            "fmt_label": label,
            "iid": iid,
        })
        return True

    def _queue_update_row(self, item: dict):
        try:
            st = item["status"]
            tags = ()
            if st == "РіРѕС‚РѕРІРѕ":
                tags = ("done",)
            elif st == "РѕС€РёР±РєР°":
                tags = ("error",)
            elif st in ("Р·Р°РіСЂСѓР·РєР°", "РёРЅС„Рѕ", "СЃС‚Р°СЂС‚", "СЃРєР»РµР№РєР°"):
                tags = ("working",)
            self.queue_tree.item(
                item["iid"],
                values=(
                    item.get("num", ""),
                    (item.get("title") or item["url"])[:90],
                    item.get("fmt_label", "вЂ”"),
                    st,
                    f"{item.get('percent', 0.0):.0f}%",
                ),
                tags=tags,
            )
        except Exception:
            pass

    def _queue_post(self, item: dict):
        self.after(0, lambda it=item: self._queue_update_row(it))

    def _queue_renumber(self):
        for i, it in enumerate(self.queue_items, 1):
            it["num"] = i
            self._queue_update_row(it)

    def _queue_clear(self):
        if self._q_running:
            messagebox.showinfo("РћС‡РµСЂРµРґСЊ", "РЎРЅР°С‡Р°Р»Р° РѕСЃС‚Р°РЅРѕРІРёС‚Рµ Р·Р°РіСЂСѓР·РєСѓ.")
            return
        for iid in self.queue_tree.get_children():
            self.queue_tree.delete(iid)
        self.queue_items.clear()
        self._log("РћС‡РµСЂРµРґСЊ РѕС‡РёС‰РµРЅР°")

    def _queue_remove_selected(self):
        if self._q_running:
            messagebox.showinfo("РћС‡РµСЂРµРґСЊ", "РЎРЅР°С‡Р°Р»Р° РѕСЃС‚Р°РЅРѕРІРёС‚Рµ Р·Р°РіСЂСѓР·РєСѓ.")
            return
        sel = set(self.queue_tree.selection())
        if not sel:
            return
        for it in list(self.queue_items):
            if it["iid"] in sel:
                self.queue_items.remove(it)
        for iid in sel:
            try:
                self.queue_tree.delete(iid)
            except Exception:
                pass
        self._queue_renumber()

    def _queue_pick(self) -> dict | None:
        with self._q_lock:
            for it in self.queue_items:
                if it["status"] == "РѕР¶РёРґР°РЅРёРµ":
                    it["status"] = "СЃС‚Р°СЂС‚"
                    return it
        return None

    def _queue_start(self):
        if self._q_running:
            return
        pending = [it for it in self.queue_items if it["status"] in ("РѕР¶РёРґР°РЅРёРµ", "РѕС€РёР±РєР°", "РѕС‚РјРµРЅР°")]
        if not pending:
            messagebox.showinfo("РћС‡РµСЂРµРґСЊ", "Р”РѕР±Р°РІСЊС‚Рµ СЃСЃС‹Р»РєРё, РєРѕС‚РѕСЂС‹Рµ РЅСѓР¶РЅРѕ СЃРєР°С‡Р°С‚СЊ.")
            return
        if not self._check_browsers_before_download():
            return
        self._q_stop.clear()
        self._q_running = True
        self._q_done_count = 0
        self._q_error_count = 0
        for it in pending:
            it["status"] = "РѕР¶РёРґР°РЅРёРµ"
            it["percent"] = 0.0
            it["error"] = ""
            self._queue_update_row(it)
        self.btn_q_start.configure(state="disabled")
        self.btn_q_stop.configure(state="normal")
        self.status_var.set("РћС‡РµСЂРµРґСЊ: Р·Р°РіСЂСѓР·РєР°...")
        self._log(f"Р—Р°РїСѓСЃРєР°СЋ РѕС‡РµСЂРµРґСЊ РёР· {len(pending)} СЃСЃС‹Р»РѕРє (РїРѕС‚РѕРєРѕРІ: {max(1, int(self.q_parallel_var.get()))})")
        n = max(1, min(4, int(self.q_parallel_var.get())))
        for _ in range(n):
            threading.Thread(target=self._queue_worker, daemon=True).start()
        threading.Thread(target=self._queue_watch, daemon=True).start()

    def _queue_worker(self):
        while not self._q_stop.is_set():
            item = self._queue_pick()
            if item is None:
                return
            self._queue_download_item(item)

    def _queue_download_item(self, item: dict):
        item["status"] = "РёРЅС„Рѕ"
        self._queue_post(item)
        out_dir = Path(self.output_dir_var.get() or str(get_default_download_dir()))
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            item["status"] = "РѕС€РёР±РєР°"
            item["error"] = str(e)
            self._queue_post(item)
            return

        dl = MediaDownloader(progress_callback=lambda p: self.after(0, lambda pp=p: self._queue_on_progress(item, pp)))
        with self._q_lock:
            self._q_active[id(item)] = dl
        try:
            dl.download(
                url=item["url"],
                output_dir=out_dir,
                mode=item["mode"],
                custom_format=item["custom_format"],
                custom_audio_only=item["audio_only"],
                audio_format=item["audio_format"],
                audio_quality=item["audio_quality"],
                playlist_start=item["start"],
                playlist_end=item["end"],
                cookies_file=self.cookies_path,
                cookies_from_browser=self._active_browser(),
                proxy=self.proxy_var.get().strip() or None,
                restrict_filenames=self.restrict_names_var.get(),
                download_archive=self.archive_var.get().strip() if self.skip_downloaded_var.get() else None,
            )
            prog = dl.progress
            if prog.status == "done":
                item["status"] = "РіРѕС‚РѕРІРѕ"
                item["percent"] = 100.0
                self._q_done_count += 1
            elif prog.status == "cancelled":
                item["status"] = "РѕС‚РјРµРЅР°"
            else:
                item["status"] = "РѕС€РёР±РєР°"
                item["error"] = prog.error or "РѕС€РёР±РєР°"
                self._q_error_count += 1
        except Exception as e:
            item["status"] = "РѕС€РёР±РєР°"
            item["error"] = str(e)
            self._q_error_count += 1
        finally:
            with self._q_lock:
                self._q_active.pop(id(item), None)
            self._queue_post(item)

    def _queue_on_progress(self, item: dict, p: DownloadProgress):
        item["percent"] = p.percent
        if p.filename:
            item["title"] = Path(p.filename).name
        if p.status == "downloading":
            item["status"] = "Р·Р°РіСЂСѓР·РєР°"
        elif p.status == "merging":
            item["status"] = "СЃРєР»РµР№РєР°"
        elif p.status == "extracting":
            item["status"] = "РёРЅС„Рѕ"
        self._queue_update_row(item)

    def _queue_watch(self):
        while self._q_running:
            with self._q_lock:
                active = len(self._q_active)
            remaining = any(it["status"] in ("РѕР¶РёРґР°РЅРёРµ", "СЃС‚Р°СЂС‚", "Р·Р°РіСЂСѓР·РєР°", "РёРЅС„Рѕ", "СЃРєР»РµР№РєР°") for it in self.queue_items)
            if active == 0 and not remaining:
                break
            time.sleep(0.3)
        self.after(0, self._queue_finish)

    def _queue_finish(self):
        self._q_running = False
        try:
            self.btn_q_start.configure(state="normal")
            self.btn_q_stop.configure(state="disabled")
        except Exception:
            pass
        done = sum(1 for it in self.queue_items if it["status"] == "РіРѕС‚РѕРІРѕ")
        err = sum(1 for it in self.queue_items if it["status"] == "РѕС€РёР±РєР°")
        cancelled = sum(1 for it in self.queue_items if it["status"] == "РѕС‚РјРµРЅР°")
        self._log(f"РћС‡РµСЂРµРґСЊ Р·Р°РІРµСЂС€РµРЅР°: РіРѕС‚РѕРІРѕ {done}, РѕС€РёР±РѕРє {err}, РѕС‚РјРµРЅРµРЅРѕ {cancelled}")
        self.status_var.set(f"РћС‡РµСЂРµРґСЊ: РіРѕС‚РѕРІРѕ {done}, РѕС€РёР±РѕРє {err}")

    def _queue_stop(self):
        if not self._q_running:
            return
        self._log("РћСЃС‚Р°РЅР°РІР»РёРІР°СЋ РѕС‡РµСЂРµРґСЊ...")
        self._q_stop.set()
        with self._q_lock:
            actives = list(self._q_active.values())
            for it in self.queue_items:
                if it["status"] in ("РѕР¶РёРґР°РЅРёРµ", "СЃС‚Р°СЂС‚"):
                    it["status"] = "РѕС‚РјРµРЅР°"
                    self.after(0, lambda i=it: self._queue_update_row(i))
        for dl in actives:
            try:
                dl.stop()
            except Exception:
                pass
        self.btn_q_stop.configure(state="disabled")

    # ---------- log ----------

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    # ---------- actions ----------

    def _paste_url(self):
        try:
            text = self.clipboard_get().strip()
        except Exception:
            self._log("Р‘СѓС„РµСЂ РѕР±РјРµРЅР° РїСѓСЃС‚")
            return
        if text:
            self.url_var.set(text)
            self._log(f"РЎСЃС‹Р»РєР° РІСЃС‚Р°РІР»РµРЅР°: {text[:70]}")

    def _clear_url(self):
        self.url_var.set("")
        self.title_lbl.config(text="РќР°Р·РІР°РЅРёРµ: вЂ”")
        self.meta_lbl.config(text="Р”Р»РёС‚РµР»СЊРЅРѕСЃС‚СЊ: вЂ” | РљР°РЅР°Р»: вЂ”")
        self.status_var.set("Р“РѕС‚РѕРІ Рє СЂР°Р±РѕС‚Рµ")
        self.progress_bar["value"] = 0
        self.percent_lbl.config(text="0%")
        self.speed_var.set("вЂ”")
        self.eta_var.set("вЂ”")
        self.size_var.set("вЂ”")
        self.fname_lbl.config(text="вЂ”")
        self._populate_formats({})
        self._log("РЎСЃС‹Р»РєР° РѕС‡РёС‰РµРЅР°")

    def _browse_dir(self):
        chosen = filedialog.askdirectory(initialdir=self.output_dir_var.get() or str(get_default_download_dir()))
        if chosen:
            self.output_dir_var.set(chosen)
            self._save_config()
            self._log(f"РџР°РїРєР° СЃРѕС…СЂР°РЅРµРЅРёСЏ: {chosen}")

    def _open_dir(self):
        p = Path(self.output_dir_var.get() or str(get_default_download_dir()))
        try:
            p.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(p))
            elif sys.platform == "darwin":
                os.system(f'open "{p}"')
            else:
                os.system(f'xdg-open "{p}"')
            self._log(f"РћС‚РєСЂС‹С‚Р° РїР°РїРєР°: {p}")
        except Exception as e:
            self._log(f"РќРµ СѓРґР°Р»РѕСЃСЊ РѕС‚РєСЂС‹С‚СЊ РїР°РїРєСѓ: {e}")

    def _browse_archive(self):
        current = Path(self.archive_var.get() or str(DEFAULT_ARCHIVE_FILE))
        chosen = filedialog.asksaveasfilename(
            title="Р¤Р°Р№Р» Р°СЂС…РёРІР° Р·Р°РіСЂСѓР·РѕРє",
            initialfile=current.name or "download_archive.txt",
            initialdir=str(current.parent),
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if chosen:
            self.archive_var.set(chosen)
            self._save_config()
            self._log(f"Р¤Р°Р№Р» Р°СЂС…РёРІР°: {chosen}")

    # ---------- hotkeys / clipboard ----------

    def _setup_shortcuts(self):
        self.bind("<Control-d>", lambda e: self._download_async())
        self.bind("<F5>", lambda e: self._get_info_async())
        self.bind("<Escape>", lambda e: self._stop_download())
        self.bind("<Control-o>", lambda e: self._open_dir())

    def _on_focus_in(self, _event=None):
        """РџРѕРґСЃС‚Р°РІР»СЏРµС‚ СЃСЃС‹Р»РєСѓ РёР· Р±СѓС„РµСЂР° РѕР±РјРµРЅР°, РµСЃР»Рё РїРѕР»Рµ РїСѓСЃС‚РѕРµ."""
        if self.is_downloading:
            return
        try:
            text = self.clipboard_get().strip()
        except Exception:
            return
        if not text or text == self._last_clip:
            return
        self._last_clip = text
        if self.url_var.get().strip() or not looks_like_url(text):
            return
        self.url_var.set(text)
        self._log(f"РЎСЃС‹Р»РєР° РёР· Р±СѓС„РµСЂР° РѕР±РјРµРЅР°: {text[:70]}")

    # ---------- yt-dlp update ----------

    def _check_updates_async(self):
        threading.Thread(target=self._check_updates, daemon=True).start()
        threading.Thread(target=self._check_app_update_async, daemon=True).start()

    def _check_app_update_async(self):
        try:
            cur = get_app_version()
            rel = get_latest_app_release()
            if not rel:
                return
            tag = rel.get("tag_name") or ""
            if not is_newer_app_version(tag, cur):
                return
            url = get_app_asset_url(rel)
            if not url:
                return
            self.after(0, lambda t=tag,u=url: self._prompt_app_update(t, u))
        except Exception:
            pass

    def _prompt_app_update(self, tag: str, url: str):
        if getattr(self, "is_downloading", False):
            self.after(60000, lambda t=tag,u=url: self._prompt_app_update(t, u))
            return
        if not messagebox.askyesno(
            "Обновление программы",
            "Доступна новая версия Media Downloader " + tag + ".\n\nСкачать и обновить сейчас?\nПрограмма закроется и обновится автоматически.",
        ):
            return
        self._do_app_update(url)

    def _do_app_update(self, url: str):
        try:
            if getattr(sys, "frozen", False):
                exe = Path(sys.executable)
                new_exe = exe.with_name("Media-Downloader.new.exe")
            else:
                messagebox.showinfo("Обновление", "Обновление exe доступно только в собранном .exe")
                return
            self._log("Скачиваю обновление...")
            if not download_file(url, new_exe):
                messagebox.showerror("Обновление", "Не удалось скачать обновление")
                return
            bat = create_updater_script(new_exe, exe)
            if not bat:
                messagebox.showerror("Обновление", "Не удалось создать скрипт обновления")
                return
            self._log("Запускаю установщик обновления...")
            subprocess.Popen(["cmd", "/c", str(bat)], shell=False)
            self._on_close()
        except Exception as e:
            messagebox.showerror("Обновление", f"Ошибка: {e}")

    def _check_updates(self):
        current = get_installed_ytdlp_version()
        self.after(0, lambda: self._set_ytdlp_bottom(current))
        latest = get_latest_pypi_version("yt-dlp")
        if not latest:
            self.after(
                0,
                lambda: self.ytdlp_lbl2.config(
                    text=f"yt-dlp: СѓСЃС‚Р°РЅРѕРІР»РµРЅР° {current or '?'}. РќРµ СѓРґР°Р»РѕСЃСЊ РїСЂРѕРІРµСЂРёС‚СЊ РѕР±РЅРѕРІР»РµРЅРёСЏ (РЅРµС‚ СЃРµС‚Рё).",
                    bootstyle="warning",
                ),
            )
            return
        if is_newer_version(latest, current):
            self.after(
                0,
                lambda: self.ytdlp_lbl2.config(
                    text=f"yt-dlp: СѓСЃС‚Р°РЅРѕРІР»РµРЅР° {current} вЂ” РґРѕСЃС‚СѓРїРЅР° РЅРѕРІР°СЏ РІРµСЂСЃРёСЏ {latest}.",
                    bootstyle="warning",
                ),
            )
            self.after(0, lambda: self._log(f"Р”РѕСЃС‚СѓРїРЅРѕ РѕР±РЅРѕРІР»РµРЅРёРµ yt-dlp: {current} в†’ {latest}"))
        else:
            self.after(
                0,
                lambda: self.ytdlp_lbl2.config(
                    text=f"yt-dlp: СѓСЃС‚Р°РЅРѕРІР»РµРЅР° {current} вЂ” СЌС‚Рѕ РїРѕСЃР»РµРґРЅСЏСЏ РІРµСЂСЃРёСЏ.", bootstyle="success"
                ),
            )

    def _set_ytdlp_bottom(self, version: str):
        try:
            self.ytdlp_lbl.config(text=f"yt-dlp: {version or '?'}")
        except Exception:
            pass

    def _update_ytdlp_async(self):
        if ytdlp_update_command() is None:
            if messagebox.askyesno(
                "РћР±РЅРѕРІР»РµРЅРёРµ yt-dlp",
                "Р­С‚Р° СЃР±РѕСЂРєР° (.exe) СЃРѕРґРµСЂР¶РёС‚ yt-dlp РІРЅСѓС‚СЂРё вЂ” РѕС‚РґРµР»СЊРЅРѕ РѕР±РЅРѕРІРёС‚СЊ РµРіРѕ РЅРµР»СЊР·СЏ.\n\n"
                "РЎРєР°С‡Р°Р№С‚Рµ РЅРѕРІСѓСЋ РІРµСЂСЃРёСЋ РїСЂРѕРіСЂР°РјРјС‹ СЃРѕ СЃС‚СЂР°РЅРёС†С‹ СЂРµР»РёР·РѕРІ. РћС‚РєСЂС‹С‚СЊ РµС‘ СЃРµР№С‡Р°СЃ?",
            ):
                import webbrowser

                webbrowser.open(RELEASES_URL)
            return
        if self.is_downloading:
            messagebox.showinfo("РћР±РЅРѕРІР»РµРЅРёРµ yt-dlp", "РЎРЅР°С‡Р°Р»Р° РґРѕР¶РґРёС‚РµСЃСЊ РѕРєРѕРЅС‡Р°РЅРёСЏ Р·Р°РіСЂСѓР·РєРё.")
            return
        threading.Thread(target=self._update_ytdlp, daemon=True).start()

    def _update_ytdlp(self):
        self.after(0, lambda: self._log("РћР±РЅРѕРІР»СЏСЋ yt-dlp..."))
        cmd = ytdlp_update_command()
        code, out = _run_process(cmd, timeout=900) if cmd else (1, "РѕР±РЅРѕРІР»РµРЅРёРµ РЅРµРґРѕСЃС‚СѓРїРЅРѕ")
        if code == 0:
            self.after(0, lambda: self._log("yt-dlp РѕР±РЅРѕРІР»С‘РЅ. РџРµСЂРµР·Р°РїСѓСЃС‚РёС‚Рµ РїСЂРѕРіСЂР°РјРјСѓ, С‡С‚РѕР±С‹ РїСЂРёРјРµРЅРёС‚СЊ."))
            self.after(
                0,
                lambda: messagebox.showinfo("yt-dlp", "yt-dlp РѕР±РЅРѕРІР»С‘РЅ.\n\nРџРµСЂРµР·Р°РїСѓСЃС‚РёС‚Рµ РїСЂРѕРіСЂР°РјРјСѓ РґР»СЏ РїСЂРёРјРµРЅРµРЅРёСЏ."),
            )
        else:
            tail = (out or "").strip()[-500:]
            self.after(0, lambda: self._log(f"РќРµ СѓРґР°Р»РѕСЃСЊ РѕР±РЅРѕРІРёС‚СЊ yt-dlp:\n{tail}"))
            self.after(0, lambda: messagebox.showerror("yt-dlp", "РќРµ СѓРґР°Р»РѕСЃСЊ РѕР±РЅРѕРІРёС‚СЊ yt-dlp. РџРѕРґСЂРѕР±РЅРѕСЃС‚Рё РІ Р¶СѓСЂРЅР°Р»Рµ."))
        self.after(0, self._check_updates_async)

    def _load_cookies(self):
        chosen = filedialog.askopenfilename(title="Р’С‹Р±РµСЂРёС‚Рµ cookies.txt", filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if chosen:
            self.cookies_path = chosen
            self._log(f"Cookies Р·Р°РіСЂСѓР¶РµРЅС‹: {chosen}")
            self._apply_cookie_status(chosen)
            self._save_config()

    def _apply_cookie_status(self, path):
        """РџРѕРєР°Р·С‹РІР°РµС‚, РµСЃС‚СЊ Р»Рё РІ cookies РґР°РЅРЅС‹Рµ РІС…РѕРґР° (SID/LOGIN_INFO)."""
        res = check_cookies_file(path)
        name = Path(path).name
        if res.get("authenticated"):
            self.cookie_lbl.config(text=f"Р—Р°РіСЂСѓР¶РµРЅС‹: {name} вЂ” РІС…РѕРґ РїРѕРґС‚РІРµСЂР¶РґС‘РЅ", bootstyle="success")
        elif res.get("ok"):
            self.cookie_lbl.config(text=f"Р—Р°РіСЂСѓР¶РµРЅС‹: {name} вЂ” Р‘Р•Р— РІС…РѕРґР° РІ Р°РєРєР°СѓРЅС‚", bootstyle="warning")
            self._log(res.get("detail", ""))
        else:
            self.cookie_lbl.config(text=f"Р—Р°РіСЂСѓР¶РµРЅС‹: {name} (РЅРµ СѓРґР°Р»РѕСЃСЊ РїСЂРѕРІРµСЂРёС‚СЊ)", bootstyle="warning")

    def _clear_cookies(self):
        self.cookies_path = None
        self.cookie_lbl.config(text="Cookies РЅРµ Р·Р°РіСЂСѓР¶РµРЅС‹", bootstyle="secondary")
        self._log("Cookies СѓРґР°Р»РµРЅС‹")
        self._save_config()

    def _reset_browser(self):
        self.browser_var.set("Р±РµР· cookies")
        self._refresh_browser_status()
        self._save_config()

    def _active_browser(self) -> str | None:
        value = self.browser_var.get()
        if not value or value == "Р±РµР· cookies":
            return None
        return value

    def _refresh_browser_list(self):
        self._detected = detect_browsers()
        self._browser_by_label = {"Р±РµР· cookies": None}
        labels = ["Р±РµР· cookies"]
        for name, _profile in self._detected:
            if browser_reads_ok(name):
                label = name
            else:
                label = f"{name} вЂ” РЅРµР»СЊР·СЏ (Р·Р°С‰РёС‚Р° 127+)"
            self._browser_by_label[label] = name
            labels.append(label)

        self.cmb_browser.configure(values=labels)
        current = self.browser_var.get()
        if current in self._browser_by_label:
            self.cmb_browser.set(current)
        else:
            self.browser_var.set("Р±РµР· cookies")
        self._refresh_browser_status()

        usable = [n for n, _ in self._detected if browser_reads_ok(n)]
        if usable:
            self._log(f"Р‘СЂР°СѓР·РµСЂС‹, РёР· РєРѕС‚РѕСЂС‹С… РјРѕР¶РЅРѕ С‡РёС‚Р°С‚СЊ cookies: {', '.join(usable)}")
        else:
            self._log("РќРё РѕРґРёРЅ Р±СЂР°СѓР·РµСЂ РЅРµР»СЊР·СЏ С‡РёС‚Р°С‚СЊ РЅР°РїСЂСЏРјСѓСЋ (Р·Р°С‰РёС‚Р° 127+) вЂ” РЅСѓР¶РµРЅ cookies.txt")

    def _active_browser(self) -> str | None:
        return self._browser_by_label.get(self.browser_var.get())

    def _refresh_browser_status(self):
        label = self.browser_var.get()
        browser = self._active_browser()
        blocked = [n for n, _ in self._detected if not browser_reads_ok(n)]

        if browser and not browser_reads_ok(browser):
            self.browser_status.config(
                text=(
                    f"{browser} РёСЃРїРѕР»СЊР·СѓРµС‚ Р·Р°С‰РёС‚Сѓ cookies 127+ вЂ” С‡РёС‚Р°С‚СЊ РёС… РЅР°РїСЂСЏРјСѓСЋ РЅРµР»СЊР·СЏ, "
                    "Р·Р°РєСЂС‹С‚РёРµ Р±СЂР°СѓР·РµСЂР° РЅРµ РїРѕРјРѕР¶РµС‚. Р­РєСЃРїРѕСЂС‚РёСЂСѓР№С‚Рµ cookies.txt СЂР°СЃС€РёСЂРµРЅРёРµРј Cookie-Editor."
                ),
                bootstyle="danger",
            )
            return

        if not browser:
            if blocked:
                self.browser_status.config(
                    text=(
                        f"Cookies РЅР°РїСЂСЏРјСѓСЋ РЅРµРґРѕСЃС‚СѓРїРЅС‹: {', '.join(blocked)} РёСЃРїРѕР»СЊР·СѓСЋС‚ Р·Р°С‰РёС‚Сѓ 127+. "
                        "РќСѓР¶РµРЅ cookies.txt РёР· СЂР°СЃС€РёСЂРµРЅРёСЏ Cookie-Editor."
                    ),
                    bootstyle="warning",
                )
            else:
                self.browser_status.config(text="Cookies РёР· Р±СЂР°СѓР·РµСЂР° РЅРµ РёСЃРїРѕР»СЊР·СѓСЋС‚СЃСЏ.", bootstyle="secondary")
            return

        if is_browser_running([browser]):
            self.browser_status.config(
                text=f"{browser} СЃРµР№С‡Р°СЃ РѕС‚РєСЂС‹С‚ вЂ” Р·Р°РєСЂРѕР№С‚Рµ РµРіРѕ РїРѕР»РЅРѕСЃС‚СЊСЋ.",
                bootstyle="warning",
            )
        else:
            self.browser_status.config(text=f"{browser} Р·Р°РєСЂС‹С‚, РјРѕР¶РЅРѕ С‡РёС‚Р°С‚СЊ cookies.", bootstyle="success")


    def _check_browsers_before_download(self) -> bool:
        browser = self._active_browser()
        if not browser:
            return True
        if not browser_reads_ok(browser):
            if not messagebox.askokcancel(
                "Р‘СЂР°СѓР·РµСЂ РЅРµРґРѕСЃС‚СѓРїРµРЅ",
                f"{browser} РёСЃРїРѕР»СЊР·СѓРµС‚ Р·Р°С‰РёС‚Сѓ 127+ вЂ” cookies РёР· РЅРµРіРѕ РїСЂРѕС‡РёС‚Р°С‚СЊ РЅРµР»СЊР·СЏ.\n\n"
                "Р’РјРµСЃС‚Рѕ СЌС‚РѕРіРѕ СЌРєСЃРїРѕСЂС‚РёСЂСѓР№С‚Рµ cookies.txt СЂР°СЃС€РёСЂРµРЅРёРµРј Cookie-Editor Рё Р·Р°РіСЂСѓР·РёС‚Рµ РµРіРѕ "
                "РІ В«РќР°СЃС‚СЂРѕР№РєРёВ» в†’ Cookies.\n\n"
                "РџСЂРѕРґРѕР»Р¶РёС‚СЊ Р±РµР· cookies?",
            ):
                return False
            return True
        if is_browser_running([browser]):
            if not messagebox.askyesno(
                "Р‘СЂР°СѓР·РµСЂ РѕС‚РєСЂС‹С‚",
                f"{browser} СЃРµР№С‡Р°СЃ Р·Р°РїСѓС‰РµРЅ. Cookies РЅРµ СѓРґР°СЃС‚СЃСЏ РїСЂРѕС‡РёС‚Р°С‚СЊ, РїРѕРєР° РѕРЅ РѕС‚РєСЂС‹С‚.\n\n"
                "Р—Р°РєСЂС‹С‚СЊ Р±СЂР°СѓР·РµСЂ Рё РїСЂРѕРґРѕР»Р¶РёС‚СЊ?",
            ):
                return False
        return True

    def _check_ffmpeg(self):
        ffmpeg = find_ffmpeg()
        ffprobe = find_ffprobe()
        if ffmpeg and ffprobe:
            self.ffmpeg_badge.config(text="FFmpeg: РЅР°Р№РґРµРЅ", bootstyle="success")
            self.ffmpeg_lbl.config(text=f"FFmpeg РЅР°Р№РґРµРЅ: {ffmpeg}", bootstyle="success")
            self._log(f"FFmpeg РЅР°Р№РґРµРЅ: {ffmpeg}")
        elif ffmpeg:
            self.ffmpeg_badge.config(text="FFmpeg: РЅРµРїРѕР»РЅС‹Р№", bootstyle="warning")
            self.ffmpeg_lbl.config(
                text=f"РќР°Р№РґРµРЅ С‚РѕР»СЊРєРѕ ffmpeg ({ffmpeg}), РЅРµС‚ ffprobe. РЎРєР»РµР№РєР° РІРёРґРµРѕ+Р°СѓРґРёРѕ СЂР°Р±РѕС‚Р°С‚СЊ РЅРµ Р±СѓРґРµС‚ вЂ” РЅР°Р¶РјРёС‚Рµ В«РЎРєР°С‡Р°С‚СЊ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРёВ».",
                bootstyle="warning",
            )
            self._log("FFmpeg РЅР°Р№РґРµРЅ, РЅРѕ РЅРµС‚ ffprobe вЂ” СЃРєР»РµР№РєР° РІРёРґРµРѕ РЅРµ СЃСЂР°Р±РѕС‚Р°РµС‚")
        else:
            self.ffmpeg_badge.config(text="FFmpeg: РЅРµ РЅР°Р№РґРµРЅ", bootstyle="danger")
            self.ffmpeg_lbl.config(text="FFmpeg РЅРµ РЅР°Р№РґРµРЅ. РС‰РёС‚Рµ РІ PATH РёР»Рё РІ РїР°РїРєРµ ffmpeg/bin/ffmpeg.exe", bootstyle="danger")
            self._log("FFmpeg РЅРµ РЅР°Р№РґРµРЅ вЂ” РєР°С‡РµСЃС‚РІР° 1080p+ Рё MP3 РјРѕРіСѓС‚ РЅРµ СЂР°Р±РѕС‚Р°С‚СЊ")

    def _check_components(self):
        deno = find_deno()
        if deno:
            self.deno_lbl.config(text=f"Deno: РЅР°Р№РґРµРЅ ({deno})", bootstyle="success")
        else:
            self.deno_lbl.config(
                text="Deno: РЅРµ РЅР°Р№РґРµРЅ вЂ” РЅСѓР¶РµРЅ РґР»СЏ СЂРµС€РµРЅРёСЏ РїСЂРѕРІРµСЂРѕРє YouTube. РќР°Р¶РјРёС‚Рµ В«РЈСЃС‚Р°РЅРѕРІРёС‚СЊ DenoВ».",
                bootstyle="danger",
            )

        if server_running():
            self.pot_lbl.config(text=f"PO Token СЃРµСЂРІРµСЂ: Р·Р°РїСѓС‰РµРЅ ({SERVER_HOST}:{SERVER_PORT})", bootstyle="success")
        elif provider_installed():
            self.pot_lbl.config(text="PO Token СЃРµСЂРІРµСЂ: СѓСЃС‚Р°РЅРѕРІР»РµРЅ, РЅРѕ РЅРµ Р·Р°РїСѓС‰РµРЅ. Р—Р°РїСѓСЃС‚РёС‚СЃСЏ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё.", bootstyle="warning")
        else:
            self.pot_lbl.config(
                text="PO Token СЃРµСЂРІРµСЂ: РЅРµ СѓСЃС‚Р°РЅРѕРІР»РµРЅ. РќР°Р¶РјРёС‚Рµ В«РЈСЃС‚Р°РЅРѕРІРёС‚СЊ PO TokenВ».",
                bootstyle="danger",
            )

    def _check_network_async(self):
        self.net_lbl.config(text="РџСЂРѕРІРµСЂСЏСЋ РґРѕСЃС‚СѓРї Рє YouTube...", bootstyle="secondary")
        threading.Thread(target=self._check_network, daemon=True).start()

    def _check_network(self):
        try:
            res = check_youtube_network()
        except Exception as e:
            self.after(0, lambda: self.net_lbl.config(text=f"РћС€РёР±РєР° РїСЂРѕРІРµСЂРєРё: {e}", bootstyle="danger"))
            return
        state = res.get("state")
        detail = res.get("detail", "")
        style = {"ok": "success", "blocked": "danger"}.get(state, "warning")
        self.after(0, lambda: self.net_lbl.config(text=detail, bootstyle=style))

    def _autostart_pot(self):
        """РўРёС…Рѕ РїРѕРґРЅРёРјР°РµС‚ PO Token СЃРµСЂРІРµСЂ, РµСЃР»Рё РїСЂРѕРІР°Р№РґРµСЂ СѓР¶Рµ СѓСЃС‚Р°РЅРѕРІР»РµРЅ."""
        if not provider_installed() or server_running():
            return
        self.after(0, lambda: self._log("Р—Р°РїСѓСЃРєР°СЋ PO Token СЃРµСЂРІРµСЂ..."))
        if start_server(log=lambda m: self.after(0, lambda msg=m: self._log(msg))):
            self.after(0, self._check_components)

    def _ensure_pot_server(self) -> bool:
        if server_running():
            return True
        if not provider_installed():
            return False
        ok = start_server(log=lambda m: self._log(m))
        self._check_components()
        return ok

    def _install_deno_async(self):
        def work():
            self._log("РЈСЃС‚Р°РЅР°РІР»РёРІР°СЋ Deno С‡РµСЂРµР· winget...")
            code, _ = _run_process(
                ["winget", "install", "--id", "DenoLand.Deno", "--exact", "--silent",
                 "--accept-package-agreements", "--accept-source-agreements"],
                timeout=900,
            )
            if code == 0:
                self._log("Deno СѓСЃС‚Р°РЅРѕРІР»РµРЅ.")
            else:
                self._log("winget РЅРµ СЃРјРѕРі РїРѕСЃС‚Р°РІРёС‚СЊ Deno. РЎРєР°С‡Р°Р№С‚Рµ РІСЂСѓС‡РЅСѓСЋ: https://deno.com")
            self.after(0, self._check_components)

        threading.Thread(target=work, daemon=True).start()

    def _install_pot_async(self):
        def work():
            self._log("РЈСЃС‚Р°РЅР°РІР»РёРІР°СЋ PO Token РїСЂРѕРІР°Р№РґРµСЂ, СЌС‚Рѕ Р·Р°Р№РјС‘С‚ РЅРµСЃРєРѕР»СЊРєРѕ РјРёРЅСѓС‚...")
            ok, msg = install_provider(log=lambda m: self._log(m))
            if ok:
                self._log(f"РџСЂРѕРІР°Р№РґРµСЂ СѓСЃС‚Р°РЅРѕРІР»РµРЅ: {msg}")
                self._log("Р—Р°РїСѓСЃРєР°СЋ СЃРµСЂРІРµСЂ...")
                if start_server(log=lambda m: self._log(m)):
                    self._log("Р“РѕС‚РѕРІРѕ вЂ” PO Token СЂР°Р±РѕС‚Р°РµС‚.")
                else:
                    self._log("РЎРµСЂРІРµСЂ РЅРµ РїРѕРґРЅСЏР»СЃСЏ, РїСЂРѕРІРµСЂСЊС‚Рµ Р¶СѓСЂРЅР°Р».")
                self.after(0, lambda: messagebox.showinfo("PO Token", "PO Token РїСЂРѕРІР°Р№РґРµСЂ СѓСЃС‚Р°РЅРѕРІР»РµРЅ Рё Р·Р°РїСѓС‰РµРЅ."))
            else:
                self._log(f"РћС€РёР±РєР° СѓСЃС‚Р°РЅРѕРІРєРё: {msg}")
                self.after(0, lambda: messagebox.showerror("PO Token", f"РќРµ СѓРґР°Р»РѕСЃСЊ СѓСЃС‚Р°РЅРѕРІРёС‚СЊ:\n\n{msg}"))
            self.after(0, self._check_components)

        threading.Thread(target=work, daemon=True).start()

    def _download_ffmpeg_async(self):
        threading.Thread(target=self._download_ffmpeg, daemon=True).start()

    @staticmethod
    def _ffmpeg_root() -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / "ffmpeg"
        return Path.cwd() / "ffmpeg"

    def _download_ffmpeg(self):
        self._log("РС‰Сѓ РїРѕСЃР»РµРґРЅСЋСЋ СЃР±РѕСЂРєСѓ FFmpeg...")
        info = get_ffmpeg_download()
        if not info:
            self._log("РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ СЃСЃС‹Р»РєСѓ РЅР° FFmpeg вЂ” РѕС‚РєСЂС‹РІР°СЋ СЃС‚СЂР°РЅРёС†Сѓ РІСЂСѓС‡РЅСѓСЋ")
            messagebox.showwarning("FFmpeg", f"РђРІС‚РѕР·Р°РіСЂСѓР·РєР° РЅРµ СѓРґР°Р»Р°СЃСЊ.\n\nРЎРєР°С‡Р°Р№С‚Рµ В«essentials build win64В» СЃРѕ СЃС‚СЂР°РЅРёС†С‹:\n{FFMPEG_URL}\n\nР—Р°С‚РµРј СЂР°СЃРїР°РєСѓР№С‚Рµ ffmpeg.exe РІ РїР°РїРєСѓ ffmpeg/bin/ СЂСЏРґРѕРј СЃ РїСЂРѕРіСЂР°РјРјРѕР№.")
            import webbrowser

            webbrowser.open(FFMPEG_URL)
            return

        import shutil
        import tempfile

        import requests

        url = info["url"]
        self._log(f"РќР°Р№РґРµРЅРѕ: {info['name']} ({format_bytes(info['size'])})")
        fd, zpath = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        try:
            with requests.get(url, stream=True, timeout=600, headers={"User-Agent": "Media-Downloader"}) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                done = 0
                with open(zpath, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        if chunk:
                            f.write(chunk)
                            done += len(chunk)
                            if total:
                                self._log(f"Р—Р°РіСЂСѓР¶РµРЅРѕ FFmpeg: {int(done / total * 100)}%")

            self._log("Р Р°СЃРїР°РєРѕРІС‹РІР°СЋ...")
            ffmpeg_dir = self._ffmpeg_root()
            with zipfile.ZipFile(zpath) as z:
                z.extractall(ffmpeg_dir)

            extracted = {}
            for root, _dirs, files in os.walk(ffmpeg_dir):
                for name in files:
                    if name in ("ffmpeg.exe", "ffprobe.exe"):
                        extracted[name] = Path(root) / name

            if "ffmpeg.exe" not in extracted:
                raise RuntimeError("ffmpeg.exe РЅРµ РЅР°Р№РґРµРЅ РїРѕСЃР»Рµ СЂР°СЃРїР°РєРѕРІРєРё")

            target_dir = ffmpeg_dir / "bin"
            target_dir.mkdir(parents=True, exist_ok=True)
            for name, source in extracted.items():
                target = target_dir / name
                if source.resolve() == target.resolve():
                    continue
                try:
                    os.replace(source, target)
                except OSError:
                    shutil.move(str(source), str(target))

            missing = [n for n in ("ffmpeg.exe", "ffprobe.exe") if n not in extracted]
            self._log(f"FFmpeg СѓСЃС‚Р°РЅРѕРІР»РµРЅ РІ {target_dir}")
            if missing:
                self._log(f"Р’РЅРёРјР°РЅРёРµ: РЅРµ РЅР°Р№РґРµРЅ {', '.join(missing)} вЂ” СЃРєР»РµР№РєР° РІРёРґРµРѕ РјРѕР¶РµС‚ РЅРµ СЂР°Р±РѕС‚Р°С‚СЊ")
            messagebox.showinfo("FFmpeg", f"FFmpeg СЃРєР°С‡Р°РЅ Рё СѓСЃС‚Р°РЅРѕРІР»РµРЅ.\n\n{target_dir}")
        except Exception as e:
            self._log(f"РћС€РёР±РєР° Р·Р°РіСЂСѓР·РєРё FFmpeg: {e}")
            messagebox.showerror("FFmpeg", f"РќРµ СѓРґР°Р»РѕСЃСЊ СЃРєР°С‡Р°С‚СЊ FFmpeg:\n{e}\n\nРЎРєР°С‡Р°Р№С‚Рµ РІСЂСѓС‡РЅСѓСЋ: {FFMPEG_URL}")
        finally:
            try:
                os.unlink(zpath)
            except OSError:
                pass
            self._check_ffmpeg()

    # ---------- info ----------

    def _get_info_async(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("РЎСЃС‹Р»РєР°", "Р’СЃС‚Р°РІСЊС‚Рµ СЃСЃС‹Р»РєСѓ РЅР° YouTube")
            return
        if not self._check_browsers_before_download():
            return
        self._refresh_browser_status()
        threading.Thread(target=self._get_info, args=(url,), daemon=True).start()

    def _get_info(self, url: str):
        browser = self._active_browser()
        try:
            if browser:
                self._log(f"РџРѕР»СѓС‡Р°СЋ РёРЅС„РѕСЂРјР°С†РёСЋ С‡РµСЂРµР· cookies РёР· {browser}...")
            else:
                self._log(f"РџРѕР»СѓС‡Р°СЋ РёРЅС„РѕСЂРјР°С†РёСЋ: {url}")
            self.title_lbl.config(text="РќР°Р·РІР°РЅРёРµ: Р·Р°РіСЂСѓР¶Р°СЋ...")
            info = self.downloader.extract_info(
                url,
                cookies_file=self.cookies_path,
                cookies_from_browser=browser,
                proxy=self.proxy_var.get().strip() or None,
            )
            if not info:
                raise RuntimeError("YouTube РЅРµ РІРµСЂРЅСѓР» РґР°РЅРЅС‹Рµ РїРѕ СЌС‚РѕР№ СЃСЃС‹Р»РєРµ")

            is_playlist = "entries" in info
            count = len(info.get("entries") or []) if is_playlist else 1
            title = info.get("playlist_title") if is_playlist else info.get("title")
            duration = format_duration(info.get("duration"))
            channel = info.get("channel") or info.get("uploader") or "вЂ”"

            self.after(0, lambda: self.title_lbl.config(text=f"РќР°Р·РІР°РЅРёРµ: {title or 'вЂ”'}"))
            self.after(
                0,
                lambda: self.meta_lbl.config(
                    text=f"{'РџР»РµР№Р»РёСЃС‚' if is_playlist else 'Р’РёРґРµРѕ'}"
                    f" В· {count} С€С‚."
                    f" В· Р”Р»РёС‚РµР»СЊРЅРѕСЃС‚СЊ: {duration}"
                    f" В· РљР°РЅР°Р»: {channel}"
                    + (f" В· РљР°С‡РµСЃС‚РІРѕ: {info['height']}p" if info.get("height") else "")
                ),
            )
            self._log(f"Р“РѕС‚РѕРІРѕ: {title or 'вЂ”'} ({count} С€С‚.)")
            self.after(0, lambda: self._populate_formats(info))
            if info.get("height"):
                self._log(f"Р”РѕСЃС‚СѓРїРЅС‹Рµ РєР°С‡РµСЃС‚РІР° РґРѕ {info['height']}p")
        except Exception as e:
            err = str(e)
            self._log(f"РћС€РёР±РєР°: {err}")
            messagebox.showerror("РћС€РёР±РєР° РїРѕР»СѓС‡РµРЅРёСЏ РёРЅС„РѕСЂРјР°С†РёРё", f"{err}{self._hint_for_error(err)}")

    @staticmethod
    def _hint_for_error(err: str) -> str:
        low = err.lower()
        if any(
            m in low
            for m in (
                "connection reset",
                "connection aborted",
                "unable to download api page",
                "getaddrinfo",
                "failed to resolve",
                "connection refused",
                "remote end closed",
                "ssl",
                "timed out",
            )
        ):
            return (
                "\n\nРџРѕС…РѕР¶Рµ, РІР°С€Р° СЃРµС‚СЊ Р±Р»РѕРєРёСЂСѓРµС‚ YouTube (С‡Р°СЃС‚Р°СЏ СЃРёС‚СѓР°С†РёСЏ РІ Р РѕСЃСЃРёРё вЂ” Р±Р»РѕРєРёСЂРѕРІРєР° РїРѕ РёРјРµРЅРё РґРѕРјРµРЅР°/SNI).\n\n"
                "РќРё РѕРґРёРЅ Р»РѕРєР°Р»СЊРЅС‹Р№ Р·Р°РіСЂСѓР·С‡РёРє РІ С‚Р°РєРѕР№ СЃРµС‚Рё РєР°С‡Р°С‚СЊ РЅРµ СЃРјРѕР¶РµС‚ вЂ” РїСЂРѕР±Р»РµРјР° РЅРµ РІ РїСЂРѕРіСЂР°РјРјРµ.\n\n"
                "Р§С‚Рѕ РґРµР»Р°С‚СЊ:\n"
                "1. Р’РєР»СЋС‡РёС‚Рµ VPN\n"
                "2. Р›РёР±Рѕ СѓРєР°Р¶РёС‚Рµ РїСЂРѕРєСЃРё РІ В«РќР°СЃС‚СЂРѕР№РєРёВ» в†’ РЎРµС‚СЊ Рё РїСЂРѕРєСЃРё\n"
                "3. РќР°Р¶РјРёС‚Рµ С‚Р°Рј Р¶Рµ В«РџСЂРѕРІРµСЂРёС‚СЊ СЃРµС‚СЊВ», С‡С‚РѕР±С‹ РїРѕРґС‚РІРµСЂРґРёС‚СЊ РїСЂРёС‡РёРЅСѓ\n\n"
                "Р¤РѕСЂРјР°С‚ РїСЂРѕРєСЃРё: http://С…РѕСЃС‚:РїРѕСЂС‚ РёР»Рё socks5://С…РѕСЃС‚:РїРѕСЂС‚"
            )
        if "could not copy" in low and "cookie" in low:
            return (
                "\n\nР‘СЂР°СѓР·РµСЂ РґРµСЂР¶РёС‚ С„Р°Р№Р» cookies Р·Р°Р±Р»РѕРєРёСЂРѕРІР°РЅРЅС‹Рј.\n\n"
                "Р§С‚Рѕ РґРµР»Р°С‚СЊ:\n"
                "1. РџРѕР»РЅРѕСЃС‚СЊСЋ Р·Р°РєСЂРѕР№С‚Рµ Р±СЂР°СѓР·РµСЂ (РЅРµ С‚РѕР»СЊРєРѕ РѕРєРЅРѕ вЂ” РїСЂРѕРІРµСЂСЊС‚Рµ С‚СЂРµР№ Рё РґРёСЃРїРµС‚С‡РµСЂ Р·Р°РґР°С‡)\n"
                "2. РџРѕРІС‚РѕСЂРёС‚Рµ РїРѕРїС‹С‚РєСѓ\n\n"
                "Р•СЃР»Рё РЅРµ РїРѕРјРѕРіР»Рѕ вЂ” РІС‹Р±РµСЂРёС‚Рµ РґСЂСѓРіРѕР№ Р±СЂР°СѓР·РµСЂ РІ В«РќР°СЃС‚СЂРѕР№РєРёВ» в†’ Cookies, "
                "Р»РёР±Рѕ Р·Р°РіСЂСѓР·РёС‚Рµ cookies.txt РІСЂСѓС‡РЅСѓСЋ."
            )
        if "could not find" in low and "cookie" in low or "no such file" in low and "cookie" in low:
            return (
                "\n\nРЈ РІС‹Р±СЂР°РЅРЅРѕРіРѕ Р±СЂР°СѓР·РµСЂР° РЅРµС‚ С„Р°Р№Р»РѕРІ cookies вЂ” Р·РЅР°С‡РёС‚, РІС‹ РІ РЅС‘Рј РЅРµ Р°РІС‚РѕСЂРёР·РѕРІР°РЅС‹ РЅР° YouTube.\n\n"
                "Р’РѕР№РґРёС‚Рµ РІ YouTube РІ СЌС‚РѕРј Р±СЂР°СѓР·РµСЂРµ Рё РїРѕРІС‚РѕСЂРёС‚Рµ."
            )
        if "failed to decrypt with dpapi" in low or ("decrypt" in low and "app-bound" in low):
            return (
                "\n\nChrome/Edge 127+ С€РёС„СЂСѓСЋС‚ cookies РєР»СЋС‡РѕРј, РїСЂРёРІСЏР·Р°РЅРЅС‹Рј Рє СЃР°РјРѕРјСѓ Р±СЂР°СѓР·РµСЂСѓ. "
                "Р’РЅРµС€РЅСЏСЏ РїСЂРѕРіСЂР°РјРјР° РёС… РЅРµ СЂР°СЃС€РёС„СЂСѓРµС‚ вЂ” СЌС‚Рѕ РѕРіСЂР°РЅРёС‡РµРЅРёРµ Р±РµР·РѕРїР°СЃРЅРѕСЃС‚Рё, Р·Р°РєСЂС‹С‚РёРµ Р±СЂР°СѓР·РµСЂР° РќР• РїРѕРјРѕР¶РµС‚.\n\n"
                "Р§С‚Рѕ РґРµР»Р°С‚СЊ:\n"
                "1. РЈСЃС‚Р°РЅРѕРІРёС‚Рµ СЂР°СЃС€РёСЂРµРЅРёРµ Cookie-Editor РІ Chrome/Edge\n"
                "2. РћС‚РєСЂРѕР№С‚Рµ youtube.com (РїРѕРґ СЃРІРѕРёРј Р°РєРєР°СѓРЅС‚РѕРј) Рё СЌРєСЃРїРѕСЂС‚РёСЂСѓР№С‚Рµ cookies РІ Netscape (.txt)\n"
                "3. В«РќР°СЃС‚СЂРѕР№РєРёВ» в†’ Cookies в†’ В«Р—Р°РіСЂСѓР·РёС‚СЊВ» в†’ РІС‹Р±РµСЂРёС‚Рµ С„Р°Р№Р»\n\n"
                "РђР»СЊС‚РµСЂРЅР°С‚РёРІР°: Firefox С‡РёС‚Р°РµС‚СЃСЏ РЅР°РїСЂСЏРјСѓСЋ Р±РµР· РѕРіСЂР°РЅРёС‡РµРЅРёР№."
            )
        if "decrypt" in low or "app-bound" in low or "dpapi" in low:
            return (
                "\n\nРќРµ СѓРґР°Р»РѕСЃСЊ СЂР°СЃС€РёС„СЂРѕРІР°С‚СЊ cookies.\n\n"
                "Р—Р°РєСЂРѕР№С‚Рµ Р±СЂР°СѓР·РµСЂ Рё РїРѕРІС‚РѕСЂРёС‚Рµ; РІС‹Р±РµСЂРёС‚Рµ РґСЂСѓРіРѕР№ Р±СЂР°СѓР·РµСЂ; "
                "Р»РёР±Рѕ Р·Р°РіСЂСѓР·РёС‚Рµ cookies.txt РІСЂСѓС‡РЅСѓСЋ С‡РµСЂРµР· В«РќР°СЃС‚СЂРѕР№РєРёВ» в†’ Cookies."
            )
        if "age" in low or "confirm your age" in low:
            return "\n\nРџРѕС…РѕР¶Рµ РЅР° РІРѕР·СЂР°СЃС‚РЅРѕРµ РѕРіСЂР°РЅРёС‡РµРЅРёРµ вЂ” РЅСѓР¶РЅС‹ cookies РёР· Р±СЂР°СѓР·РµСЂР°, РіРґРµ РІС‹ РІРѕС€Р»Рё РІ YouTube."
        if "private" in low:
            return "\n\nР’РёРґРµРѕ РїСЂРёРІР°С‚РЅРѕРµ вЂ” РґРѕСЃС‚СѓРїРЅРѕ С‚РѕР»СЊРєРѕ РїРѕ СЃСЃС‹Р»РєРµ РґР»СЏ РїСЂРёРіР»Р°С€С‘РЅРЅС‹С…."
        if "unavailable" in low or "not available" in low:
            return "\n\nР’РёРґРµРѕ СѓРґР°Р»РµРЅРѕ РёР»Рё РЅРµРґРѕСЃС‚СѓРїРЅРѕ РІ РІР°С€РµРј СЂРµРіРёРѕРЅРµ."
        if "sign in" in low or "bot" in low or "429" in low:
            return (
                "\n\nYouTube С‚СЂРµР±СѓРµС‚ РїРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ В«СЏ РЅРµ СЂРѕР±РѕС‚В».\n\n"
                "Р§С‚Рѕ РґРµР»Р°С‚СЊ:\n"
                "1. Р­РєСЃРїРѕСЂС‚РёСЂСѓР№С‚Рµ cookies.txt СЂР°СЃС€РёСЂРµРЅРёРµРј Cookie-Editor, Р±СѓРґСѓС‡Рё Р°РІС‚РѕСЂРёР·РѕРІР°РЅРЅС‹Рј РЅР° YouTube\n"
                "2. Р—Р°РіСЂСѓР·РёС‚Рµ С„Р°Р№Р» РІ В«РќР°СЃС‚СЂРѕР№РєРёВ» в†’ Cookies\n\n"
                "Р’Р°Р¶РЅРѕ: РіРѕРґСЏС‚СЃСЏ С‚РѕР»СЊРєРѕ cookies РЎРћ РІС…РѕРґРѕРј. Р•СЃР»Рё РІ С„Р°Р№Р»Рµ РЅРµС‚ SID Рё LOGIN_INFO вЂ” "
                "YouTube РІСЃС‘ СЂР°РІРЅРѕ СЃС‡РёС‚Р°РµС‚ РІР°СЃ РіРѕСЃС‚РµРј (РІ В«РќР°СЃС‚СЂРѕР№РєР°С…В» Р±СѓРґРµС‚ РїРѕРјРµС‚РєР° В«Р‘Р•Р— РІС…РѕРґР° РІ Р°РєРєР°СѓРЅС‚В»).\n"
                "РќР° Chrome/Edge 127+ cookies РЅР°РїСЂСЏРјСѓСЋ РёР· Р±СЂР°СѓР·РµСЂР° РЅРµ С‡РёС‚Р°СЋС‚СЃСЏ вЂ” С‚РѕР»СЊРєРѕ С„Р°Р№Р»РѕРј."
            )
        return ""

    # ---------- download ----------

    def _download_async(self):
        if self.is_downloading:
            return
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("РЎСЃС‹Р»РєР°", "Р’СЃС‚Р°РІСЊС‚Рµ СЃСЃС‹Р»РєСѓ РЅР° YouTube")
            return

        out_dir = Path(self.output_dir_var.get() or str(get_default_download_dir()))
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("РћС€РёР±РєР°", f"РќРµ РјРѕРіСѓ СЃРѕР·РґР°С‚СЊ РїР°РїРєСѓ:\n{out_dir}\n\n{e}")
            return

        if not self._check_browsers_before_download():
            return

        self.is_downloading = True
        self.btn_download.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress_bar["value"] = 0
        self.percent_lbl.config(text="0%")
        self.status_var.set("РџРѕРґРіРѕС‚РѕРІРєР°...")
        self._log(f"РЎС‚Р°СЂС‚ Р·Р°РіСЂСѓР·РєРё РІ {out_dir}")

        mode, custom_format, custom_audio_only = self._current_mode()
        args = dict(
            url=url,
            output_dir=out_dir,
            mode=mode,
            custom_format=custom_format,
            custom_audio_only=custom_audio_only,
            audio_format=self.audio_format_var.get(),
            audio_quality=self.audio_quality_var.get(),
            playlist_start=max(1, self.playlist_start_var.get() or 1),
            playlist_end=0 if self.playlist_all_var.get() else max(0, self.playlist_end_var.get() or 0),
            cookies_file=self.cookies_path,
            cookies_from_browser=self._active_browser(),
            proxy=self.proxy_var.get().strip() or None,
            restrict_filenames=self.restrict_names_var.get(),
            download_archive=self.archive_var.get().strip() if self.skip_downloaded_var.get() else None,
        )
        threading.Thread(target=self._worker, args=(args,), daemon=True).start()

    def _worker(self, args: dict):
        try:
            self.downloader.download(**args)
        except Exception as e:
            self._log(f"РљСЂРёС‚РёС‡РµСЃРєР°СЏ РѕС€РёР±РєР°: {e}")
        finally:
            final = self.downloader.progress
            if final.status == "done":
                self._log("Р—Р°РіСЂСѓР·РєР° Р·Р°РІРµСЂС€РµРЅР° СѓСЃРїРµС€РЅРѕ")
                self.after(0, lambda: messagebox.showinfo("Р“РѕС‚РѕРІРѕ", f"Р¤Р°Р№Р» СЃРѕС…СЂР°РЅС‘РЅ РІ:\n{args['output_dir']}"))
            elif final.status == "cancelled":
                self._log("Р—Р°РіСЂСѓР·РєР° РѕС‚РјРµРЅРµРЅР°")
            elif final.status == "error":
                self._log(f"РћС€РёР±РєР° Р·Р°РіСЂСѓР·РєРё: {final.error}")
                self.after(
                    0,
                    lambda: messagebox.showerror(
                        "РћС€РёР±РєР° Р·Р°РіСЂСѓР·РєРё",
                        f"{final.error or 'РќРµРёР·РІРµСЃС‚РЅР°СЏ РѕС€РёР±РєР°'}{self._hint_for_error(final.error or '')}",
                    ),
                )
            self.after(0, self._finish)
            self._save_config()

    def _finish(self):
        self.is_downloading = False
        self.btn_download.configure(state="normal")
        self.btn_stop.configure(state="disabled")

    def _stop_download(self):
        if not self.is_downloading:
            return
        self._log("РћСЃС‚Р°РЅР°РІР»РёРІР°СЋ...")
        self.downloader.stop()
        self.btn_stop.configure(state="disabled")
        self.status_var.set("РћСЃС‚Р°РЅР°РІР»РёРІР°СЋ...")

    def on_progress(self, p: DownloadProgress):
        self.after(0, lambda: self._render(p))

    def _render(self, p: DownloadProgress):
        if p.status == "extracting":
            if p.retry_message:
                self.status_var.set(p.retry_message)
            else:
                self.status_var.set("РџРѕР»СѓС‡Р°СЋ РёРЅС„РѕСЂРјР°С†РёСЋ СЃ YouTube...")
        elif p.status == "downloading":
            counter = f" [{p.current_index}/{p.total_count}]" if p.is_playlist and p.total_count else ""
            self.status_var.set(f"Р—Р°РіСЂСѓР·РєР°{counter}...")
            pct = round(p.percent, 1)
            self.progress_bar["value"] = pct
            self.percent_lbl.config(text=f"{pct}%")
            self.speed_var.set(f"РЎРєРѕСЂРѕСЃС‚СЊ: {format_bytes(int(p.speed))}/СЃ" if p.speed > 0 else "РЎРєРѕСЂРѕСЃС‚СЊ: вЂ”")
            self.eta_var.set(f"РћСЃС‚Р°Р»РѕСЃСЊ: {format_eta(p.eta)}")
            if p.total > 0:
                self.size_var.set(f"{format_bytes(p.downloaded)} / {format_bytes(p.total)}")
            else:
                self.size_var.set(format_bytes(p.downloaded))
            if p.filename:
                self.fname_lbl.config(text=Path(p.filename).name)
        elif p.status == "merging":
            self.progress_bar["value"] = 99
            self.percent_lbl.config(text="99%")
            self.status_var.set("РЎРєР»РµРёРІР°СЋ РІРёРґРµРѕ + Р°СѓРґРёРѕ (FFmpeg)...")
            self.speed_var.set("РЎРєРѕСЂРѕСЃС‚СЊ: вЂ”")
        elif p.status == "done":
            self.progress_bar["value"] = 100
            self.percent_lbl.config(text="100%")
            self.status_var.set("Р“РѕС‚РѕРІРѕ")
            self.speed_var.set("РЎРєРѕСЂРѕСЃС‚СЊ: вЂ”")
            self.eta_var.set("РћСЃС‚Р°Р»РѕСЃСЊ: вЂ”")
            self.size_var.set("Р“РѕС‚РѕРІРѕ")
        elif p.status == "cancelled":
            self.status_var.set("РћС‚РјРµРЅРµРЅРѕ")
        elif p.status == "error":
            self.status_var.set("РћС€РёР±РєР°")

    def _on_close(self):
        busy = self.is_downloading or self._q_running
        if busy:
            if not messagebox.askyesno("Р’С‹С…РѕРґ", "РРґС‘С‚ Р·Р°РіСЂСѓР·РєР°. РћСЃС‚Р°РЅРѕРІРёС‚СЊ Рё РІС‹Р№С‚Рё?"):
                return
            self.downloader.stop()
            self._queue_stop()
        self._save_config()
        try:
            stop_server()
        except Exception:
            pass
        self.destroy()


def main():
    app = YTApp()
    app.mainloop()


if __name__ == "__main__":
    main()

