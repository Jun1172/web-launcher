# 🏗 架构设计

## 整体架构

```
┌─────────────────────────────────────────────────────┐
│  Launcher (Python stdlib, http.server, port 8000)  │
│  ─────────────────────────────────────────────────  │
│  launcher.py            ← 薄壳入口                  │
│  launcher/              ← 9 个功能模块              │
│    ├ config.py          ← 配置加载/路径常量         │
│    ├ app_registry.py    ← 应用扫描/注册表           │
│    ├ process_manager.py ← spawn/port_probe/close   │
│    ├ app_operations.py  ← install/uninstall/回退    │
│    ├ repo.py            ← 仓库索引/HTTP 客户端      │
│    ├ http_handler.py    ← 路由                      │
│    ├ frontend.py        ← 首页 HTML 渲染             │
│    ├ layout.py          ← 用户布局覆盖（layout.json）│
│    └ updater.py         ← 二进制 OTA 替换脚本       │
│  publish.py             ← 发布到仓库                │
│  ─────────────────────────────────────────────────  │
│  • 桌面 UI（毛玻璃 + 分页 + Dock + 最近任务面板）   │
│  • 应用生命周期（spawn / port_probe / graceful stop）│
│  • 安装/卸载/版本回退 + 受保护分组（system 不可卸载）│
│  • 自更新（开发态 zip 覆盖 / 编译态 bat/sh 替换）   │
└─────────────┬───────────────────────────┬──────────┘
              │ subprocess.Popen          │ HTTP/HTTPS
              ▼                           ▼
┌─────────────────────────┐    ┌──────────────────────────┐
│  Apps (任意语言)         │    │  Repo (HTTP 静态目录)    │
│  ─────────────────────  │    │  ──────────────────────  │
│  apps/system/           │    │  index.json              │
│    store/  todo/  clock/│    │  packages/<id>-<ver>.zip │
│    sysinfo/ settings/   │    │  launcher-<ver>.zip      │
│  apps/user/             │    └──────────────────────────┘
│    hello/  notes/       │              ▲
│    weather/ game2048/   │              │ scp
│    proc-demo/ file-demo/│ ─────────────┘
│    system-monitor/      │  publish.py --all / --launcher
│    cpp-hello/ (C++)     │
└─────────────────────────┘
```

Launcher 是单进程的 Python HTTP 服务器，通过 `subprocess.Popen` 拉起每个应用作为独立进程，用 iframe 把应用嵌入桌面。

---

## 模块职责

Launcher 包共 9 个功能模块，职责单一，依赖方向清晰：

| 模块 | 职责 | 关键函数 |
|------|------|----------|
| [config.py](../launcher/config.py) | 配置加载、路径常量 | `load_config()`、`BASE`/`APPS_DIR` 等常量 |
| [app_registry.py](../launcher/app_registry.py) | 应用扫描、注册表维护 | `reload_apps()`、`rebuild_registry()`、`resolve_cmd()` |
| [process_manager.py](../launcher/process_manager.py) | 进程启动、端口分配、进程树清理 | `open_app()`、`close_app()`、`terminate_all()` |
| [app_operations.py](../launcher/app_operations.py) | 安装、卸载、版本回退、launcher 自更新 | `do_install()`、`do_uninstall()`、`do_launcher_update()` |
| [repo.py](../launcher/repo.py) | 仓库索引、HTTP 客户端、原子解压 | `repo_index()`、`repo_get()`、`atomic_extract_zip()` |
| [http_handler.py](../launcher/http_handler.py) | HTTP 路由 | `Handler` 类（BaseHTTPRequestHandler 子类） |
| [frontend.py](../launcher/frontend.py) | 首页 HTML 渲染 | `render_home()` |
| [layout.py](../launcher/layout.py) | 用户布局覆盖（layout.json 读写） | `load_layout()`、`save_layout()`、`apply_layout()` |
| [updater.py](../launcher/updater.py) | 二进制 OTA 替换脚本生成 | `launch_self_update()`、`_write_windows_updater()` |

**依赖方向**：`http_handler → app_operations / process_manager / app_registry / repo / layout / frontend`，`app_operations → repo / process_manager / app_registry`，模块间通过显式 import 传递，没有全局可变状态（除 `procs` / `actual_ports` / `REGISTRY` 三个模块级字典/列表）。

---

## 启动一个应用的完整流程

以打开 `hello` 应用为例，调用 `GET /api/open?id=hello`：

```
1. http_handler 收到请求 → 调用 process_manager.open_app(app_meta)

2. open_app 检查 procs[aid] 是否在运行
   ├── 已在运行 → 返回 actual_ports[aid]（已有的端口）
   └── 未运行 → 进入启动流程

3. 分配端口（_alloc_port）
   ├── 优先 app.json 的 port 字段（建议端口）
   ├── socket.bind(("127.0.0.1", preferred)) 测试可用性
   └── 被占或 None → socket.bind(("127.0.0.1", 0)) 随机分配

4. 构造环境变量 env = os.environ.copy()
   env["LAUNCHER_APP_PORT"] = str(port)   ← 关键：端口通过 env 传给 app

5. subprocess.Popen(app["cmd"], env=env, **_popen_kwargs())
   ├── Windows: creationflags=CREATE_NO_WINDOW（隐藏控制台）
   └── POSIX:  start_new_session=True（方便后续 killpg）

6. 轮询端口就绪（最多 6 秒）
   while time.time() < end:
   ├── p.poll() is not None → 进程崩溃，返回 None
   ├── socket.create_connection(("127.0.0.1", port), 0.3) 成功
   │   → sleep 0.3s 确认 → 返回 port
   └── 失败 → sleep 0.1s 重试

7. 返回 actual_port → http_handler 构造 iframe URL
   iframe.src = http://127.0.0.1:<actual_port>/
```

