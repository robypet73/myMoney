@echo off
rem Crea sul Desktop il collegamento myMoney che avvia il programma, con l'icona dell'app.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$q='%~dp0'; $d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut($d+'\myMoney.lnk'); $s.TargetPath=$q+'avvia.cmd'; $s.WorkingDirectory=$q; $s.IconLocation=$q+'icons\myMoney.ico'; $s.Description='myMoney - portafogli ETF'; $s.WindowStyle=7; $s.Save(); Write-Host ('Collegamento creato: '+$d+'\myMoney.lnk')"
if errorlevel 1 echo Non sono riuscito a creare il collegamento: crealo a mano (tasto destro su avvia.cmd, Invia a, Desktop) e scegli l'icona icons\myMoney.ico dalle sue Proprieta'.
pause
