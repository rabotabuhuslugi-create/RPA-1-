@echo off
chcp 65001 >nul
cd /d "%~dp0"
title RPA 1C
if not exist .venv\Scripts\python.exe (
  echo Первый запуск: устанавливаю программу, это займёт пару минут...
  where python >nul 2>nul || (
    echo Не найден Python. Установите: winget install -e --id Python.Python.3.12
    pause & exit /b 1
  )
  python -m venv .venv || (pause & exit /b 1)
  .venv\Scripts\python -m pip install -q -r requirements.txt || (pause & exit /b 1)
)
.venv\Scripts\python run_app.py
pause
