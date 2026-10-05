@echo off
rem Builds MassCopyPurchases.epf from the "dump" folder using 1C Designer (no programming needed).
setlocal
set "V8="
for /f "delims=" %%D in ('dir /b /ad /o-n "%ProgramFiles%\1cv8" 2^>nul') do if not defined V8 if exist "%ProgramFiles%\1cv8\%%D\bin\1cv8.exe" set "V8=%ProgramFiles%\1cv8\%%D\bin\1cv8.exe"
for /f "delims=" %%D in ('dir /b /ad /o-n "%ProgramFiles(x86)%\1cv8" 2^>nul') do if not defined V8 if exist "%ProgramFiles(x86)%\1cv8\%%D\bin\1cv8.exe" set "V8=%ProgramFiles(x86)%\1cv8\%%D\bin\1cv8.exe"
if not defined V8 (
  echo 1cv8.exe not found. Edit this file and set V8 to the full path of 1cv8.exe.
  pause & exit /b 1
)
set "BASE=%TEMP%\epf_build_base"
if exist "%BASE%" rmdir /s /q "%BASE%"
"%V8%" CREATEINFOBASE File="%BASE%"
for %%F in ("%~dp0dump\*.xml") do set "ROOTXML=%%~fF"
set "OUT=%~dp0MassCopyPurchases.epf"
set "LOG=%~dp0build.log"
"%V8%" DESIGNER /F "%BASE%" /DisableStartupDialogs /LoadExternalDataProcessorOrReportFromFiles "%ROOTXML%" "%OUT%" /Out "%LOG%"
if exist "%OUT%" (echo DONE: %OUT%) else (echo FAILED. See %LOG% & type "%LOG%")
pause
