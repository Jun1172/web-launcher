"""main - Launcher 启动入口 (pywebview 桌面窗口版)

python -m launcher  或  python launcher.py 都会运行 main()。

职责:
- 后台线程跑 ThreadingHTTPServer
- 主线程跑 pywebview 桌面窗口
  （Windows: 原生窗口 + Win32 去标题栏，保留边缘 resize 与 Alt+F4；
    拖拽仅限顶部状态栏，内容区按下拖动仍是翻页手势）
- 窗口关闭时清理所有子进程
"""
import atexit
import os
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


# ── Win32 无边框窗口支持（仅 Windows 生效）──
# 原生窗口创建后把样式改为 WS_POPUP | WS_THICKFRAME | WS_SYSMENU，并子类化窗口过程：
#   - WM_NCCALCSIZE→0：无标题栏/系统边框/缩放边框（彻底无边框，无叠加感）
#   - 缩放仍可用：WS_THICKFRAME 保留，由前端边缘热区触发原生缩放循环
#   - 保留系统菜单（Alt+F4 关闭）
# 拖拽窗口只在顶部状态栏（标题栏替代）按下触发（PostMessage→GUI 线程原生模态循环），
# 内容区按下拖动仍走前端的翻页手势（不用 easy_drag，避免整窗误拖）。
_IS_WIN = platform.system() == "Windows"
if _IS_WIN:
    import ctypes
    from ctypes import wintypes

    _GWL_STYLE = -16
    _GWL_EXSTYLE = -20
    _WS_OVERLAPPEDWINDOW = 0x00CF0000
    _WS_POPUP = 0x80000000
    _WS_THICKFRAME = 0x00040000
    _WS_SYSMENU = 0x00080000
    _WS_EX_APPWINDOW = 0x00040000
    _SWP_NOZORDER = 0x0004
    _SWP_NOMOVE = 0x0002
    _SWP_NOSIZE = 0x0001
    _SWP_FRAMECHANGED = 0x0020
    _MON_DEFAULTTONEAREST = 2
    # 子类化窗口过程相关
    _GWLP_WNDPROC = -4
    _WM_NCCALCSIZE = 0x0083
    _WM_NCDESTROY = 0x0082
    _WM_NCLBUTTONDOWN = 0x00A1
    _WM_APP_BORDERLESS = 0x8051  # 自定义消息：GUI 线程执行原生拖拽/缩放
    _HTCAPTION = 2
    _HTLEFT = 10
    _HTRIGHT = 11
    _HTTOP = 12
    _HTTOPLEFT = 13
    _HTTOPRIGHT = 14
    _HTBOTTOM = 15
    _HTBOTTOMLEFT = 16
    _HTBOTTOMRIGHT = 17

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.FindWindowW.restype = wintypes.HWND
    _user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    _user32.GetWindowLongW.restype = wintypes.DWORD
    _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.SetWindowLongW.restype = wintypes.DWORD
    _user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.DWORD]
    _user32.SetWindowPos.restype = wintypes.BOOL
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]
    _user32.GetWindowRect.restype = wintypes.BOOL
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.MonitorFromWindow.restype = wintypes.HANDLE
    _user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    _user32.GetMonitorInfoW.restype = wintypes.BOOL
    _user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    _user32.GetWindowTextLengthW.restype = ctypes.c_int
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextW.restype = ctypes.c_int
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, ctypes.c_int]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.ReleaseCapture.restype = wintypes.BOOL
    _user32.ReleaseCapture.argtypes = []
    _user32.GetCursorPos.restype = wintypes.BOOL
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    _user32.PostMessageW.restype = wintypes.BOOL
    _user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.CallWindowProcW.restype = wintypes.LPARAM
    _user32.CallWindowProcW.argtypes = [
        ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    ]
    _user32.DefWindowProcW.restype = wintypes.LPARAM
    _user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    try:
        _user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        _user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        _set_wndproc = _user32.SetWindowLongPtrW
    except AttributeError:  # 32 位 Python 无 SetWindowLongPtrW
        _user32.SetWindowLongW.restype = ctypes.c_ssize_t
        _user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        _set_wndproc = _user32.SetWindowLongW

    # Windows 11+: 隐藏 DWM 绘制的缩放边框（WS_THICKFRAME 的可见白边），
    # 纯视觉属性，不影响边缘 resize 命中测试；旧系统调用失败则忽略
    _DWMWA_USE_IMMERSIVE_DARK_MODE = 20
    _DWMWA_BORDER_COLOR = 34
    _DWMWA_COLOR_NONE = 0xFFFFFFFE
    _dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    _dwmapi.DwmSetWindowAttribute.restype = wintypes.LONG
    _dwmapi.DwmSetWindowAttribute.argtypes = [
        wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ]


