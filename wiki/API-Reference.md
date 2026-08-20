# 🔌 HTTP API 文档

Launcher 启动后监听 `127.0.0.1:8000`，所有 API 都是 HTTP 接口。响应均为 JSON 格式，含 `Cache-Control: no-store` 头避免缓存。

> 调用方可以加 `Access-Control-Allow-Origin: *`，便于开发调试。

---

## API 总览

| 路径 | 方法 | 说明 |
|------|------|------|
| [`/`](#get-) | GET | 首页 HTML（桌面 UI） |
| [`/api/apps`](#get-apiapps) | GET | 列出全部应用 + 运行状态 + 实际端口 |
| [`/api/repo`](#get-apirepo) | GET | 拉取远端仓库索引（含可升级标记） |
| [`/api/repo/config`](#get-apirepoconfig) | GET | 读取仓库 URL / BASIC 认证 / SSL 配置 |
| [`/api/repo/config`](#post-apirepoconfig) | POST | 保存仓库配置（原子写 config.json + reload） |
| [`/api/layout`](#get-apilayout) | GET | 读取用户布局（dock / hidden） |
| [`/api/layout`](#post-apilayout) | POST | 保存布局配置（原子写 layout.json + reload_apps） |
| [`/api/install`](#get-apiinstall) | GET | 安装 / 升级应用到最新版本 |
| [`/api/install-version`](#get-apiinstall-version) | GET | 安装指定历史版本（供回退） |
| [`/api/uninstall`](#get-apiuninstall) | GET | 卸载用户应用（受保护分组 system 拒绝） |
| [`/api/open`](#get-apiopen) | GET | 启动应用进程 + 返回 iframe URL |
| [`/api/close`](#get-apiclose) | GET | 关闭应用进程树（terminate → 2s → 强 kill） |
| [`/api/launcher/version`](#get-apilauncherversion) | GET | launcher 本地 + 远端版本对比 |
| [`/api/launcher/update`](#get-apilauncherupdate) | GET | 触发 launcher 自更新流程 |
| [`/stub`](#get-stub) | GET | stub 占位页（无 cmd 的应用用此页代替） |

---

## GET /

返回首页 HTML（桌面 UI，含状态栏、分页桌面、Dock、最近任务面板、应用商店弹窗等）。

**响应**：`text/html;charset=utf-8`

**示例**：

```bash
curl http://127.0.0.1:8000/
```

---

## GET /api/apps

列出全部已安装应用 + 运行状态 + 实际监听端口。

**响应字段**（每个应用对象）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 应用唯一标识 |
| `name` | string | 显示名称 |
| `version` | string | 本地版本号 |
| `port` | int\|null | app.json 建议端口 |
| `cmd` | string[]\|null | 启动命令（已解析为绝对路径） |
| `dock` | bool | 是否常驻 Dock（已应用 layout 覆盖） |
| `system` | bool | 是否系统应用 |
| `group` | string | 分组 |
| `running` | bool | **运行状态**：true = 进程在运行 |
| `actual_port` | int\|null | **实际监听端口**（未运行则为 null） |
| `port_conflict` | bool | 端口冲突标记（多 app 写同一 port 时 true） |
| `icon` / `color` / `changelog` / `released` | — | 元信息 |

**示例**：

```bash
curl http://127.0.0.1:8000/api/apps
```

```json
[
  {
    "id": "store",
    "name": "应用商店",
    "version": "1.0.0",
    "port": 8100,
    "cmd": ["C:\\...\\python.exe", "C:\\...\\apps\\system\\store\\app.py"],
    "dock": true,
    "system": true,
    "group": "system",
    "running": false,
    "actual_port": null,
    "icon": "🛒",
    "color": "#00cec9",
    "changelog": "系统应用，可更新不可卸载"
  }
]
```

> **注意**：iframe URL 应该用 `actual_port` 字段（实际监听端口），不是 `port` 字段（建议端口）。

---

## GET /api/repo

拉取远端仓库索引，与本地应用列表对比，标记是否已安装 / 可升级。

**响应**：

```json
{
  "apps": [
    {
      "id": "hello",
      "name": "你好世界",
      "version": "1.0.0",
      "pkg": "packages/hello-1.0.0.zip",
      "sha256": "abc123...",
      "size": 4096,
      "local": "1.0.0",
      "installed": true,
      "upgradable": false,
      "system": false,
      "versions": [...]
    }
  ]
}
```

**字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `local` | string\|null | 本地版本号；未安装则为 null |
| `installed` | bool | 是否已安装 |
| `upgradable` | bool | 本地版本 < 远端版本时为 true |
| `system` | bool | 是否系统应用（**只由本地 apps/system 目录决定，不信任仓库元数据**） |
| `versions` | array | 历史版本列表（供回退） |

**错误响应**：

```json
{ "error": "连不上仓库: ...", "apps": [] }
```

---

## GET /api/repo/config

读取仓库 URL / BASIC 认证 / SSL 配置（settings 应用用）。

**响应**：

```json
{
  "url": "https://1.15.30.237",
  "auth_user": "",
  "auth_pass": "",
  "verify_ssl": false
}
```

---

## POST /api/repo/config

保存仓库配置。原子写 [config.json](../config.json) + 立即刷新内存配置。

**请求体**：

```json
{
  "url": "https://1.15.30.237",
  "auth_user": "user",
  "auth_pass": "pass",
  "verify_ssl": false
}
```

**响应**：

```json
{ "ok": true, "msg": "已保存，配置已实时刷新" }
```

---

## GET /api/layout

读取用户布局配置。dock 为 null 表示 [layout.json](../layout.json) 未保存过，前端应回退到 app.json 默认值。

**响应**：

```json
{
  "dock": ["store", "todo"],
  "hidden": ["file-demo"]
}
```

或未保存过：

```json
{
  "dock": null,
  "hidden": []
}
```

---

## POST /api/layout

保存用户布局配置。原子写 layout.json + 立即 `reload_apps()` 刷新内存注册表。

**请求体**：

```json
{
  "dock": ["store", "todo", "clock"],
  "hidden": ["file-demo", "proc-demo"]
}
```

**字段**：

- `dock`: array of string — 在 Dock 显示的应用 id 列表
- `hidden`: array of string — 从桌面隐藏的应用 id 列表

**响应**：

```json
{ "ok": true, "msg": "布局已保存" }
```

**错误响应**：

```json
{ "ok": false, "msg": "dock / hidden 必须为数组" }
```

---

## GET /api/install

安装 / 升级应用到最新版本。流程：
1. 在仓库索引中找到应用
2. 如果应用正在运行，先 `close_app(aid)` 关闭
3. 下载 zip → sha256 校验 → 原子解压到 `apps/<group>/<id>/`
4. `reload_apps()` 刷新注册表

**查询参数**：

- `id`: string — 应用 ID

**响应**：

```json
{ "ok": true, "msg": "ok" }
```

**错误**：

```json
{ "ok": false, "msg": "仓库中不存在该 id" }
```

**示例**：

```bash
curl "http://127.0.0.1:8000/api/install?id=hello"
```

---

## GET /api/install-version

安装指定历史版本（供回退）。

**查询参数**：

- `id`: string — 应用 ID
- `version`: string — 目标版本号（必须在仓库 `versions` 列表中）

**响应**：

```json
{ "ok": true, "msg": "ok" }
```

**示例**：

```bash
curl "http://127.0.0.1:8000/api/install-version?id=hello&version=0.9.0"
```

---

## GET /api/uninstall

卸载用户应用。**受保护分组（system）拒绝卸载**。

**查询参数**：

- `id`: string — 应用 ID

**响应**：

```json
{ "ok": true, "msg": "ok" }
```

**错误**：

```json
{ "ok": false, "msg": "受保护分组，禁止卸载" }
```

---

## GET /api/open

启动应用进程 + 返回 iframe URL。

**查询参数**：

- `id`: string — 应用 ID

**响应**：

启动成功（HTTP 服务型应用）：

```json
{
  "ok": true,
  "url": "http://127.0.0.1:51234",
  "reason": null
}
```

启动成功（stub 应用，无 cmd）：

```json
{
  "ok": true,
  "url": "/stub?id=file-demo",
  "reason": null
}
```

启动失败（进程崩溃 / 端口超时）：

```json
{
  "ok": false,
  "url": null,
  "reason": "应用启动失败（进程崩溃或端口被占）"
}
```

**流程**：
1. launcher 优先尝试 app.json 的建议 port
2. 被占则 `socket.bind(0)` 随机分配可用端口
3. 通过 `env["LAUNCHER_APP_PORT"]` 传给 app
4. `subprocess.Popen` 拉起进程
5. TCP 轮询端口监听（最多 6 秒）
6. 监听成功 → 返回 `actual_port`；超时 / 进程崩溃 → 返回 None

**前端用法**：

```javascript
fetch('/api/open?id=hello')
  .then(r => r.json())
  .then(data => {
    if (data.ok) {
      iframe.src = data.url;  // 嵌入 iframe
    }
  });
```

---

## GET /api/close

关闭应用进程树。流程：
1. `p.terminate()` 发 SIGTERM
2. 等 2 秒让子进程自行退出
3. 仍在运行 → `taskkill /F /T`（Windows）/ `killpg`（POSIX）强杀整棵进程树

**查询参数**：

- `id`: string — 应用 ID

**响应**：

```json
{ "ok": true }
```

**示例**：

```bash
curl "http://127.0.0.1:8000/api/close?id=hello"
```

---

## GET /api/launcher/version

对比 launcher 本地版本与远端版本，判断是否可升级。

**响应**：

```json
{
  "local": "1.0.2",
  "remote": "1.0.3",
  "upgradable": true,
  "changelog": "修复 X，新增 Y",
  "binary": true
}
```

**字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `local` | string | 本地版本号 |
| `remote` | string\|null | 远端最新版本号；连不上仓库则为 null |
| `upgradable` | bool | 本地 < 远端 时为 true |
| `changelog` | string | 远端版本的更新说明 |
| `binary` | bool | 是否为编译模式（影响更新流程） |

---

## GET /api/launcher/update

触发 launcher 自更新。流程区分开发模式 / 编译模式：

- **开发模式**：下载 `launcher-<ver>.zip` → 解压覆盖 `launcher.py` / `launcher/` 包 → 合并 `config.json` → 提示 reload
- **编译模式**：下载二进制 → 校验 sha256 → spawn `updater.bat`（Windows）/ `updater.sh`（Linux）→ 主进程退出 → 脚本替换 exe → 自动重启

**响应**：

```json
{
  "ok": true,
  "msg": "update scheduled",
  "restart": true
}
```

详见 [Self Update](Self-Update)。

---

## GET /stub

stub 占位页。无 cmd 的应用（如 file-demo）打开时返回此页。

**查询参数**：

- `id`: string — 应用 ID

**响应**：`text/html;charset=utf-8`，显示应用名 + 图标 + "无独立进程" 提示。
