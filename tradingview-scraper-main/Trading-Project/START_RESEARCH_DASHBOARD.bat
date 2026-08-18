@echo off
setlocal
cd /d "%~dp0"
title Candlestick Representation Learning Dashboard

where py >nul 2>&1
if %errorlevel%==0 (
    py start_research_dashboard.py
) else (
    python start_research_dashboard.py
)

if not %errorlevel%==0 (
    echo.
    echo Dashboard stopped with an error. Review the message above.
    pause
)
endlocal
