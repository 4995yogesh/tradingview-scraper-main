@echo off
title Trading Dashboard Web Launcher

set "PYTHON_EXEC=.venv\Scripts\python.exe"

if not exist "%PYTHON_EXEC%" (
    echo [WARN] Virtual environment not found. Falling back to system python...
    set "PYTHON_EXEC=python"
)

echo Starting Web Launcher...
"%PYTHON_EXEC%" web_launcher.py
pause
