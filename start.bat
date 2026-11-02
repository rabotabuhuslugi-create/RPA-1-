@echo off
chcp 65001 >nul
cd /d "%~dp0"
title RPA 1C
rem 1. обновление программы (если папка скачана через git)
where git >nul 2>nul && if exist .git git pull --ff-only origin claude/new-session-04th4h >nul 2>nul
rem 2. Python
where python >nul 2>nul || (
  echo Устанавливаю Python...
  winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
  echo Python установлен. Закройте это окно и запустите start.bat ещё раз.
  pause & exit /b 0
)
rem 3. Ollama (распознавание)
where ollama >nul 2>nul || if not exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
  echo Устанавливаю Ollama...
  winget install -e --id Ollama.Ollama --silent --accept-package-agreements --accept-source-agreements
)
rem 4. окружение программы
if not exist .venv\Scripts\python.exe (
  echo Первый запуск: устанавливаю программу, это займёт пару минут...
  python -m venv .venv || (pause & exit /b 1)
)
.venv\Scripts\python -m pip install -q -r requirements.txt || (pause & exit /b 1)
rem 5. запуск (модель распознавания скачается сама)
.venv\Scripts\python run_app.py
pause
