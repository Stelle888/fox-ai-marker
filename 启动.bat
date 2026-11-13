@echo off
cd /d "%~dp0"

if not exist "katago\katago.exe" goto noengine
if not exist "weights\b18c384nbt-uec.bin.gz" goto noengine

rem Use the bundled Python first, so nothing has to be installed on this machine.
if exist "%~dp0python\python.exe" (
    set "PY=%~dp0python\python.exe"
    set "PYW=%~dp0python\pythonw.exe"
) else (
    set "PY=python"
    set "PYW=pythonw"
)

echo Starting Fox Weiqi AI candidate marker...
echo Open a game in the Fox client first, then leave this window running.
echo First start takes a few seconds to load the engine.
echo.

"%PY%" run.py
if errorlevel 1 (
    echo.
    echo Failed. Paste the error above into a GitHub issue.
    pause
)
exit /b 0

:noengine
echo [!] katago.exe or weights missing.
echo     Re-download the release zip and keep all files together.
echo.
pause
exit /b 1
