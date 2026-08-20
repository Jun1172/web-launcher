# 🚀 Web Launcher Wiki

**一个用 Python 标准库写的应用运行时**——支持部署 Python / C/C++ / Web 等多种类型的应用，提供应用商店、版本仓库与进程管理。

适用场景：嵌入式主板、工控机、边缘设备、本地开发机——只要能跑 Python，就能用 launcher 管理任意语言写的应用。

![桌面截图](../doc/images/桌面.png)

---

## 📌 项目定位

| 维度 | 说明 |
|------|------|
| **是什么** | 应用运行时 + 应用商店 + 版本仓库的整套方案 |
| **不是什么** | 不是容器运行时（无 namespace/cgroup 隔离），不是包管理器（不替代 pip/npm） |
| **核心价值** | 用最小依赖（Python 标准库）+ 最小协议（app.json）管理多语言应用的部署、增删、升级 |
| **目标平台** | Windows / Linux / macOS / ARM 嵌入式（树莓派、Jetson 等） |

---

## 🚀 快速开始

```bash
# 1. 启动 launcher（需要 Python ≥ 3.8，无第三方依赖）
python launcher.py

# 2. 浏览器打开（一般会自动打开）
#    http://127.0.0.1:8000/

# 3. 点桌面图标打开任意应用，或点 🛒 应用商店安装新应用
```

> 详见 [Getting Started](Getting-Started)

---

## ✨ 核心特性

- **进程启动 + 端口就绪探测**：`subprocess.Popen` 拉起进程，TCP 轮询直到端口监听成功
- **优雅停止 + 进程树清理**：`terminate` → 2 秒兜底 `taskkill /T` 或 `killpg` 杀整棵进程树，避免 C/C++ 孤儿进程
- **系统/用户应用分层 + 自定义分组**：`apps/system/` 不可卸载，`apps/user/` 可增删，`group` 字段可定义任意分组
- **仓库索引 + 原子安装**：HTTP 静态仓库 + sha256 校验 + 原子解压替换
- **多语言 cmd 解析**：`.py` 自动加 `sys.executable` 前缀，`.exe` / ELF / 任意二进制直接执行
- **Launcher 自更新（双模式 OTA）**：源码 zip 覆盖 / 编译态 bat·sh 替换脚本
- **用户级布局覆盖**：`layout.json` 覆盖 `app.json` 默认值，dock/hidden 由用户控制
- **桌面交互（仿移动端）**：状态栏 / 分页桌面 / Dock 栏 / 最近任务面板 / 应用商店详情弹窗

---

## 📚 文档导航

| 文档 | 内容 |
|------|------|
| [Architecture](Architecture) | 模块划分、数据流、端口分配机制、设计哲学 |
| [Getting Started](Getting-Started) | 环境要求、启动、第一个应用、关闭退出 |
| [App Development](App-Development) | 应用开发指南：目录结构、app.json、demo 模板 |
| [API Reference](API-Reference) | HTTP API 完整文档与示例 |
| [Configuration](Configuration) | config.json / app.json / layout.json 字段详解 |
| [Repo Server Setup](Repo-Server-Setup) | Nginx 仓库服务器搭建、HTTPS、发布流程 |
| [Self Update](Self-Update) | Launcher 自身 OTA 更新机制 |
| [Embedded Deployment](Embedded-Deployment) | 树莓派 / ARM / C++ 跨架构部署 |
| [Build Standalone EXE](Build-Standalone-EXE) | PyInstaller 打包成单文件 exe |
| [FAQ](FAQ) | 常见问题与排错 |

---

## 📦 内置应用一览

### 系统应用（`apps/system/`）

| 应用 | 默认端口 | 说明 |
|------|---------|------|
| 🛒 store | 8100 | 应用商店：安装 / 升级 / 卸载 / 历史版本回退 |
| 📝 todo | 8101 | 待办清单 demo |
| ⏱️ clock | 8102 | 番茄钟 demo |
| 📊 sysinfo | 8103 | CPU / 内存 / 磁盘 + 已安装应用列表 |
| ⚙️ settings | 8104 | 仓库地址 / BASIC 认证 / SSL 配置 |

### 用户应用 demo（`apps/user/`）

| 应用 | 默认端口 | 演示场景 |
|------|---------|----------|
| 👋 hello | 8110 | 最简交互（计数器 + 时钟） |
| 🗒️ notes | 8112 | `localStorage` 持久化 |
| 🌤️ weather | 8113 | 多视图切换 + mock 数据 + JSON API |
| 🎮 game2048 | 8114 | 完整游戏（矩阵算法 + 键盘/触摸） |
| ⚙️ proc-demo | — | 进程型应用（无端口，启动即视为就绪） |
| 📄 file-demo | — | 占位 stub（无 cmd，启动即视为就绪） |
| 📈 system-monitor | 8130 | 实时 CPU/内存折线图 + TOP 进程 |
| 🦾 cpp-hello | 8140 | C++ 应用部署模板（原生 socket + run.py 包装） |

> 端口仅为 `app.json` 的建议值，实际端口由 launcher 在启动时分配并通过 `LAUNCHER_APP_PORT` 环境变量传给 app。详见 [Architecture#端口分配机制](Architecture#端口分配机制)。

---

## 📜 License

MIT
