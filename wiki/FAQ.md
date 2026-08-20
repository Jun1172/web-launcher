# ❓ 常见问题

## 安装与启动

### Q1: 启动 launcher 报错 `Address already in use`

**原因**：`config.json` 配置的端口（默认 8000）被其他程序占用。

**解决**：
1. 改 [config.json](../config.json) 的 `launcher.port` 为其他端口（如 8080）
2. 或杀掉占用端口的进程：
   ```bash
   # Windows
   netstat -ano | findstr :8000
   taskkill /PID <PID> /F

   # Linux
   lsof -i :8000
   kill -9 <PID>
   ```

---

### Q2: 打包后的 launcher.exe 双击没反应

**原因**：PyInstaller `-w` 模式下 stdout 是 None 或 GBK 编码，emoji 会导致 `UnicodeEncodeError` 崩溃。

**解决**：已在代码中修复（3 个必崩点）。详见 [Build Standalone EXE#3-个必崩点修复](Build-Standalone-EXE#3-个必崩点修复)。

**临时排查**：从命令行启动 exe，能立即看到错误：
```bash
.\launcher.exe
```

---

### Q3: 打包后找不到 apps 或 config.json

**原因**：打包模式下 BASE 路径错。

**解决**：
- 确认 [launcher/config.py](../launcher/config.py) 用 `sys.frozen` 检测打包模式
- 把 `apps/` 目录和 `config.json` 复制到 exe 同级目录

详见 [Build Standalone EXE#部署步骤](Build-Standalone-EXE#部署步骤)。

---

### Q4: 启动后浏览器没自动打开

**原因**：launcher 不会自动打开浏览器，需要手动访问。

**解决**：浏览器打开 `http://127.0.0.1:8000/`（或 [config.json](../config.json) 配置的端口）。

---

## 应用管理

### Q5: 打开应用显示「应用启动失败（进程崩溃或端口被占）」

**原因**：
1. app.py 启动时崩溃（代码错误）
2. 端口探测 6 秒超时（app 启动慢）
3. 端口被其他程序占用且 launcher 随机分配也失败（罕见）

**排查**：
1. 查看 launcher.log（打包模式）或控制台输出（开发模式）
2. 手动启动 app 测试：
   ```bash
   $env:LAUNCHER_APP_PORT = "8110"
   python apps/user/hello/app.py
   ```
3. 浏览器直接访问 `http://127.0.0.1:<actual_port>/`

**解决**：根据 app 的报错修复代码。

---

### Q6: 应用图标显示 ⚠️ 端口冲突角标

**原因**：多个 app.json 写了同一个 `port` 字段。

**说明**：launcher 已自动处理冲突——启动时如果建议端口被占，会分配随机可用端口，**不杀已有进程**，让冲突的 app 共存。⚠️ 角标只是提示。

**解决**：如需消除角标，编辑各 app.json 给不同端口。

---

### Q7: 卸载应用提示「受保护分组，禁止卸载」

**原因**：该应用在 [app_operations.py](../launcher/app_operations.py) 的 `PROTECTED_GROUPS` 集合（当前只有 `"system"`）。

**解决**：系统应用（apps/system/）不可卸载，这是设计如此。如需自定义不可卸载分组，把分组名加到 `PROTECTED_GROUPS`：

```python
PROTECTED_GROUPS = {"system", "admin", "dev"}
```

---

### Q8: 关闭应用后进程还在跑

**原因**：C/C++ 子进程可能成为孤儿。

**说明**：launcher 用 `taskkill /F /T`（Windows）或 `killpg`（Linux）递归杀整棵进程树，应该不会留孤儿。如果还有残留：

**排查**：
1. 确认 app 的启动方式（是否用了 `subprocess.Popen` 包装）
2. 确认 [process_manager.py](../launcher/process_manager.py) 的 `close_app` 流程生效

**临时清理**：
```bash
# Windows
tasklist | findstr <process_name>
taskkill /F /IM <process_name>

# Linux
pkill -f <process_name>
```

---

## 仓库与更新

### Q9: 应用商店显示「连不上仓库」

**原因**：[config.json](../config.json) 的 `repo.url` 配置错或仓库服务器没启动。

**排查**：
1. 检查 `repo.url` 是否正确
2. 手动 curl 测试：
   ```bash
   curl -k https://your-repo-url/index.json
   ```
3. 自签名证书需设置 `verify_ssl: false`

**解决**：详见 [Repo Server Setup](Repo-Server-Setup) 搭建仓库。

---

### Q10: Launcher 自更新后无法启动

**原因**：编译模式下 updater 脚本失败，exe 没正确替换。

**排查**：
1. 检查 exe 同级目录是否有 `updater.bat` / `updater.sh` 残留
2. 检查 `launcher.new` 是否存在（说明下载成功但替换失败）
3. 手动运行 `updater.bat` 看报错

**解决**：
1. 关闭所有 launcher 进程
2. 手动重命名 `launcher.new` → `launcher.exe`
3. 删除 `updater.bat`

详见 [Self Update#失败场景与处理](Self-Update#失败场景与处理)。

---

### Q11: 安装应用报「sha256 mismatch」

**原因**：仓库 `index.json` 记录的 sha256 与实际下载的包不一致。

**原因可能是**：
1. 上传 zip 后没更新 index.json
2. 上传过程中文件损坏
3. 仓库 index.json 被手工编辑过

**解决**：重新发布该应用：
```bash
python publish.py apps/user/hello
```

详见 [Repo Server Setup#发布流程详解](Repo-Server-Setup#发布流程详解)。

---

## 开发与调试

### Q12: 修改了 app.json 但不生效

**原因**：launcher 内存中的 REGISTRY 没刷新。

**解决**：
1. 在桌面布局编辑面板保存一次（会触发 `reload_apps()`）
2. 或重启 launcher

---

### Q13: 改了 app.py 的端口没生效

**原因**：app.py 的端口应该从环境变量读取，而不是硬编码。

**正确写法**：
```python
import os
PORT = int(os.environ.get("LAUNCHER_APP_PORT", 0))
```

**错误写法**：
```python
PORT = 8110  # ❌ 硬编码，launcher 分配的端口不会生效
```

详见 [App Development#编写应用代码](App-Development#4-编写应用代码关键从环境变量读端口)。

---

### Q14: 怎么调试 app 进程

**方法 1**：手动启动 app 看报错

```bash
# PowerShell
$env:LAUNCHER_APP_PORT = "8110"
python apps/user/hello/app.py

# bash
LAUNCHER_APP_PORT=8110 python apps/user/hello/app.py
```

**方法 2**：绕开 launcher 直接访问 app 端口

```bash
# 先通过 /api/open?id=hello 拿到 actual_port
curl http://127.0.0.1:8000/api/open?id=hello
# → {"ok":true,"url":"http://127.0.0.1:51234"}

# 直接访问
curl http://127.0.0.1:51234/
```

**方法 3**：浏览器直接打开 app URL，绕开 iframe

---

### Q15: 如何在多个 app 之间通信

**当前**：launcher 没有提供 app 间 IPC 机制。app 之间只能：
1. 通过 HTTP 互调（如果允许）
2. 通过共享文件
3. 通过环境变量传递只读配置

**路线图**：应用间 IPC 总线（发现 + 调用）。

---

## 嵌入式部署

### Q16: 树莓派上启动报 `ModuleNotFoundError`

**原因**：用了第三方库（如 `psutil`）。

**解决**：
- `system-monitor` 用了 `psutil`：`pip3 install psutil`
- 或接受回退到原生 `wmic`/`proc`（功能受限）

详见 [Embedded Deployment#python-环境准备](Embedded-Deployment#python-环境准备)。

---

### Q17: C++ 应用在树莓派上跑不了

**原因**：C++ 二进制需对应架构编译。x86 编译的不能跑在 ARM 上。

**解决**：
1. 在目标架构上编译（或交叉编译）：
   ```bash
   # ARM64 交叉编译
   aarch64-linux-gnu-g++ -static -o cpp-hello cpp-hello.cpp
   ```
2. 建议静态链接（`-static`）避免运行时缺 DLL
3. 用 zip 名后缀区分架构：`cpp-hello-1.0.0-linux-arm64.zip`

详见 [Embedded Deployment#cc-应用](Embedded-Deployment#cc-应用) 和 [App Development#部署-cc-应用](App-Development#🦾-部署-cc-应用)。

---

### Q18: 树莓派 Zero 2W 内存不够

**原因**：512MB RAM 启动多个 Python app 会 swap。

**建议**：
1. 用 C/C++ 写 app（占用 2-10MB vs Python 15-30MB）
2. 一次只开 1-2 个 app
3. 关闭不用的 app（最近任务面板上滑）
4. 未来引入 embedded 模式（app 作为同进程路由托管，0 额外进程开销）

详见 [Embedded Deployment#资源占用](Embedded-Deployment#资源占用)。

---

## 配置

### Q19: 如何让 launcher 远程访问

**默认**：launcher 监听 `127.0.0.1`，不对外暴露。

**远程访问**：
1. 改 [config.json](../config.json) 的 `launcher.host` 为 `0.0.0.0`
2. **务必加反向代理 + 鉴权**（如 Nginx + basic auth）

详见 [Embedded Deployment#远程管理建议](Embedded-Deployment#远程管理建议)。

---

### Q20: layout.json 被破坏怎么办

**解决**：直接删除 [layout.json](../layout.json)，launcher 会回退到 app.json 的默认 `dock` 值。

```bash
rm layout.json
# 重启 launcher
```
