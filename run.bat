@echo off
title Shallot Media Archive
cd /d "%~dp0"

if not exist "%~dp0.venv\Scripts\python.exe" (
    echo [ERROR] Python virtual environment was not found at .venv!
    echo Please make sure .venv exists.
    pause
    exit /b 1
)

:: Launch Shallot Media Archive
"%~dp0.venv\Scripts\python.exe" "%~dp0app.py"

if errorlevel 1 (
    echo.
    echo [Application closed with an error code: %errorlevel%]
    pause
)
