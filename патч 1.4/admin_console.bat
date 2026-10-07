@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
call tools\run.bat tools\admin_console.py %*
if errorlevel 1 goto failed
pause
exit /b 0
:failed
pause
exit /b 1
