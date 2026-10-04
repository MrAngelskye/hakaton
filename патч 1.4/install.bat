@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto no_python
py -3 -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Installation complete. Network mode: open START_HERE.txt.
pause
exit /b 0
:no_python
echo Python launcher not found. Install 64-bit Python 3.12 from python.org.
pause
exit /b 1
:failed
echo Installation failed. Keep this window open and send the error text.
pause
exit /b 1
