"""window_win32 - Windows 无边框窗口支持（仅 Windows 生效）

从 __main__.py 拆分而来，职责单一：Windows 平台下去掉原生标题栏/系统边框，
改为 WS_POPUP | WS_THICKFRAME | WS_SYSMENU + 子类化窗口过程：
  - WM_NCCALCSIZE→0：彻底无标题栏/系统边框/缩放边框
  - 保留 WS_THICKFRAME：边缘 resize 命中测试仍可用
  - 保留 WS_SYSMENU：Alt+F4 关闭
拖拽/缩放由前端热区触发 PostMessage，GUI 线程跑原生 WM_NCLBUTTONDOWN 模态循环。
"""
import os
import platform
import threading
import time
import ctypes
from ctypes import wintypes

from .config import LAUNCHER_TITLE, safe_print

IS_WIN = platform.system() == "Windows"

# ── 模块级状态（窗口级单例）──
_borderless_done = threading.Event()
_borderless_lock = threading.Lock()
_orig_wndproc = ctypes.c_void_p(0) if IS_WIN else None
_wndproc_keepalive = None
_maximized = False
_saved_rect = None  # 最大化前的窗口矩形 (left, top, right, bottom)


if IS_WIN:
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
    _GWLP_WNDPROC = -4
    _WM_NCCALCSIZE = 0x0083
    _WM_NCDESTROY = 0x0082
    _WM_NCLBUTTONDOWN = 0x00A1
    _WM_APP_BORDERLESS = 0x8051
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

    _DWMWA_USE_IMMERSIVE_DARK_MODE = 20
    _DWMWA_BORDER_COLOR = 34
    _DWMWA_COLOR_NONE = 0xFFFFFFFE
    _dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    _dwmapi.DwmSetWindowAttribute.restype = wintypes.LONG
    _dwmapi.DwmSetWindowAttribute.argtypes = [
        wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ]


def find_hwnd():
    """枚举顶层窗口，返回属于本进程、标题匹配的主窗口句柄。

    不用 FindWindowW：多实例并存时会命中其它实例窗口。
    """
    if not IS_WIN:
        return None
    me = os.getpid()
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        n = _user32.GetWindowTextLengthW(hwnd)
        if n != len(LAUNCHER_TITLE):
            return True
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


if IS_WIN:
    @ctypes.WINFUNCTYPE(wintypes.LPARAM, wintypes.HWND, wintypes.UINT,
                        wintypes.WPARAM, wintypes.LPARAM)
    def _borderless_wndproc(hwnd, msg, wparam, lparam):
        """GUI 线程：去 NC 边框 + 执行原生拖拽/缩放模态循环。"""
        global _orig_wndproc
        if not _orig_wndproc:
            return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)
        try:
            if msg == _WM_NCCALCSIZE and wparam:
                safe_print("[DBG] NCCALCSIZE 拦截 -> 0")
                return 0
            if msg == _WM_APP_BORDERLESS:
                _user32.ReleaseCapture()
                pt = wintypes.POINT()
                _user32.GetCursorPos(ctypes.byref(pt))
                lp = ((pt.y & 0xFFFF) << 16) | (pt.x & 0xFFFF)
                return _user32.CallWindowProcW(
                    _orig_wndproc, hwnd, _WM_NCLBUTTONDOWN, wparam, lp)
            if msg == _WM_NCDESTROY:
                orig = _orig_wndproc
                _orig_wndproc = ctypes.c_void_p(0)
                _set_wndproc(hwnd, _GWLP_WNDPROC, orig.value or 0)
                return _user32.CallWindowProcW(orig, hwnd, msg, wparam, lparam)
        except Exception:
            pass
        return _user32.CallWindowProcW(_orig_wndproc, hwnd, msg, wparam, lparam)