def _find_hwnd():
    """枚举顶层窗口，返回属于本进程、标题匹配的主窗口句柄。

    不用 FindWindowW：多个 WebLauncher 实例并存时它会命中其它实例的窗口，
    导致去标题栏操作作用到错误窗口、本实例窗口样式不变。
    """
    if not _IS_WIN:
        return None
    me = os.getpid()
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        n = _user32.GetWindowTextLengthW(hwnd)
        if n != len(LAUNCHER_TITLE):
            return True  # 继续枚举
        buf = ctypes.create_unicode_buffer(n + 1)
        _user32.GetWindowTextW(hwnd, buf, n + 1)
        if buf.value != LAUNCHER_TITLE:
            return True
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == me:
            found.append(hwnd)
        return True

    _user32.EnumWindows(_cb, 0)
    return found[0] if found else None


# ── 窗口子类化：彻底去边框 + 原生拖拽/缩放 ──
# DWM 深色模式只能把 WS_THICKFRAME 的可见边框“染黑”，去不掉（两个窗口叠加感）；
# 子类化后拦截 WM_NCCALCSIZE 返回 0，客户区覆盖整个窗口，边框彻底消失。
# 拖拽/缩放：pywebview 的 js_api 在工作线程执行，跑不了原生模态循环；
# 用 PostMessage 把请求转发到 GUI 线程，由窗口过程调
# CallWindowProc(WM_NCLBUTTONDOWN, HT*) 进入系统原生拖拽/缩放循环，
# 同步跟随鼠标、丝滑不抖动（增量 SetWindowPos 方案有异步延迟会剧烈晃动）。
if _IS_WIN:
    _orig_wndproc = ctypes.c_void_p(0)
    _wndproc_keepalive = None

    @ctypes.WINFUNCTYPE(wintypes.LPARAM, wintypes.HWND, wintypes.UINT,
                        wintypes.WPARAM, wintypes.LPARAM)
    def _borderless_wndproc(hwnd, msg, wparam, lparam):
        """GUI 线程上运行：去掉 NC 边框 + 执行原生拖拽/缩放模态循环。"""
        global _orig_wndproc
        if not _orig_wndproc:
            return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)
        try:
            if msg == _WM_NCCALCSIZE and wparam:
                # 客户区 = 整个窗口：WS_THICKFRAME 的可见边框（黑/白）彻底消失
                _safe_print("[DBG] NCCALCSIZE 拦截 -> 0")
                return 0
            if msg == _WM_APP_BORDERLESS:
                # 工作线程转发来的请求：进入原生 WM_NCLBUTTONDOWN 模态循环
                # （wparam 为命中码：HTCAPTION=拖拽，HTLEFT..HTBOTTOMRIGHT=缩放）
                _user32.ReleaseCapture()  # 释放 WebView2 持有的鼠标捕获（同线程，有效）
                pt = wintypes.POINT()
                _user32.GetCursorPos(ctypes.byref(pt))
                lp = ((pt.y & 0xFFFF) << 16) | (pt.x & 0xFFFF)
                return _user32.CallWindowProcW(
                    _orig_wndproc, hwnd, _WM_NCLBUTTONDOWN, wparam, lp)
            if msg == _WM_NCDESTROY:
                # 窗口销毁前还原 WndProc，避免析构期回调进入 Python 崩溃
                orig = _orig_wndproc
                _orig_wndproc = ctypes.c_void_p(0)
                _set_wndproc(hwnd, _GWLP_WNDPROC, orig.value or 0)
                return _user32.CallWindowProcW(orig, hwnd, msg, wparam, lparam)
        except Exception:
            pass
        return _user32.CallWindowProcW(_orig_wndproc, hwnd, msg, wparam, lparam)


_borderless_done = threading.Event()
_borderless_lock = threading.Lock()


