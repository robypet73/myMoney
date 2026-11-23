@echo off
rem Attiva (o con il parametro off, disattiva) l'avvio automatico del widget myMoney con Windows.
cd /d "%~dp0"
set STATO=on
if /i "%~1"=="off" set STATO=off
where py >nul 2>nul
if %errorlevel%==0 (py -3 widget.py --avvio %STATO%) else (python widget.py --avvio %STATO%)
pause
