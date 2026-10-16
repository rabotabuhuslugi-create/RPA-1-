@echo off
rem Сборка РазведкаЭПД.epf из исходников. Путь к 1cv8.exe поправьте под свою версию платформы.
chcp 65001 >nul
set V8="C:\Program Files\1cv8\8.3.25.1445\bin\1cv8.exe"
%V8% DESIGNER /DisableStartupDialogs /DisableStartupMessages /LoadExternalDataProcessorOrReportFromFiles "%~dp0src\РазведкаЭПД.xml" "%~dp0РазведкаЭПД.epf" /Out "%~dp0build.log"
type "%~dp0build.log"
