# 📜 实时日志查看器（log-viewer）

终端风格的实时日志查看器，基于 SSE（Server-Sent Events）推流，纯 Python 后端 + 原生 JS 前端，离线可用、跨平台。

## 功能

- **实时推流**：SSE 长连接持续推送日志新增内容（`tail -f` 效果），断线自动重连
- **历史回看**：`/api/tail` 从文件末尾 `seek` 倒读最后 N 行（纯 Python，不依赖系统 `tail`）
- **文件选择**：自动扫描 `launcher.log`（脚本同目录及上级）、`/var/log/syslog`、当前目录 `*.log`
- **关键字高亮**：`ERROR/CRITICAL/FATAL`(红)、`WARNING/WARN`(橙)、`INFO`(蓝)、`DEBUG/TRACE`(灰)
- **关键字过滤**：仅显示含关键字的行（前端过滤，不阻断 SSE 流）
- **搜索跳转**：高亮匹配行，`↑/↓` 或按钮上下跳转，`Enter` 下一个
- **暂停 / 清屏**：暂停冻结视图（不丢缓冲），恢复后同步；一键清空
- **自动滚动**：贴底自动滚，向上滚动即停（手动查看不被打断）
- **日志轮转感知**：inode 变化或文件变小时从头追踪

## 路由

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 内嵌 HTML 首页 |
| GET | `/api/files` | 可选日志文件列表（JSON） |
| GET | `/api/tail?file=<path>&lines=100` | 读取文件末尾 N 行 |
| GET | `/api/logs?file=<path>` | SSE 实时推流 |

> 文件参数会与 `/api/files` 白名单比对，路径穿越会被拒绝。

## 启动

launcher 自动以 `LAUNCHER_APP_PORT` 环境变量拉起；手动运行：

```bash
python app.py            # 默认 8151
# 或
LAUNCHER_APP_PORT=8200 python app.py
```

## 文件

- `app.json` —— 应用清单
- `app.py` —— 单文件 HTTP 服务（HTML/CSS/JS 内联）
