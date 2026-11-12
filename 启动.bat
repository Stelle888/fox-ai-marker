@echo off
cd /d "%~dp0"
if not exist "katago\katago.exe" goto noengine
if not exist "weights\*.bin.gz" goto noengine
echo 正在启动「野狐 AI 候选点标注」...
echo 先在野狐里进到对局页，再让这个窗口跑着就行。
echo 第一次启动要等几秒加载引擎，别急着关。
echo.
python run.py
if errorlevel 1 (
    echo.
    echo 出错了，把上面这几行报错发到 issues。
    pause
)
exit /b 0

:noengine
echo [!] 没找到引擎或权重。
echo     先跑一次：
echo         powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
echo.
pause
exit /b 1