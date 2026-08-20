# ⚙️ 配置文件详解

Launcher 涉及 3 个配置文件 + 端口分配机制：

| 文件 | 作用 | 谁来写 |
|------|------|--------|
| [config.json](#configjson) | Launcher 主配置 | 开发者 / 用户通过 settings 应用 |
| [app.json](#appjson) | 单个应用清单 | 应用开发者 |
| [layout.json](#layoutjson) | 用户级布局覆盖 | 用户通过布局编辑面板 |

---

## config.json

Launcher 主配置文件，位于项目根目录。打包成 exe 后放在 exe 同级目录。

### 完整示例

```json
{
  "launcher": {
    "host": "127.0.0.1",
    "port": 8000,
    "title": "WebLauncher",
    "version": "1.0.2",
    "released": "2026-08-18T16:00:00",
    "changelog": "- 应用分类重构：system/user 两级目录\n- ..."
  },
  "repo": {
    "url": "https://1.15.30.237",
    "auth": null,
    "verify_ssl": false
  },
  "publish": {
    "server": "ubuntu@1.15.30.237",
    "remote_path": "/var/www/repo",
    "packages_dir": "packages"
  }
}
```

### 字段说明

#### `launcher` 节

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `host` | string | `127.0.0.1` | HTTP 监听地址。默认仅本机访问；如需远程访问改为 `0.0.0.0`（**务必加反向代理 + 鉴权**） |
| `port` | int | `8000` | HTTP 监听端口 |
| `title` | string | `"WebLauncher"` | 桌面 UI 显示的标题 |
| `version` | string | — | Launcher 版本号（语义化版本，用于自更新对比） |
| `released` | string | — | 发布时间（ISO 8601 格式） |
| `changelog` | string | — | 更新说明（显示在关于面板） |

#### `repo` 节（仓库地址）

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `url` | string | — | 仓库服务器 URL（HTTP/HTTPS） |
| `auth` | `[user, pass]`\|null | null | BASIC 认证凭据；null 表示不认证 |
| `verify_ssl` | bool | false | 是否校验 SSL 证书；自签名证书设为 false |

#### `publish` 节（发布配置，仅本地开发用）

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `server` | string | — | SSH 服务器地址（如 `ubuntu@1.15.30.237`） |
| `remote_path` | string | — | 远端仓库目录（如 `/var/www/repo`） |
| `packages_dir` | string | `packages` | 包子目录名 |

> **重要**：`publish` 节仅供本地 `publish.py` 使用，**不进 launcher 自更新包**（[publish.py](../publish.py) 的 `build_launcher_zip` 会脱敏处理，只保留 `launcher` / `repo` 节）。

### 修改方式

- **手工编辑**：直接改文件，重启 launcher 生效
- **通过 settings 应用**：在桌面点 ⚙️ settings → 改仓库 URL / 认证 / SSL → POST `/api/repo/config` 原子写

### 安全注意事项

- `auth` 字段明文存储 BASIC 认证，不要泄露 config.json
- 默认 `host: 127.0.0.1`，不对外暴露；远程访问需自行加反向代理 + 鉴权
- 仓库 URL 若含敏感信息，建议用 HTTPS + basic auth（`config.json.repo.auth`）

---

## app.json

应用清单文件，放在 `apps/<group>/<id>/app.json`。详见 [App Development#app-json-schema](App-Development#appjson-schema)。

### 当前生效字段

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `id` | string | ✅ | — | 应用唯一标识（与目录名一致） |
| `name` | string | ✅ | — | 显示名称 |
| `version` | string | ✅ | — | 语义化版本号 |
| `cmd` | string[] | ❌ | — | 启动命令（`.py` 自动加 `sys.executable` 前缀） |
| `port` | int | ❌ | — | 建议端口（launcher 主导实际分配） |
| `icon` | string | ❌ | 📦 | emoji 图标 |
| `color` | string | ❌ | `#999` | 主题色（CSS） |
| `changelog` | string | ❌ | — | 版本说明 |
| `released` | string | ❌ | — | 发布时间（ISO 8601） |
| `dock` | bool | ❌ | false | 是否常驻 Dock（出厂默认；用户可覆盖） |
| `system` | bool | ❌ | false | 是否系统应用（按目录自动推导） |
| `group` | string | ❌ | 推导 | 自定义分组 |
| `requires` | object | ❌ | `{}` | 依赖声明（**当前未校验**） |

### 不生效字段（路线图）

| 字段 | 当前行为 |
|------|----------|
| `ready_check` | 不读取；只做 TCP 端口探测 |
| `restart_policy` | 不读取；崩溃不自动重启 |
| `stop_signal` / `stop_timeout` | 不读取；硬编码 terminate + 2s |
| `workdir` / `env` | 不读取；`Popen` 不传 |

### 最小可用示例

```json
{
  "id": "my-app",
  "name": "我的应用",
  "version": "1.0.0",
  "cmd": ["apps/user/my-app/app.py"],
  "port": 8120
}
```

详见 [App Development](App-Development)。

---

## layout.json

用户级布局覆盖层，位于项目根目录。**首次通过布局编辑面板保存后生成**，不存在时所有应用用 app.json 的 `dock` 默认值。

### 结构

```json
{
  "dock": ["store", "todo", "clock"],
  "hidden": ["file-demo", "proc-demo"],
  "version": 1
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `dock` | string[] | 在 Dock 显示的应用 id 列表（**覆盖** app.json 的 `dock` 默认值） |
| `hidden` | string[] | 从桌面隐藏的应用 id 列表（仍可在应用商店看到） |
| `version` | int | schema 版本号（当前固定为 1） |

### 覆盖逻辑

[layout.py#apply_layout](../launcher/layout.py) 的处理顺序：

1. `app_registry.reload_apps()` 扫描 `apps/` 下所有 app.json
2. 调用 `layout.apply_layout(apps)`：
   - 如果 app id 在 `hidden` 列表 → 从列表中过滤掉
   - 如果 layout.json 有 `dock` 字段 → 用 layout 的 dock 覆盖 app.json 的 `dock`
   - 否则保持 app.json 默认值
3. 返回新列表给 `REGISTRY`

**关键点**：app.json 的 `dock` 字段降级为"出厂默认值"，仅当 layout.json 未保存过或未指定该 app 时使用。

### 修改方式

- **手工编辑**：直接改文件，调 `/api/apps` 时不会立即生效，需触发 `reload_apps()`（重启或再次保存布局）
- **通过布局编辑面板**：状态栏 🗂️ → 勾选 → 保存 → POST `/api/layout` → 原子写 + `reload_apps()`

### 原子写实现

[layout.py#save_layout](../launcher/layout.py) 使用 `tmp.replace` 同盘原子替换：

```python
tmp = LAYOUT_JSON.with_suffix(".json.tmp.new")
tmp.write_bytes(json.dumps(cur, ...).encode("utf-8"))
tmp.replace(LAYOUT_JSON)  # 原子替换
```

中途断电不会损坏 layout.json（最多丢失 .tmp.new 临时文件）。

---

## 端口分配机制

### 设计原则

- **launcher 主导**：app 开发者不管冲突
- **app.json 的 `port` 仅作建议**：launcher 优先尝试，被占则自动分配随机端口
- **通过环境变量传递**：`LAUNCHER_APP_PORT` 环境变量传给 app
- **iframe URL 用实际端口**：不是 app.json 里的 port

### 分配流程

```
1. 读取 app.json 的 port 字段（建议端口）
2. socket.bind(("127.0.0.1", preferred)) 测试可用性
   ├── 成功 → 用 preferred
   └── 失败（被占）→ socket.bind(("127.0.0.1", 0)) 让 OS 选随机端口
3. env["LAUNCHER_APP_PORT"] = str(actual_port)
4. subprocess.Popen(cmd, env=env)
5. TCP 轮询 actual_port 直到监听成功（最多 6s）
6. 返回 actual_port（用于构造 iframe URL）
```

### App.py 推荐写法

**不要硬编码端口**：

```python
# ❌ 错误：硬编码端口
PORT = 8110

# ✅ 正确：从环境变量读取
import os
PORT = int(os.environ.get("LAUNCHER_APP_PORT", 0))
```

详见 [Architecture#端口分配机制](Architecture#端口分配机制)。

---

## 配置文件之间的关系

```
┌────────────────────────────────────────────────────┐
│ config.json (launcher 主配置)                      │
│  ├── launcher: host/port/title/version             │
│  ├── repo: 仓库地址                                │
│  └── publish: 发布配置（不进自更新包）             │
└────────────────────────────────────────────────────┘
                         │
                         │ 启动时加载
                         ▼
┌────────────────────────────────────────────────────┐
│ app_registry 扫描 apps/<group>/<id>/app.json       │
│  └── 每个应用的元数据（id/port/cmd/dock...）       │
└────────────────────────────────────────────────────┘
                         │
                         │ apply_layout 覆盖
                         ▼
┌────────────────────────────────────────────────────┐
│ layout.json (用户级覆盖)                           │
│  ├── dock: 用户选择的 Dock 应用                    │
│  └── hidden: 用户隐藏的应用                         │
└────────────────────────────────────────────────────┘
                         │
                         │ 合并后
                         ▼
┌────────────────────────────────────────────────────┐
│ app_registry.REGISTRY (内存)                       │
│  └── 最终的应用列表（供 /api/apps 返回）           │
└────────────────────────────────────────────────────┘
```
