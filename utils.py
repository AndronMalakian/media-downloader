import os
import shutil
import subprocess
import sys

import requests
from pathlib import Path


GECKO_BROWSERS = {"firefox", "thunderbird", "librewolf", "waterfox"}


def browser_reads_ok(name: str) -> bool:
    """Читает ли yt-dlp cookies этого браузера.

    Chromium 127+ хранит ключ через app-bound encryption — он привязан к самому
    браузеру, и внешняя программа (yt-dlp) расшифровать его не может.
    """
    if name in GECKO_BROWSERS:
        return True
    root = _browser_root(name)
    if root is None:
        return True
    local_state = root / "Local State"
    if not local_state.exists():
        return True
    try:
        import json

        data = json.loads(local_state.read_text(encoding="utf-8"))
        os_crypt = data.get("os_crypt") or {}
        return "app_bound_encrypted_key" not in os_crypt
    except Exception:
        return True


def _browser_root(name: str) -> Path | None:
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
    roots = {
        "chrome": local / "Google" / "Chrome" / "User Data",
        "edge": local / "Microsoft" / "Edge" / "User Data",
        "chromium": local / "Chromium" / "User Data",
        "brave": local / "BraveSoftware" / "Brave-Browser" / "User Data",
        "opera": appdata / "Opera Software" / "Opera Stable",
        "vivaldi": local / "Vivaldi" / "User Data",
    }
    return roots.get(name)


def detect_browsers() -> list[tuple[str, str]]:
    """Возвращает список (имя для yt-dlp, профиль) для браузеров с профилем на этом ПК."""
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))

    known = {
        "chrome": (local / "Google" / "Chrome" / "User Data", "Default"),
        "edge": (local / "Microsoft" / "Edge" / "User Data", "Default"),
        "chromium": (local / "Chromium" / "User Data", "Default"),
        "brave": (local / "BraveSoftware" / "Brave-Browser" / "User Data", "Default"),
        "opera": (appdata / "Opera Software" / "Opera Stable", "Default"),
        "vivaldi": (local / "Vivaldi" / "User Data" / "Default", "Default"),
        "firefox": (appdata / "Mozilla" / "Firefox" / "Profiles", None),
        "thunderbird": (appdata / "Thunderbird" / "Profiles", None),
    }

    found: list[tuple[str, str]] = []
    for name, (root, profile) in known.items():
        if not root.exists():
            continue
        if profile is None:
            subs = [p for p in root.iterdir() if p.is_dir()] if root.is_dir() else []
            if not subs:
                continue
            found.append((name, str(subs[0])))
        else:
            if (root / profile).exists():
                found.append((name, str(root / profile)))
    return found


def is_browser_running(names: list[str]) -> list[str]:
    """Какие из процессов браузеров сейчас запущены."""
    import subprocess as sp

    running = []
    try:
        out = sp.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.lower()
    except Exception:
        return running
    for name in names:
        if f'"{name}.exe"' in out:
            running.append(name)
    return running


def get_default_download_dir() -> Path:
    downloads = Path.home() / "Downloads"
    downloads.mkdir(exist_ok=True)
    return downloads


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _tool_candidates(tool: str) -> list[Path]:
    names = (f"{tool}.exe", tool)
    roots = [Path.cwd(), app_dir()]
    seen = set()
    out: list[Path] = []
    for root in roots:
        for rel in ("", "ffmpeg", "ffmpeg/bin", "bin"):
            for name in names:
                p = (root / rel / name) if rel else (root / name)
                key = str(p).lower()
                if key not in seen:
                    seen.add(key)
                    out.append(p)
    return out


