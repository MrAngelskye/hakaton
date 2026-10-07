@echo off
setlocal
set PYTHONUTF8=1
where py >nul 2>nul
if errorlevel 1 goto no_python
py -3 "%~dp0run.py" %*
exit /b %errorlevel%
:no_python
echo Python launcher not found. Install 64-bit Python with the Python launcher, then run install.bat.
exit /b 1
