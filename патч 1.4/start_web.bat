@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "NARYADAI_WEB_PYTHON=.webvenv\Scripts\python.exe"
if not exist "%NARYADAI_WEB_PYTHON%" set "NARYADAI_WEB_PYTHON=.venv\Scripts\python.exe"
if not exist "%NARYADAI_WEB_PYTHON%" (
  echo Сначала запустите install_web.bat для браузерной версии или install.bat для настольной.
  pause
  exit /b 1
)
echo Откройте http://127.0.0.1:8841 в браузере после запуска сервера.
"%NARYADAI_WEB_PYTHON%" run_demo.py %*
if errorlevel 1 pause
