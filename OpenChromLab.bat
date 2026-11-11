@echo off
title OpenChromLab
cd /d "%~dp0"

:: Auto-heal / create shortcut with icon if missing or relocated
if not exist "%~dp0OpenChromLab.lnk" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell;$s=$ws.CreateShortcut('%~dp0OpenChromLab.lnk');$s.TargetPath='%~dp0OpenChromLab.bat';$s.WorkingDirectory='%~dp0';$s.IconLocation='%~dp0OpenChromLab.ico,0';$s.Description='OpenChromLab - Chromatography Data System';$s.Save()" >nul 2>&1
)

:: 1. Check local portable Python in .python or python folder
if exist "%~dp0.python\pythonw.exe" (
    start "" "%~dp0.python\pythonw.exe" main.py %*
    exit /b 0
)
if exist "%~dp0.python\python.exe" (
    "%~dp0.python\python.exe" main.py %*
    exit /b %errorlevel%
)
if exist "%~dp0python\pythonw.exe" (
    start "" "%~dp0python\pythonw.exe" main.py %*
    exit /b 0
)
if exist "%~dp0python\python.exe" (
    "%~dp0python\python.exe" main.py %*
    exit /b %errorlevel%
)

:: 2. Check system pyw / py / pythonw / python
where pyw >nul 2>&1
if %errorlevel% equ 0 (
    start "" pyw main.py %*
    exit /b 0
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    py main.py %*
    if errorlevel 1 pause
    exit /b %errorlevel%
)

where pythonw >nul 2>&1
if %errorlevel% equ 0 (
    start "" pythonw main.py %*
    exit /b 0
)

where python >nul 2>&1
if %errorlevel% equ 0 (
    python main.py %*
    if errorlevel 1 pause
    exit /b %errorlevel%
)

:: 3. Check Astral uv standalone runner (user-space, no admin required)
if exist "%LOCALAPPDATA%\uv\uv.exe" (
    "%LOCALAPPDATA%\uv\uv.exe" run python main.py %*
    exit /b %errorlevel%
)
if exist "%USERPROFILE%\.cargo\bin\uv.exe" (
    "%USERPROFILE%\.cargo\bin\uv.exe" run python main.py %*
    exit /b %errorlevel%
)
where uv >nul 2>&1
if %errorlevel% equ 0 (
    uv run python main.py %*
    exit /b %errorlevel%
)

:: 4. If Python is not installed on this system: Auto-bootstrap portable runtime in user space (no admin rights needed)
echo ======================================================================
echo   OpenChromLab — Initializing Portable Environment
echo ======================================================================
echo   No Python installation was detected on this PC.
echo   Setting up an isolated, portable runtime (no administrator rights needed)...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" >nul 2>&1
if exist "%LOCALAPPDATA%\uv\uv.exe" (
    echo   Launching OpenChromLab...
    "%LOCALAPPDATA%\uv\uv.exe" run python main.py %*
    exit /b %errorlevel%
)

echo.
echo [ERROR] Python is required to run OpenChromLab.
echo Neither Python nor an internet connection to fetch the portable runtime was found.
echo.
echo To run OpenChromLab:
echo   1. Copy the portable .python/ folder from your lab's shared network drive, OR
echo   2. Install Python from python.org or Microsoft Store (no admin rights needed).
echo.
pause
exit /b 1
