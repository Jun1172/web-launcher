@echo off
setlocal

rem 旧版 launcher.exe 运行时会锁住 dist\launcher.exe，先结束它再覆盖构建产物。
taskkill /F /IM launcher.exe >nul 2>&1
if exist ".\dist\launcher.exe" del /F /Q ".\dist\launcher.exe" >nul 2>&1
if exist ".\dist\launcher.exe" (
    echo [ERROR] dist\launcher.exe 仍被占用，请关闭正在运行的 Launcher 后重试。
    exit /b 1
)

pyinstaller -F -w -i .\doc\images\launcher.ico ^
    --add-data "launcher\templates;launcher\templates" ^
    --add-data "apps\system;apps\system" ^
    --add-data "apps\user;apps\user" ^
    --hidden-import=clr ^
    --hidden-import=webview.platforms.edgechromium ^
    --hidden-import=webview.platforms.winforms ^
    --collect-submodules=webview ^
    --clean ^
    .\launcher.py

if errorlevel 1 (
    echo [ERROR] PyInstaller 打包失败。
    exit /b %errorlevel%
)
echo [OK] 打包完成：dist\launcher.exe
endlocal