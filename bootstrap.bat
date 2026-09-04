@echo off
REM =====================================================================
REM  WebLauncher 一键重建脚本
REM  用途：误删 runtime/ 或 wheels/ 后，重新生成这两个二进制产物目录。
REM
REM  前置条件：
REM    1. 机器能联网（首次需下载 Python embeddable 包 + 依赖 wheels）
REM    2. 命令行里有 python（任意版本，仅用于跑这两个生成脚本）
REM
REM  原理：
REM    make_runtime.py  下载官方 embeddable Python -> runtime/win-x64/
REM    make_wheels.py   扫描所有 app.json 的 deps 字段 -> wheels/<平台>/
REM
REM  这两个生成脚本都放在仓库根目录（不进 runtime/），因此即使
REM  把 runtime/ 整个删掉，脚本也不会丢，且已被 git 追踪可随时 checkout。
REM =====================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo [1/2] 重建内嵌 Python runtime (runtime/win-x64)
echo ============================================
python make_runtime.py
if errorlevel 1 (
    echo.
    echo [错误] runtime 生成失败，请检查：
    echo   - 网络是否可访问 https://www.python.org
    echo   - 命令行 python 是否存在
    pause
    exit /b 1
)

echo.
echo ============================================
echo [2/2] 下载应用依赖 wheels (wheels/^<平台^>)
echo ============================================
python make_wheels.py
if errorlevel 1 (
    echo.
    echo [错误] wheels 下载失败，请检查：
    echo   - 网络是否可访问 PyPI
    echo   - 各依赖是否有对应平台的预编译 wheel
    pause
    exit /b 1
)

echo.
echo ============================================
echo 完成！runtime/ 与 wheels/ 已重建。
echo ============================================
pause
endlocal
