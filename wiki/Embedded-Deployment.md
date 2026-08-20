# 🍓 嵌入式部署

Launcher 适合部署到嵌入式主板（树莓派、Jetson、工控机、边缘设备），因为它具备以下特性：

- **纯 Python 标准库**：无第三方依赖，部署到 ARM 设备不用装 pip 包
- **无架构依赖**：launcher 本身是 Python 代码，不区分 x86/ARM
- **进程隔离**：C/C++ 子进程崩溃不影响 launcher
- **低开销常驻**：launcher 单进程常驻约 30-50MB 内存，CPU 几乎为 0
- **远程更新**：通过 HTTP 仓库 + OTA 实现远程升级

---

## 目标平台

| 平台 | 支持度 | 说明 |
|------|--------|------|
| 树莓派 3B+ / 4 / 5 (ARMv7/ARM64, 1GB+ RAM) | ✅ 完美 | 推荐 Python 3.10+，系统自带 python3 |
| 树莓派 Zero 2W (ARM64, 512MB RAM) | ⚠️ 受限 | 仅 launcher + 1-2 个 app 可跑；多开会 swap |
| 树莓 Pi Zero (ARMv6, 512MB RAM) | ⚠️ 受限 | 性能弱，仅适合做 launcher host，少开 app |
| Jetson Nano / NX | ✅ 完美 | ARM64 + 4GB+ RAM |
| 工控机 (x86 Linux) | ✅ 完美 | 标准环境 |
| Windows CE / RT | ❌ 不支持 | 依赖 `subprocess.CREATE_NO_WINDOW`，CE 不支持 |
| Linux musl (Alpine 等) | ✅ 可用 | POSIX 信号可用，`CTRL_BREAK_EVENT` 不可用 |

---

## 资源占用

### Launcher 本身（常驻进程）

| 指标 | 数值 |
|------|------|
| 内存 | ~30-50MB（Python 解释器 + 业务代码） |
| CPU（空闲时） | 几乎为 0（只在 poll 端口） |
| 包体积（PyInstaller onefile） | ~8MB |

### App 进程（每个独立子进程）

每个 app 启动后是一个独立的 OS 进程，有自己的 Python 解释器：

| 类型 | 内存 |
|------|------|
| Python HTTP app 进程 | ~15-30MB |
| C/C++ app 进程 | ~2-10MB（取决于程序大小） |

### 内存估算示例（树莓派 Zero 2W, 512MB RAM）

```
系统本身占用       ~100MB
Launcher 常驻       ~50MB
启动 3 个 Python app  +45-90MB
────────────────────────────
合计                195-240MB
剩余可用            272-317MB
```

> 多开几个 app 就会触发 swap，性能急剧下降。建议这类小内存设备：
> - 用 C/C++ 写 app（占用低）
> - 一次只开 1-2 个 app
> - 考虑未来引入 embedded 模式（app 作为同进程路由托管，0 额外进程开销）

---

## Python 环境准备

### 树莓派 / Jetson

用系统自带 `python3` 即可（通常是 Python 3.9+）：

```bash
python3 --version
# Python 3.9.x 或更高
```

无需 `pip install` 任何东西，launcher 只用标准库。

### 极小设备

如 OpenWrt、busybox 环境：

```bash
opkg install python3-minimal
opkg install python3-pip  # 可选
```

### 验证依赖

```bash
python3 -c "import http.server, subprocess, socket, json, zipfile; print('OK')"
```

---

## 部署步骤

### 1. 复制项目到目标设备

```bash
# 方式 A: scp 上传
scp -r web-launcher/ pi@raspberrypi.local:~/

# 方式 B: git clone
ssh pi@raspberrypi.local
git clone <your-repo-url> web-launcher
```

### 2. 启动 launcher

```bash
cd web-launcher
python3 launcher.py
```

### 3. 配置仓库地址

编辑 [config.json](../config.json) 的 `repo.url`，指向你自己的仓库：

```json
{
  "repo": {
    "url": "https://your-repo.example.com",
    "auth": null,
    "verify_ssl": false
  }
}
```

或通过 settings 应用 UI 配置。

### 4. 配置开机自启（systemd）

创建 `/etc/systemd/system/launcher.service`：

