@echo off
rem Avvia il widget myMoney sul desktop (nessuna finestra nera: usa pythonw/pyw se ci sono).
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel%==0 (
  start "" pyw -3 widget.py
  exit /b
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
  start "" pythonw widget.py
  exit /b
)
where py >nul 2>nul
if %errorlevel%==0 (py -3 widget.py) else (python widget.py)
if errorlevel 1 (
  echo.
  echo Non riesco ad avviare il widget. Serve Python 3.9 o piu' recente con Tkinter: https://www.python.org/downloads/
  pause
)
