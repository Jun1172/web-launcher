@echo off
REM =====================================================================
REM  WebLauncher 统一工具箱 启动器
REM  双击即可打开「工具箱」桌面窗口；自动管理所有开发/发布脚本。
REM
REM  优先用 pywebview 桌面窗口；若本机没有 GUI 环境，会自动转成
REM  浏览器模式（本地 HTTP 服务）并弹出页面。
REM
REM  可选参数：
REM    toolbox.bat --http        强制浏览器模式
REM    toolbox.bat --port 8799   指定端口
REM =====================================================================
setlocal
cd /d "%~dp0"
REM 工具箱本体在 tools\toolbox.py；本 .bat 只是根目录的便捷入口
pythonw tools\toolbox.py %*
if errorlevel 1 (
    echo [错误] 工具箱启动失败，请确认本目录有 pythonw 且 tools\toolbox.py 存在。
    pause
)
endlocal
