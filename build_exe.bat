@echo off
title Build OpenChromLab.exe
cd /d "%~dp0"

echo ======================================================================
echo   OpenChromLab — Standalone Single-File Windows Executable Builder
echo ======================================================================
echo.

:: 1. Ensure Python or uv is available
where py >nul 2>&1
if %errorlevel% equ 0 (
    set "PY_CMD=py"
) else (
    where python >nul 2>&1
    if %errorlevel% equ 0 (
        set "PY_CMD=python"
    ) else (
        echo [ERROR] Python was not found on PATH.
        echo Please ensure Python is installed to build the executable.
        pause
        exit /b 1
    )
)

:: 2. Install PyInstaller, Pillow, and openpyxl
echo Installing / verifying build dependencies (pyinstaller, pillow, openpyxl)...
%PY_CMD% -m pip install --upgrade pyinstaller pillow openpyxl
if errorlevel 1 (
    echo [ERROR] Failed to install build dependencies.
    pause
    exit /b 1
)

:: 3. Clean old build artifacts
if exist "dist\OpenChromLab.exe" del /f /q "dist\OpenChromLab.exe"
if exist "build" rd /s /q "build"

:: 4. Build single-file executable using OpenChromLab.spec
echo.
echo Compiling OpenChromLab.exe (embedding multi-res icon, splash, and runtime)...
%PY_CMD% -m PyInstaller --clean --noconfirm OpenChromLab.spec
if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller compilation failed.
    pause
    exit /b 1
)

echo.
echo ======================================================================
echo   BUILD SUCCESSFUL!
echo   Standalone executable created at:
echo   %~dp0dist\OpenChromLab.exe
echo ======================================================================
echo.
echo You can now copy dist\OpenChromLab.exe directly to your Desktop or
echo share it with colleagues — no Python installation or extra files required!
echo.
pause
