# 🚀 Web Launcher — 轻量级多语言应用部署平台

一个用 Python 标准库写的应用运行时，支持部署 Python / C/C++ / Web / 串口 / socket / ROS2 等多种类型的应用，提供完整的生命周期管理：启动就绪判定、崩溃自动重启、优雅停止、依赖声明、版本升级。

适用场景：嵌入式主板、工控机、边缘设备、本地开发机——只要能跑 Python，就能用 launcher 管理任意语言写的应用。

## 📌 项目定位

| 维度 | 说明 |
|------|------|
| **是什么** | 一个应用运行时 + 应用商店 + 版本仓库的整套方案 |
| **不是什么** | 不是容器运行时（无 namespace/cgroup 隔离），不是包管理器（不替代 pip/npm） |
| **核心价值** | 用最小依赖（Python 标准库）+ 最小协议（app.json）管理多语言应用的部署、增删、升级 |
| **目标平台** | Windows / Linux / macOS / ARM 嵌入式（树莓派、Jetson 等） |

## ✨ 核心特性

### 1. ready_check 协议 — 5 种就绪判定
应用启动后，launcher 按类型判断"是否就绪"，**不再硬编码 HTTP 端口探测**：
- `http` — HTTP 服务（GET `/health` 等 path，校验状态码）
- `tcp` — 裸 TCP 服务（端口能 accept 即可）
- `process` — 进程型应用（活过 grace period 即可，串口/ROS2 节点用）
- `file` — 文件型应用（写出 ready 文件声明就绪，ROS2 lifecycle 节点用）
- `none` — 占位应用（立即就绪）

### 2. 完整生命周期管理
- **启动**：`workdir` / `env` 透传，按 `ready_check` 判定就绪
- **监控**：每个应用一个 daemon watcher 线程，阻塞在 `proc.wait()` 上
- **崩溃恢复**：`restart_policy.on = always | failure | never`，配 `max_retries` + `delay`
- **优雅停止**：`stop_signal`（POSIX）/ `stop_timeout`（强 kill 兜底）
- **退出清理**：launcher 退出时按 stop_timeout 顺序停所有子进程

### 3. 依赖声明 + 安装闸门
`app.json.requires` 在 `do_install` 前校验：
```json
"requires": {
  "python": ">=3.8",
  "packages": ["pyserial", "rclpy"],
  "system": ["g++", "ros2"]
}
```
- `python` — 版本比对（`>=3.8` 语法）
- `packages` — `__import__()` 检查 Python 包
- `system` — `shutil.which()` 检查可执行命令

### 4. 多语言 cmd 解析
- `.py` / `.pyw` 自动前缀 `sys.executable`
- `.exe` / ELF / 任意可执行文件直接执行
- 支持 `workdir`（工作目录）和 `env`（环境变量）透传

### 5. 系统应用 vs 用户应用分层
- **系统应用**（`apps/system/`）：默认安装、接受更新、不可卸载
- **用户应用**（`apps/user/`）：允许安装 / 卸载

### 6. Launcher 自更新
launcher.py 本身支持 OTA 升级：`/api/launcher/update` 下载新版本 → 写 bat/sh 替换脚本 → 退出 launcher → 自动替换文件并重启。客户端在桌面状态栏可见版本号与"有新版本"红点提示。

## 🏗 架构

```
┌─────────────────────────────────────────────────┐
│  Launcher (Python, http.server, port 8000)     │
│  ─────────────────────────────────────────────  │
│  • 桌面 UI（HTML + JS，浏览器打开即用）         │
│  • 应用生命周期（spawn / watcher / restart）    │
│  • ready_check 5 种探测器                       │
│  • do_install / do_uninstall                    │
│  • 依赖校验 _check_requires                     │
│  • 自更新 do_launcher_update                    │
└─────────────┬───────────────────────────┬───────┘
              │ subprocess.Popen          │ HTTP/HTTPS
              ▼                           ▼
┌─────────────────────────┐    ┌──────────────────────────┐
│  Apps (任意语言)         │    │  Repo (HTTP 静态目录)    │
│  ─────────────────────  │    │  ──────────────────────  │
│  apps/system/           │    │  index.json              │
│    store/  (Python)     │    │  packages/<id>-<ver>.zip │
│    todo/   (Python)     │    │  launcher-<ver>.zip      │
│    clock/  (Python)     │    └──────────────────────────┘
│    sysinfo/ (Python)    │              ▲
│  apps/user/             │              │
│    hello/   (Python)    │              │ scp
│    calc/    (Python)    │              │
│    weather/ (Python)    │ ─────────────┘
│    proc-demo/ (Python)  │  publish.py --all / --launcher
│    tcp-probe/ (Python)  │
│    file-demo/ (Python)  │
│    cpp-hello/ (C++)     │  ← 后续扩展
│    serial-echo/ (pyserial) │ ← 后续扩展
│    ros2-listener/ (rclpy)  │ ← 后续扩展
└─────────────────────────┘
```

