@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
 echo Сначала запустите install.bat.
 pause
 exit /b 1
)
".venv\Scripts\python.exe" tools\admin_console.py
pause
