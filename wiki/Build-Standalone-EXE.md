# 🔨 打包可执行文件

Launcher 可以用 PyInstaller 打包成单文件 exe，便于分发到没有 Python 环境的机器。

---

## 打包命令

项目根目录已有 [package.bat](../package.bat)：

```batch
@echo off
pyinstaller -F -w -i .\doc\images\launcher.ico ^
    --add-data "launcher\templates;launcher\templates" ^
    --clean ^
    .\launcher.py

echo.
echo === 打包完成 ===
echo exe 位置: dist\launcher.exe
echo 运行前请把 apps\ 和 config.json 复制到 exe 同级目录
```

### 参数说明

| 参数 | 含义 |
|------|------|
| `-F` | 单文件（onefile）模式，所有依赖打包进一个 exe |
| `-w` | 无控制台（windowed）模式，运行时不显示黑窗口 |
| `-i .\doc\images\launcher.ico` | 指定图标 |
| `--add-data "launcher\templates;launcher\templates"` | 打包 templates 资源（分隔符 `;` 是 Windows，Linux/macOS 用 `:`） |
| `--clean` | 清理上次打包缓存 |
| `.\launcher.py` | 入口脚本 |

### 跨平台打包

- **Windows**：用 `package.bat`
- **Linux/macOS**：直接运行 `pyinstaller` 命令（注意 `--add-data` 分隔符是 `:`）

```bash
# Linux/macOS
pyinstaller -F -w -i ./doc/images/launcher.ico \
    --add-data "launcher/templates:launcher/templates" \
    --clean \
    ./launcher.py
```

---

## 3 个必崩点修复

PyInstaller `-w` 模式打包后，launcher 默认会启动失败。需要修复以下 3 个问题（已在代码中修复）：

### 问题 1：路径找不到（config.py）

**根因**：打包后 `__file__` 指向 PyInstaller 临时解压目录（`sys._MEIPASS`），找不到 `apps/` 和 `config.json`。

**修复**：[launcher/config.py](../launcher/config.py) 用 `sys.frozen` 判断是否为打包模式：

```python
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller 打包后：exe 所在目录 = 项目根
    BASE = Path(sys.executable).resolve().parent
else:
    # 开发模式：launcher/config.py 的 parent.parent = 项目根
    BASE = Path(__file__).resolve().parent.parent
```

### 问题 2：模板资源丢失（frontend.py）

**根因**：`templates/` 目录没打包进 exe，`Path(__file__).parent` 路径错。

**修复**：[launcher/frontend.py](../launcher/frontend.py) 用 `sys._MEIPASS` 读取打包资源：

```python
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller 打包后：资源解压到 sys._MEIPASS（临时目录）
    # 需在 package.bat 用 --add-data "launcher\templates;launcher\templates"
    _TEMPLATES_DIR = Path(sys._MEIPASS) / "launcher" / "templates"
else:
    _TEMPLATES_DIR = Path(__file__).parent / "templates"
```

配合 `--add-data "launcher\templates;launcher\templates"` 把 templates 打包进 exe。

### 问题 3：emoji 崩溃（__main__.py）

**根因**：`-w` 模式下 `sys.stdout` 是 `None` 或 GBK 编码，`print("🚀")` 直接 `UnicodeEncodeError` 崩溃。

**修复**：[launcher/__main__.py](../launcher/__main__.py) 在打包模式下重定向 stdout 到 UTF-8 日志文件：

```python
def _redirect_stdout_if_needed():
    if getattr(sys, "frozen", False):
        log_path = Path(sys.executable).parent / "launcher.log"
        sys.stdout = open(log_path, "a", encoding="utf-8")
        sys.stderr = sys.stdout
```

并在 [app_registry.py](../launcher/app_registry.py) 用 `_safe_print` 替换裸 `print`：

```python
def _safe_print(msg):
    """安全 print：处理 PyInstaller -w 模式下 stdout=None 和 GBK 编码无法输出 emoji 的问题。"""
    try:
        print(msg)
    except (UnicodeEncodeError, AttributeError, ValueError):
        pass
```

---

## 部署步骤

### 1. 打包

```bash
cd web-launcher
.\package.bat
```

产物：`dist/launcher.exe`（约 8-10MB）

### 2. 复制运行时数据

`apps/` 和 `config.json` 是用户数据，**不打包进 exe**，必须放在 exe 同级目录：

```bash
cd dist
# 复制 apps 目录
xcopy ..\apps apps\ /E /I /Y
# 复制 config.json
copy ..\config.json
```

或用 PowerShell：

