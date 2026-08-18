"""编译 launcher 为可执行文件：Windows → .exe，Linux → 可执行二进制。

使用 PyInstaller 打包：
  pip install pyinstaller
  python apps/build_launcher.py [--clean] [--onefile]

产物：
  dist/launcher.exe (Windows) 或 dist/launcher (Linux)
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent.resolve()
LAUNCHER_PY = BASE / "launcher.py"
DIST_DIR = BASE / "dist"
BUILD_DIR = BASE / "build"


def check_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
        return True
    except ImportError:
        print("❌ PyInstaller 未安装。请运行: pip install pyinstaller")
        return False


def build(clean: bool = False):
    if not check_pyinstaller():
        sys.exit(1)

    if not LAUNCHER_PY.exists():
        print(f"❌ 找不到 {LAUNCHER_PY}")
        sys.exit(1)

    if clean:
        for d in [DIST_DIR, BUILD_DIR]:
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
                print(f"  清理 {d}")

    # PyInstaller 参数
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name", "launcher",
        # 添加 templates 目录
        "--add-data", f"launcher/templates;templates" if sys.platform == "win32"
                       else f"launcher/templates:templates",
        # 隐藏控制台（Windows）
        *(["--windowed"] if sys.platform == "win32" else []),
        str(LAUNCHER_PY),
    ]

    print(f"🚀 编译 launcher...")
    print(f"  命令: {' '.join(args)}")
    result = subprocess.run(args, cwd=str(BASE), capture_output=False)

    exe = DIST_DIR / ("launcher.exe" if sys.platform == "win32" else "launcher")
    if exe.exists():
        size_mb = exe.stat().st_size / 1024 / 1024
        print(f"\n✅ 编译成功: {exe} ({size_mb:.1f} MB)")
        print(f"   路径: {exe}")
    else:
        print(f"❌ 编译失败，产物未找到")
        sys.exit(1)

    return exe


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--clean", action="store_true", help="清理旧产物后再编译")
    args = p.parse_args()
    build(args.clean)
