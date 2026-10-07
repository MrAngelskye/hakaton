@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
call tools\run.bat tools\setup_voice.py %*
if errorlevel 1 goto failed
echo Offline voice input installed. Restart the application.
pause
exit /b 0
:failed
echo Voice installation failed. Manual report input remains available.
pause
exit /b 1