**关键设计**：app.py 不应该硬编码端口，而是从 `LAUNCHER_APP_PORT` 环境变量读取：

```python
import os
PORT = int(os.environ.get("LAUNCHER_APP_PORT", 0))
```

这样 launcher 主导端口分配，app 开发者完全不用关心冲突。

---

## 端口分配机制

### 设计目标

- **app 开发者不管冲突**：app.json 的 `port` 字段只是"建议值"
- **launcher 主导分配**：启动时优先建议端口，被占则自动分配随机可用端口
- **iframe URL 用实际端口**：不是 app.json 里的 port

### 端口分配策略

```python
def _alloc_port(preferred=None):
    if preferred:
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", int(preferred)))
            s.close()
            return int(preferred)       # 建议端口可用
        except OSError:
            pass                        # 被占，继续随机分配
    s = socket.socket()
    s.bind(("127.0.0.1", 0))            # OS 自动选可用端口
    port = s.getsockname()[1]
    s.close()
    return port
```

### 端口冲突处理

- **静态冲突检测**：[app_registry.py](../launcher/app_registry.py) 的 `_mark_port_conflicts()` 扫描所有 app.json，多个 app 写同一 port 时全部标记 `port_conflict: True`，前端显示 ⚠️ 角标
- **动态冲突处理**：启动时如果建议端口被占，launcher 自动分配随机端口，**不杀已有进程**，让冲突的 app 共存
- **环境变量传递**：实际端口通过 `LAUNCHER_APP_PORT` 环境变量传给 app

### 端口分配约定

| 应用 | 默认端口 |
|------|---------|
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

新应用建议从 8150 开始往上分配。

---

## 状态管理

Launcher 的状态散落在 5 处，没有统一 state layer：

| 状态 | 位置 | 说明 |
|------|------|------|
| Launcher 配置 | [config.json](../config.json) | host/port/repo/publish |
| 应用元数据 | 各 `apps/<group>/<id>/app.json` | id/name/port/cmd 等 |
| 用户布局 | [layout.json](../layout.json)（首次保存后生成） | dock/hidden 覆盖层 |
| 进程字典 | `process_manager.procs` | `{app_id: Popen}` 内存 |
| 实际端口字典 | `process_manager.actual_ports` | `{app_id: int}` 内存 |
| 应用注册表 | `app_registry.REGISTRY` | 扫描结果 + layout 覆盖 |

任何磁盘变更（安装/卸载/布局保存）都触发 `reload_apps()` 全量重扫 `apps/` 目录。增量更新机制在路线图。

---

## 进程树清理

### 为什么需要进程树清理

C/C++ 应用通常是这样启动的：

```
launcher → subprocess.Popen(run.py) → subprocess.Popen(cpp-hello.exe)
```

如果只杀 `run.py`，`cpp-hello.exe` 会变成孤儿进程。所以需要递归杀整棵进程树。

### 跨平台实现

**Windows**：`taskkill /F /T /PID`（`/T` = 递归杀子进程）

```python
def _kill_tree_nt(pid):
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)],
        capture_output=True, timeout=5,
    )
```

**POSIX**：用 `start_new_session=True` 创建进程组，`os.killpg(pid, 9)` 杀整组

```python
def _kill_tree_posix(pid):
    try:
        os.killpg(pid, 9)   # 负 pid = 进程组
    except Exception:
        os.kill(pid, 9)
```

### 关闭流程

`close_app(aid)` 的两段式关闭：

1. `p.terminate()` → 等 2 秒让子进程自行退出
2. 2 秒后还在 → 兜底 `_kill_tree_nt` / `_kill_tree_posix` 强杀

`terminate_all()` 在 launcher 退出时（`atexit` 钩子）按上述流程顺序停所有子进程，保证不留孤儿。

---

## 应用分类机制

### 双重判定

应用是系统应用还是用户应用，由两处共同决定：

1. **目录结构**：`apps/system/` vs `apps/user/`（物理隔离）
2. **app.json 字段**：`"system": true/false` 或 `"group": "system"/"user"/<自定义>`

### group 字段优先级

[app_operations.py](../launcher/app_operations.py) 的 `_resolve_pkg_meta()` 推导逻辑：

```python
app_group = match.get("group")
if app_group is None:
    app_group = "system" if match.get("system") else "user"
```

- 优先读 `group` 字段
- 没写 `group` 时按 `system` 字段推导
- 都没有则默认 `"user"`

### 受保护分组

[app_operations.py](../launcher/app_operations.py) 顶部定义：

```python
PROTECTED_GROUPS = {"system"}
```

卸载时检查 `app_group in PROTECTED_GROUPS`，是则拒绝卸载。未来要加 `admin`、`dev` 等不可卸载分组，直接往这个集合里加即可。

---

## 设计哲学

### 1. 最小依赖

- 全程用 Python 标准库（`http.server` / `subprocess` / `socket` / `json` / `zipfile`）
- 没有第三方依赖，部署到嵌入式设备不用装 pip 包

### 2. 最小协议

- 应用接入只需要一个 `app.json` 清单文件
- 不限制应用语言（Python / C++ / Node.js / 任意 ELF 都行）

### 3. launcher 主导，app 端零侵入

- 端口分配：launcher 主导，app 通过环境变量获取
- 端口冲突：launcher 自动分配随机端口，不杀已有进程
- 进程清理：launcher 通过 `taskkill /T` 或 `killpg` 杀整棵树，app 不用关心

### 4. 文件系统即状态

- 所有配置都是 JSON 文件，可读可手工编辑
- 进程状态是内存字典，重启即清空（简化设计，但代价是无持久化）
- 原子写：所有配置写都通过 `tmp.replace` 同盘原子替换
