# 🚀 快速开始

## 环境要求

| 项目 | 要求 |
|------|------|
| Python | ≥ 3.8（推荐 3.10+） |
| 第三方依赖 | **无**（纯标准库实现） |
| 操作系统 | Windows / Linux / macOS / ARM 嵌入式 |

> 树莓派 / Jetson 直接用系统自带 `python3` 即可。极小设备可用 `python3-minimal` + 手动补 `pip`。

---

## 启动 Launcher

### 1. 进入项目目录

```bash
cd web-launcher
```

### 2. 启动 launcher

```bash
python launcher.py
```

启动后控制台输出（开发模式）：

```
🚀 WebLauncher v1.0.2 已就绪
   地址: http://127.0.0.1:8000
```

### 3. 打开浏览器

Launcher 默认监听 `127.0.0.1:8000`，浏览器访问：

```
http://127.0.0.1:8000/
```

会看到桌面 UI：分页应用图标 + 底部 Dock 栏 + 顶部状态栏。

> 如果端口 8000 被占，可在 [config.json](../config.json) 的 `launcher.port` 改成其他端口。

---

## 第一次使用

### 打开应用

1. 在桌面找到应用图标（如 🛒 应用商店）
2. 单击图标 → launcher 拉起独立进程 → iframe 嵌入桌面
3. 应用在自己的端口上提供 HTTP 服务，launcher 已自动分配并探测就绪

### 安装新应用

1. 点击 🛒 应用商店图标
2. 浏览可安装应用列表
3. 点击应用卡片 → 查看详情（Changelog / 历史版本）
4. 点击「安装」→ launcher 下载 zip → sha256 校验 → 原子解压到 `apps/<group>/<id>/`
5. 桌面会自动刷新出现新图标

### 切换应用 / 最近任务

- **底部上滑手势**：呼出最近任务面板，卡片展示所有运行中的应用
- **卡片上滑**：单独清除一个应用
- **全部清除按钮**：关闭所有应用
- **点击卡片**：切回该应用

### 布局编辑

- 点击状态栏 🗂️ 布局编辑按钮
- 勾选每个应用是否在 Dock / 是否从桌面隐藏
- 保存后写入 [layout.json](../layout.json)，覆盖 app.json 的 `dock` 默认值

---

## 关闭与退出

### 关闭单个应用

- 在最近任务面板上滑卡片
- 或调用 API：`GET /api/close?id=<aid>`

关闭流程：
1. `p.terminate()` 发 SIGTERM
2. 等 2 秒让子进程自行退出
3. 仍在运行 → `taskkill /F /T /PID`（Windows）/ `os.killpg`（POSIX）强杀整棵进程树

### 退出 Launcher

- `Ctrl+C` 中断
- 或关闭终端窗口

Launcher 注册了 `atexit` 钩子，退出时会自动调用 `terminate_all()` 顺序关闭所有子进程，**不会留下孤儿进程**。

---

## 开发模式 vs 打包模式

### 开发模式（源码运行）

```bash
python launcher.py
```

- stdout 输出到控制台
- 配置文件、应用都在源码目录
- 自更新走 zip 覆盖路径

### 打包模式（PyInstaller exe）

详见 [Build Standalone EXE](Build-Standalone-EXE)。

```bash
# 打包
package.bat

# 运行（dist 目录下需要 apps/ 和 config.json）
cd dist
.\launcher.exe
```

- stdout 重定向到 `launcher.log`（UTF-8）
- `apps/` 和 `config.json` 不打包进 exe，放在 exe 同级目录
- 自更新走 `updater.bat` / `updater.sh` 替换脚本

---

## 下一步

- [应用开发指南](App-Development)：编写自己的第一个应用
- [HTTP API 文档](API-Reference)：通过 API 自动化操作
- [仓库服务器搭建](Repo-Server-Setup)：搭建自己的应用仓库
- [嵌入式部署](Embedded-Deployment)：部署到树莓派
