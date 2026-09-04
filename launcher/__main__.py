"""main - Launcher 启动入口 (pywebview 桌面窗口版)

python -m launcher  或  python launcher.py 都会运行 main()。

职责:
- 后台线程跑 ThreadingHTTPServer
- 主线程跑 pywebview 桌面窗口
  （Windows: 原生窗口 + Win32 去标题栏，保留边缘 resize 与 Alt+F4；
    拖拽仅限顶部状态栏，内容区按下拖动仍是翻页手势）
- 窗口关闭时清理所有子进程

Win32 无边框窗口实现见 launcher/window_win32.py（仅 Windows 生效）。
"""
import atexit
import socket
import sys
import threading
import time
from pathlib import Path

from http.server import ThreadingHTTPServer

from .config import LAUNCHER_HOST, LAUNCHER_PORT, LAUNCHER_TITLE, LAUNCHER_VERSION, safe_print
from .process_manager import terminate_all
from .http_handler import Handler
from . import window_win32


def _redirect_stdout_if_needed():
    """PyInstaller -w 模式下 stdout 可能是 None 或 GBK，emoji 会崩。

    打包模式下重定向到 exe 同级的 launcher-stdout.log（UTF-8），
    捕获第三方库（pywebview 等）的 print 输出；launcher 自身日志走
    logging 的 RotatingFileHandler 写 launcher.log（见 config.py）。
    开发模式不重定向。
    """
    if getattr(sys, "frozen", False):
        log_path = Path(sys.executable).parent / "launcher-stdout.log"
        sys.stdout = open(log_path, "a", encoding="utf-8")
        sys.stderr = sys.stdout