def _ensure_borderless():
    """去标题栏 + 去可见边框 + 子类化窗口，成功后只执行一次。"""
    if not _IS_WIN or _borderless_done.is_set():
        return
    with _borderless_lock:
        if _borderless_done.is_set():
            return
        hwnd = _find_hwnd()
        if not hwnd:
            return
        global _wndproc_keepalive, _orig_wndproc
        try:
            style = _user32.GetWindowLongW(hwnd, _GWL_STYLE)
            _safe_print(f"[DBG] 开始处理 hwnd={hwnd}")
            _user32.SetWindowLongW(
                hwnd, _GWL_STYLE,
                (style & ~_WS_OVERLAPPEDWINDOW) | _WS_POPUP | _WS_THICKFRAME | _WS_SYSMENU,
            )
            # WS_POPUP 窗口强制显示在任务栏
            ex = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex | _WS_EX_APPWINDOW)
            # Windows 11+: 深色模式 + DWM 边框透明（配合 NCCALCSIZE=0 彻底无边框；
            # 旧系统不支持则只剩暗色细边框，功能不受影响）
            try:
                _dwmapi.DwmSetWindowAttribute(
                    hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE,
                    ctypes.byref(ctypes.c_int(1)), 4,
                )
                _dwmapi.DwmSetWindowAttribute(
                    hwnd, _DWMWA_BORDER_COLOR,
                    ctypes.byref(ctypes.c_ulong(_DWMWA_COLOR_NONE)), 4,
                )
            except Exception:
                pass
            # 子类化窗口过程（WM_NCCALCSIZE 去边框 + 转发原生拖拽/缩放）。
            # 必须在 FRAMECHANGED 之前安装，NCCALCSIZE 才能在本次样式变化中生效。
            if not _orig_wndproc:
                _wndproc_keepalive = _borderless_wndproc  # 防 GC 导致回调失效
                prev = _set_wndproc(
                    hwnd, _GWLP_WNDPROC,
                    ctypes.cast(_borderless_wndproc, ctypes.c_void_p).value,
                )
                if prev:
                    _orig_wndproc = ctypes.c_void_p(prev)
            _safe_print(f"[DBG] hwnd={hwnd} 子类化 orig=0x{_orig_wndproc.value or 0:x} "
                        f"our=0x{ctypes.cast(_borderless_wndproc, ctypes.c_void_p).value or 0:x}")
            _user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                _SWP_FRAMECHANGED | _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER,
            )
            # 关键：样式/边框变化后客户区变大，但 pywebview 宿主(WinForms)里
            # WebView2 是 Dock=Fill 布局，不会自动触发 WM_SIZE 重排，
            # 顶部会残留窗体底色白条。
            # → 微调窗口尺寸 ±1px 强制触发两次 WM_SIZE，让 WebView2 重新铺满。
            rect = wintypes.RECT()
            if _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                _w, _h = rect.right - rect.left, rect.bottom - rect.top
                _user32.SetWindowPos(hwnd, 0, rect.left, rect.top, _w, _h + 1, _SWP_NOZORDER)
                _user32.SetWindowPos(hwnd, 0, rect.left, rect.top, _w, _h, _SWP_NOZORDER)
            _borderless_done.set()
        except Exception as e:
            _safe_print(f"[DBG] _ensure_borderless 异常: {e!r}")