```powershell
cd dist
if (-not (Test-Path apps)) { Copy-Item ..\apps -Recurse -Force }
Copy-Item ..\config.json -Force
```

### 3. 目录结构

打包后的部署目录：

```
my-launcher-deploy/
├── launcher.exe           # 打包产物（含 Python 解释器 + 业务代码 + templates）
├── apps/                  # 用户数据（运行时扫描）
│   ├── system/
│   │   ├── store/
│   │   ├── todo/
│   │   └── ...
│   └── user/
│       ├── hello/
│       └── ...
├── config.json            # 用户配置（launcher 节/repo 节/publish 节）
└── launcher.log           # 运行日志（打包模式自动生成）
```

### 4. 启动

```bash
# 双击 launcher.exe
# 或命令行启动
.\launcher.exe
```

启动成功后：
- launcher.log 自动生成（UTF-8）
- HTTP 监听 config.json 配置的端口（默认 8000）

### 5. 验证

```bash
# 测试 HTTP 响应
curl http://127.0.0.1:8000/api/apps
# 应返回 JSON 应用列表
```

---

## 打包模式与开发模式差异

| 维度 | 开发模式 (`python launcher.py`) | 打包模式 (`launcher.exe`) |
|------|--------------------------------|--------------------------|
| stdout | 控制台输出（UTF-8） | 重定向到 `launcher.log`（UTF-8） |
| BASE 路径 | `Path(__file__).parent.parent` | `Path(sys.executable).parent` |
| templates | `Path(__file__).parent/templates` | `sys._MEIPASS/launcher/templates` |
| 自更新 | zip 覆盖源码 + reload | 二进制替换 + bat/sh 脚本重启 |
| apps/config.json | 在源码目录 | 在 exe 同级目录 |

判断逻辑：`getattr(sys, "frozen", False)` 为 `True` 即打包模式。

---

## 调试打包后的问题

### 启动失败排查

1. **查看 launcher.log**：exe 同级目录的 `launcher.log` 记录了启动信息和报错
2. **从命令行启动**：不要双击，用 `cmd` 或 PowerShell 启动，能立即看到错误：
   ```bash
   .\launcher.exe
   # 如果立即退出，命令行会显示错误
   ```
3. **检查 apps/ 和 config.json 是否在 exe 同级目录**

### 常见错误

| 症状 | 原因 | 解决 |
|------|------|------|
| 双击没反应 | stdout 崩溃（emoji） | 已修复，确认 __main__.py 重定向生效 |
| 找不到 config.json | BASE 路径错 | 确认 config.py 用 `sys.frozen` 检测 |
| 找不到 templates | 没打包资源 | 确认 `--add-data` 参数正确 |
| 找不到 apps 目录 | 没复制 apps 到 dist | 手动复制 `apps/` 到 exe 同级 |
| 端口被占 | config.json 配置的端口被占 | 改 `launcher.port` 或杀占用进程 |

### 临时切换为有控制台模式（调试用）

如果需要看实时输出，去掉 `-w` 参数重新打包：

```bash
pyinstaller -F -i .\doc\images\launcher.ico ^
    --add-data "launcher\templates;launcher\templates" ^
    --clean ^
    .\launcher.py
```

这样会有黑窗口显示 stdout，便于调试。

---

## 与源码模式的对比

| 场景 | 推荐模式 |
|------|---------|
| 个人开发机 | 源码模式（便于调试、改代码） |
| 部署到生产 / 客户机器 | 打包模式（不需要装 Python） |
| 嵌入式设备（已装 Python） | 源码模式（占用更小） |
| 嵌入式设备（无 Python） | 打包模式（带 Python 解释器） |
| 分发给非技术用户 | 打包模式（双击即可） |

---

## 发布打包版到仓库

打包后可以发布到仓库供 OTA 更新：

```bash
# 打包并发布（含二进制）
python publish.py --launcher --build --changelog "修复 X，新增 Y"
```

`--build` 会：
1. 调用 PyInstaller 编译出 `launcher-<ver>.exe`
2. 复制到 `packages/` 目录
3. 上传到仓库
4. index.json 的 launcher 条目会多出 `binary` / `binary_sha256` / `binary_size` 字段

客户端的 `do_launcher_update()` 会根据 `getattr(sys, "frozen", False)` 判断走编译模式更新流程（下载二进制 → updater.bat/sh 替换）。

详见 [Self Update#编译模式](Self-Update#编译模式) 和 [Repo Server Setup#发布-launcher-自身更新](Repo-Server-Setup#发布-launcher-自身更新)。
