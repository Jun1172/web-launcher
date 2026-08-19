"""main - Launcher 启动入口 (带桌面窗口版)"""
import atexit
import threading
import time
import webview
from http.server import ThreadingHTTPServer

from .config import LAUNCHER_HOST, LAUNCHER_PORT, LAUNCHER_TITLE, LAUNCHER_VERSION
from .process_manager import terminate_all
from .http_handler import Handler

def start_http_server():
    """在后台线程运行 HTTP 服务器"""
    addr = (LAUNCHER_HOST, LAUNCHER_PORT)
    server = ThreadingHTTPServer(addr, Handler)
    server.serve_forever()

def main():
    # 1. 注册退出钩子
    atexit.register(terminate_all)
    
    # 2. 启动 HTTP 服务器 (后台线程)
    server_thread = threading.Thread(target=start_http_server, daemon=True)
    server_thread.start()
    
    # 等待服务器完全就绪 (简单延时，或者用 socket 轮询)
    time.sleep(0.5) 
    
    print(f"{LAUNCHER_TITLE} v{LAUNCHER_VERSION} 已就绪")
    
    # 3. 创建桌面窗口并加载本地 URL
    url = f"http://{LAUNCHER_HOST}:{LAUNCHER_PORT}"
    window = webview.create_window(
        LAUNCHER_TITLE, 
        url, 
        width=1024, 
        height=800,
        resizable=True,
        text_select=True
    )
    
    # 4. 启动 GUI 事件循环 (这里会阻塞主线程，直到窗口关闭)
    webview.start()
    
    # 5. 窗口关闭后，执行清理
    print("\n 窗口已关闭，正在清理所有应用进程…")
    terminate_all()

if __name__ == "__main__":
    main()