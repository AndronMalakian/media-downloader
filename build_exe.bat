@echo off
chcp 65001 > nul
title YT Downloader - build

echo ==========================================
echo   YT Downloader - сборка .exe
echo ==========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ОШИБКА] Python не найден в PATH. Установите Python 3.10+ с python.org
    pause
    exit /b 1
)

if not exist "venv\" (
    echo Создаю виртуальное окружение...
    python -m venv venv
    if errorlevel 1 goto :fail
)

call venv\Scripts\activate.bat

echo Ставлю зависимости...
pip install -q --upgrade pip
if errorlevel 1 goto :fail
pip install -q -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo Собираю .exe (это 1-3 минуты)...
echo.

set BUILD_ARGS=--noconfirm --clean --onefile --windowed ^
    --name "YT-Downloader" ^
    --collect-all ttkbootstrap ^
    --collect-all yt_dlp ^
    --collect-all yt_dlp_ejs ^
    --collect-all bgutil_ytdlp_pot_provider ^
    --hidden-import=yt_dlp_plugins.extractor.getpot_bgutil_http ^
    --hidden-import=yt_dlp_plugins.extractor.getpot_bgutil_script

if exist "icon.ico" (
    pyinstaller %BUILD_ARGS% --icon="icon.ico" --add-data "icon.ico;." main.py
) else (
    pyinstaller %BUILD_ARGS% main.py
)

if errorlevel 1 goto :fail

echo.
echo ==========================================
echo   Готово: dist\YT-Downloader.exe
echo ==========================================
echo.
pause
exit /b 0

:fail
echo.
echo [ОШИБКА] Сборка не удалась. Смотрите текст выше.
pause
exit /b 1