def _which(name: str) -> str | None:
    # Возвращаем ПОЛНЫЙ путь: иначе dirname("ffmpeg.exe") даёт "." и yt-dlp
    # не находит FFmpeg при склейке видео+аудио.
    try:
        found = shutil.which(name)
        if not found:
            return None
        result = subprocess.run(
            [found, "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )
        if result.returncode == 0:
            return found
    except Exception:
        pass
    return None


def _find_tool(tool: str) -> str | None:
    found = _which(f"{tool}.exe") or _which(tool)
    if found:
        return found
    for c in _tool_candidates(tool):
        if c.exists() and c.is_file():
            return str(c)
    return None


def find_ffmpeg() -> str | None:
    return _find_tool("ffmpeg")


def find_ffprobe() -> str | None:
    return _find_tool("ffprobe")


def get_ffmpeg_download() -> dict | None:
    try:
        url = "https://api.github.com/repos/yt-dlp/FFmpeg-Builds/releases/latest"
        r = requests.get(url, timeout=10, headers={"User-Agent": "Media-Downloader"})
        r.raise_for_status()
        data = r.json()
        for a in data.get("assets", []):
            name = a.get("name", "").lower()
            if "essentials" in name and "win64" in name and name.endswith(".zip"):
                return {
                    "name": a["name"],
                    "url": a["browser_download_url"],
                    "size": a.get("size", 0),
                }
    except Exception:
        pass
    return None


def format_bytes(size: int) -> str:
    if size <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(size)
    while size >= 1024 and i < len(units) - 1:
        size /= 1024.0
        i += 1
    return f"{size:.2f} {units[i]}"


def format_duration(seconds) -> str:
    if seconds is None or seconds < 0:
        return "00:00"
    s = int(seconds)
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def format_eta(seconds) -> str:
    if not seconds or seconds <= 0:
        return "—"
    s = int(seconds)
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


_LOGIN_COOKIE_NAMES = {"SID", "__Secure-1PSID", "LOGIN_INFO"}


def check_cookies_file(path) -> dict:
    """Проверяет, что cookies.txt содержит данные входа в аккаунт YouTube.

    Многие расширения экспортируют только «гостевые» cookies (например,
    ``__Secure-3PSID`` без ``SID``/``LOGIN_INFO``). Такой файл выглядит
    нормально, но YouTube считает вас неавторизованным — приватные,
    возрастные и часть эфиров не открываются с ошибкой «Sign in to confirm
    you're not a bot».
    """
    import http.cookiejar as cj

    try:
        jar = cj.MozillaCookieJar(str(path))
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception:
        return {
            "ok": False,
            "total": 0,
            "authenticated": False,
            "detail": "Не удалось прочитать файл cookies. Проверьте формат (Netscape .txt).",
        }

    names = {c.name for c in jar}
    if not names:
        return {
            "ok": False,
            "total": 0,
            "authenticated": False,
            "detail": "Файл cookies пуст.",
        }

    if names & _LOGIN_COOKIE_NAMES:
        return {
            "ok": True,
            "total": len(names),
            "authenticated": True,
            "detail": f"Cookies загружены ({len(names)} шт.), вход в аккаунт подтверждён.",
        }

    return {
        "ok": True,
        "total": len(names),
        "authenticated": False,
        "detail": (
            f"В файле {len(names)} cookies, но НЕТ данных входа (SID / LOGIN_INFO).\n"
            "YouTube будет считать вас гостем: приватные, возрастные видео и часть "
            "эфиров не скачаются («Sign in to confirm you're not a bot»).\n"
            "Экспортируйте cookies заново, находясь авторизованным на YouTube."
        ),
    }


def _tls_ok(ip: str, sni: str, timeout: float) -> bool:
    """Проверяет, проходит ли TLS-рукопожатие к ip с указанным SNI."""
    import socket
    import ssl

    try:
        sock = socket.create_connection((ip, 443), timeout=timeout)
    except Exception:
        return False
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.wrap_socket(sock, server_hostname=sni)
        return True
    except Exception:
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass


def check_youtube_network(timeout: float = 8.0) -> dict:
    """Диагностика доступа к YouTube.

    Различает обычные сбои и блокировку по SNI (DPI у провайдера): тогда
    TLS к YouTube не проходит, а к google.com через тот же IP — проходит.
    """
    import socket

    yt_host = "www.youtube.com"
    probe_host = "www.google.com"

    try:
        yt_ip = socket.gethostbyname(yt_host)
    except Exception:
        return {
            "state": "dns",
            "detail": f"DNS не может найти {yt_host}. Похоже на проблему с интернетом или DNS-сервером.",
        }

    try:
        sock = socket.create_connection((yt_ip, 443), timeout=timeout)
        sock.close()
    except Exception:
        return {
            "state": "tcp",
            "detail": f"Порт 443 у {yt_ip} недоступен. Соединение блокируется до начала шифрования.",
        }

    if _tls_ok(yt_ip, yt_host, timeout):
        return {"state": "ok", "detail": f"YouTube доступен ({yt_ip})."}

    if _tls_ok(yt_ip, probe_host, timeout):
        return {
            "state": "blocked",
            "detail": (
                f"Провайдер блокирует YouTube по имени домена (SNI/DPI).\n"
                f"Один и тот же IP {yt_ip} открывается как «{probe_host}», "
                f"но не открывается как «{yt_host}» — значит режется именно имя сайта.\n\n"
                "Это блокировка на стороне вашей сети, а не в программе.\n"
                "Помогает только VPN или прокси — тогда YouTube качается нормально."
            ),
        }

    return {
        "state": "tls",
        "detail": (
            f"TLS-рукопожатие к {yt_ip} не проходит ни с одним именем.\n"
            "Похоже на общий сбой канала или блокировку шифрованного трафика."
        ),
    }