def _start_borderless_poller():
    """后台线程：本进程窗口一创建就去标题栏（仅本进程窗口，多实例互不干扰）。"""
    if not _IS_WIN:
        return

    def _run():
        for _ in range(200):  # 最多等待 ~10s
            _ensure_borderless()
            if _borderless_done.is_set():
                return
            time.sleep(0.05)

    threading.Thread(target=_run, daemon=True).start()


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

    def __init__(self):
        self._maximized = False
        self._saved_rect = None  # 最大化前的窗口位置 (left, top, right, bottom)

    def minimize_window(self):
        """前端 — 按钮调用此方法最小化窗口。"""
        try:
            import webview
            for w in webview.windows:
                w.minimize()
        except Exception:
            pass

    def start_drag(self):
        """状态栏（标题栏）按下 → 请求原生窗口拖拽。

        只 PostMessage 一个请求，由窗口过程在 GUI 线程上进入
        WM_NCLBUTTONDOWN(HTCAPTION) 原生模态移动循环，
        系统级同步跟随鼠标，平滑不抖动。"""
        if not _IS_WIN or self._maximized:
            return
        hwnd = _find_hwnd()
        if hwnd:
            _user32.PostMessageW(hwnd, _WM_APP_BORDERLESS, _HTCAPTION, 0)

    def start_resize(self, edge):
        """边缘热区按下 → 请求原生窗口缩放。

        edge: l/r/t/b/tl/tr/bl/br（前端 JS 边缘热区判定后传入）；
        同样转发到 GUI 线程跑 WM_NCLBUTTONDOWN(HT*) 原生缩放循环。"""
        if not _IS_WIN or self._maximized:
            return
        codes = {"l": _HTLEFT, "r": _HTRIGHT, "t": _HTTOP, "tl": _HTTOPLEFT,
                 "tr": _HTTOPRIGHT, "b": _HTBOTTOM, "bl": _HTBOTTOMLEFT,
                 "br": _HTBOTTOMRIGHT}
        code = codes.get(str(edge).lower())
        if not code:
            return
        hwnd = _find_hwnd()
        if hwnd:
            _user32.PostMessageW(hwnd, _WM_APP_BORDERLESS, code, 0)

    def toggle_maximize(self):
        """前端 ▢ 按钮：最大化到当前显示器工作区（不遮任务栏）/ 还原。"""
        if not _IS_WIN:
            try:
                import webview
                for w in webview.windows:
                    w.toggle_fullscreen()
            except Exception:
                pass
            return
        hwnd = _find_hwnd()
        if not hwnd:
            return
        try:
            rect = wintypes.RECT()
            if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return
            if not self._maximized:
                # 保存当前窗口矩形，然后铺满所在显示器的工作区
                self._saved_rect = (rect.left, rect.top, rect.right, rect.bottom)
                hmon = _user32.MonitorFromWindow(hwnd, _MON_DEFAULTTONEAREST)
                mi = _MONITORINFO()
                mi.cbSize = ctypes.sizeof(mi)
                if not _user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                    return
                wa = mi.rcWork
                _user32.SetWindowPos(hwnd, 0, wa.left, wa.top,
                                     wa.right - wa.left, wa.bottom - wa.top,
                                     _SWP_NOZORDER)
                self._maximized = True
            else:
                l, t, r, b = self._saved_rect or (80, 80, 1104, 848)
                _user32.SetWindowPos(hwnd, 0, l, t, r - l, b - t, _SWP_NOZORDER)
                self._maximized = False
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

    # 6. 有 pywebview → 创建桌面窗口
    #    Windows 不再使用 frameless/easy_drag：
    #    - easy_drag 会让整个内容区都能拖动窗口（内容区拖动应翻页）
    #    - frameless 会失去原生边缘 resize
    #    改为：原生窗口启动后立刻用 Win32 去标题栏（保留 resize 边框）；
    #    去标题栏失败也只是短暂显示原生标题栏，窗口必定可见
    url = f"http://{LAUNCHER_HOST}:{LAUNCHER_PORT}/"
    window = webview.create_window(
        LAUNCHER_TITLE,
        url,
        width=1024,
        height=768,
        resizable=True,
        text_select=True,
        js_api=LauncherApi(),
    )

    # 7. GUI 启动后回调：去标题栏 → 注入控制按钮与状态栏拖拽
    def _after_start():
        if not _IS_WIN:
            return
        _ensure_borderless()
        try:
            window.evaluate_js("""
                (function(){
                    var sb=document.getElementById('statusbar');
                    if(!sb)return;
                    var sbR=sb.querySelector('.sbR');
                    if(!sbR)return;
                    /* 状态栏 = 标题栏：按下即请求原生拖拽（PostMessage 到 GUI 线程跑
                       WM_NCLBUTTONDOWN 模态循环，同步跟随鼠标不抖动）；
                       快速双击最大化/还原；按钮除外 */
                    var lastDown=0;
                    sb.addEventListener('pointerdown',function(e){
                        if(e.target.closest('button'))return;
                        var now=Date.now();
                        if(now-lastDown<350){lastDown=0;pywebview.api.toggle_maximize();return;}
                        lastDown=now;
                        pywebview.api.start_drag();
                    });
                    /* 窗口已无可见边框，边缘缩放改用页面内的不可见热区触发
                       （原生缩放循环，wparam 传命中码） */
                    (function(){
                        function mkZone(cur,code,css){
                            var d=document.createElement('div');
                            d.style.cssText='position:fixed;z-index:9998;background:transparent;cursor:'+cur+';'+css;
                            d.addEventListener('pointerdown',function(e){
                                e.stopPropagation();e.preventDefault();
                                try{pywebview.api.start_resize(code);}catch(_){}
                            });
                            document.body.appendChild(d);
                        }
                        mkZone('ew-resize','l','left:0;top:0;width:6px;height:100%;');
                        mkZone('ew-resize','r','right:0;top:0;width:6px;height:100%;');
                        mkZone('ns-resize','t','left:0;top:0;width:100%;height:6px;');
                        mkZone('ns-resize','b','left:0;bottom:0;width:100%;height:6px;');
                        mkZone('nwse-resize','tl','left:0;top:0;width:12px;height:12px;');
                        mkZone('nesw-resize','tr','right:0;top:0;width:12px;height:12px;');
                        mkZone('nesw-resize','bl','left:0;bottom:0;width:12px;height:12px;');
                        mkZone('nwse-resize','br','right:0;bottom:0;width:12px;height:12px;');
                    })();
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
    _start_borderless_poller()  # 句柄一出现就去标题栏（仅本进程窗口）
    gui_ok = False
    try:
        webview.start(func=_after_start)
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
