# tcp-probe —— TCP 就绪判定验证 demo

- **就绪判定**：`ready_check.type=tcp`，8120 端口开放即判为 ready
- **重启策略**：`on=failure` → 只在非 0 退出码时重启
- **行为**：启动后 5 秒随机退出（70% exit 1，30% exit 0）
- **用途**：验证 launcher 对非 HTTP 服务（裸 socket、串口网关等）的就绪探测

验证命令：

```bash
telnet 127.0.0.1 8120
# 连接成功会收到 "hello from tcp-probe\n"
```
