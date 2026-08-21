"""main - Launcher 启动入口 (pywebview 桌面窗口版)

python -m launcher  或  python launcher.py 都会运行 main()。

职责:
- 后台线程跑 ThreadingHTTPServer
- 主线程跑 pywebview 无边框窗口（frameless）
- 窗口关闭时清理所有子进程
"""
import atexit
import platform
import socket
import sys
import threading
import time
from pathlib import Path

from http.server import ThreadingHTTPServer

from .config import LAUNCHER_HOST, LAUNCHER_PORT, LAUNCHER_TITLE, LAUNCHER_VERSION
from .process_manager import terminate_all
from .http_handler import Handler


def _redirect_stdout_if_needed():
    """PyInstaller -w 模式下 stdout 可能是 None 或 GBK，emoji 会崩。

    打包模式下重定向到 exe 同级的 launcher.log（UTF-8），便于调试。
    开发模式不重定向。
    """
    if getattr(sys, "frozen", False):
        log_path = Path(sys.executable).parent / "launcher.log"
        sys.stdout = open(log_path, "a", encoding="utf-8")
        sys.stderr = sys.stdout


def _safe_print(msg):
    """安全 print：处理 -w 模式 stdout=None / GBK 编码无法输出 emoji 的问题。"""
    try:
        print(msg)
    except (UnicodeEncodeError, AttributeError, ValueError):
        pass


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
    """pywebview JS API：供前端调用 Python 端功能。"""

    def minimize_window(self):
        """前端 — 按钮调用此方法最小化窗口。"""
        try:
            import webview
            for w in webview.windows:
                w.minimize()
        except Exception:
            pass

    def toggle_maximize(self):
        """前端 ▢ 按钮调用此方法切换全屏/还原。"""
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


def _start_http_server(server):
    """后台线程运行 HTTP 服务器。"""
    try:
        server.serve_forever()
    except Exception as e:
        _safe_print(f"[ERR] HTTP 服务器异常: {e}")


def main():
    _redirect_stdout_if_needed()

    # 1. 尝试导入 pywebview；未安装则回退到纯 HTTP 模式
    try:
        import webview
        has_webview = True
    except ImportError:
        has_webview = False
        _safe_print("[WARN] 未安装 pywebview，回退到纯 HTTP 模式")
        _safe_print("       安装桌面窗口模式: pip install pywebview")
        _safe_print(f"       浏览器访问: http://{LAUNCHER_HOST}:{LAUNCHER_PORT}/")

    # 2. 注册退出钩子（清理所有子进程）
    atexit.register(terminate_all)

    # 3. 启动 HTTP 服务器（后台线程）
    addr = (LAUNCHER_HOST, LAUNCHER_PORT)
    server = ThreadingHTTPServer(addr, Handler)
    server_thread = threading.Thread(target=_start_http_server, args=(server,), daemon=True)
    server_thread.start()

    # 4. 等待 HTTP 端口就绪
    if not _wait_port_ready(LAUNCHER_HOST, LAUNCHER_PORT, timeout=8):
        _safe_print(f"[ERR] HTTP 端口 {LAUNCHER_PORT} 未就绪，可能被占")
        return

    _safe_print(f"[READY] {LAUNCHER_TITLE} v{LAUNCHER_VERSION} 已就绪")

    # 5. 无 pywebview → 纯 HTTP 模式（阻塞主线程，Ctrl+C 退出）
    if not has_webview:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            _safe_print("\n[STOP] 用户中断，正在关闭所有应用进程...")
            terminate_all()
        return

    # 6. 有 pywebview → 创建无边框桌面窗口
    url = f"http://{LAUNCHER_HOST}:{LAUNCHER_PORT}/"
    is_windows = platform.system() == "Windows"
    window = webview.create_window(
        LAUNCHER_TITLE,
        url,
        width=1024,
        height=768,
        resizable=True,
        text_select=True,
        frameless=is_windows,  # Windows: frameless; Linux: native titlebar
        easy_drag=is_windows,  # only needed in frameless mode
        js_api=LauncherApi(),
    )

    # 7. 注入关闭按钮到状态栏（frameless 模式需要自给关闭入口）
    def _inject_close_button():
        if not is_windows:
            return
        try:
            window.evaluate_js("""
                (function(){
                    var sb=document.getElementById('statusbar');
                    if(!sb)return;
                    var sbR=sb.querySelector('.sbR');
                    if(!sbR)return;
                    var grp=document.createElement('span');
                    grp.style.cssText='display:flex;align-items:center;gap:2px;margin-left:12px;background:rgba(255,255,255,0.05);border-radius:8px;padding:2px;';
                    function mkBtn(svg,title,fn){
                        var b=document.createElement('button');
                        b.title=title;
                        b.style.cssText='background:transparent;border:0;cursor:pointer;padding:6px 8px;border-radius:6px;transition:all 0.15s;display:flex;align-items:center;color:var(--text-secondary);';
                        b.innerHTML=svg;
                        b.onmouseover=function(){b.style.background='rgba(255,255,255,0.1)';b.style.color='var(--text-primary)';};
                        b.onmouseout=function(){b.style.background='transparent';b.style.color='var(--text-secondary)';};
                        b.onclick=fn;
                        return b;
                    }
                    var minSvg='<svg width="12" height="12" viewBox="0 0 12 12"><rect x="2" y="5.5" width="8" height="1.2" rx="0.6" fill="currentColor"/></svg>';
                    var maxSvg='<svg width="12" height="12" viewBox="0 0 12 12"><rect x="2.5" y="2.5" width="7" height="7" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>';
                    var closeSvg='<svg width="12" height="12" viewBox="0 0 12 12"><path d="M3.5 3.5L8.5 8.5M8.5 3.5L3.5 8.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>';
                    grp.appendChild(mkBtn(minSvg,'最小化',function(){pywebview.api.minimize_window();}));
                    grp.appendChild(mkBtn(maxSvg,'最大化/还原',function(){pywebview.api.toggle_maximize();}));
                    var cb=mkBtn(closeSvg,'关闭',function(){pywebview.api.close_window();});
                    cb.onmouseover=function(){cb.style.background='rgba(248,113,113,0.2)';cb.style.color='#f87171';};
                    cb.onmouseout=function(){cb.style.background='transparent';cb.style.color='var(--text-secondary)';};
                    grp.appendChild(cb);
                    sbR.appendChild(grp);
                })();
            """)
        except Exception:
            pass

    # 8. 启动 GUI 事件循环（阻塞，直到窗口关闭）
    #    某些环境（无图形后端的 Linux/VM、缺 GTK/Qt 依赖）下 webview.start 会抛异常，
    #    此处捕获后回退到纯 HTTP 模式，避免直接崩溃退出。
    gui_ok = False
    try:
        webview.start(func=_inject_close_button)
        gui_ok = True
    except Exception as e:
        _safe_print(f"[WARN] GUI 窗口启动失败: {e}")
        _safe_print("[WARN] 回退到纯 HTTP 模式，请用浏览器访问:")
        _safe_print(f"       http://{LAUNCHER_HOST}:{LAUNCHER_PORT}/")

    if not gui_ok:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            _safe_print("\n[STOP] 用户中断，正在关闭所有应用进程...")
        server.shutdown()
        terminate_all()
        return

    # 9. 窗口关闭后清理
    _safe_print("[STOP] 窗口已关闭，正在清理所有应用进程...")
    server.shutdown()
    terminate_all()


if __name__ == "__main__":
    main()
