# -*- coding: utf-8 -*-
"""跨平台清理：结束卡住的 launcher / python 开发进程，释放被占端口。

替代原 kill.bat（taskkill /F /IM python.exe，仅 Windows）。

- Windows：taskkill /F /IM <image> /FI "PID ne <自身>" /FI "PID ne <父进程>"
- Linux/macOS：ps 枚举 python / launcher.py 进程，SIGKILL 之

会自动排除工具箱自身进程与其父进程，避免把自己一起杀掉。
"""
import os
import subprocess
import sys

IMAGES_WIN = ["launcher.exe", "python.exe", "pythonw.exe", "python3.exe"]


def kill_windows(me, ppid):
    for img in IMAGES_WIN:
        r = subprocess.run(
            ["taskkill", "/F", "/IM", img,
             "/FI", "PID ne %d" % me, "/FI", "PID ne %d" % ppid],
            capture_output=True, text=True)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        # taskkill 找不到对应进程时会报错，属正常，打印即可
        if out:
            print(out)


def kill_posix(me, ppid):
    import signal
    r = subprocess.run(["ps", "-eo", "pid,comm,args"],
                       capture_output=True, text=True)
    for line in r.stdout.splitlines()[1:]:
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        comm, args = parts[1], parts[2]
        if pid in (me, ppid):
            continue
        if comm.startswith("python") or "launcher.py" in args:
            try:
                os.kill(pid, signal.SIGKILL)
                print("killed %d  %s" % (pid, args[:70]))
            except Exception as e:
                print("skip %d: %s" % (pid, e))


def main():
    me, ppid = os.getpid(), os.getppid()
    if os.name == "nt":
        kill_windows(me, ppid)
    else:
        kill_posix(me, ppid)
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
