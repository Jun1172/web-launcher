# ⚙️ 进程 Demo（proc-demo）

验证**无端口进程型应用**如何接入 launcher。

## 验证什么

| 能力 | 实际行为 |
|------|----------|
| **无端口就绪** | app.json 不写 `port`，launcher 启动 `app.py` 后立即视为就绪（不轮询任何端口） |
| **优雅停止（POSIX）** | `/api/close` → `p.terminate()` 在 POSIX 上发 SIGTERM → 触发 app.py 注册的 `_stop` handler → 打印"收到信号 15，准备优雅退出" → 进程自然退出 |
| **Windows 停止** | `p.terminate()` 在 Windows 上等价于 `TerminateProcess`，**不触发**信号 handler；2s 后 launcher 兜底 `taskkill /F /T /PID` 强杀进程树 |

## ⚠️ 不验证的能力（README 历史版本误标，已纠正）

| 能力 | 状态 |
|------|------|
| `ready_check.type=process` 就绪判定 | **未实现**；launcher 当前只看 `port` 字段做 TCP 探测，无 port 时立即视为就绪 |
| `restart_policy.on=always` 崩溃重启 | **未实现**；进程被 kill 后 launcher 不会自动拉起 |
| `max_retries` 重试上限 | **未实现** |
| `status` 字段（crashed / restarting） | **未实现**；`/api/apps` 只返回 `running: bool` |

## 验证步骤

```powershell
# 1. 启动 launcher
python launcher.py

# 2. 浏览器打开桌面，点 ⚙️ 进程 Demo

# 3. 查看进程是否拉起（无端口监听，但进程在跑）
Get-Process python | Where-Object { $_.CommandLine -like '*proc-demo*' }

# 4. /api/apps 里 proc-demo 的 running=true
Invoke-RestMethod "http://127.0.0.1:8000/api/apps" | ? id -eq proc-demo

# 5. /api/close 触发停止
Invoke-RestMethod "http://127.0.0.1:8000/api/close?id=proc-demo"
```

## 信号 handler 平台差异

```python
# Windows: SIGTERM 不可捕获（Python 在 Win 上把 SIGTERM 直接映射为 TerminateProcess）
# 但 SIGINT 可用（CTRL_C_EVENT / CTRL_BREAK_EVENT）
# POSIX: 两个都可捕获
if sys.platform == "win32":
    signal.signal(signal.SIGINT, _stop)
else:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
```

- **POSIX**：`p.terminate()` = `SIGTERM`，handler 被触发，进程优雅退出
- **Windows**：`p.terminate()` = `TerminateProcess`，handler 不被触发，进程被强杀；2s 兜底 `taskkill /F /T`

## 文件
- `app.json` —— 应用清单（无 `port` 字段，启动即视为就绪）
- `app.py` —— 注册 signal handler + 主循环心跳