```ini
[Unit]
Description=Web Launcher
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/web-launcher
ExecStart=/usr/bin/python3 /home/pi/web-launcher/launcher.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable launcher
sudo systemctl start launcher

# 查看状态
sudo systemctl status launcher

# 查看日志
journalctl -u launcher -f
```

### 5. 应用预装

- `apps/system/` 全部预装到主板（出厂默认）
- `apps/user/` 由用户后续通过应用商店安装
- 仓库 URL 配置成自己的镜像（HTTPS + basic auth 可选）

---

## 跨架构注意事项

### Launcher 本身

- 纯 Python 代码，**无架构依赖**
- 同一份代码可跑在 x86 / ARM / ARM64 上
- 用 PyInstaller 打包时需在目标架构上打包（PyInstaller 不交叉编译）

### C/C++ 应用

C/C++ 应用需对应架构编译。建议用 zip 名后缀区分：

```
cpp-hello-1.0.0-win-x64.zip
cpp-hello-1.0.0-linux-x64.zip
cpp-hello-1.0.0-linux-arm64.zip   # 树莓派 3B+ / 4 / 5
cpp-hello-1.0.0-linux-armv7.zip   # 树莓派 2/3
```

建议静态链接（`-static`）避免运行时缺 DLL：

```bash
# ARM64 静态编译
aarch64-linux-gnu-g++ -static -o cpp-hello cpp-hello.cpp
```

详见 [App Development#部署-cc-应用](App-Development#🦾-部署-cc-应用)。

### Python 应用

Python 应用通常无架构依赖（除非用了 C 扩展，如 `psutil`、`numpy`）。

- `system-monitor` demo 用了 `psutil`，需 `pip install psutil`（或回退到原生 `wmic`/`proc`）
- 其他 demo 都是纯标准库，直接跑

---

## 跨平台差异

| 平台 | 子进程清理 | 信号 | 备注 |
|------|-----------|------|------|
| Linux | `os.killpg(pid, 9)`（进程组） | `SIGTERM` / `SIGKILL` 可用 | `start_new_session=True` 创建进程组 |
| macOS | 同 Linux | 同 Linux | 同 Linux |
| Windows | `taskkill /F /T /PID`（递归） | `CTRL_BREAK_EVENT` 可用 | `creationflags=CREATE_NO_WINDOW` 隐藏控制台 |
| Windows CE/RT | ❌ 不支持 | — | `CREATE_NO_WINDOW` 不可用 |
| Linux musl (Alpine) | `killpg` 可用 | `SIGTERM` 可用 | `CTRL_BREAK_EVENT` 不可用 |

---

## 远程管理建议

### 1. 配置 HTTPS 反向代理

默认 launcher 监听 `127.0.0.1:8000`，不对外暴露。如需远程管理：

```nginx
server {
    listen 443 ssl;
    server_name launcher.example.com;

    ssl_certificate /etc/letsencrypt/live/launcher.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/launcher.example.com/privkey.pem;

    # 基础认证
    auth_basic "Launcher";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 2. 通过 API 远程操作

```bash
# 列出应用
curl -u user:pass https://launcher.example.com/api/apps

# 远程启动应用
curl -u user:pass https://launcher.example.com/api/open?id=hello

# 远程关闭应用
curl -u user:pass https://launcher.example.com/api/close?id=hello

# 触发 launcher 自更新
curl -u user:pass https://launcher.example.com/api/launcher/update
```

### 3. 监控

通过 [sysinfo 应用](../apps/system/sysinfo) 可视化查看：
- CPU / 内存 / 磁盘占用
- 已安装应用列表
- Launcher 版本信息

通过 [system-monitor 应用](../apps/user/system-monitor) 实时监控：
- CPU / 内存折线图
- TOP 进程
- 网络流量

---

## 性能优化建议

### 小内存设备

- 用 C/C++ 写 app，进程占用低（2-10MB vs Python 15-30MB）
- 一次只开 1-2 个 app
- 关闭不用的 app（最近任务面板上滑）
- 用 `systemd` 限制 launcher 内存配额（路线图：cgroup 集成）

### 弱网络设备

- 仓库就近部署（同机房 / 内网）
- 包大小尽量小（C/C++ 用 `-Os` 优化体积）
- 启用 HTTP 缓存（`packages/` 已配 `max-age=31536000`）

### 多核设备

- launcher 单进程，CPU 几乎不占用
- 每个 app 独立进程，OS 自动调度到不同核心
- 无需特殊配置
