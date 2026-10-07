@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" tools\setup_voice.py
if errorlevel 1 goto failed
echo Offline voice input installed. Restart the application.
pause
exit /b 0
:missing
echo First run install.bat to install the application.
pause
exit /b 1
:failed
echo Voice installation failed. Manual report input remains available.
pause
exit /b 1
