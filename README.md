# WebLauncher

WebLauncher 是一个面向 Windows、Linux 和嵌入式设备的本地应用运行时与应用仓库客户端。它负责扫描、安装、升级和启动多语言应用，并提供桌面 UI、应用商店、依赖管理、运行时自动部署和 Launcher 自更新。

## 项目结构

```text
web-launcher/
├── launcher.py              # 程序入口
├── launcher/                # Launcher 核心包
│   ├── __main__.py          # HTTP 服务、pywebview 窗口、启动流程
│   ├── config.py            # 配置、路径、日志和版本工具
│   ├── app_registry.py      # app.json 扫描、分组、图标发现
│   ├── process_manager.py   # 进程启动、端口探测、进程树清理
│   ├── app_operations.py    # 应用安装、卸载、Launcher OTA
│   ├── deps_installer.py    # wheels → 应用 site/ 依赖安装
│   ├── runtime_bootstrap.py # runtime/wheels 自动下载和自愈
│   ├── repo.py              # Repo HTTP 客户端
│   ├── zipio.py             # 安全校验和原子解压
│   ├── http_handler.py      # HTTP API 路由
│   ├── frontend.py          # 桌面首页模板渲染
│   ├── layout.py            # 用户布局配置
│   ├── updater.py           # exe 自更新替换脚本
│   ├── window_win32.py      # Windows 无边框窗口
│   └── templates/           # 四种布局和六种主题
├── apps/system/             # 随 Launcher 发布的系统应用
├── apps/user/               # 主仓库中的用户示例应用
├── tools/                   # 构建、运行时、依赖和工具箱脚本
├── publish.py               # 应用和 Launcher 发布工具
├── config.json              # 本地运行和 Repo 配置
└── launcher.spec            # PyInstaller 构建配置
```

业务应用源码位于独立仓库 `web-launcher-apps`，包括 game、general、ros 等分组。

## 快速开始

```powershell
# 在仓库根目录运行
python launcher.py
```

默认浏览器地址：

```text
http://127.0.0.1:8000/
```

局域网访问时，将 `config.json` 中的 `launcher.host` 设置为 `0.0.0.0`，然后用主机实际局域网 IP 访问，例如：

```text
http://192.168.1.101:8000/
```

`0.0.0.0` 只能用于监听，不能直接填进浏览器地址栏。

手机和电脑不在同一局域网、或 Windows 防火墙未放行 8000 端口时，手机无法访问。

## 核心功能

### 应用管理

- 递归扫描 `apps/**/app.json`
- `group` 决定应用分组，`system` 分组不可卸载
- 安装、升级、卸载应用
- 应用 zip sha256 校验和安全解压
- 启动时分配可用端口，支持端口就绪探测
- Windows 使用 `taskkill /F /T` 清理整棵进程树
- 应用日志写入应用目录的 `data/app-output.log`

### 运行时和依赖

Launcher 按以下顺序选择 Python：

```text
应用自带 runtime/<平台>/
    ↓
全局 runtime/<平台>/
    ↓
系统 Python
```

首次启动会自动下载：

```text
runtime.zip
wheels-<平台>.zip
```

依赖安装流程：

```text
应用 app.json 的 deps
    ↓
本地 wheels/<平台>/
    ↓
Repo 的 /wheels/<平台>/
    ↓
公网 pip 镜像
    ↓
apps/<group>/<id>/site/
```

Launcher 还会后台巡检依赖。应用启动前如果发现 `site/` 缺少依赖，会自动补装，不需要用户执行 pip。

### standalone 应用

```json
{
  "standalone": true
}
```

发布时会把 Python runtime 放进应用包：

```text
apps/<group>/<id>/runtime/win-x64/
```

适合需要独立 Python 版本或隔离运行时的应用。

### 应用图标

Launcher 按以下顺序查找图标：

```text
1. app.json 的 icon_file
2. icon.png
3. icon.svg
4. icon.webp
5. icon.jpg / icon.jpeg
```

图片成功加载时优先显示图片；不存在、路径不安全或加载失败时回退到 `app.json` 的 `icon` Emoji；两者都没有时显示 `📦`。

示例：

```text
apps/user/my-app/
├── app.json
├── icon.svg
└── app.py
```

