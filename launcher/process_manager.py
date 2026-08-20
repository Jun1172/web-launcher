"""process_manager - 进程启动、端口分配、进程树清理

职责：
- 维护 procs 全局字典 {app_id: Popen}
- 维护 actual_ports 全局字典 {app_id: 实际监听端口}
- open_app(): 分配可用端口（优先 app.json 建议端口，被占则随机），
  通过环境变量 LAUNCHER_APP_PORT 传给 app，启动并等待就绪
- close_app(): 优雅 terminate → 2 秒兜底 taskkill/killpg 进程树，避免孤儿进程
- terminate_all(): Launcher atexit 钩子调用，或"全部清除"调用

端口分配策略（launcher 主导，app 开发者不管冲突）：
- app.json 的 port 字段作为"建议端口"（optional）
- launcher 启动 app 时优先尝试建议端口，被占则 socket.bind(0) 分配随机端口
- 通过 LAUNCHER_APP_PORT 环境变量传给 app，app.py 读 env 用此端口
- iframe URL 用 actual_port（不是 app.json port）
"""
import os
import socket
import subprocess
import time

procs = {}         # {app_id: subprocess.Popen}
actual_ports = {}  # {app_id: 实际监听端口（int）}


def _alloc_port(preferred=None):
    """分配可用端口。优先 preferred，被占或 None 则随机分配。

    返回 int 端口号。通过 socket bind 测试端口可用性（bind 后立即 close，
    app 启动时有微小 race window，但实际场景罕见）。
    """
    if preferred:
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", int(preferred)))
            s.close()
            return int(preferred)
        except OSError:
            pass  # 被占，分配随机
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _popen_kwargs():
    """跨平台 Popen 公共 kwargs：Windows 隐藏控制台、POSIX 设进程组以便 killpg。"""
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    else:
        kw["start_new_session"] = True  # 方便 os.killpg
    return kw


def open_app(app):
    """启动应用进程，分配端口，通过 env 传给 app。返回 actual_port（int）或 None。

    - 无 cmd（stub）: 返回 None（无进程无端口）
    - 有 cmd 无 port: 启动进程，检查进程存活即可（无端口应用）
    - 有 cmd 有 port: 分配端口 → 传 env LAUNCHER_APP_PORT → Popen → 轮询端口就绪
    - 启动失败（崩溃/超时）: 返回 None

    app.json 的 port 字段作为"建议端口"，被占时 launcher 自动分配随机端口。
    """
    if not app.get("cmd"):
        return None  # stub 应用，无进程
    aid = app["id"]
    p = procs.get(aid)
    if p and p.poll() is None:
        return actual_ports.get(aid)  # 已在运行，返回已分配端口

    has_port = bool(app.get("port"))

    if has_port:
        # 有端口的应用：分配端口 → 传 env → 轮询端口就绪
        port = _alloc_port(app.get("port"))
        actual_ports[aid] = port

        env = os.environ.copy()
        env["LAUNCHER_APP_PORT"] = str(port)
        p = subprocess.Popen(app["cmd"], env=env, **_popen_kwargs())
        procs[aid] = p

        # 轮询端口就绪，同时检查进程是否已崩溃
        end = time.time() + 6
        while time.time() < end:
            if p.poll() is not None:
                return None  # 进程崩溃
            try:
                with socket.create_connection(("127.0.0.1", int(port)), timeout=0.3):
                    time.sleep(0.3)
                    if p.poll() is None:
                        return port
                    return None  # 进程崩了
            except OSError:
                time.sleep(0.1)
        return None  # 超时
    else:
        # 无端口的应用：启动进程，等待 0.5s 确认进程存活
        p = subprocess.Popen(app["cmd"], **_popen_kwargs())
        procs[aid] = p
        time.sleep(0.5)
        if p.poll() is None:
            return True  # 进程存活，返回 True 表示启动成功（无端口）
        return None  # 进程已崩溃


def get_port(aid):
    """查询 app 实际监听端口。未运行返回 None。"""
    return actual_ports.get(aid)


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
    actual_ports.pop(aid, None)  # 清除端口映射
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
