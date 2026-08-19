# cpp-hello —— C++ 应用部署 demo

验证 C++ 应用如何接入 launcher 的进程管理与停止链路。

## 文件结构

```
apps/user/cpp-hello/
├── app.json         # 应用清单：cmd 指向 run.py（启动包装）
├── cpp-hello.cpp    # C++ 源码：跨平台 socket HTTP server，端口 8140
├── run.py           # 启动包装：按平台选可执行文件，用 subprocess.Popen 拉起
├── build.bat        # Windows 编译脚本（g++ 或 MSVC cl）
├── build.sh         # Linux/macOS 编译脚本（g++ 或 clang++）
└── bin/             # 编译产物（gitignore 推荐）
    ├── cpp-hello.exe    # Windows
    └── cpp-hello        # Linux/macOS
```

## 部署约定

C++ 应用在 launcher 中的部署流程：

1. **源码即文档**：`app.json.requires.comment` 说明编译方式（`requires` 字段当前不阻塞安装，仅作为提示）
2. **本机编译**：发布前在目标机器上跑 `build.bat` / `bash build.sh`，产物在 `bin/` 下
3. **启动包装**：`run.py` 负责跨平台选可执行文件 + 用 `subprocess.Popen` 拉起
   - launcher 看到的 PID 是 Python 包装进程（可观测、可停止）
   - close_app 时 launcher 用 `taskkill /F /T`（Win）/ `os.killpg`（POSIX）递归杀整棵树，C++ 子进程不会成孤儿
4. **跨架构部署**：x86 / ARM 需各自编译，建议用 zip 名后缀区分（如 `cpp-hello-1.0.0-win-x64.zip`）

## 编译

```bash
# Windows（PowerShell / CMD）
.\build.bat

# Linux / macOS
bash build.sh
```

依赖：仅 C++17 标准库 + winsock2（Windows 自带）/ POSIX socket（Linux/macOS 自带）。**无第三方依赖**。

## 验证

```bash
# 编译完后，通过 launcher 启动
curl http://127.0.0.1:8000/api/open?id=cpp-hello

# 应返回 {"ok": true, "url": "http://127.0.0.1:8140"}
# 浏览器打开 http://127.0.0.1:8140 看到 "Hello from C++!" 页面

# 停止：launcher 用 terminate() + 2s 兜底 taskkill /T 或 killpg
curl http://127.0.0.1:8000/api/close?id=cpp-hello
```

## 实际行为说明

> ⚠️ README 历史版本提到 `ready_check` / `stop_signal` / `stop_timeout` / 崩溃重启，**当前 launcher 不读这些字段**：
>
> | 能力 | 状态 |
> |------|------|
> | `ready_check.type=tcp` 端口探测 | **不读取字段**；但 launcher 看 `app.json.port` 字段做 TCP probe（行为等同 tcp 类型） |
> | `stop_signal` / `stop_timeout` 可配 | **不读取**；`close_app` 硬编码 `terminate()` + 2s 后强 kill 进程树 |
> | `restart_policy` 崩溃重启 | **未实现**；C++ 进程崩溃后不自动拉起 |
>
> 实际停止链路：`p.terminate()` → 等 2 秒 → `taskkill /F /T /PID`（Win）/ `os.killpg`（POSIX）。

## 嵌入式部署场景

把 cpp-hello 当模板：

- 替换 `cpp-hello.cpp` 为你的 socket / 串口 / ROS2 节点实现
- 修改 `PORT` 和 `app.json` 里的 `port`
- 如果不是 HTTP 服务，不写 `port` 字段（launcher 启动后立即视为就绪）
- 在目标板（如树莓派 / Jetson）上交叉编译，把 bin/ 拷贝过去
- 在 launcher 机器上拉取 zip 即可部署

## C++ 程序的优雅停止（可选）

C++ 程序默认捕获 SIGTERM 会直接退出（默认行为）。当前 launcher 在 POSIX 上 `p.terminate()` 就是发 SIGTERM，所以你可以在 C++ 里注册 handler 做资源清理：

```cpp
#include <csignal>
static std::atomic<bool> g_running{true};
void on_sigterm(int) { g_running = false; }
int main() {
    signal(SIGTERM, on_sigterm);
    // accept 用 select 设置超时，让主循环能周期性检查 g_running
}
```

> 注意：Windows 上 `p.terminate()` 是 `TerminateProcess`，不发信号，handler 不触发——需要靠 launcher 兜底 `taskkill /T` 杀整棵树。
