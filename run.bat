@echo off
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo [ERROR] Python environment was not found at .venv!
    echo Please run installation first.
    pause
    exit /b 1
)

:: Launch Shallot Media Archive with no console window
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0app.py"
exit
