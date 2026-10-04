@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" tools\client_launcher.py
if errorlevel 1 pause
exit /b
:missing
echo First run install.bat.
pause
