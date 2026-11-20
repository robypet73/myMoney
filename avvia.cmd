@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py -3 francesca.py) else (python francesca.py)
if errorlevel 1 (
  echo.
  echo Non riesco ad avviare il programma. Serve Python 3.9 o piu' recente: https://www.python.org/downloads/ ^(spunta Add python.exe to PATH^)
)
pause
