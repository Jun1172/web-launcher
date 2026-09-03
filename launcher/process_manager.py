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
import sys
import threading
import time

procs = {}         # {app_id: subprocess.Popen}
actual_ports = {}  # {app_id: 实际监听端口（int）}
_lock = threading.Lock()   # 保护 procs / actual_ports 的短操作
_starting = set()          # 正在启动中的 app_id，防止同一应用并发重复启动


def _resolve_python():
    """解析可用的 Python 解释器（仅 Windows，结果缓存）。

    Windows CreateProcess 无法直接执行 .py/.pyc（WinError 193），
    且部署机 PATH 里可能没有 python 命令。解析优先级：
      1) 注册表 .py 文件关联的解释器（资源管理器双击 .py 能跑，用它必能跑）
      2) PATH 中的 python / py
      3) launcher 以源码运行时的 sys.executable
    返回 [解释器, 参数...] 列表；找不到返回 None。
    """
    if os.name != "nt":
        return None
    exe = getattr(_resolve_python, "_cache", None)
    if exe is not None:
        return list(exe)
    found = None
    # 1) 注册表文件关联: 如 '"D:\\Python\\311\\python.exe" "%1" %*'
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,
                            r"Python.File\shell\open\command") as k:
            cmdline = winreg.QueryValueEx(k, "")[0]
        if cmdline.startswith('"'):
            end = cmdline.index('"', 1)
            cand, rest = cmdline[1:end], cmdline[end + 1:]
        else:
            parts = cmdline.split(None, 1)
            cand = parts[0]
            rest = parts[1] if len(parts) > 1 else ""
        cand = os.path.expandvars(cand.strip())
        if cand and os.path.isfile(cand):
            found = [cand] + (["-3"] if os.path.basename(cand).lower() == "py.exe" else [])
    except OSError:
        pass
    # 2) PATH
    if found is None:
        import shutil
        for name in ("python", "py"):
            p = shutil.which(name)
            if p:
                found = [p] + (["-3"] if name == "py" else [])
                break
    # 3) 源码运行时自身的解释器
    if found is None and not getattr(sys, "frozen", False):
        found = [sys.executable]
    if found:
        _resolve_python._cache = list(found)
    return list(found) if found else None


def _prep_cmd(cmd):
    """启动命令预处理。

    Windows 下 cmd[0] 为 .py/.pyw/.pyc 时，前缀解析出的 Python 解释器；
    其余（exe/bat/显式解释器）与 POSIX 原样返回。
    """
    cmd = list(cmd)
    if os.name != "nt" or not cmd:
        return cmd
    first = str(cmd[0])
    if first.lower().endswith((".py", ".pyw", ".pyc")):
        py = _resolve_python()
        if py:
            return py + cmd
    return cmd


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
    """启动应用进程，分配端口，通过 env 传给 app。返回 {"ok","running","port","reason"}。

    - 无 cmd（stub）: {"ok": True, "running": False, "port": None}（无进程无端口）
    - 有 cmd 无 port: 启动进程，检查进程存活即可（无端口应用）
    - 有 cmd 有 port: 分配端口 → 传 env LAUNCHER_APP_PORT → Popen → 轮询端口就绪
    - 启动失败（崩溃/超时/正在启动中）: {"ok": False, ...}

    app.json 的 port 字段作为"建议端口"，被占时 launcher 自动分配随机端口。
    锁只保护短字典操作，Popen 与 6 秒端口轮询在锁外进行，避免阻塞其他请求。
    """
    if not app.get("cmd"):
        return {"ok": True, "running": False, "port": None}  # stub 应用，无进程
    aid = app["id"]
    with _lock:
        p = procs.get(aid)
        if p and p.poll() is None:
            return {"ok": True, "running": True, "port": actual_ports.get(aid)}
        if aid in _starting:
            return {"ok": False, "running": False, "port": None,
                    "reason": "应用正在启动中，请稍候"}
        _starting.add(aid)

    try:
        if bool(app.get("port")):
            # 有端口的应用：分配端口 → 传 env → 轮询端口就绪
            port = _alloc_port(app.get("port"))
            actual_ports[aid] = port

            env = os.environ.copy()
            env["LAUNCHER_APP_PORT"] = str(port)
            p = subprocess.Popen(_prep_cmd(app["cmd"]), env=env, **_popen_kwargs())
            procs[aid] = p

            # 轮询端口就绪，同时检查进程是否已崩溃
            end = time.time() + 6
            while time.time() < end:
                if p.poll() is not None:
                    return {"ok": False, "running": False, "port": None}  # 进程崩溃
                try:
                    with socket.create_connection(("127.0.0.1", int(port)), timeout=0.3):
                        time.sleep(0.3)
                        if p.poll() is None:
                            return {"ok": True, "running": True, "port": port}
                        return {"ok": False, "running": False, "port": None}  # 进程崩了
                except OSError:
                    time.sleep(0.1)
            return {"ok": False, "running": False, "port": None}  # 超时
        else:
            # 无端口的应用：启动进程，等待 0.5s 确认进程存活
            p = subprocess.Popen(_prep_cmd(app["cmd"]), **_popen_kwargs())
            procs[aid] = p
            time.sleep(0.5)
            if p.poll() is None:
                return {"ok": True, "running": True, "port": None}  # 进程存活
            return {"ok": False, "running": False, "port": None}  # 进程已崩溃
    finally:
        with _lock:
            _starting.discard(aid)


def get_port(aid):
    """查询 app 实际监听端口。未运行返回 None。"""
    return actual_ports.get(aid)


def _kill_tree_nt(pid):
    """Windows: taskkill /F /T /PID 杀进程树。

    必须带 CREATE_NO_WINDOW：launcher 以无控制台 exe 运行时，直接跑
    控制台子进程 taskkill 会闪出一个命令行窗口（点退出时的黑窗）。
    """
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, timeout=5, creationflags=flags,
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
    """关闭单个应用进程 + 进程树，确保子进程（如 ROS 节点）一并终止，避免孤儿残留。

    应用可能通过 subprocess 起一整条子进程链（如 shell → pixi → python → ROS 节点）。
    若只 terminate 主进程、主进程一退出就跳过强杀，子节点会被引用为孤儿继续运行。
    因此在 Windows 上直接 taskkill /F /T（连根带支整体杀），POSIX 上 SIGKILL 整个进程组。
    """
    with _lock:
        actual_ports.pop(aid, None)  # 清除端口映射
        p = procs.pop(aid, None)
        _starting.discard(aid)
    if p is None or p.poll() is not None:
        return
    root = p.pid
    if os.name == "nt":
        _kill_tree_nt(root)   # taskkill /F /T 一次性终止整棵进程树
    else:
        _kill_tree_posix(root)  # 负 pid 给进程组发 SIGKILL，连同子进程
    # reap 根进程，避免僵尸
    try:
        p.wait(timeout=3)
    except Exception:
        try:
            p.kill()
        except Exception:
            pass
    try:
        p.poll()
    except Exception:
        pass


def terminate_all():
    """关闭所有 procs 中应用进程（用于 atexit 与全部清除）。"""
    with _lock:
        ids = list(procs.keys())
    for aid in ids:
        close_app(aid)
