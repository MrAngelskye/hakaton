@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
call tools\run.bat tools\client_launcher.py %*
if errorlevel 1 goto failed
exit /b 0
:failed
pause
exit /b 1
