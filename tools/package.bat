@echo off
setlocal

REM This script lives in tools\; switch to the repo root so all
REM relative paths below resolve correctly.
cd /d "%~dp0.."

rem A running launcher.exe locks dist\launcher.exe; kill it before rebuilding.
taskkill /F /IM launcher.exe >nul 2>&1
if exist ".\dist\launcher.exe" del /F /Q ".\dist\launcher.exe" >nul 2>&1
if exist ".\dist\launcher.exe" (
    echo [ERROR] dist\launcher.exe is still in use; close the running Launcher and retry.
    exit /b 1
)

pyinstaller -F -w -i .\doc\images\launcher.ico ^
    --add-data "launcher\templates;launcher\templates" ^
    --add-data "apps\system;apps\system" ^
    --add-data "config.json;." ^
    --hidden-import=clr ^
    --hidden-import=webview.platforms.edgechromium ^
    --hidden-import=webview.platforms.winforms ^
    --collect-submodules=webview ^
    --clean ^
    .\launcher.py

if errorlevel 1 (
    echo [ERROR] PyInstaller packaging failed.
    exit /b 1
)
copy /Y ".\config.json" ".\dist\config.json" >nul
if not exist ".\dist\config.json" (
    echo [ERROR] Could not copy config.json into dist.
    exit /b 1
)
echo [OK] Packaged: dist\launcher.exe
endlocal
