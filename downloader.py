import os
import threading
from pathlib import Path
from typing import Any, Callable, Dict

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, ExtractorError

from utils import find_ffmpeg
from pot import find_deno, server_running, start_server

# Порядок клиентов YouTube. Если один не отдаёт видео (ошибка PO Token,
# «страница требует перезагрузки», пустой список форматов), пробуем следующий.
# Так же поступает QSaver: несколько попыток вместо одной.
CLIENT_FALLBACKS: list[list[str]] = [
    ["default", "web_embedded"],
    ["mweb"],
    ["tv_simply", "web_embedded"],
    ["web_safari"],
    ["default"],
]

# Ошибки, при которых имеет смысл повторить с другим клиентом.
RETRYABLE_MARKERS = (
    "page needs to be reloaded",
    "sign in to confirm",
    "no video formats found",
    "unable to download api page",
    "failed to resolve",
    "getaddrinfo",
    "name resolution",
    "connection reset",
    "connection aborted",
    "connection refused",
    "timed out",
    "temporary failure",
    "http error 5",
    "unable to connect",
)

MAX_ATTEMPTS = 3


def build_runtime_opts(cookies_used: bool, clients: list[str] | None = None, proxy: str | None = None) -> dict:
    """Опции, нужные для текущего состояния YouTube (PO token, JS-челлендж)."""
    opts: dict[str, Any] = {}

    if proxy:
        opts["proxy"] = proxy

    deno = find_deno()
    if deno:
        opts["js_runtimes"] = {"deno": {"path": deno}}

    if clients is None:
        clients = ["default", "web_embedded"] if cookies_used else ["default"]
    args: dict[str, dict[str, list[str]]] = {"youtube": {"player_client": clients}}
    if server_running():
        args["youtubepot-bgutilhttp"] = {"base_url": ["http://127.0.0.1:4416"]}
    opts["extractor_args"] = args
    return opts


def ensure_pot_server() -> bool:
    """Поднимает PO Token сервер, если он установлен, но упал."""
    if server_running():
        return True
    return start_server()


class DownloadProgress:
    def __init__(self):
        self.status = "idle"
        self.percent = 0.0
        self.speed = 0.0
        self.eta = 0
        self.downloaded = 0
        self.total = 0
        self.filename = ""
        self.error = ""
        self.current_index = 0
        self.total_count = 0
        self.is_playlist = False
        self.retry_message = ""


