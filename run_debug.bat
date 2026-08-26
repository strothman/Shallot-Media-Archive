@echo off
cd /d "%~dp0"
echo ==============================================
echo   Shallot Media Archive (Debug Launcher)
echo ==============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment (.venv) not found!
    echo Please run: python -m venv .venv
    pause
    exit /b 1
)

".venv\Scripts\python.exe" app.py
if errorlevel 1 (
    echo.
    echo [Application exited with an error]
    pause
)
