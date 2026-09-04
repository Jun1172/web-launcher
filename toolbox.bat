@echo off
setlocal
REM ---------------------------------------------------------------
REM  WebLauncher unified toolbox launcher (repo-root entry).
REM  Double-click to open the toolbox window that manages all
REM  dev/publish scripts. Uses a pywebview desktop window, or falls
REM  back to browser mode (local HTTP) when no GUI is available.
REM  Options:  toolbox.bat --http    force browser mode
REM            toolbox.bat --port N  set port
REM ---------------------------------------------------------------
cd /d "%~dp0"
REM The toolbox itself lives in tools\toolbox.py; this file is just
REM a convenient repo-root entry point.
pythonw tools\toolbox.py %*
if errorlevel 1 (
    echo [ERROR] Toolbox failed to start. Make sure "pythonw" is on PATH
    echo         and tools\toolbox.py exists. Or try: python tools\toolbox.py
    pause
)
endlocal
