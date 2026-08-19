# 📄 文件就绪 Demo（file-demo）

验证**带 cmd 但无端口**的应用如何接入 launcher，以及应用自身如何用 ready 文件做"主动声明就绪"模式（虽然 launcher 当前不读这个文件）。

## 应用行为
- 启动后 sleep 1 秒
- 写 `var/ready` 文件（>0 字节）
- 进入主循环
- 收到 SIGTERM 时（POSIX）删 ready 文件后退出

## 验证什么

| 能力 | 实际行为 |
|------|----------|
| **无端口就绪** | app.json 不写 `port`，launcher 启动 `app.py` 后立即视为就绪 |
| **ready 文件** | launcher **不读取** `var/ready`；这个文件只是给人观察用，不影响 launcher 判定 |
| **POSIX 优雅停止** | `/api/close` → `p.terminate()` 发 SIGTERM → 触发 `_stop` handler → 删 ready 文件后退出 |
| **Windows 停止** | `p.terminate()` = `TerminateProcess`，handler 不被触发；2s 后 `taskkill /F /T` 兜底强杀 |

## ⚠️ 不验证的能力（README 历史版本误标，已纠正）

| 能力 | 状态 |
|------|------|
| `ready_check.type=file` 就绪判定 | **未实现**；launcher 当前不读 ready 文件，只看 `port` 字段做 TCP 探测 |
| `status` 多状态字段 | **未实现** |

## 适用场景

虽然 launcher 当前不读 ready 文件，但这个模式可作文档参考——未来若实现 `ready_check.type=file`，应用可主动写文件声明就绪：
- ROS2 lifecycle 节点（启动后注册到 ROS domain，再写 ready 文件）
- 需要预热资源的应用（加载模型、连接数据库完成后才接收流量）
- 嵌入式守护进程（硬件初始化完成后才接受命令）

## 验证步骤

```powershell
# 1. 点 📄 文件就绪 Demo
# 2. /api/apps 应立即显示 file-demo running=true（不等文件写入）
Invoke-RestMethod "http://127.0.0.1:8000/api/apps" | ? id -eq file-demo

# 3. 1 秒后应用自己写了 ready 文件（仅观察用，不影响 launcher）
Test-Path apps/user/file-demo/var/ready  # True

# 4. /api/close 后 POSIX 上文件被 handler 删，Windows 上进程直接被强杀
Invoke-RestMethod "http://127.0.0.1:8000/api/close?id=file-demo"
```

## 文件
- `app.json` —— 应用清单（无 `port` 字段）
- `app.py` —— 1 秒后写文件 + signal handler 删文件
