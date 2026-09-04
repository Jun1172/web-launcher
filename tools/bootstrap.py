# -*- coding: utf-8 -*-
"""跨平台一键重建：本仓库 runtime/ + wheels/。

替代原 bootstrap.bat（仅 Windows）。等价于依次运行 make_runtime.py + make_wheels.py。

前置：联网 + 命令行里有 python（仅用于跑这两个生成脚本）。
runtime/ 与 wheels/ 是 git 忽略的二进制产物；生成脚本在 tools/ 已被 git 追踪。
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # tools/ 上一级 = 仓库根


def run(script, label):
    print("=" * 44)
    print(label)
    print("=" * 44)
    r = subprocess.run([sys.executable, str(ROOT / "tools" / script)], cwd=str(ROOT))
    return r.returncode == 0


def main():
    if not run("make_runtime.py", "[1/2] 重建内嵌 Python runtime (runtime/win-x64)"):
        print("\n[ERROR] runtime 生成失败，请检查网络与命令行 python。")
        return 1
    print()
    if not run("make_wheels.py", "[2/2] 下载本仓库应用依赖 wheels"):
        print("\n[ERROR] wheels 下载失败，请检查网络与依赖 wheel 可用性。")
        return 1
    print("\n完成！本仓库 runtime/ 与 wheels/ 已重建。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
