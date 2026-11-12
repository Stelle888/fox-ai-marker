@echo off
cd /d "%~dp0"
if not exist "katago\katago.exe" goto noengine
if not exist "weights\*.bin.gz" goto noengine
echo Starting Fox Weiqi AI candidate marker...
echo Open a game in the Fox client first, then leave this window running.
echo First start takes a few seconds to load the engine.
echo.
python run.py
if errorlevel 1 (
    echo.
    echo Failed. Paste the error above into a GitHub issue.
    pause
)
exit /b 0

:noengine
echo [!] engine or weights not found.
echo     Run this first:
echo         powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
echo.
pause
exit /b 1