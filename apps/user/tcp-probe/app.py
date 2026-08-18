"""tcp-probe —— 验证 ready_check=tcp 的就绪判定
- 裸 socket TCP echo server，监听 8120 端口（非 HTTP）
- 启动 5 秒后随机崩溃：70% sys.exit(1)（异常退出），30% sys.exit(0)（正常退出）
- 用来验证 restart_policy.on=failure 只对非 0 退出码重启
"""
import random
import socket
import sys
import time

PORT = 8120

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", PORT))
s.listen(5)
print(f"[tcp-probe] listening on 127.0.0.1:{PORT}", flush=True)

# 非阻塞 accept 循环：5 秒后崩
deadline = time.time() + 5
s.settimeout(0.5)
while time.time() < deadline:
    try:
        conn, addr = s.accept()
        conn.sendall(b"hello from tcp-probe\n")
        conn.close()
    except socket.timeout:
        continue
    except OSError:
        break

s.close()

# 随机崩溃
if random.random() < 0.7:
    print("[tcp-probe] 模拟异常退出 (exit 1)", flush=True)
    sys.exit(1)
else:
    print("[tcp-probe] 模拟正常退出 (exit 0)", flush=True)
    sys.exit(0)
