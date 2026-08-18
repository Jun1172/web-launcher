"""__main__ - Launcher 启动入口

python -m launcher  或  python launcher.py （根目录薄壳）都会运行 main()。

职责:
- 注册 atexit 钩子，确保进程树彻底回收（AC-11）
- 绑定 host:port，启动 ThreadingHTTPServer
"""
import atexit

from http.server import ThreadingHTTPServer

from .config import LAUNCHER_HOST, LAUNCHER_PORT, LAUNCHER_TITLE, LAUNCHER_VERSION
from .process_manager import terminate_all
from .http_handler import Handler


def main():
    # 退出时一次性关闭所有子进程树（避免 C/C++ 孤儿、残留 app.py 进程）
    atexit.register(terminate_all)

    addr = (LAUNCHER_HOST, LAUNCHER_PORT)
    print(f"🚀 {LAUNCHER_TITLE} v{LAUNCHER_VERSION} 已就绪")
    print(f"   地址: http://{LAUNCHER_HOST}:{LAUNCHER_PORT}")
    try:
        ThreadingHTTPServer(addr, Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 用户中断，正在关闭所有应用进程…")
        terminate_all()


if __name__ == "__main__":
    main()
