@echo off
chcp 65001 > nul
cd /d "%~dp0"

if not exist "venv\Scripts\pythonw.exe" (
    echo.
    echo  Первый запуск. Создаю окружение, это может занять пару минут...
    echo.
    python -m venv venv || goto :fail
    call venv\Scripts\activate.bat
    pip install -q --upgrade pip
    pip install -q -r requirements.txt || goto :fail
)

start "" "venv\Scripts\pythonw.exe" main.py
exit /b 0

:fail
echo.
echo  Не удалось. Проверьте, что Python установлен и доступен в PATH.
echo.
pause
exit /b 1
