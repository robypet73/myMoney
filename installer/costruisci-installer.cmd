@echo off
rem Costruisce sul tuo PC l'installer di myMoney (dist-installer\myMoney-Setup.exe), senza GitHub.
rem Serve Python 3.9+ (https://www.python.org/downloads/, spunta "Add python.exe to PATH") e Inno Setup 6 (https://jrsoftware.org/isdl.php).
cd /d "%~dp0.."
where py >nul 2>nul
if %errorlevel%==0 (set PY=py -3) else (set PY=python)
%PY% --version >nul 2>nul || goto nopy

echo [1/3] Installo PyInstaller...
%PY% -m pip install --quiet --upgrade pyinstaller tzdata || goto errore

echo [2/3] Creo i programmi (cartella dist\myMoney)...
%PY% -m PyInstaller installer\myMoney.spec --noconfirm --distpath dist --workpath build-pyi || goto errore

set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe
if "%ISCC%"=="" goto noinno

echo [3/3] Creo l'installer...
for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy.M.d"') do set VER=%%d
"%ISCC%" /DVersione=%VER% installer\myMoney.iss || goto errore
echo.
echo Fatto: dist-installer\myMoney-Setup.exe
pause
exit /b 0

:noinno
echo.
echo Inno Setup non e' installato: i programmi sono pronti in dist\myMoney (myMoney.exe e myMoney-widget.exe, usabili cosi').
echo Per avere anche l'installer installa Inno Setup 6 (https://jrsoftware.org/isdl.php oppure: winget install JRSoftware.InnoSetup) e rilancia questo file.
pause
exit /b 1

:nopy
echo Python non trovato: installa Python 3.9 o piu' recente da https://www.python.org/downloads/ (spunta Add python.exe to PATH).
pause
exit /b 1

:errore
echo.
echo Qualcosa e' andato storto: guarda il messaggio qui sopra.
pause
exit /b 1
