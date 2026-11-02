@echo off
rem Сборка RPA1C.exe (запускать на Windows один раз, нужен Python)
chcp 65001 >nul
cd /d "%~dp0"
python -m venv .build-venv
.build-venv\Scripts\python -m pip install -q -r requirements.txt pyinstaller
.build-venv\Scripts\pyinstaller --noconfirm --onedir --name RPA1C --add-data "rpa1c\web;rpa1c\web" run_app.py
echo.
echo Готово: папка dist\RPA1C, запускайте dist\RPA1C\RPA1C.exe
echo Для PDF положите рядом папку poppler (poppler\bin) и укажите путь в config.yaml: ocr.poppler_path
pause
