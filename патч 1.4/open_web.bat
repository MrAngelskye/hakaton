@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "NARYADAI_OPEN_PYTHON=.venv\Scripts\python.exe"
if not exist "%NARYADAI_OPEN_PYTHON%" set "NARYADAI_OPEN_PYTHON=.webvenv\Scripts\python.exe"
if not exist "%NARYADAI_OPEN_PYTHON%" set "NARYADAI_OPEN_PYTHON=python"
"%NARYADAI_OPEN_PYTHON%" tools\open_web.py %*
if errorlevel 1 pause
