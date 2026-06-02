@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"

echo Starting Screen Translation...
echo Working directory: %CD%
echo.

if not exist ".venv\Scripts\python.exe" (
    echo .venv was not found. Creating a Python 3.14 virtual environment...
    py -3.14 -m venv .venv
    if errorlevel 1 (
        echo.
        echo Failed to create .venv.
        echo Please check that Python 3.14 is installed and py -3.14 is available.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -c "import mss, PIL, pytesseract, argostranslate, pygetwindow" >nul 2>nul
if errorlevel 1 (
    echo Installing Python dependencies into .venv...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Failed to install Python dependencies.
        pause
        exit /b 1
    )
)

where tesseract >nul 2>nul
if errorlevel 1 (
    echo.
    echo Warning: Tesseract OCR was not found in PATH.
    echo OCR requires the Tesseract OCR desktop program.
    echo.
)

if not exist "config" mkdir "config"

if "%~1"=="--check" (
    echo Launcher check passed.
    exit /b 0
)

set "PYTHONPATH=src"
".venv\Scripts\python.exe" -m app.main --desktop
if errorlevel 1 (
    echo.
    echo The app failed to start or exited with an error.
    pause
    exit /b 1
)

endlocal
