@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
call tools\run.bat --web-fallback --system-fallback tools\open_web.py %*
if errorlevel 1 goto failed
exit /b 0
:failed
pause
exit /b 1
