"""Launcher 自更新模块：下载新版本 → 原子替换当前可执行文件 → 重启。

设计要点：
- Windows 下 .exe 被锁定，不能直接覆盖。解决方案：
  1. 下载新 exe → launcher.new
  2. 生成 updater.bat 脚本（等待当前进程退出 → 替换 → 重启）
  3. 后台 spawn updater.bat，然后主进程退出
- Linux 下同样思路：updater.sh
- updater 脚本在主进程退出后执行替换和重启
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def get_exe_dir() -> Path:
    """返回当前 launcher 可执行文件所在目录（PyInstaller 环境下 sys.frozen 为 True）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


def get_current_exe() -> Path:
    """返回当前 launcher 可执行文件路径（打包后为 .exe，开发态为 python 解释器）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable)
    # 开发态：返回 launcher.py（由 python 解释器运行）
    return Path(sys.argv[0]).resolve()


def download_binary(url: str, dest: Path, timeout: int = 60) -> tuple[bool, str]:
    """从 url 下载二进制到 dest。"""
    import urllib.request
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            dest.write_bytes(r.read())
        return True, f"downloaded {dest} ({dest.stat().st_size} bytes)"
    except Exception as e:
        return False, f"download failed: {e}"


def launch_self_update(binary_url: str) -> tuple[bool, str]:
    """下载新 launcher 二进制并安排替换。返回 (ok, msg)。

    流程：
    1. 下载新二进制到 launcher.new
    2. 生成 updater 脚本（Windows: .bat，Linux: .sh）
    3. 后台 spawn 脚本，脚本将等待当前进程退出后执行替换和重启
    4. 调用方应在返回 True 后尽快退出
    """
    exe_dir = get_exe_dir()
    current_exe = get_current_exe()
    new_exe = exe_dir / "launcher.new"

    # 1. 下载新二进制
    ok, msg = download_binary(binary_url, new_exe)
    if not ok:
        return False, msg

    # 2. 生成 updater 脚本
    is_windows = os.name == "nt"
    if is_windows:
        script_path = _write_windows_updater(current_exe, new_exe)
    else:
        script_path = _write_linux_updater(current_exe, new_exe)

    # 3. 后台 spawn updater 脚本
    try:
        if is_windows:
            # Windows: 使用 start /min 后台运行，避免黑窗口
            DETACHED_PROCESS = 0x00000008
            subprocess.Popen(
                ["cmd", "/c", str(script_path)],
                creationflags=DETACHED_PROCESS,
                cwd=str(exe_dir),
            )
        else:
            # Linux: nohup 后台运行
            subprocess.Popen(
                ["nohup", str(script_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=str(exe_dir),
                start_new_session=True,
            )
        return True, "update scheduled"
    except Exception as e:
        return False, f"failed to spawn updater: {e}"


def _write_windows_updater(current_exe: Path, new_exe: Path) -> Path:
    """生成 Windows updater.bat：等待当前进程退出 → 替换 → 重启。"""
    script = current_exe.parent / "updater.bat"
    current_name = current_exe.name
    new_name = new_exe.name
    # 获取当前进程 PID（通过 WMIC）
    script_content = f"""@echo off
setlocal
set "TARGET={current_exe}"
set "NEW={new_exe}"

rem 等待当前进程退出（轮询检查）
:wait_loop
tasklist /FI "IMAGENAME eq {current_name}" 2>NUL | find /I "{current_name}" >NUL
if %ERRORLEVEL%==0 (
    timeout /t 1 /nobreak >NUL
    goto wait_loop
)

rem 等待文件系统释放
timeout /t 2 /nobreak >NUL

rem 替换旧版本
if exist "%TARGET%" del /f "%TARGET%"
move /Y "%NEW%" "%TARGET%"

rem 清理 updater 自身
del /f "%~f0"

rem 重启
start "" "%TARGET%"
"""
    script.write_text(script_content, encoding="utf-8")
    return script


def _write_linux_updater(current_exe: Path, new_exe: Path) -> Path:
    """生成 Linux updater.sh：等待当前进程退出 → 替换 → 重启。"""
    script = current_exe.parent / "updater.sh"
    script_content = f"""#!/bin/bash
TARGET="{current_exe}"
NEW="{new_exe}"
PID={os.getpid()}

# 等待父进程（launcher）退出
while kill -0 "$PPID" 2>/dev/null; do
    sleep 1
done

# 等待文件系统释放
sleep 2

# 替换
if [ -f "$TARGET" ]; then
    chmod +x "$TARGET"
    rm -f "$TARGET"
fi
mv "$NEW" "$TARGET"
chmod +x "$TARGET"

# 清理自身
rm -f "$0"

# 重启
exec "$TARGET"
"""
    script.write_text(script_content, encoding="utf-8")
    script.chmod(0o755)
    return script
