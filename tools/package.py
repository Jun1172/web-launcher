# -*- coding: utf-8 -*-
"""跨平台打包 launcher 为单文件可执行（PyInstaller）。

替代原 package.bat（仅 Windows）。产物：
- Windows:      dist/launcher.exe
- Linux/macOS:  dist/launcher

注意：打包机需已安装 PyInstaller（pip install pyinstaller）。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # tools/ 上一级 = 仓库根
IS_WIN = os.name == "nt"
DIST = ROOT / "dist"
OUT = DIST / ("launcher.exe" if IS_WIN else "launcher")


def main():
    # 停掉正在运行的旧 launcher，避免占用/覆盖产物（仅 Windows 有此问题）
    if IS_WIN:
        subprocess.run(["taskkill", "/F", "/IM", "launcher.exe"], capture_output=True)
        if OUT.exists():
            try:
                OUT.unlink()
            except OSError:
                pass
        if OUT.exists():
            print("[ERROR] dist/launcher.exe 仍被占用，请关闭正在运行的 Launcher 后重试。")
            return 1

    sep = os.pathsep  # --add-data 的分隔符：Windows 用 ';'，POSIX 用 ':'
    args = ["-F", "-w",
            "--add-data", "launcher/templates%slauncher/templates" % sep,
            "--add-data", "apps/system%sapps/system" % sep,
            "--add-data", "config.json%s." % sep,
            "--collect-submodules=webview",
            "--clean"]
    if IS_WIN:
        ico = ROOT / "doc" / "images" / "launcher.ico"
        if ico.exists():
            args = ["-i", str(ico)] + args
        # Windows 专属 hidden-import
        args += ["--hidden-import=clr",
                 "--hidden-import=webview.platforms.edgechromium",
                 "--hidden-import=webview.platforms.winforms"]
    args.append("launcher.py")

    cmd = [sys.executable, "-m", "PyInstaller"] + args
    print("[运行]", " ".join(cmd))
    r = subprocess.run(cmd, cwd=str(ROOT))
    if r.returncode != 0:
        print("[ERROR] PyInstaller 打包失败。")
        return 1

    shutil.copy2(ROOT / "config.json", DIST / "config.json")
    print("[OK] 打包完成: %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
