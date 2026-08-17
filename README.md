# 📱 Web Launcher

一个用 Python 标准库写的"手机桌面风格"应用启动器。
- 桌面 / Dock / 最近任务 / 多页滑动 / 上拉手势
- 每个应用是独立 Python HTTP 进程，被 iframe 嵌入到桌面里
- 内置应用商店，支持从远端仓库安装 / 升级 / 卸载
- 区分 **系统应用** 和 **用户应用** 两种类型

## 📁 目录结构

```
web-launcher/
├── launcher.py          # 启动器主程序（桌面 UI + HTTP API）
├── config.json          # 全局配置（端口、仓库地址、应用端口映射）
├── _index.json          # 远端仓库索引的本地缓存（首次发布后生成）
├── apps/
│   ├── publish.py       # 应用打包 + 上传脚本
│   ├── README.md        # 应用开发 / 发布指南
│   ├── system/          # 系统应用（默认安装，可更新，不可卸载）
│   │   ├── store/       # 应用商店（系统）
│   │   ├── todo/        # 待办清单（系统）
│   │   └── clock/       # 番茄钟（系统）
│   └── user/            # 用户应用（可安装 / 卸载）
│       ├── hello/       # 👋 你好世界（demo）
│       ├── calc/        # 🧮 计算器（demo）
│       ├── notes/       # 🗒️ 便签（demo）
│       └── weather/     # 🌤️ 天气（demo）
├── server/
│   └── 服务器端-部署.md  # 远端仓库（nginx）部署文档
└── doc/
    └── images/          # 文档图片
```

## 🚀 快速开始

```bash
python launcher.py
```
浏览器访问 `http://127.0.0.1:8000` 即可看到桌面。

启动后默认显示：
- 3 个系统应用（store / todo / clock）固定在 Dock
- 4 个用户 demo 应用在桌面图标区

## 🧩 应用类型

| 类型 | 目录 | 默认安装 | 接受更新 | 允许卸载 |
|------|------|----------|----------|----------|
| 系统应用 | `apps/system/<id>/` | ✅（启动时自动扫描注册） | ✅ | ❌ |
| 用户应用 | `apps/user/<id>/` | ❌（需从商店安装） | ✅ | ✅ |

系统应用随项目一起分发，启动时由 launcher 扫描 `apps/system/*/app.json` 自动注册。
用户应用通过应用商店从远端仓库拉取 zip 包并解压到 `apps/user/<id>/`。

> 注意：用户应用也可以直接放进 `apps/user/` 目录来"预装"（就像 demo 一样），
> launcher 同样会扫描到，只是从商店 UI 角度看它们就是"已安装"状态。

## 🛠️ 单个应用的结构

每个应用是一个目录，必须包含 `app.json` 清单和 `app.py` 入口：

```
apps/user/<id>/
├── app.json    # 清单：id、name、icon、port、cmd 等
├── app.py      # HTTP 服务（HTML 可内联）
└── README.md    # 应用介绍（推荐写）
```

`app.json` 示例：

```json
{
  "id": "hello",
  "name": "你好世界",
  "icon": "👋",
  "color": "#ff6b6b",
  "version": "1.0.0",
  "changelog": "最简单的 demo",
  "port": 8110,
  "cmd": ["apps/user/hello/app.py"],
  "dock": false,
  "system": false
}
```

| 字段 | 说明 |
|------|------|
| `id` | 全局唯一，卸载 / 升级 / 打开都用它 |
| `name` | 桌面图标下显示的名称 |
| `icon` | emoji 或字符（直接渲染） |
| `color` | 图标底色（CSS 颜色） |
| `version` | 语义化版本，比较升级用 |
| `changelog` | 更新说明，商店列表里展示 |
| `port` | 应用监听的端口 |
| `cmd` | 启动命令（相对项目根） |
| `dock` | `true` 显示在底部 Dock，`false` 在桌面图标区 |
| `system` | `true` 标记为系统应用（仅清单用，实际以目录位置为准） |

## 📡 Launcher HTTP API

| 路径 | 说明 |
|------|------|
| `GET /` | 桌面 HTML（单页） |
| `GET /api/apps` | 当前注册的所有应用（含运行状态） |
| `GET /api/repo` | 远端仓库索引（合并本地版本 / 是否可升级标记） |
| `GET /api/install?id=<id>` | 安装 / 升级应用 |
| `GET /api/uninstall?id=<id>` | 卸载应用（系统应用拒绝） |
| `GET /api/open?id=<id>` | 拉起应用进程，返回 `http://127.0.0.1:<port>` |
| `GET /api/close?id=<id>` | 关闭应用进程 |
| `GET /stub?id=<id>` | 无 `cmd` 的应用的占位 HTML |

## 📦 发布应用到远端仓库

详见 [apps/README.md](apps/README.md)。一行命令：

```bash
python apps/publish.py apps/user/hello
```

发布后远端 `index.json` 会更新，客户端打开"应用商店"刷新即可看到。

## 🌐 远端仓库部署

详见 [server/服务器端-部署.md](server/服务器端-部署.md)。
本质就是一个 nginx 静态站点，挂 `index.json` 和 `packages/*.zip`。

## ⚙️ 配置文件 `config.json`

```json
{
  "launcher": { "host": "127.0.0.1", "port": 8000, "title": "我的 Launcher" },
  "repo":     { "url": "https://...", "auth": null, "verify_ssl": false },
  "publish":  { "server": "user@host", "remote_path": "/var/www/repo", "packages_dir": "packages" },
  "ports":    { "store": 8100, "todo": 8101, "clock": 8102 }
}
```

`ports` 是可选的端口覆盖，应用可在自己的 `app.py` 里读取这个映射，
没有时回退到 `app.json` 里的 `port` 字段。

## 🧪 内置 demo 应用

| 应用 | 端口 | 演示场景 |
|------|------|----------|
| 👋 你好世界 | 8110 | 最简交互（计数器 + 时钟） |
| 🧮 计算器 | 8111 | 复杂前端 UI + 表达式求值 |
| 🗒️ 便签 | 8112 | `localStorage` 持久化 |
| 🌤️ 天气 | 8113 | 多视图切换 + mock 数据 + JSON API |

## 📝 设计要点

- **零依赖**：launcher 和所有应用只用 Python 标准库
- **进程隔离**：每个应用独立子进程，崩溃不影响 launcher
- **iframe 嵌入**：应用只需要返回 HTML，不用关心桌面外壳
- **文件系统即清单**：扫描 `apps/system/*` 和 `apps/user/*` 即注册，无需数据库
