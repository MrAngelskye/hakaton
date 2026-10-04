@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" tools\network_info.py
".venv\Scripts\python.exe" run_server.py
pause
exit /b
:missing
echo First run install.bat.
pause
