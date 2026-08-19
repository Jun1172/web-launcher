# Apps — 应用开发指南

所有应用都放在 `apps/` 目录下，按分组组织。每个应用是一个独立目录，包含 `app.json` 清单 + 任意语言的代码。

## 📋 应用分类

| 类型 | 目录 | 默认安装 | 接受更新 | 允许卸载 |
|------|------|----------|----------|----------|
| 系统应用 | `apps/system/` | ✅ | ✅ | ❌ |
| 用户应用 | `apps/user/` | ❌ | ✅ | ✅ |
| 自定义分组 | `apps/<group>/`（如 `apps/etws/`） | ❌ | ✅ | ✅ |

- **系统应用**：launcher 启动时自动注册，受保护分组 `"system"`，不可卸载；适合放应用商店、系统工具、监控等基础设施
- **用户应用**：默认走 `apps/user/`，由用户通过应用商店安装/卸载
- **自定义分组**：app.json 写 `"group": "etws"`，发布与卸载按此分组；目录可在 `apps/<group>/` 下（也可仍在 `apps/user/` 下，靠 group 字段决定归属）

## 📄 app.json Schema

完整字段说明见根目录 [README.md#app-json-schema](../README.md#-appjson-schema)。

### 当前生效字段速查

| 字段 | 类型 | 必填 | 默认 | 用途 |
|------|------|------|------|------|
| `id` | string | ✅ | — | 应用唯一标识（与目录名一致） |
| `name` | string | ✅ | — | 显示名称 |
| `version` | string | ✅ | — | 语义化版本号（`1.0.0`） |
| `cmd` | string[] | ❌ | — | 启动命令；`.py`/`.pyw` 自动前缀 `sys.executable`，其他直接执行 |
| `port` | int | ❌ | — | 端口；用于 TCP 就绪探测 + iframe URL；无端口则启动即视为就绪 |
| `icon` | string | ❌ | 📦 | emoji 图标 |
| `color` | string | ❌ | #999 | 主题色（CSS） |
| `changelog` | string | ❌ | — | 版本说明 |
| `released` | string | ❌ | — | 发布时间（ISO 8601） |
| `dock` | bool | ❌ | false | 是否常驻底部 Dock（出厂默认；用户可用 layout.json 覆盖） |
| `system` | bool | ❌ | false | 是否系统应用（一般不手填，按目录自动推导） |
| `group` | string | ❌ | 推导 | 自定义分组；缺省时按 `system` 推导为 `"system"` 或 `"user"` |
| `requires` | object | ❌ | `{}` | 依赖声明（**当前未校验**，仅作文档，见路线图） |

### ⚠️ 当前不生效字段

下列字段写在 app.json 里**不会报错也不会生效**（路线图里待实现）：

| 字段 | 当前行为 |
|------|----------|
| `ready_check` | 不读取；只看 `port` 字段做 TCP 端口探测 |
| `restart_policy` | 不读取；进程崩溃后不自动重启 |
| `stop_signal` | 不读取；`close_app` 直接 `p.terminate()` |
| `stop_timeout` | 不读取；硬编码 2 秒后强 kill |
| `workdir` | 不读取；`Popen` 未传 `cwd` |
| `env` | 不读取；`Popen` 未传 `env`（且 `env` 不进 index.json，避免密钥泄漏） |

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

无端口的进程型应用（无 HTTP 服务）：

```json
{
  "id": "my-daemon",
  "name": "我的守护进程",
  "version": "1.0.0",
  "cmd": ["apps/user/my-daemon/daemon.py"]
}
```

### 完整示例（C++ 二进制 + 自定义分组）

```json
{
  "id": "cpp-hello",
  "name": "C++ Hello",
  "icon": "🔵",
  "color": "#3498db",
  "version": "1.0.0",
  "port": 8140,
  "cmd": ["apps/user/cpp-hello/run.py"],
  "group": "user",
  "requires": {
    "comment": "C++ 源码，需要本机先编译：build.bat / bash build.sh"
  }
}
```

## 🆕 新建应用

### 1. 创建目录

```
apps/user/<id>/
├── app.json
├── app.py  (或 main.cpp / index.js / hello.exe 等)
└── README.md
```

### 2. 选择是否有端口

| 你的应用类型 | 推荐 `port` | 行为 |
|-------------|-------------|------|
| HTTP 服务 | ✅ 填端口 | 启动后 launcher 用 TCP 轮询直到端口监听，超时 6s |
| 裸 socket 服务 | ✅ 填端口 | 同上（只验端口监听，不验协议层） |
| 后台进程 / 守护进程 | ❌ 不填 | 启动即视为就绪 |
| C++ 二进制（监听端口） | ✅ 填端口 | 同 HTTP 服务 |
| 占位 stub | ❌ 不填 cmd | 无 cmd 时立即视为就绪 |

### 3. 编写 app.json

参考 [hello/app.json](user/hello/app.json) 等示例。

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
python publish.py apps/user/<id>

# 或随全部应用一起发布
python publish.py --user

# 按分组发布
python publish.py --group etws
```

## 🔌 端口分配约定

| 应用 | 端口 |
|------|------|
| store（应用商店） | 8100 |
| todo（待办清单） | 8101 |
| clock（番茄钟） | 8102 |
| sysinfo（系统信息） | 8103 |
| settings（设置） | 8104 |
| hello（demo） | 8110 |
| notes（demo） | 8112 |
| weather（demo） | 8113 |
| game2048（demo） | 8114 |
| proc-demo（后台进程 demo） | — |
| file-demo（占位 stub demo） | — |
| system-monitor（监控 demo） | 8130 |
| cpp-hello（C++ demo） | 8140 |

新应用建议从 8150 开始往上分配，避免和现有应用冲突。

## 📦 打包结构

`publish.py` 打包的 zip 顶层结构统一为 `apps/<group>/<id>/...`：

```
hello-1.0.0.zip
└── apps/user/hello/
    ├── app.json
    ├── app.py
    └── README.md
```

`do_install` 解压时自动识别 3 种结构（详见 [launcher/repo.py#atomic_extract_zip](../launcher/repo.py)）：
- 结构 A：`apps/<group>/<id>/...`（统一打包，推荐）
- 结构 B：`<id>/...`（旧打包格式）
- 结构 C：扁平文件列表（旧扁平打包）

## 🎯 各 demo 演示场景

详见根 [README.md#内置应用](../README.md#-内置应用)。

## 🦾 部署 C/C++ 应用

`cpp-hello` 是 C++ 应用部署模板，约定如下：

1. **源码即文档**：`app.json.requires.comment` 写明编译方式（`requires` 字段当前不阻塞安装，仅作为提示）
2. **本机编译**：发布前在目标机器上跑 `build.bat`（Windows）/ `bash build.sh`（Linux/macOS），产物在 `bin/` 下
3. **启动包装**：`run.py` 负责跨平台选可执行文件 + 用 `subprocess.Popen` 拉起
   - launcher 看到的 PID 是 Python 包装进程（可观测、可停止）
   - close_app 时 launcher 用 `taskkill /T /F` 或 `killpg` 递归杀整棵树，C++ 子进程不会成孤儿
4. **跨架构部署**：x86 / ARM 需各自编译，建议用 zip 名后缀区分（如 `cpp-hello-1.0.0-win-x64.zip`）

`app.json` 关键字段示例：

```json
{
  "id": "cpp-hello",
  "name": "C++ Hello",
  "version": "1.0.0",
  "port": 8140,
  "cmd": ["apps/user/cpp-hello/run.py"],
  "requires": {
    "comment": "C++ 源码，需要本机先编译：build.bat / bash build.sh"
  }
}
```

> 注：当前 launcher 不读 `ready_check` / `stop_signal` / `stop_timeout` 等字段，C++ 程序的停止靠 `terminate()` + 2s 后 `taskkill /T` 兜底杀进程树。可配置信号能力在路线图。
