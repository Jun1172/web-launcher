# ⚙️ 进程 Demo（proc-demo）

验证 `ready_check.type=process` 就绪判定 + `restart_policy.on=always` 崩溃自动重启 + 优雅停止链路。

## 验证什么

| 能力 | 验证方式 |
|------|---------|
| **process 就绪** | 应用不监听端口，launcher 靠"活过 2s 未崩"判定 ready |
| **always 重启** | 手动 kill 进程 → status 转 `crashed` → 1s 后 `restarting` → `running` |
| **max_retries 上限** | 连续 kill 5 次后 status 停在 `crashed`，不再重启 |
| **优雅停止（POSIX）** | `/api/close` 触发 SIGTERM → 日志打印"收到信号 15，准备优雅退出" → 进程退出 |
| **Windows SIGINT** | Windows 上 SIGTERM=强杀；本 demo 注册了 SIGINT handler，但默认 `stop_signal: SIGTERM` 走强杀路径 |

## 验证步骤

```powershell
# 1. 启动 launcher
python launcher.py

# 2. 浏览器打开桌面，点 ⚙️ 进程 Demo

# 3. 查看进程是否拉起
Get-Process python | Where-Object { $_.CommandLine -like '*proc-demo*' }

# 4. 模拟崩溃（kill -9 等价）
Stop-Process -Id <pid> -Force

# 5. 1 秒后查看 /api/apps，proc-demo 应为 restarting → running
curl http://127.0.0.1:8000/api/apps | ConvertFrom-Json | ? id -eq proc-demo

# 6. 重复 5 次后停在 crashed
```

## 文件
- `app.json` —— 应用清单（含 ready_check / restart_policy / stop_signal）
- `app.py` —— 注册 signal handler + 主循环
