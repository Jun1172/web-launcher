# Apps — 应用开发指南

所有应用都放在 `apps/` 目录下，按 `system` / `user` 分类。每个应用是一个独立目录，包含 `app.json` 清单 + 任意语言的代码。

## 📋 应用分类

| 类型 | 目录 | 默认安装 | 接受更新 | 允许卸载 |
|------|------|----------|----------|----------|
| 系统应用 | `apps/system/` | ✅ | ✅ | ❌ |
| 用户应用 | `apps/user/` | ❌ | ✅ | ✅ |

- **系统应用**：launcher 启动时自动注册，不可卸载；适合放应用商店、系统工具、监控等基础设施
- **用户应用**：由用户通过应用商店安装/卸载；适合放业务应用、demo、第三方扩展

## 📄 app.json 完整 Schema

完整字段说明见根目录 [README.md#app-json-完整-schema](../README.md#-appjson-完整-schema)。

### 最小可用清单

```json
{
  "id": "my-app",
  "name": "我的应用",
  "version": "1.0.0",
  "cmd": ["apps/user/my-app/app.py"],
  "port": 8120
}
```

缺省字段会自动推导：
- `ready_check` — 有 `port` → `http`；有 `cmd` 无 `port` → `process`；无 `cmd` → `none`
- `workdir` — `BASE`（项目根目录）
- `stop_signal` — `SIGTERM`
- `stop_timeout` — 5 秒
- `restart_policy` — `{on: never, max_retries: 3, delay: 2}`

### 完整示例（C++ 二进制 + 依赖校验 + 重启策略）

```json
{
  "id": "cpp-hello",
  "name": "C++ Hello",
  "icon": "🔵",
  "color": "#3498db",
  "version": "1.0.0",
  "port": 8120,
  "cmd": ["apps/user/cpp-hello/hello.exe"],
  "ready_check": {"type": "tcp", "port": 8120, "timeout": 4},
  "workdir": "apps/user/cpp-hello",
  "env": {"MY_CONFIG_PATH": "config/settings.ini"},
  "stop_signal": "SIGTERM",
  "stop_timeout": 5,
  "restart_policy": {"on": "failure", "max_retries": 3, "delay": 2},
  "requires": {
    "python": ">=3.8",
    "system": ["g++"]
  }
}
```

### 各字段速查

| 字段 | 默认 | 用途 |
|------|------|------|
| `ready_check.type` | 推导 | 5 种就绪判定：http / tcp / process / file / none |
| `ready_check.port` | app.port | http/tcp 探测端口 |
| `ready_check.path` | — | http 探测路径（缺省降级 TCP probe） |
| `ready_check.expect` | 200 | http 期望状态码 |
| `ready_check.file` | — | file 类型的 ready 文件路径（相对 BASE） |
| `ready_check.timeout` | 6 | 探测超时秒数 |
| `workdir` | BASE | 子进程工作目录 |
| `env` | `{}` | 环境变量（不进仓库，本地填写） |
| `stop_signal` | SIGTERM | 优雅停止信号（Windows 仅 SIGINT 可捕获） |
| `stop_timeout` | 5 | 优雅停止等待秒数，超时强 kill |
| `restart_policy.on` | never | always / failure / never |
| `restart_policy.max_retries` | 3 | 最大重启次数 |
| `restart_policy.delay` | 2 | 重启延迟秒数 |
| `requires.python` | — | Python 版本要求（`>=3.8`） |
| `requires.packages` | — | Python 包列表（用 `__import__` 校验） |
| `requires.system` | — | 系统命令列表（用 `which` 校验） |

## 🆕 新建应用

### 1. 创建目录

```
apps/user/<id>/
├── app.json
├── app.py  (或 main.cpp / index.js / hello.exe 等)
└── README.md
```

### 2. 选择 ready_check 类型

| 你的应用类型 | 推荐 ready_check | 推荐 restart_policy |
|-------------|------------------|---------------------|
| HTTP 服务 | `http`（带 path）或留空（默认） | `never` 或 `failure` |
| 裸 TCP 服务 | `tcp` | `failure` |
| 串口程序 | `process` | `always` |
| ROS2 节点 | `file`（写 ready 文件） | `always` |
| C++ 二进制 | `tcp`（若监听端口）或 `process` | `failure` |
| 占位 stub | `none` | `never` |

### 3. 编写 app.json

参考 [proc-demo/app.json](user/proc-demo/app.json) 等示例。

### 4. 本地测试

```bash
# 启动 launcher
python launcher.py

# 浏览器打开 http://127.0.0.1:8000/
# 点你的应用图标，应能正常启动
```

### 5. 发布

```bash
# 单个发布
python apps/publish.py apps/user/<id>

# 或随全部应用一起发布
python apps/publish.py --user
```

## 🔌 端口分配约定

| 应用 | 端口 |
|------|------|
| store（应用商店） | 8100 |
| todo（待办清单） | 8101 |
| clock（番茄钟） | 8102 |
| sysinfo（系统信息） | 8103 |
| hello（demo） | 8110 |
| calc（demo） | 8111 |
| notes（demo） | 8112 |
| weather（demo） | 8113 |
| game2048（demo） | 8114 |
| tcp-probe（验证） | 8120 |
| proc-demo（验证，无端口） | — |
| file-demo（验证，无端口） | — |
| system-monitor（监控 demo） | 8130 |
| cpp-hello（C++ demo） | 8140 |

新应用建议从 8150 开始往上分配，避免和现有应用冲突。

## 📦 打包结构

`publish.py` 打包的 zip 顶层结构统一为 `apps/{system|user}/<id>/...`：

```
hello-1.0.0.zip
└── apps/user/hello/
    ├── app.json
    ├── app.py
    └── README.md
```

`do_install` 解压时自动识别 3 种结构（详见 [launcher.py#L540-L560](../launcher.py#L540-L560)）：
- 结构 A：`apps/system/<id>/...` 或 `apps/user/<id>/...`（统一打包，推荐）
- 结构 B：`<id>/...`（旧打包格式）
- 结构 C：扁平文件列表（旧扁平打包）

## 🎯 各 demo 演示场景

详见根 [README.md#内置应用](../README.md#-内置应用)。

## 🦾 部署 C/C++ 应用

`cpp-hello` 是 C++ 应用部署模板，约定如下：

1. **源码即文档**：`app.json.requires.comment` 写明编译方式（`requires` 字段不会阻塞安装，仅作为提示）
2. **本机编译**：发布前在目标机器上跑 `build.bat`（Windows）/ `bash build.sh`（Linux/macOS），产物在 `bin/` 下
3. **启动包装**：`run.py` 负责跨平台选可执行文件 + 用 `subprocess.Popen` 拉起 + 转发 SIGTERM 给子进程
   - launcher 看到的 PID 是 Python 包装进程（可观测、可停止）
   - close_app 时 launcher 用 `taskkill /T /F` 或 `killpg` 递归杀整棵树，C++ 子进程不会成孤儿
4. **跨架构部署**：x86 / ARM 需各自编译，建议用 zip 名后缀区分（如 `cpp-hello-1.0.0-win-x64.zip`）

`app.json` 关键字段示例：

```json
{
  "cmd": ["apps/user/cpp-hello/run.py"],
  "ready_check": {"type": "http", "timeout": 5},
  "stop_signal": "SIGTERM",
  "stop_timeout": 3,
  "requires": {
    "comment": "C++ 源码，需要本机先编译：build.bat / bash build.sh"
  }
}
```

非 HTTP 服务（如裸 socket / 串口 / ROS2 节点）改 `ready_check.type` 为 `tcp` / `process` / `file` 即可。

