@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" tools\check_ai.py
pause
exit /b
:missing
echo First run install.bat.
pause