图片随 App 一起发布，不需要单独上传。

### 桌面 UI

当前提供四种布局：

- 九宫格
- 列表式
- 侧边栏
- 磁贴

当前提供六种主题：

- 深空靛蓝
- 深空青
- 暖沙米白
- 薄荷浅青
- 晨雾浅灰
- 暗夜紫

桌面支持分页、Dock、最近任务、布局隐藏、手机端适配和响应式状态栏。

## app.json 示例

```json
{
  "id": "my-app",
  "name": "我的应用",
  "version": "1.0.0",
  "icon": "📦",
  "icon_file": "icon.svg",
  "color": "#3b82f6",
  "cmd": ["apps/user/my-app/app.py"],
  "port": 8120,
  "group": "user",
  "deps": ["requests"],
  "dock": false,
  "standalone": false
}
```

常用字段：

| 字段 | 用途 |
|---|---|
| `id` | 应用唯一 ID |
| `name` | 显示名称 |
| `version` | 应用版本 |
| `author` | 作者/维护人（商店展示与搜索；多人协作时便于找到负责人） |
| `cmd` | 启动命令 |
| `port` | 建议端口，Launcher 会自动处理冲突 |
| `group` | 应用分组 |
| `icon` | 图片图标失败时的 Emoji 回退 |
| `icon_file` | App 目录内的图片图标 |
| `deps` | Python 第三方依赖 |
| `standalone` | 是否将 runtime 打进应用包 |
| `protect` | 是否以 pyc 形式发布源码 |
| `dock` | 是否默认放入 Dock |
| `exclude` | 发布时额外排除的目录或文件名 |

## 发布应用

```powershell
# 列出应用
python publish.py --list

# 发布单个应用
python publish.py apps/user/hello

# 发布全部应用
python publish.py --all

# 发布指定分组
python publish.py --group etws

# 只打包，不上传
python publish.py apps/user/hello --dry-run
```

发布器会自动：

- 打包 App 目录中的代码、图片和资源
- 收集 App 引用的 `apps/` 本地公共模块
- 按 `deps` 下载并上传 wheels
- 按 `standalone` 打包 runtime
- 按 `protect` 编译 pyc
- 更新 Repo 的 `index.json`

## 发布 Launcher

```powershell
# 发布 zip、runtime、wheels
python publish.py --launcher --changelog "更新说明"

# 构建并上传 launcher.exe
python publish.py --launcher --build --changelog "更新说明"

# 自动递增 patch 版本并同步 released/changelog
python publish.py --launcher --build --auto-version --changelog "更新说明"

# 构建测试但不上传
python publish.py --launcher --build --dry-run
```

`--auto-version` 会将例如 `1.1.2` 自动递增到 `1.1.3`，并同步更新：

```text
config.json 的 launcher.version
config.json 的 launcher.released
config.json 的 launcher.changelog
Repo index.json 的 launcher 节点
launcher-<version>.zip
launcher-<version>.exe
```

Repo 结构：

```text
/var/www/repo/
├── index.json
├── packages/
│   ├── <app>-<version>.zip
│   ├── launcher-<version>.zip
│   └── launcher-<version>.exe
├── runtime.zip
├── wheels-<platform>.zip
└── wheels/<platform>/*.whl
```

源码版 Launcher 使用 zip OTA；打包版 Launcher 使用 Repo 中的 binary OTA。更新完成后会清理旧 `config.json` 和 `updater.bat`，新版本重新释放配置。

## 工具

```powershell
python tools/toolbox.py       # 打开工具箱
python tools/package.py       # PyInstaller 构建 Launcher
python tools/make_runtime.py  # 重建 Windows runtime
python tools/make_wheels.py   # 重建本地 wheels
python tools/bootstrap.py     # 重建 runtime + wheels
python tools/make_icons.py    # 批量生成应用图标
python tools/kill.py          # 清理卡住的开发进程
```

## 其他说明

- 源码运行需要 Python 3.10 或更高版本。
- 桌面窗口模式需要 pywebview 和 WebView2；缺少时自动回退纯 HTTP。
- `runtime/`、`wheels/`、`dist/`、构建缓存和日志不属于源码提交内容。
- 局域网部署建议使用反向代理或其他鉴权机制，当前 API 默认无用户认证。

## License

MIT
