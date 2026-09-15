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

echo [1/3] Checking dependencies...
python -m pip install -r requirements.txt pyinstaller

echo.
echo [2/3] Compiling with PyInstaller...
pyinstaller --noconfirm --onefile --clean ^
  --name "WaygroundAutomator" ^
  --icon "assets/icon.ico" ^
  --collect-data playwright_stealth ^
  --paths "src" ^
  src/main.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Build failed!
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [3/3] Build complete!
echo Output file: dist\WaygroundAutomator.exe
echo ===================================================
pause
