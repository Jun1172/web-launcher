# 👋 你好世界（hello）

最简单的 demo 应用，用来验证 launcher 的核心链路。

## 功能
- 单文件 Python HTTP 服务，监听 `127.0.0.1:8110`
- 显示实时时钟（每秒刷新）
- 一个 `+1` 计数按钮（状态仅在内存中，刷新重置）

## 验证什么
1. launcher 能从 `apps/user/hello/app.json` 读取清单
2. 点击图标后能拉起独立 Python 进程
3. iframe 能正常嵌入并显示页面
4. 简单的 JS 交互能在 iframe 内运行

## 文件
- `app.json` —— 应用清单
- `app.py` —— 单文件 HTTP 服务（HTML 内联）
