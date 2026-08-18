# 📄 文件就绪 Demo（file-demo）

验证 `ready_check.type=file` 就绪判定 + 优雅停止时清理资源。

## 应用行为
- 启动后 sleep 1 秒
- 写 `var/ready` 文件（>0 字节）
- launcher 探测到文件存在 → 标 ready
- 收到 SIGTERM 时删 ready 文件后退出（模拟资源清理）

## 验证什么

| 能力 | 验证方式 |
|------|---------|
| **file 就绪** | launcher 轮询 `var/ready` 文件存在且非空 → ready |
| **消极就绪的局限** | 文件不出现时 launcher 会等满 timeout（5s）才判失败 |
| **POSIX 优雅停止** | `/api/close` 发 SIGTERM → 应用打印"清理 ready 文件并退出" → 文件被删 |

## 适用场景

`file` 类型适合需要**主动声明就绪**的应用：
- ROS2 lifecycle 节点（启动后注册到 ROS domain，再写 ready 文件）
- 需要预热资源的应用（加载模型、连接数据库完成后才接收流量）
- 嵌入式守护进程（硬件初始化完成后才接受命令）

## 验证步骤
```powershell
# 1. 点 📄 文件就绪 Demo
# 2. 1 秒后 /api/apps 应显示 file-demo status=running
Test-Path apps/user/file-demo/var/ready  # True

# 3. /api/close?id=file-demo 后 2 秒内文件被删
Invoke-RestMethod "http://127.0.0.1:8000/api/close?id=file-demo"
Test-Path apps/user/file-demo/var/ready  # False
```

## 文件
- `app.json` —— `ready_check.type=file`，file 路径相对 BASE
- `app.py` —— 1 秒后写文件 + signal handler 删文件