def _wait_port_ready(host, port, timeout=8):
    """轮询 TCP 端口直到 HTTP server 监听成功；超时返回 False。"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection((host, int(port)), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


class LauncherApi:
    """pywebview JS API：供前端调用 Python 端功能。

    Win32 平台委托给 window_win32；其他平台回退到 pywebview 原生 API。
    """

    def minimize_window(self):
        """前端 — 按钮调用此方法最小化窗口。"""
        try:
            import webview
            for w in webview.windows:
                w.minimize()
        except Exception:
            pass

    def start_drag(self):
        """状态栏（标题栏）按下 → 请求原生窗口拖拽。"""
        window_win32.start_drag()

    def start_resize(self, edge):
        """边缘热区按下 → 请求原生窗口缩放。"""
        window_win32.start_resize(edge)

    def toggle_maximize(self):
        """前端 ▢ 按钮：最大化/还原。Win32 由 window_win32 处理，其他平台用 webview。"""
        if window_win32.IS_WIN:
            window_win32.toggle_maximize()
        else:
            try:
                import webview
                for w in webview.windows:
                    w.toggle_fullscreen()
            except Exception:
                pass

    def close_window(self):
        """前端 ✕ 按钮调用此方法关闭窗口。"""
        try:
            import webview
            for w in webview.windows:
                w.destroy()
        except Exception:
            pass


def _webview2_available():
    """粗检 WebView2 Runtime 是否已安装(仅 Windows)。

    GUI 启动前预判: 缺 WebView2 时 pywebview 可能抛异常, 也可能只开一个
    空白窗口(不抛异常), 后者无法靠 try/except 兜底。检查 EdgeUpdate 注册表
    的 Evergreen 安装记录(HKLM/HKCU 各两种视图), 消费级场景足够准确;
    fixed-version 绿色目录分发属于罕见部署, 不在此覆盖。
    """
    if sys.platform != "win32":
        return True
    try:
        import winreg
        guid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
        subs = (
            rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}",
            rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}",
        )
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for sub in subs:
                try:
                    winreg.OpenKey(root, sub)
                    return True
                except OSError:
                    continue
    except Exception:
        return True  # 检测失败不拦截, 交给 webview.start 的异常兜底
    return False


def _start_http_server(server):
    """后台线程运行 HTTP 服务器。"""
    try:
        server.serve_forever()
    except Exception as e:
        safe_print(f"[ERR] HTTP 服务器异常: {e}")


def main():
    _redirect_stdout_if_needed()

    # 1.5 子应用绑定地址跟随 launcher：Popen 默认继承当前进程环境，
    #     应用端读 os.environ.get("APP_HOST", "127.0.0.1") 决定监听地址。
    #     桌面默认 127.0.0.1 保持不变；嵌入式把 config.json 的
    #     launcher.host 改成 0.0.0.0 后，应用也随之对局域网开放。
    import os
    os.environ["APP_HOST"] = LAUNCHER_HOST

    # 1. 尝试导入 pywebview；未安装或 LAUNCHER_HTTP_ONLY 设置则回退到纯 HTTP 模式
    if os.environ.get("LAUNCHER_HTTP_ONLY"):
        has_webview = False
        safe_print("[INFO] LAUNCHER_HTTP_ONLY 已设置，使用纯 HTTP 模式")
        safe_print(f"       浏览器访问: http://{LAUNCHER_HOST}:{LAUNCHER_PORT}/")
    else:
        try:
            import webview
            has_webview = True
        except ImportError:
            has_webview = False
            safe_print("[WARN] 未安装 pywebview，回退到纯 HTTP 模式")
            safe_print(f"       浏览器访问: http://{LAUNCHER_HOST}:{LAUNCHER_PORT}/")

    # 2. 注册退出钩子（清理所有子进程）
    atexit.register(terminate_all)

    # 3. 启动 HTTP 服务器（后台线程）
    addr = (LAUNCHER_HOST, LAUNCHER_PORT)
    server = ThreadingHTTPServer(addr, Handler)
    server_thread = threading.Thread(target=_start_http_server, args=(server,), daemon=True)
    server_thread.start()

    # 4. 等待 HTTP 端口就绪
    if not _wait_port_ready(LAUNCHER_HOST, LAUNCHER_PORT, timeout=8):
        safe_print(f"[ERR] HTTP 端口 {LAUNCHER_PORT} 未就绪，可能被占")
        return

    safe_print(f"[READY] {LAUNCHER_TITLE} v{LAUNCHER_VERSION} 已就绪")

    # 5. 无 pywebview → 纯 HTTP 模式（阻塞主线程，Ctrl+C 退出）
    if not has_webview:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            safe_print("\n[STOP] 用户中断，正在关闭所有应用进程...")
            terminate_all()
        return

    # 5.5 WebView2 预检: 未安装则桌面窗口必然空白, 静默转纯 HTTP 模式(不开窗口)
    if has_webview and not _webview2_available():
        has_webview = False
        safe_print("[WARN] 系统未安装 WebView2 Runtime, 桌面窗口不可用")
        safe_print("       安装后可恢复桌面窗口: https://developer.microsoft.com/microsoft-edge/webview2/")
        safe_print(f"[INFO] 已切换纯 HTTP 模式, 浏览器访问: http://{LAUNCHER_HOST}:{LAUNCHER_PORT}/")

    # 6. 有 pywebview → 创建桌面窗口
    url = f"http://{LAUNCHER_HOST}:{LAUNCHER_PORT}/"
    # 句柄由 window_win32 通过 FindWindow 自行获取，此处无需保留返回值
    webview.create_window(
        LAUNCHER_TITLE,
        url,
        width=1024,
        height=768,
        resizable=True,
        text_select=True,
        js_api=LauncherApi(),
    )

    # 7. GUI 启动后回调：去标题栏（Win32）
    #    窗口控制按钮（—▢✕）、状态栏拖拽、边缘缩放热区已迁移到
    #    layouts/_shared.js 的 setupWinChrome()，由前端自注入，
    #    location.reload() 后不会丢失，无需在此 evaluate_js。
    def _after_start():
        if not window_win32.IS_WIN:
            return
        window_win32.ensure_borderless()

    # 8. 启动 GUI 事件循环（阻塞，直到窗口关闭）
    window_win32.start_borderless_poller()  # 句柄一出现就去标题栏（仅本进程窗口）
    gui_ok = False
    try:
        webview.start(func=_after_start)
        gui_ok = True
    except Exception as e:
        safe_print(f"[WARN] GUI 窗口启动失败: {e}")
        safe_print("[WARN] 回退到纯 HTTP 模式，请用浏览器访问:")
        safe_print(f"       http://{LAUNCHER_HOST}:{LAUNCHER_PORT}/")

    if not gui_ok:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            safe_print("\n[STOP] 用户中断，正在关闭所有应用进程...")
        server.shutdown()
        terminate_all()
        return

    # 9. 窗口关闭后清理
    safe_print("[STOP] 窗口已关闭，正在清理所有应用进程...")
    server.shutdown()
    terminate_all()


if __name__ == "__main__":
    main()