def ensure_borderless():
    """去标题栏 + 去可见边框 + 子类化窗口，成功后只执行一次。"""
    if not IS_WIN or _borderless_done.is_set():
        return
    with _borderless_lock:
        if _borderless_done.is_set():
            return
        hwnd = find_hwnd()
        if not hwnd:
            return
        global _wndproc_keepalive, _orig_wndproc
        try:
            style = _user32.GetWindowLongW(hwnd, _GWL_STYLE)
            safe_print(f"[DBG] 开始处理 hwnd={hwnd}")
            _user32.SetWindowLongW(
                hwnd, _GWL_STYLE,
                (style & ~_WS_OVERLAPPEDWINDOW) | _WS_POPUP | _WS_THICKFRAME | _WS_SYSMENU,
            )
            ex = _user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            _user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, ex | _WS_EX_APPWINDOW)
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
            if not _orig_wndproc:
                _wndproc_keepalive = _borderless_wndproc
                prev = _set_wndproc(
                    hwnd, _GWLP_WNDPROC,
                    ctypes.cast(_borderless_wndproc, ctypes.c_void_p).value,
                )
                if prev:
                    _orig_wndproc = ctypes.c_void_p(prev)
            safe_print(f"[DBG] hwnd={hwnd} 子类化 orig=0x{_orig_wndproc.value or 0:x} "
                        f"our=0x{ctypes.cast(_borderless_wndproc, ctypes.c_void_p).value or 0:x}")
            _user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                _SWP_FRAMECHANGED | _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER,
            )
            rect = wintypes.RECT()
            if _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                _w, _h = rect.right - rect.left, rect.bottom - rect.top
                _user32.SetWindowPos(hwnd, 0, rect.left, rect.top, _w, _h + 1, _SWP_NOZORDER)
                _user32.SetWindowPos(hwnd, 0, rect.left, rect.top, _w, _h, _SWP_NOZORDER)
            _borderless_done.set()
        except Exception as e:
            safe_print(f"[DBG] ensure_borderless 异常: {e!r}")


def start_borderless_poller():
    """后台线程：本进程窗口一创建就去标题栏（仅本进程窗口，多实例互不干扰）。"""
    if not IS_WIN:
        return

    def _run():
        for _ in range(200):  # 最多等待 ~10s
            ensure_borderless()
            if _borderless_done.is_set():
                return
            time.sleep(0.05)

    threading.Thread(target=_run, daemon=True).start()


def start_drag():
    """状态栏（标题栏）按下 → 请求原生窗口拖拽。"""
    if not IS_WIN or _maximized:
        return
    hwnd = find_hwnd()
    if hwnd:
        _user32.PostMessageW(hwnd, _WM_APP_BORDERLESS, _HTCAPTION, 0)


def start_resize(edge):
    """边缘热区按下 → 请求原生窗口缩放。

    edge: l/r/t/b/tl/tr/bl/br
    """
    if not IS_WIN or _maximized:
        return
    codes = {"l": _HTLEFT, "r": _HTRIGHT, "t": _HTTOP, "tl": _HTTOPLEFT,
             "tr": _HTTOPRIGHT, "b": _HTBOTTOM, "bl": _HTBOTTOMLEFT,
             "br": _HTBOTTOMRIGHT}
    code = codes.get(str(edge).lower())
    if not code:
        return
    hwnd = find_hwnd()
    if hwnd:
        _user32.PostMessageW(hwnd, _WM_APP_BORDERLESS, code, 0)


def toggle_maximize():
    """最大化到当前显示器工作区（不遮任务栏）/ 还原。返回 True 表示已处理。"""
    global _maximized, _saved_rect
    if not IS_WIN:
        return False
    hwnd = find_hwnd()
    if not hwnd:
        return True
    try:
        rect = wintypes.RECT()
        if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        if not _maximized:
            _saved_rect = (rect.left, rect.top, rect.right, rect.bottom)
            hmon = _user32.MonitorFromWindow(hwnd, _MON_DEFAULTTONEAREST)
            mi = _MONITORINFO()
            mi.cbSize = ctypes.sizeof(mi)
            if not _user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                return True
            wa = mi.rcWork
            _user32.SetWindowPos(hwnd, 0, wa.left, wa.top,
                                 wa.right - wa.left, wa.bottom - wa.top,
                                 _SWP_NOZORDER)
            _maximized = True
        else:
            l, t, r, b = _saved_rect or (80, 80, 1104, 848)
            _user32.SetWindowPos(hwnd, 0, l, t, r - l, b - t, _SWP_NOZORDER)
            _maximized = False
    except Exception:
        pass
    return True
