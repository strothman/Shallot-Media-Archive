@echo off
cd /d "%~dp0"

:: Check if virtual environment exists
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment (.venv) not found!
    echo Please run: python -m venv .venv
    pause
    exit /b 1
)

:: Run SMArchive directly via Python
start "" ".venv\Scripts\pythonw.exe" app.py
