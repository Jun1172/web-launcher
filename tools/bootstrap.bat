@echo off
setlocal enabledelayedexpansion
REM ---------------------------------------------------------------
REM  web-launcher one-shot rebuild: regenerates runtime/ and wheels/.
REM  Only rebuilds THIS repo (does NOT touch web-launcher-apps).
REM  Needs network + a "python" on PATH (used only to run the two
REM  generator scripts). runtime/ and wheels/ are git-ignored binary
REM  outputs; the generator scripts live in tools/ and are tracked.
REM ---------------------------------------------------------------
cd /d "%~dp0"

echo ============================================
echo [1/2] Rebuild embedded Python runtime (runtime/win-x64)
echo ============================================
python make_runtime.py
if errorlevel 1 (
    echo.
    echo [ERROR] runtime generation failed. Check network to python.org and that python exists.
    pause
    exit /b 1
)

echo.
echo ============================================
echo [2/2] Download this repo's app dependency wheels (wheels/^<platform^>)
echo ============================================
python make_wheels.py
if errorlevel 1 (
    echo.
    echo [ERROR] wheels download failed. Check PyPI access and that prebuilt wheels exist.
    pause
    exit /b 1
)

echo.
echo ============================================
echo Done. This repo's runtime/ and wheels/ rebuilt.
echo (For web-launcher-apps wheels, run its own tools\bootstrap.bat)
echo ============================================
pause
endlocal
