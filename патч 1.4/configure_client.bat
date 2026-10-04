@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
".venv\Scripts\python.exe" tools\client_launcher.py --change-server
pause
