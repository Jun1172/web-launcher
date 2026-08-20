# 📦 自更新机制

Launcher 支持两种自更新模式：**源码模式**（开发态）和**编译模式**（PyInstaller exe）。两种模式都通过 `/api/launcher/update` 触发，由 [app_operations.py#do_launcher_update](../launcher/app_operations.py) 自动判断分支。

---

## 双模式架构

```
GET /api/launcher/update
        │
        ▼
do_launcher_update()
        │
        ├── getattr(sys, "frozen", False) == False → 源码模式
        │   ├── 下载 launcher-<ver>.zip
        │   ├── 校验 sha256
        │   ├── 解压覆盖 launcher.py / launcher/ / apps/system/
        │   ├── 合并 config.json（保留本地 repo.auth / publish）
        │   └── 提示 reload（不自动重启）
        │
        └── getattr(sys, "frozen", False) == True → 编译模式
            ├── 下载二进制 launcher-<ver>.exe
            ├── 校验 sha256
            ├── spawn updater.bat / updater.sh（后台）
            └── 主进程退出 → 脚本替换 exe → 自动重启
```

---

## 源码模式

适用于：开发态（`python launcher.py`）或解包后的源码部署。

### 流程

1. 从仓库下载 `launcher-<ver>.zip`
2. 校验 sha256（与 `index.json` 的 `launcher.sha256` 比对）
3. 解压覆盖以下文件：
   - `launcher.py`
   - `launcher/` 包目录
   - `apps/system/` 下所有系统应用
4. 合并 config.json：
   - 用 zip 包内的 `config.json`（已脱敏，去掉 publish/auth）
   - 保留本地 config.json 的 `repo.auth` / `publish` 节
5. reload_apps() 刷新注册表
6. 返回 `restart: false`（开发模式不重启进程）

### 关键点

- 不自动重启：开发态改完代码可以立即生效（通过 reload），不需要杀进程
- config.json 合并：避免本地 BASIC 认证 / 发布配置被覆盖丢失
- 系统应用一起更新：launcher 主更新包里打包了所有 `group=system` 的应用源码

### 配置发布

修改 [config.json](../config.json) 的 `launcher.version` 后发布：

```bash
# 1. 改 config.json 的 launcher.version（如 1.0.3）
# 2. 发布
python publish.py --launcher --changelog "修复 X，新增 Y"
```

详见 [Repo Server Setup#发布-launcher-自身更新](Repo-Server-Setup#发布-launcher-自身更新)。

---

## 编译模式

适用于：PyInstaller 打包后的 `launcher.exe`。

### Windows 流程

```
1. 下载 launcher-<ver>.exe → launcher.new
2. 校验 sha256
3. 生成 updater.bat：
   ┌──────────────────────────────────────┐
   │ @echo off                            │
   │ :wait_loop                           │
   │   tasklist ... | find launcher.exe   │
   │   if 还在运行 → timeout 1 → goto loop│
   │ timeout 2  (等待文件系统释放)        │
   │ del launcher.exe                     │
   │ move launcher.new launcher.exe      │
   │ del updater.bat (自杀)               │
   │ start launcher.exe (重启)            │
   └──────────────────────────────────────┘
4. subprocess.Popen(["cmd", "/c", updater.bat],
                   creationflags=DETACHED_PROCESS)
5. 主进程退出
6. updater.bat 接管：等进程退出 → 替换 → 重启
```

### Linux 流程

```
1. 下载 launcher-<ver> → launcher.new
2. 校验 sha256
3. 生成 updater.sh：
   ┌──────────────────────────────────────┐
   │ #!/bin/bash                           │
   │ while kill -0 "$PPID" 2>/dev/null; do │
   │   sleep 1                             │
   │ done                                  │
   │ sleep 2                               │
   │ rm -f launcher                        │
   │ mv launcher.new launcher              │
   │ chmod +x launcher                     │
   │ rm -f updater.sh (自杀)               │
   │ exec launcher (重启)                  │
   └──────────────────────────────────────┘
4. subprocess.Popen(["nohup", updater.sh],
                   stdout=DEVNULL, stderr=DEVNULL,
                   start_new_session=True)
5. 主进程退出
6. updater.sh 接管：等父进程退出 → 替换 → 重启
```

### 关键点

- **Windows 锁文件问题**：`.exe` 在运行时被锁定，不能直接覆盖。所以需要先退出主进程再替换
- **后台脚本**：`DETACHED_PROCESS`（Windows）/ `nohup`（Linux）让脚本独立于主进程
- **轮询等待**：脚本不断检查主进程是否退出，避免主进程还没释放就尝试替换
- **自杀清理**：替换完成后脚本删除自身，不留下垃圾

### 关键代码

[updater.py#launch_self_update](../launcher/updater.py)：

```python
def launch_self_update(binary_url: str) -> tuple[bool, str]:
    exe_dir = get_exe_dir()
    current_exe = get_current_exe()
    new_exe = exe_dir / "launcher.new"

    # 1. 下载新二进制
    ok, msg = download_binary(binary_url, new_exe)
    if not ok:
        return False, msg

    # 2. 生成 updater 脚本
    is_windows = os.name == "nt"
    if is_windows:
        script_path = _write_windows_updater(current_exe, new_exe)
    else:
        script_path = _write_linux_updater(current_exe, new_exe)

    # 3. 后台 spawn updater 脚本
    if is_windows:
        DETACHED_PROCESS = 0x00000008
        subprocess.Popen(
            ["cmd", "/c", str(script_path)],
            creationflags=DETACHED_PROCESS,
            cwd=str(exe_dir),
        )
    else:
        subprocess.Popen(
            ["nohup", str(script_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(exe_dir),
            start_new_session=True,
        )
    return True, "update scheduled"
```

---

## 触发更新

### 通过 UI 触发

1. 桌面状态栏右上角 ⚙️ 关于按钮（带版本号 `v1.0.2` 胶囊）
2. 有新版本时红点闪烁
3. 点击「立即检查更新」→ 显示本地 vs 远端版本对比
4. 点击「立即更新」→ `GET /api/launcher/update`
5. 编译模式下主进程会退出，updater 脚本接管替换并重启

### 通过 API 触发

```bash
# 检查版本
curl http://127.0.0.1:8000/api/launcher/version
# → {"local":"1.0.2","remote":"1.0.3","upgradable":true,"changelog":"..."}

# 触发更新
curl http://127.0.0.1:8000/api/launcher/update
# → {"ok":true,"msg":"update scheduled","restart":true}
```

### 独立更新工具（外部触发）

当 launcher 进程已退出或无法通过 UI 触发更新时，可用 `launcher_updater.py` 独立检查 / 更新：

```bash
# 检查版本
python launcher_updater.py check --base .

# 更新（自动通知 launcher 优雅退出 → 替换 → 重启）
python launcher_updater.py update --base . --stop --restart

# 强制更新（不通知，强杀占用端口的进程，慎用）
python launcher_updater.py update --base . --force --stop --restart
```

> 注：当前 `launcher_updater.py` 仅完整支持源码模式更新；编译模式（PyInstaller）的 `update_binary()` 是 TODO。

---

## 发布 Launcher 更新

详见 [Repo Server Setup#发布-launcher-自身更新](Repo-Server-Setup#发布-launcher-自身更新)。

### 源码模式发布

```bash
# 1. 改 config.json 的 launcher.version
# 2. 发布
python publish.py --launcher --changelog "修复 X，新增 Y"
```

打包出来的 `launcher-<ver>.zip` 包含：
- `launcher.py` + `launcher/` 包目录
- 脱敏后的 config.json（去掉 publish/repo.auth）
- 所有 group=system 的应用源码

### 编译模式发布（含二进制）

```bash
python publish.py --launcher --build --changelog "..."
```

`--build` 会调用 PyInstaller 编译出 `launcher-<ver>.exe`，并上传到仓库的 `packages/` 目录。index.json 的 launcher 条目会多出 `binary` / `binary_sha256` / `binary_size` 字段：

```json
{
  "launcher": {
    "version": "1.0.3",
    "pkg": "packages/launcher-1.0.3.zip",
    "binary": "packages/launcher-1.0.3.exe",
    "binary_sha256": "...",
    "binary_size": 8388608
  }
}
```

客户端的 `do_launcher_update()` 会根据 `getattr(sys, "frozen", False)` 判断走哪种流程。

---

## 安全注意事项

- **sha256 校验**：所有更新包下载后必须校验 sha256 与 index.json 中记录的一致
- **原子替换**：编译模式 updater 脚本先下载到 `launcher.new`，确认主进程退出后才 `move` 替换
- **config.json 脱敏**：源码模式更新包里的 config.json 去掉了 `publish` 节和 `repo.auth`，避免 SSH 服务器地址和 BASIC 认证凭据泄露
- **HTTPS 建议**：仓库服务器建议上 HTTPS，避免下载过程被中间人篡改

---

## 失败场景与处理

| 场景 | 表现 | 处理 |
|------|------|------|
| 下载失败 | `{"ok":false,"msg":"download failed: ..."}` | 检查网络 / 仓库 URL |
| sha256 校验失败 | `{"ok":false,"msg":"sha256 mismatch"}` | 仓库 index.json 与实际包不一致，重新发布 |
| Windows exe 被锁 | updater.bat 轮询等待 | 等 launcher 主进程退出后自动替换 |
| updater.bat 失败 | exe 没重启 | 手动运行 `updater.bat`，或检查 launcher.log |
| 中途中断 | `launcher.new` 残留 | 下次启动时 launcher 忽略 `.new` 文件 |
