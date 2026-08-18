"""file-demo —— 验证 ready_check=file 的就绪判定
- 启动后 sleep 1 秒，然后写 var/ready 文件（>0 字节）
- launcher 探测到文件存在 → 标记应用 ready
- 收到 SIGTERM 时删 ready 文件，让下次启动从零开始
- 模拟 ROS2 lifecycle 节点的"主动声明就绪"模式
"""
import signal
import sys
import time
from pathlib import Path

BASE = Path(__file__).parent
READY = BASE / "var" / "ready"
RUNNING = True


def _stop(signum, frame):
    global RUNNING
    print(f"[file-demo] 收到信号 {signum}，清理 ready 文件并退出", flush=True)
    try:
        READY.unlink()
    except FileNotFoundError:
        pass
    RUNNING = False


if sys.platform != "win32":
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
else:
    signal.signal(signal.SIGINT, _stop)

READY.parent.mkdir(parents=True, exist_ok=True)
# 启动时先清理上次残留
try:
    READY.unlink()
except FileNotFoundError:
    pass

print(f"[file-demo] 启动中，1 秒后写 ready 文件: {READY}", flush=True)
time.sleep(1)
READY.write_text(f"ready at {time.strftime('%H:%M:%S')}\n", encoding="utf-8")
print(f"[file-demo] ready 文件已写入，应用进入运行态", flush=True)

while RUNNING:
    time.sleep(0.5)

print("[file-demo] 退出", flush=True)
sys.exit(0)
