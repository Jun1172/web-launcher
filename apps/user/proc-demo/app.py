"""proc-demo —— 验证 ready_check=process 的就绪判定
- 不监听任何端口
- 注册 SIGTERM / SIGINT handler，模拟"优雅退出"
- 主循环每 0.5s 打印心跳，便于观察 watcher 重启
"""
import signal
import sys
import time

RUNNING = True
STARTED = time.strftime("%H:%M:%S")


def _stop(signum, frame):
    global RUNNING
    print(f"[proc-demo {STARTED}] 收到信号 {signum}，准备优雅退出", flush=True)
    RUNNING = False


# Windows: SIGTERM 不可捕获（Python 在 Win 上把 SIGTERM 直接映射为 TerminateProcess）
# 但 SIGINT 可用（CTRL_C_EVENT / CTRL_BREAK_EVENT）
# POSIX: 两个都可捕获
if sys.platform == "win32":
    signal.signal(signal.SIGINT, _stop)
else:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

print(f"[proc-demo {STARTED}] 已就绪，开始空转（无端口监听）", flush=True)

while RUNNING:
    time.sleep(0.5)

print(f"[proc-demo {STARTED}] 优雅退出", flush=True)
sys.exit(0)
