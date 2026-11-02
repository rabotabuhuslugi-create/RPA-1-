@echo off
chcp 65001 >nul
echo Останавливаю RPA 1C...
for /f "tokens=2" %%p in ('tasklist /fi "imagename eq python.exe" /nh ^| find "python.exe"') do taskkill /f /pid %%p >nul 2>nul
echo Готово. Теперь можно запустить start.bat заново.
pause
