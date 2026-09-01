# Apps — 应用开发指南

所有应用都放在 `apps/` 目录下，按分组组织。每个应用是一个独立目录，包含 `app.json` 清单 + 任意语言的代码。

## 📋 应用分类

| 类型 | 目录 | 默认安装 | 接受更新 | 允许卸载 |
|------|------|----------|----------|----------|
| 系统应用 | `apps/system/` | ✅ | ✅ | ❌ |
| 用户应用 | `apps/user/` | ❌ | ✅ | ✅ |
| 自定义分组 | `apps/<group>/`（如 `apps/business/`） | ❌ | ✅ | ✅ |

- **系统应用**：launcher 启动时自动注册，受保护分组 `"system"`，不可卸载；适合放应用商店、系统工具、监控等基础设施
- **用户应用**：默认走 `apps/user/`，由用户通过应用商店安装/卸载
- **自定义分组**：app.json 写 `"group": "business"`，发布与卸载按此分组；目录可在 `apps/<group>/` 下（也可仍在 `apps/user/` 下，靠 group 字段决定归属）

## 📄 app.json Schema

完整字段说明见根目录 [README.md#app-json-schema](../README.md#-appjson-schema)。

### 当前生效字段速查

| 字段 | 类型 | 必填 | 默认 | 用途 |
|------|------|------|------|------|
| `id` | string | ✅ | — | 应用唯一标识（与目录名一致） |
| `name` | string | ✅ | — | 显示名称 |
| `version` | string | ✅ | — | 语义化版本号（`1.0.0`） |
| `cmd` | string[] | ❌ | — | 启动命令；`.py`/`.pyw` 自动前缀 `sys.executable`，其他直接执行 |
| `port` | int | ❌ | — | 建议端口（被占时 launcher 自动分配随机端口）；用于 TCP 就绪探测 + iframe URL；无端口则启动即视为就绪 |
| `icon` | string | ❌ | 📦 | emoji 图标 |
| `color` | string | ❌ | #999 | 主题色（CSS） |
| `changelog` | string | ❌ | — | 版本说明 |
| `released` | string | ❌ | — | 发布时间（ISO 8601） |
| `dock` | bool | ❌ | false | 是否常驻底部 Dock（出厂默认；用户可用 layout.json 覆盖） |
| `group` | string | ❌ | `"user"` | 分组来源；`"system"` 受保护不可卸载，自定义分组发布/卸载按此分组 |

> 已从 schema 移除的未实现字段：`ready_check` / `restart_policy` / `stop_signal` / `stop_timeout` / `workdir` / `requires` / `system`。当前只做 TCP 端口探测，进程停止固定用 `terminate()` + 2s 后强 kill 兜底。

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
  "port": 8124,
  "cmd": ["apps/user/cpp-hello/run.py"],
  "group": "user"
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
python publish.py --group business
```

## 🔌 端口分配约定

`app.json.port` 只是"建议端口"：launcher 启动时优先尝试该端口，被占则自动分配随机空闲端口，并通过 `LAUNCHER_APP_PORT` 环境变量传给应用；应用单独运行时回退读取 `app.json.port`（见下方 get_port() 约定）。

| 分组 | 应用 | 端口 |
|------|------|------|
| system | store（应用商店） | 8100 |
| user | todo（待办清单） | 8101 |
| system | clock（番茄钟） | 8102 |
| system | sysinfo（系统信息） | 8103 |
| system | settings（设置） | 8104 |
| etws | ad-analysis（AD 数据解析） | 8116 |
| etws | mqtt-monitor（状态监测） | 8150 |
| system | md-viewer（文档查看） | 8154 |
| etws | radar-viewer（雷达数据） | 8160 |
| etws | channel-analyse（通道分析） | 8165 |
| user | game2048（2048 小游戏） | 8121 |
| user | hello（最简 demo） | 8122 |
| user | weather（天气 demo） | 8123 |
| user | cpp-hello（C++ demo） | 8124 |
| user | system-monitor（监控 demo） | 8125 |
| user | log-viewer（日志 demo） | 8151 |
| user | cron-ui（定时任务 demo） | 8152 |
| user | nixie-clock（数码管时钟） | 8168 |
| ros | ros2-monitor（ROS2 监控） | 8201 |
| ros | ros2-topic-inspector（话题） | 8203 |
| ros | ros2-service（服务） | 8204 |
| ros | ros2-param（参数） | 8205 |
| ros | ros2-action（动作） | 8206 |
| ros | ros2-graph（关系图） | 8207 |
| ros | ros2-type-studio（类型/波形） | 8209 |

端口段建议：system `8100-8199`、user `8100-8199`、etws `8110-8169`、ros `8201-8209`；**新应用从 8210 开始往上分配**，避免和现有应用冲突。

### get_port() 端口读取约定

应用侧统一用下面的模板读取端口（launcher 注入优先 → 回退 app.json → 均无效返回 0 由 OS 随机分配）：

```python
def get_port():
    """端口读取：优先 LAUNCHER_APP_PORT，缺失回退 app.json 的 port，均无效返回 0。"""
    env_port = os.environ.get("LAUNCHER_APP_PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            pass
    j = Path(__file__).resolve().parent / "app.json"
    if j.exists():
        try:
            return int(json.loads(j.read_text(encoding="utf-8")).get("port", 0))
        except Exception:
            pass
    return 0


PORT = get_port()
```

（`json` / `os` / `pathlib.Path` 需在文件顶部导入。）

### 监听地址约定（APP_HOST）

应用**不要硬编码** `127.0.0.1` / `0.0.0.0`。launcher 启动时会把自己的监听地址写入 `APP_HOST` 环境变量，子进程（应用）继承后据此绑定，从而自动跟随 launcher：桌面模式默认只监听回环；把 `config.json` 的 `launcher.host` 改成 `0.0.0.0` 后，所有应用随之一并对局域网开放，无需逐个修改。

```python
# 推荐写法：读 APP_HOST，缺省回退 127.0.0.1
ThreadingHTTPServer((os.environ.get("APP_HOST", "127.0.0.1"), PORT), H).serve_forever()
```

需要复用地址时（如打印启动日志）先取到变量再传入：

```python
HOST = os.environ.get("APP_HOST", "127.0.0.1")
print(f"[my-app] 启动于 http://{HOST}:{PORT}")
ThreadingHTTPServer((HOST, PORT), H).serve_forever()
```

> 应用单独运行（未经过 launcher）时 `APP_HOST` 不存在，回退 `127.0.0.1`，行为与改造前一致。

## 📦 打包结构

`publish.py` 打包的 zip 顶层结构统一为 `apps/<group>/<id>/...`：

```
hello-1.0.0.zip
└── apps/user/hello/
    ├── app.json
    ├── app.py
    └── README.md
```

`do_install` 解压时自动识别 3 种结构（详见 [launcher/zipio.py](../launcher/zipio.py)）：
- 结构 A：`apps/<group>/<id>/...`（统一打包，推荐）
- 结构 B：`<id>/...`（旧打包格式）
- 结构 C：扁平文件列表（旧扁平打包）

## 🎯 各 demo 演示场景

详见根 [README.md#内置应用](../README.md#-内置应用)。

## 🦾 部署 C/C++ 应用

`cpp-hello` 是 C++ 应用部署模板，约定如下：

1. **源码即文档**：`app.json.changelog` 写明编译方式与注意事项
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
  "port": 8124,
  "cmd": ["apps/user/cpp-hello/run.py"]
}
```

> 注：C++ 程序的停止靠 `terminate()` + 2s 后 `taskkill /T` 兜底杀进程树。
