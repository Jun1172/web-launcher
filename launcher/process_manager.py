"""process_manager - 进程启动、端口就绪、进程树清理

职责：
- 维护 procs 全局字典 {app_id: Popen}
- open_app(): 应用未运行时启动其 cmd，并等待端口就绪（若 app 有 port 字段）
- close_app(): 优雅 terminate → 2 秒兜底 taskkill/killpg 进程树，避免孤儿进程
- terminate_all(): Launcher atexit 钩子调用，或"全部清除"调用
- port_ready(): TCP 轮询直到端口监听

不依赖仓库与注册表，但 open_app 需要 app 元数据（含 cmd/port）——由调用方传入。
"""
import os
import socket
import subprocess
import sys
import time

procs = {}   # {app_id: subprocess.Popen}


def port_ready(port, timeout=6):
    """TCP connect 轮询直到 127.0.0.1:port 监听成功；timeout 秒内失败返回 False。"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _popen_kwargs():
    """跨平台 Popen 公共 kwargs：Windows 隐藏控制台、POSIX 设进程组以便 killpg。"""
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    else:
        kw["start_new_session"] = True  # 方便 os.killpg
    return kw


def open_app(app):
    """启动应用进程（若未运行），等待端口就绪。成功 True，超时 False。

    app 需包含 'cmd' 字段。
    - 有 cmd 且有 port: 启动进程 + 等待端口就绪
    - 有 cmd 无 port: 启动进程即视为就绪（后台进程类应用）
    - 无 cmd（纯 stub）: 直接成功
    """
    if not app.get("cmd"):
        return True
    aid = app["id"]
    p = procs.get(aid)
    if p and p.poll() is None:
        return True
    p = subprocess.Popen(app["cmd"], **_popen_kwargs())
    procs[aid] = p
    port = app.get("port")
    if port:
        return port_ready(port)
    # 无 port 的后台进程：直接返回成功
    return True


def _kill_tree_nt(pid):
    """Windows: taskkill /F /T /PID 杀进程树。"""
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass


def _kill_tree_posix(pid):
    """POSIX: 负 pid 发送 SIGKILL 给进程组。"""
    try:
        os.killpg(pid, 9)
    except Exception:
        try:
            os.kill(pid, 9)
        except Exception:
            pass


def close_app(aid):
    """关闭单个应用进程 + 进程树。先 terminate 等 2s，兜底强杀。"""
    p = procs.pop(aid, None)
    if p is None or p.poll() is not None:
        return
    try:
        p.terminate()
    except Exception:
        pass
    # 等待 2 秒让子进程自行退出
    deadline = time.time() + 2.0
    while time.time() < deadline and p.poll() is None:
        time.sleep(0.05)
    if p.poll() is None:
        pid = p.pid
        if os.name == "nt":
            _kill_tree_nt(pid)
        else:
            _kill_tree_posix(pid)
    # 最后一次 reap，避免僵尸
    try:
        p.poll()
    except Exception:
        pass


def terminate_all():
    """关闭所有 procs 中应用进程（用于 atexit 与全部清除）。"""
    for aid in list(procs.keys()):
        close_app(aid)
