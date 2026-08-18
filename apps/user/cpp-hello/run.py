"""cpp-hello 跨平台启动包装

设计目标：
- launcher 看到的 PID 是 Python 包装进程，可控可停止
- 内部用 subprocess.Popen 拉起 C++ 二进制
- 转发 SIGTERM/SIGINT 给子进程，实现优雅停止

为什么不用 os.execv？
- Windows 上没有真正的 exec，os.execv 会 spawn 子进程然后退出当前 Python
- 导致 launcher 跟丢 C++ 进程（看到 Python 退出 = "应用停止"，但 C++ 还在跑）
- 用 subprocess + 信号转发更可靠
"""
import os
import platform
import signal
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).parent
IS_WIN = platform.system() == "Windows"

exe = BASE / "bin" / ("cpp-hello.exe" if IS_WIN else "cpp-hello")

if not exe.exists():
    sys.stderr.write(
        f"[cpp-hello] missing binary: {exe}\n"
        f"[cpp-hello] please compile first:\n"
        f"  {'build.bat' if IS_WIN else 'bash build.sh'}\n"
    )
    sys.exit(2)


def main():
    proc = subprocess.Popen([str(exe)])

    # 转发终止信号给子进程
    def relay(signum, frame):
        try:
            proc.send_signal(signum)
        except (ProcessLookupError, OSError):
            pass
    signal.signal(signal.SIGTERM, relay)
    signal.signal(signal.SIGINT, relay)

    # Windows 上 launcher 的 close_app 最后会 taskkill /T /F，子进程会递归一起被杀

    while True:
        rc = proc.wait()
        if rc is not None:
            return rc


if __name__ == "__main__":
    sys.exit(main())
