# HTTP API

launcher 默认监听 `127.0.0.1`，提供以下路由（均返回 JSON）。

## 路由表

| 路径 | 方法 | 说明 |
|------|------|------|
| `/api/apps` | GET | 列出全部应用 + 运行状态（含 `running: bool`） |
| `/api/layout` | GET | 读取用户布局（dock / hidden；未保存过 dock 为 null） |
| `/api/layout` | POST | 保存布局配置（原子写 layout.json + reload_apps） |
| `/api/repo` | GET | 拉取远端仓库索引（含可升级标记） |
| `/api/repo/config` | GET | 读取仓库 URL / BASIC 认证 / SSL 配置 |
| `/api/repo/config` | POST | 保存仓库配置（原子写 config.json + reload） |
| `/api/install?id=<aid>` | GET | 安装 / 升级应用到最新版本 |
| `/api/uninstall?id=<aid>` | GET | 卸载用户应用（受保护分组 system 拒绝） |
| `/api/open?id=<aid>` | GET | 启动应用进程 + 返回 iframe URL |
| `/api/close?id=<aid>` | GET | 关闭应用进程树（terminate → 2s → 强 kill） |
| `/api/launcher/version` | GET | launcher 本地 + 远端版本对比（是否可升级） |
| `/api/launcher/update` | GET | 触发 launcher 自更新流程 |
| `/stub?id=xxx` | GET | stub 占位页 |

## `running` 字段

`/api/apps` 返回的每个应用含 `running: bool`：

- `true` = 进程正在运行
- `false` = 未启动或已退出

> 当前只有二值 `running`，暂无多状态（starting / restarting / crashed），见路线图。

## `/api/repo` 应用条目

每个条目包含：

| 字段 | 说明 |
|------|------|
| `id` / `name` / `version` | 应用标识与版本 |
| `group` | 分组 |
| `system` | 是否系统应用（由本地 `apps/system` 目录决定） |
| `installed` | 是否已在本机安装 |
| `upgradable` | 是否有可升级的新版本 |
| `size` / `sha256` | 包大小与校验值 |
| `released` / `changelog` | 发布信息 |

## 下一步

- 自更新与部署、安全 → [07-自更新与部署](07-自更新与部署.md)