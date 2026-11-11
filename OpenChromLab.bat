@echo off
title OpenChromLab
cd /d "%~dp0"

rem Launch OpenChromLab natively on Windows.
rem Prefers pyw / pythonw for a clean desktop window without a black console window.

where pyw >nul 2>&1
if %errorlevel% equ 0 (
    start "" pyw main.py %*
    exit /b 0
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    py main.py %*
    if errorlevel 1 (
        echo.
        echo OpenChromLab exited with error %errorlevel%.
        pause
    )
    exit /b %errorlevel%
)

where pythonw >nul 2>&1
if %errorlevel% equ 0 (
    start "" pythonw main.py %*
    exit /b 0
)

python main.py %*
if errorlevel 1 (
    echo.
    echo OpenChromLab exited with error %errorlevel%.
    pause
)
