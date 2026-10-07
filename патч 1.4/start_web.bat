@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
echo Откройте http://127.0.0.1:8841 после запуска сервера.
call tools\run.bat --web-first run_demo.py %*
if errorlevel 1 goto failed
exit /b 0
:failed
pause
exit /b 1