## 🚀 快速开始

```bash
# 1. 启动 launcher
python launcher.py

# 2. 浏览器打开（一般会自动打开）
# http://127.0.0.1:8000/

# 3. 点桌面图标打开任意应用，或点 🛒 应用商店安装新应用
```

需要 Python ≥ 3.8，无第三方依赖（标准库足够）。

## 📋 app.json 完整 Schema

应用清单文件，放在 `apps/system/<id>/app.json` 或 `apps/user/<id>/app.json`。

### 基础字段（必填 / 旧字段）

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `id` | string | ✅ | — | 应用唯一标识（与目录名一致） |
| `name` | string | ✅ | — | 显示名称 |
| `version` | string | ✅ | — | 语义化版本号（`1.0.0`） |
| `cmd` | string[] | ❌ | — | 启动命令（`.py` 自动加 python 前缀） |
| `port` | int | ❌ | — | HTTP/TCP 端口（用于 ready_check 与 iframe URL） |
| `icon` | string | ❌ | 📦 | emoji 图标 |
| `color` | string | ❌ | #999 | 主题色（CSS） |
| `changelog` | string | ❌ | — | 版本说明 |
| `dock` | bool | ❌ | false | 是否常驻底部 Dock |
| `system` | bool | ❌ | false | 是否系统应用（自动推导，一般不手填） |

### 生命周期字段（新增，全部可选）

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `ready_check` | object | 推导 | 就绪判定协议（见下表） |
| `workdir` | string | `BASE` | 子进程工作目录 |
| `env` | object | `{}` | 环境变量（合并到 `os.environ` 之上） |
| `stop_signal` | string | `"SIGTERM"` | 优雅停止信号（POSIX）；Windows 仅 SIGINT 有效 |
| `stop_timeout` | number | 5 | 优雅停止等待秒数，超时强 kill |
| `restart_policy` | object | 见下 | 崩溃重启策略 |
| `requires` | object | `{}` | 依赖声明（安装前校验） |

> ⚠️ `env` **不进 index.json**（防密钥泄漏），由部署方在本地 app.json 手填。

### `ready_check` 字段

```json
"ready_check": {
  "type": "http | tcp | process | file | none",
  "port": 8110,           // http/tcp 用，默认 = app.port
  "path": "/health",      // http 用，缺省时降级为 TCP probe
  "expect": 200,          // http 用，期望状态码
  "file": "var/ready",    // file 用，相对 BASE 的路径
  "timeout": 6            // 探测超时秒数
}
```

**缺省推导**：
- 有 `port` → `http`（无 path 时降级为 TCP probe，保证旧 app 零回归）
- 有 `cmd` 无 `port` → `process`
- 无 `cmd` → `none`

### `restart_policy` 字段

```json
"restart_policy": {
  "on": "always | failure | never",  // 默认 never
  "max_retries": 3,                   // 默认 3
  "delay": 2                          // 默认 2 秒
}
```

| on 策略 | 触发条件 |
|---------|---------|
| `always` | 进程退出（无视 exit code） |
| `failure` | exit code ≠ 0 |
| `never` | 不重启（保持当前行为） |

### ready_check 类型对照表

| type | 适用场景 | 判定逻辑 | 局限 |
|------|---------|---------|------|
| `http` | HTTP 服务 | GET path 校验状态码；无 path 时降级为 TCP probe | 需要应用实现 HTTP 接口 |
| `tcp` | 裸 socket 服务、C++ echo server | `socket.create_connection` 能 accept | 只验端口监听，不验协议层 |
| `process` | 串口程序、ROS2 节点、CLI 工具 | 活过 grace 0.5s + 直到 timeout 未崩 | 消极就绪，5s 后才崩会误判 ready |
| `file` | ROS2 lifecycle 节点、需预热的守护进程 | 文件存在且 >0 字节 | 应用需主动写 ready 文件 |
| `none` | 占位应用 | 立即 ready | 无任何校验 |

> 💡 对 ROS2 lifecycle 节点推荐 `file`（让节点声明就绪），对长驻 CLI/串口程序推荐 `process` + `restart_policy.on=always`。

## 🛡 应用类型对比

| 属性 | 系统应用 | 用户应用 |
|------|---------|---------|
| 目录 | `apps/system/` | `apps/user/` |
| 默认安装 | ✅ | ❌（需手动装） |
| 接受更新 | ✅ | ✅ |
| 允许卸载 | ❌ | ✅ |
| 桌面图标标记 | 右上角青色小圆点 | 无 |
| 用途 | 商店、待办、番茄钟、系统信息 | 业务应用、demo |

