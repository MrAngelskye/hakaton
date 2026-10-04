@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto no_python
py -3 tools\install.py
if errorlevel 1 goto failed
echo Installation complete. Network mode: open START_HERE.txt.
pause
exit /b 0
:no_python
echo Python launcher not found. Install 64-bit Python 3.12 from python.org.
pause
exit /b 1
:failed
echo Installation failed. See the explanation above. Keep this window open.
pause
exit /b 1
