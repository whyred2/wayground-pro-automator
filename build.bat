@echo off
setlocal
cd /d "%~dp0"

echo ===================================================
echo   Building Wayground Pro Automator (Standalone EXE)
echo ===================================================

REM Ensure local user Python installation is in PATH if available
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PATH=%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;%PATH%"
)

set "BUILD_PYTHON=python"
if exist ".venv\Scripts\python.exe" set "BUILD_PYTHON=%CD%\.venv\Scripts\python.exe"

echo [1/3] Checking dependencies...
"%BUILD_PYTHON%" -m pip install -r requirements.txt pyinstaller
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Dependency installation failed!
    pause
    exit /b 1
)

echo.
echo [2/3] Compiling the desktop executable...
"%BUILD_PYTHON%" scripts\build_windows.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Build failed!
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [3/3] Build complete!
echo Output file: dist\^<version^>\WaygroundAutomator.exe
echo ===================================================
pause