## 🔌 API 列表

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/apps` | GET | 列出全部应用 + 运行状态（含 `status` 字段） |
| `/api/repo` | GET | 拉取远端仓库索引（含可升级标记） |
| `/api/install?id=<aid>` | GET | 安装 / 升级应用（先校验 requires） |
| `/api/uninstall?id=<aid>` | GET | 卸载用户应用（系统应用返回错误） |
| `/api/open?id=<aid>` | GET | 启动应用 + 返回访问 URL |
| `/api/close?id=<aid>` | GET | 优雅停止应用（发 stop_signal → 等 stop_timeout → 强 kill） |
| `/api/launcher` | GET | launcher 版本 + 远端最新版本 + 是否可升级 |
| `/api/launcher/update` | GET | 触发 launcher 自更新流程 |

### `status` 字段取值

`/api/apps` 返回的每个应用含 `status`：

| status | 含义 |
|--------|------|
| `starting` | 启动中（正在 spawn 或 ready_check 未通过） |
| `running` | 已就绪并运行 |
| `restarting` | 崩溃后正在重启 |
| `stopped` | 已停止（自然退出或被 close_app） |
| `crashed` | 崩溃且不再重启（exit≠0 或 retries 满） |
| `missing-deps` | 缺依赖（保留字段，未来用） |

## 📦 发布流程

### 发布应用

```bash
# 列出所有可发布的应用
python apps/publish.py --list

# 发布单个应用
python apps/publish.py apps/user/hello

# 一键发布所有应用
python apps/publish.py --all

# 只发系统应用 / 用户应用
python apps/publish.py --system
python apps/publish.py --user

# 只打包不上传（测试）
python apps/publish.py apps/user/hello --dry-run
```

### 发布 Launcher 自身更新

```bash
# 1. 修改 config.json 的 launcher.version（如 1.0.1）
# 2. 发布
python apps/publish.py --launcher --changelog "修复 X，新增 Y"
```

客户端在状态栏右上角 🔧 `v1.0.0` 胶囊可见，有新版本时红点闪烁，点击「立即更新」即可 OTA。

### 仓库结构（远端）

```
/var/www/repo/
├── index.json              # 应用清单 + launcher 元信息
└── packages/
    ├── hello-1.0.0.zip
    ├── calc-1.0.0.zip
    ├── weather-1.0.0.zip
    └── launcher-1.0.0.zip   # launcher 自更新包
