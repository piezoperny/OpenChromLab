@echo off
title OpenChromLab
cd /d "%~dp0"
where py >nul 2>&1
if %errorlevel% equ 0 (
    py main.py %*
) else (
    python main.py %*
)
if errorlevel 1 (
    echo.
    echo OpenChromLab exited with an error code: %errorlevel%.
    pause
)
