@echo off
REM Запуск приложения учёта в виртуальном окружении.
REM При первом запуске окружение создаётся автоматически.

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Создаю виртуальное окружение .venv ...
    python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

echo Запуск приложения на http://127.0.0.1:5000
".venv\Scripts\python.exe" app.py %*
pause