```

## 🎯 内置应用

### 系统应用（`apps/system/`）

| 应用 | 端口 | 说明 |
|------|------|------|
| 🛒 应用商店 store | 8100 | 安装 / 升级 / 卸载用户应用 |
| 📝 待办清单 todo | 8101 | 最简待办 demo |
| ⏱️ 番茄钟 clock | 8102 | 计时器 demo |
| 📊 系统信息 sysinfo | 8103 | CPU / 内存 / 磁盘 + 版本信息 |

### 用户应用 demo（`apps/user/`）

#### Web 类 demo（端口 8110-8114）

| 应用 | 端口 | 演示场景 |
|------|------|----------|
| 👋 hello | 8110 | 最简交互（计数器 + 时钟） |
| 🧮 calc | 8111 | 复杂前端 UI + 表达式求值 |
| 🗒️ notes | 8112 | `localStorage` 持久化 |
| 🌤️ weather | 8113 | 多视图切换 + mock 数据 + JSON API |
| 🎮 game2048 | 8114 | 完整游戏（矩阵算法 + 键盘/触摸） |

#### 生命周期验证 demo（无端口 / TCP / file）

| 应用 | 验证场景 | ready_check | restart_policy |
|------|---------|-------------|----------------|
| ⚙️ proc-demo | 串口 / ROS2 节点场景（无端口） | `process` | `always` |
| 🔌 tcp-probe | 裸 socket 服务（非 HTTP） | `tcp` | `failure` |
| 📄 file-demo | 主动声明就绪（ROS2 lifecycle） | `file` | `never` |

#### 实时与原生 demo（端口 8130-8140）

| 应用 | 端口 | 演示场景 |
|------|------|----------|
| 📈 system-monitor | 8130 | 实时 CPU / 内存折线图 + TOP 进程 + 网络流量（psutil 优先，无则原生 wmic/proc） |
| 🦾 cpp-hello | 8140 | **C++ 应用部署模板**：原生 socket HTTP server，跨平台编译产物 + `run.py` 启动包装 + 子进程树清理 |

> `cpp-hello` 是 C/C++ 应用的接入模板。`socket / 串口 / ROS2` 等原生程序可参照它：源码 + `build.{bat,sh}` + `run.py` 包装 + `app.json`，按 `ready_check` 类型选择就绪判定方式。详见 [apps/README.md#部署-cc-应用](apps/README.md#🦾-部署-cc-应用)。

## 🔧 配置

`config.json`：

```json
{
  "launcher": {
    "host": "127.0.0.1",
    "port": 8000,
    "title": "我的 Launcher",
    "version": "1.0.0"
  },
  "repo": {
    "url": "https://your-repo.example.com",
    "verify_ssl": false
  },
  "ports": {                     // 系统应用端口映射
    "store": 8100,
    "todo": 8101,
    "clock": 8102,
    "sysinfo": 8103
  }
}
```

`publish` / `system_apps` 字段仅供本地开发用，**不进 launcher 自更新包**（脱敏处理）。

## 🌐 部署到嵌入式主板

### 1. Python 环境
- 推荐 Python 3.10+（兼容性最好）
- 树莓派 / Jetson：用系统自带 `python3` 即可
- 极小设备：用 `python3-minimal` + 手动补 `pip`

### 2. 跨平台注意事项
- **ARM 架构**：launcher 本身是纯 Python，无架构依赖；C/C++ 应用需对应架构编译
- **Windows CE / RT**：不支持（依赖 `subprocess.CREATE_NO_WINDOW`）
- **Linux musl**：注意 `signal.SIGTERM` 等 POSIX 信号可用，`signal.CTRL_BREAK_EVENT` 不可用
- **C/C++ 应用部署**：参照 [cpp-hello 模板](apps/user/cpp-hello/)，建议静态链接（`-static`）避免运行时缺 DLL；x86 / ARM 分别出 zip（如 `xxx-1.0.0-arm64.zip`）

### 3. 应用预装
- 把 `apps/system/` 全部预装到主板（出厂默认）
- `apps/user/` 由用户后续通过应用商店安装
- 仓库 URL 配置成自己的镜像（HTTPS + basic auth 可选）

### 4. ROS2 节点接入示例

```json
{
  "id": "my-ros2-node",
  "name": "ROS2 Listener",
  "icon": "🤖",
  "version": "1.0.0",
  "cmd": ["ros2", "run", "my_pkg", "listener"],
  "workdir": "/opt/ros2/install/setup.bash",
  "env": {
    "ROS_DOMAIN_ID": "42",
    "RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp"
  },
  "ready_check": {"type": "file", "file": "var/my-ros2-node.ready", "timeout": 10},
  "restart_policy": {"on": "always", "max_retries": 10, "delay": 3},
  "stop_signal": "SIGINT",
  "stop_timeout": 5,
  "requires": {"system": ["ros2"]}
}
```

## 📂 目录结构

```
web-launcher/
├── launcher.py              # 主程序（HTTP server + 生命周期管理）
├── config.json              # 配置（host/port/repo/ports）
├── README.md                # 本文档
├── apps/
│   ├── publish.py           # 发布工具（应用 + launcher 自更新）
│   ├── README.md            # 应用开发指南
│   ├── system/              # 系统应用（默认安装、不可卸载）
│   │   ├── store/           # 应用商店
│   │   ├── todo/            # 待办清单
│   │   ├── clock/           # 番茄钟
│   │   └── sysinfo/         # 系统信息
│   └── user/                # 用户应用（可增删）
│       ├── hello/           # 👋 最简 demo
│       ├── calc/            # 🧮 计算器
│       ├── notes/           # 🗒️ 便签
│       ├── weather/         # 🌤️ 天气
│       ├── game2048/        # 🎮 2048 小游戏
│       ├── proc-demo/       # ⚙️ process 就绪验证
│       ├── tcp-probe/       # 🔌 tcp 就绪验证
│       └── file-demo/       # 📄 file 就绪验证
└── server/                  # 服务端部署文档
    └── 服务器端-部署.md
```

## 🔒 安全注意事项

- `env` 字段不进 index.json（防密钥泄漏到仓库）
- `/api/apps` 不暴露 env 内容（可能含 token）
- 仓库 URL 若包含敏感信息，建议用 HTTPS + basic auth（`config.json.repo.auth`）
- launcher 默认监听 `127.0.0.1`，不对外暴露；如需远程访问请加反向代理 + 鉴权

## 🛣 路线图

- [x] ready_check 5 种就绪判定
- [x] 完整生命周期（spawn / watcher / restart / graceful stop）
- [x] 依赖声明 + 安装闸门
- [x] launcher 自更新
- [ ] 应用间 IPC 总线（发现 + 调用）
- [ ] 应用资源限制（CPU / 内存配额）
- [ ] 日志收集与轮转
- [ ] cpp-hello demo（验证非 Python cmd + requires: g++）
- [ ] serial-echo demo（验证 pyserial 串口应用）
- [ ] ros2-listener demo（验证 ROS2 节点接入）

## 📜 License

MIT
