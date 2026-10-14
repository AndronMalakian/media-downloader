"""Управление PO Token provider (bgutil) и поиск Deno.

YouTube с 2025 требует PO Token для большинства запросов. Без него yt-dlp
получает «The page needs to be reloaded». Токены генерирует bgutil-провайдер,
который представляет собой Node.js-приложение (HTTP-сервер на порту 4416).
"""

import os
import socket
import subprocess
import sys
from pathlib import Path

PROVIDER_VERSION = "2.0.0"
PROVIDER_REPO = "https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git"
PROVIDER_URL = f"{PROVIDER_REPO}#v{PROVIDER_VERSION}"
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 4416
SERVER_PING_PATH = "/ping"

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# Процесс запущенного нами сервера, чтобы корректно остановить его при выходе
_proc: "subprocess.Popen | None" = None


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def provider_dir() -> Path:
    # Не кладём 165 МБ рядом с .exe: папка может быть в OneDrive/Program Files.
    # Используем локальное хранилище пользователя.
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / "YT-Downloader" / "pot"


def server_dir() -> Path:
    return provider_dir() / "server"


def server_main() -> Path:
    return server_dir() / "build" / "main.js"


def provider_installed() -> bool:
    return server_main().exists() and (server_dir() / "node_modules").exists()


def find_deno() -> str | None:
    # Возвращаем ПОЛНЫЙ путь, а не просто имя: в собранном .exe рабочий каталог
    # и PATH могут отличаться, и yt-dlp не сможет запустить "deno.exe".
    import shutil

    for name in ("deno.exe", "deno"):
        full = shutil.which(name)
        if not full:
            continue
        try:
            r = subprocess.run(
                [full, "--version"],
                capture_output=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )
            if r.returncode == 0:
                return full
        except Exception:
            pass

    home = Path.home()
    candidates = [
        home / ".deno" / "bin" / "deno.exe",
        home / ".deno" / "bin" / "deno",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "deno" / "deno.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)

    packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if packages.is_dir():
        for entry in packages.iterdir():
            if entry.is_dir() and entry.name.lower().startswith("denoland.deno"):
                for cand in (entry / "deno.exe", entry / "Links" / "deno.exe"):
                    if cand.exists():
                        return str(cand)

    links = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / "deno.exe"
    if links.exists():
        return str(links)

    return None


def find_node() -> str | None:
    for name in ("node.exe", "node"):
        try:
            r = subprocess.run(
                [name, "--version"],
                capture_output=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )
            if r.returncode == 0:
                return name
        except Exception:
            pass
    return None


def _port_open() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.5)
        return s.connect_ex((SERVER_HOST, SERVER_PORT)) == 0


def server_running() -> bool:
    return _port_open()


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 1800) -> tuple[int, str]:
    try:
        r = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 1, f"Таймаут после {timeout} с"
    except Exception as e:
        return 1, str(e)


def install_provider(log=None) -> tuple[bool, str]:
    """Клонирует и собирает bgutil-провайдер. Блокирующий вызов."""
    def emit(msg: str):
        if log:
            log(msg)

    git = _find_git()
    if not git:
        return False, "Не найден git. Установите Git for Windows: https://git-scm.com/download/win"

    node = find_node()
    if not node:
        return False, "Не найден Node.js (нужен версии 20+). Установите: https://nodejs.org"

    npm = _find_npm()
    if not npm:
        return False, "Не найден npm. Переустановите Node.js."

    provider_dir().mkdir(parents=True, exist_ok=True)

    emit(f"Клонирую PO Token провайдер (версия {PROVIDER_VERSION})...")
    code, out = _run([git, "clone", "--depth", "1", "--branch", PROVIDER_VERSION, PROVIDER_REPO, str(provider_dir())])
    if code != 0 and "already exists" not in out:
        # Повторная попытка после неудачного клона
        emit("Клон не удался, повторяю после очистки...")
        _run([git, "clone", "--depth", "1", "--branch", PROVIDER_VERSION, PROVIDER_REPO, str(provider_dir())])
    if not server_dir().exists():
        return False, f"Не удалось склонировать провайдер:\n{out[-400:]}"

    emit("Ставлю зависимости Node.js (это долго, ~2-5 минут)...")
    code, out = _run([npm, "ci"], cwd=server_dir())
    if code != 0:
        code, out2 = _run([npm, "install"], cwd=server_dir())
        out = out + "\n" + out2
        if code != 0:
            return False, f"npm ci не удался:\n{out[-400:]}"

    emit("Собираю провайдер...")
    for cmd in (
        [node, "node_modules/typescript/bin/tsc"],
        ["npx.cmd", "tsc"],
        ["npx", "tsc"],
    ):
        code, out = _run(cmd, cwd=server_dir())
        if code == 0 and server_main().exists():
            break
    else:
        return False, f"Сборка не удалась:\n{out[-400:]}"

    emit("Провайдер готов.")
    return True, str(server_main())


def _find_git() -> str | None:
    for name in ("git.exe", "git"):
        try:
            r = subprocess.run(
                [name, "--version"],
                capture_output=True,
                timeout=10,
                creationflags=CREATE_NO_WINDOW,
            )
            if r.returncode == 0:
                return name
        except Exception:
            pass
    return None


def _find_npm() -> str | None:
    for name in ("npm.cmd", "npm"):
        try:
            r = subprocess.run(
                [name, "--version"],
                capture_output=True,
                timeout=20,
                creationflags=CREATE_NO_WINDOW,
            )
            if r.returncode == 0:
                return name
        except Exception:
            pass
    return None


def start_server(log=None) -> bool:
    """Запускает PO Token сервер. Возвращает True, если он отвечает."""
    global _proc
    if server_running():
        return True
    if not provider_installed():
        return False

    node = find_node()
    if not node:
        return False

    if log:
        log(f"Запускаю PO Token сервер ({SERVER_HOST}:{SERVER_PORT})...")

    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)

    try:
        _proc = subprocess.Popen(
            [node, str(server_main())],
            cwd=str(server_dir()),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
    except Exception as e:
        if log:
            log(f"Не удалось запустить PO Token сервер: {e}")
        return False

    import time

    for _ in range(30):
        if server_running():
            if log:
                log("PO Token сервер запущен.")
            return True
        time.sleep(1)

    if log:
        log("PO Token сервер не ответил за 30 секунд.")
    return False


def _server_pids() -> list[str]:
    """PID-ы процессов, слушающих порт провайдера (без учёта языка ОС)."""
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=20,
            creationflags=CREATE_NO_WINDOW,
        ).stdout
    except Exception:
        return []

    pids: list[str] = []
    for line in out.splitlines():
        parts = line.split()
        # Proto Local Foreign State PID — состояние локализовано, PID всегда последний
        if len(parts) < 5 or not parts[0].upper().startswith("TCP"):
            continue
        if not parts[1].endswith(f":{SERVER_PORT}"):
            continue
        pid = parts[-1]
        if pid.isdigit() and pid not in pids:
            pids.append(pid)
    return pids


def stop_server() -> None:
    if os.name != "nt":
        return

    pids = _server_pids()
    if _proc is not None and _proc.poll() is not None:
        pids = [str(_proc.pid)] if not pids else pids

    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/PID", pid, "/T", "/F"],
                capture_output=True,
                timeout=20,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception:
            pass
