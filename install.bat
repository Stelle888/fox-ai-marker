@echo off
setlocal
echo ==========================================
echo   fox-ai-marker  -  first time setup
echo ==========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [x] Python not found.
    echo.
    echo     Install Python 3.10 or newer from:
    echo     https://www.python.org/downloads/
    echo.
    echo     During install, tick "Add python.exe to PATH".
    echo.
    pause
    exit /b 1
)

echo [1/2] Installing Python packages...
python -m pip install --upgrade pip >nul 2>nul
python -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo [x] pip install failed. Check your network and run this again.
    pause
    exit /b 1
)

echo.
echo [2/2] Checking bundled engine...
if not exist "%~dp0katago\katago.exe" (
    echo [x] katago\katago.exe is missing.
    echo     Re-download the release zip, do not move files out of it.
    pause
    exit /b 1
)
if not exist "%~dp0weights\b18c384nbt-uec.bin.gz" (
    echo [x] weights\b18c384nbt-uec.bin.gz is missing.
    echo     Re-download the release zip, do not move files out of it.
    pause
    exit /b 1
)
echo     ok

echo.
echo ==========================================
echo   Done. Now double-click:  start.bat
echo ==========================================
pause
