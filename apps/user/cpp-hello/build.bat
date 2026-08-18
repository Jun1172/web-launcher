@echo off
REM cpp-hello build script (Windows)
REM try g++ first, then cl (MSVC)
setlocal

set OUTDIR=%~dp0bin
set OUTEXE=%OUTDIR%\cpp-hello.exe

if not exist "%OUTDIR%" mkdir "%OUTDIR%"

where g++ >nul 2>nul
if %errorlevel%==0 (
    echo [build] g++ detected, compiling...
    g++ -std=c++17 -O2 -static -o "%OUTEXE%" "%~dp0cpp-hello.cpp" -lws2_32
    if errorlevel 1 (
        echo [build] FAILED
        exit /b 1
    )
    echo [build] OK: %OUTEXE%
    exit /b 0
)

where cl >nul 2>nul
if %errorlevel%==0 (
    echo [build] MSVC cl detected, compiling...
    cl /std:c++17 /O2 /EHsc /Fe:"%OUTEXE%" "%~dp0cpp-hello.cpp" ws2_32.lib
    if errorlevel 1 (
        echo [build] FAILED
        exit /b 1
    )
    del /q "%OUTDIR%\cpp-hello.obj" 2>nul
    echo [build] OK: %OUTEXE%
    exit /b 0
)

echo [build] No C++ compiler found. Install MinGW or Visual Studio.
exit /b 1
