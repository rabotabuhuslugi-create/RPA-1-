@echo off
rem Builds SverkaVozvratov.epf from the "dump" folder using 1C Designer.
rem The form uses documents and catalogs of Kompleksnaya Avtomatizaciya, so the build
rem must be done on a COPY of your database (a blank database does not know these types).
rem Close Designer on that base before running. The base itself is NOT modified.
setlocal
set "V8="
for /f "delims=" %%D in ('dir /b /ad /o-n "%ProgramFiles%\1cv8" 2^>nul') do if not defined V8 if exist "%ProgramFiles%\1cv8\%%D\bin\1cv8.exe" set "V8=%ProgramFiles%\1cv8\%%D\bin\1cv8.exe"
for /f "delims=" %%D in ('dir /b /ad /o-n "%ProgramFiles(x86)%\1cv8" 2^>nul') do if not defined V8 if exist "%ProgramFiles(x86)%\1cv8\%%D\bin\1cv8.exe" set "V8=%ProgramFiles(x86)%\1cv8\%%D\bin\1cv8.exe"
if not defined V8 (
  echo 1cv8.exe not found. Edit this file and set V8 to the full path of 1cv8.exe.
  pause & exit /b 1
)
echo Build on a COPY of your database.
echo   1 - file base
echo   2 - server base
set /p KIND=Enter 1 or 2: 
set "CONN="
if "%KIND%"=="1" (
  set /p BASEDIR=Full path to the base folder, without quotes: 
  set "CONN=File=%BASEDIR%;"
)
if "%KIND%"=="2" (
  set /p SRV=Server name: 
  set /p REF=Base name on the server: 
  set "CONN=Srvr=%SRV%;Ref=%REF%;"
)
if not defined CONN (
  echo Nothing entered.
  pause & exit /b 1
)
set /p USR=1C user name, Enter if none: 
set /p PWD=Password, Enter if none: 
set "AUTH="
if defined USR set "AUTH=/N "%USR%" /P "%PWD%""
for %%F in ("%~dp0dump\*.xml") do set "ROOTXML=%%~fF"
set "OUT=%~dp0SverkaVozvratov.epf"
set "LOG=%~dp0build.log"
if exist "%OUT%" del "%OUT%"
"%V8%" DESIGNER /IBConnectionString "%CONN%" %AUTH% /DisableStartupDialogs /LoadExternalDataProcessorOrReportFromFiles "%ROOTXML%" "%OUT%" /Out "%LOG%"
if exist "%OUT%" (echo DONE: %OUT%) else (echo FAILED. See %LOG% & type "%LOG%")
pause