class YTDownloader:
    def __init__(self, progress_callback: Callable[[DownloadProgress], None] | None = None):
        self.progress_callback = progress_callback
        self.progress = DownloadProgress()
        self._stop_event = threading.Event()
        self._ydl = None
        self._url = ""

    def _emit(self):
        if self.progress_callback:
            try:
                self.progress_callback(self.progress)
            except Exception:
                pass

    def stop(self):
        self._stop_event.set()

    def extract_info(
        self,
        url: str,
        cookies_file: str | None = None,
        cookies_from_browser: str | None = None,
        proxy: str | None = None,
    ) -> Dict[str, Any]:
        base_opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": False,
            "noprogress": True,
            "socket_timeout": 30,
        }
        if cookies_file:
            base_opts["cookiefile"] = cookies_file
        if cookies_from_browser:
            base_opts["cookiesfrombrowser"] = (cookies_from_browser,)
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            base_opts["ffmpeg_location"] = ffmpeg

        cookies_used = bool(cookies_file or cookies_from_browser)
        last_error = ""

        for attempt in range(1, MAX_ATTEMPTS + 1):
            opts = dict(base_opts)
            ensure_pot_server()
            opts.update(build_runtime_opts(cookies_used, clients=CLIENT_FALLBACKS[attempt - 1], proxy=proxy))
            try:
                with YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                if not info:
                    last_error = "YouTube не вернул данные по этой ссылке"
                    if attempt < MAX_ATTEMPTS:
                        if self._stop_event.wait(2 * attempt):
                            raise RuntimeError("Отменено")
                        continue
                    break

                # Без явного "format" info['height'] отражает произвольный
                # формат, а не лучший. Считаем максимум по всем форматам,
                # иначе в GUI показывается 360p вместо 1080p.
                fmts = info.get("formats") or []
                vids = [f for f in fmts if f.get("vcodec") not in (None, "none")]
                heights = [f["height"] for f in vids if f.get("height")]
                if heights:
                    info["height"] = max(heights)
                elif not info.get("height") and vids:
                    info["height"] = None
                return info
            except (DownloadError, ExtractorError) as e:
                last_error = self._clean_error(str(e))
            except Exception as e:
                last_error = self._clean_error(str(e))

            if attempt < MAX_ATTEMPTS and self._should_retry(last_error):
                if self._stop_event.wait(2 * attempt):
                    raise RuntimeError("Отменено")
                continue
            break

        raise RuntimeError(last_error or "Не удалось получить информацию")

    @staticmethod
    def _clean_error(msg: str) -> str:
        cleaned = "\n".join(line for line in msg.splitlines() if line.strip() and not line.strip().startswith("["))
        return cleaned.strip() or "Неизвестная ошибка"

    def download(
        self,
        url: str,
        output_dir: Path,
        format_selector: str = "best",
        audio_format: str = "mp3",
        audio_quality: str = "192",
        playlist_start: int = 1,
        playlist_end: int = 0,
        cookies_file: str | None = None,
        cookies_from_browser: str | None = None,
        proxy: str | None = None,
        restrict_filenames: bool = True,
    ):
        self._stop_event.clear()
        self.progress = DownloadProgress()
        self._url = url
        self.progress.status = "extracting"
        self._emit()

        output_dir.mkdir(parents=True, exist_ok=True)

        limit = 60 if restrict_filenames else 0
        outtmpl = str(output_dir / f"%(title).{limit}s [%(id)s].%(ext)s")

        opts: Dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": False,
            "outtmpl": outtmpl,
            "progress_hooks": [self._hook],
            "noprogress": False,
            "continuedl": True,
            "retries": 10,
            "fragment_retries": 10,
            "concurrent_fragment_downloads": 5,
            "http_chunk_size": 1048576,
            "buffersize": 16777216,
            "merge_output_format": "mp4",
            "socket_timeout": 30,
        }

        if cookies_file:
            opts["cookiefile"] = cookies_file
        if cookies_from_browser:
            opts["cookiesfrombrowser"] = (cookies_from_browser,)

        ffmpeg = find_ffmpeg()
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg

        if format_selector == "bestaudio":
            opts["format"] = "ba/best"
            codec = audio_format if audio_format in ("mp3", "m4a", "opus", "wav") else "mp3"
            pp = {"key": "FFmpegExtractAudio", "preferredcodec": codec}
            if codec != "wav":
                pp["preferredquality"] = audio_quality
            opts["postprocessors"] = [pp, {"key": "FFmpegMetadata"}]
        elif format_selector == "bestvideo":
            opts["format"] = "bv*+ba/b"
        else:
            opts["format"] = "bv*+ba/b"

        if playlist_end and playlist_end >= playlist_start:
            opts["playlist_items"] = f"{playlist_start}:{playlist_end}"
            opts["ignoreerrors"] = True
        elif playlist_start > 1:
            opts["playlist_items"] = f"{playlist_start}:"
            opts["ignoreerrors"] = True

        cookies_used = bool(cookies_file or cookies_from_browser)
        last_error = ""

        try:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                if self._stop_event.is_set():
                    self.progress.status = "cancelled"
                    return

                attempt_opts = dict(opts)
                ensure_pot_server()
                attempt_opts.update(build_runtime_opts(cookies_used, clients=CLIENT_FALLBACKS[attempt - 1], proxy=proxy))

                try:
                    with YoutubeDL(attempt_opts) as ydl:
                        self._ydl = ydl
                        ydl.download([url])
                    if self._stop_event.is_set():
                        self.progress.status = "cancelled"
                    else:
                        self.progress.status = "done"
                        self.progress.percent = 100.0
                        self.progress.retry_message = ""
                        self.progress.error = ""
                    return
                except (DownloadError, ExtractorError) as e:
                    if "cancel" in str(e).lower() or self._stop_event.is_set():
                        self.progress.status = "cancelled"
                        return
                    last_error = self._clean_error(str(e)) or "Ошибка загрузки"
                except Exception as e:
                    if self._stop_event.is_set():
                        self.progress.status = "cancelled"
                        return
                    last_error = self._clean_error(str(e)) or "Неизвестная ошибка"

                if attempt < MAX_ATTEMPTS and self._should_retry(last_error):
                    self.progress.status = "extracting"
                    self.progress.retry_message = (
                        f"Попытка {attempt} не удалась, пробую способ {attempt + 1} из {MAX_ATTEMPTS}..."
                    )
                    self.progress.error = last_error
                    self._emit()
                    # Нарастающая пауза: сеть/DNS часто отходят через несколько секунд
                    if self._stop_event.wait(2 * attempt):
                        self.progress.status = "cancelled"
                        return
                    continue
                break

            self.progress.status = "error"
            self.progress.error = last_error
        finally:
            self._ydl = None
            self._emit()

    @staticmethod
    def _should_retry(error: str) -> bool:
        low = error.lower()
        return any(marker in low for marker in RETRYABLE_MARKERS)

    def _hook(self, d: Dict[str, Any]):
        if self._stop_event.is_set():
            raise DownloadError("cancelled by user")

        status = d.get("status")
        info = d.get("info_dict") or {}
        if info:
            idx = info.get("playlist_index")
            n = info.get("playlist_count")
            if idx and n:
                self.progress.is_playlist = True
                self.progress.current_index = idx
                self.progress.total_count = n

        if d.get("filename"):
            self.progress.filename = d["filename"]

        if status == "downloading":
            self.progress.status = "downloading"
            self.progress.retry_message = ""
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            self.progress.total = total
            self.progress.downloaded = downloaded
            self.progress.percent = min(downloaded / total * 100.0, 100.0) if total else 0.0
            self.progress.speed = d.get("speed") or 0
            self.progress.eta = d.get("eta") or 0
        elif status == "finished":
            self.progress.status = "merging"
            self.progress.percent = 99.0
        elif status == "error":
            self.progress.status = "error"
            self.progress.error = str(d.get("error", "Unknown error"))

        self._emit()
