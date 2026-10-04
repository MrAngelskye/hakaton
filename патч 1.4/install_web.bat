@echo off
setlocal
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto no_python
py -3.12 -c "import sys; print(sys.version)" >nul 2>nul
if errorlevel 1 goto no_python
py -3.12 -m venv .webvenv
if errorlevel 1 goto failed
".webvenv\Scripts\python.exe" -m pip install -r requirements-server.txt
if errorlevel 1 goto failed
".webvenv\Scripts\python.exe" -m pip check
if errorlevel 1 goto failed
echo Web installation complete. Run start_web.bat.
pause
exit /b 0
:no_python
echo Install 64-bit Python 3.12 with the Python launcher from python.org.
pause
exit /b 1
:failed
echo Installation failed. See the explanation above.
pause
exit /b 1
