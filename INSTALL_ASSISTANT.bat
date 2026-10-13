@echo off
cd /d "%~dp0"
echo Installing...
python -m pip install -r assistant\requirements.txt || (echo Install Python from python.org first, tick "Add to PATH" & pause & exit /b 1)
echo Installing optional frameless window...
python -m pip install pywebview || echo (pywebview not installed - the window will open in Edge/Chrome app mode)
for /f "delims=" %%i in ('python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set PYW=%%i
powershell -NoProfile -Command "$s=New-Object -ComObject WScript.Shell; foreach($p in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Startup'))){$l=$s.CreateShortcut((Join-Path $p 'Assistant.lnk')); $l.TargetPath='%PYW%'; $l.Arguments='-m assistant.app'; $l.WorkingDirectory='%~dp0'; $l.Save()}"
echo.
echo Done. Shortcut "Assistant" is on your Desktop and in Startup.
pause
