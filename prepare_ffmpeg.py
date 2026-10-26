"""Скачивает FFmpeg перед упаковкой приложения. Не запускается у пользователя."""

import subprocess
from pathlib import Path

from ffmpeg_tools import TOOLS, install_ffmpeg


def main():
    destination = Path(__file__).resolve().parent / ".build-tools" / "ffmpeg"
    if not all((destination / "bin" / tool).is_file() for tool in TOOLS):
        install_ffmpeg(destination, log=lambda message: print(message, flush=True))
    for tool in TOOLS:
        result = subprocess.run(
            [str(destination / "bin" / tool), "-version"],
            capture_output=True, text=True, timeout=15,
        )
        result.check_returncode()
        print(result.stdout.splitlines()[0], flush=True)


if __name__ == "__main__":
    main()
