# cpp-hello —— C++ 应用部署 demo

验证 C++ 应用如何接入 launcher 的完整生命周期管理：编译 → 启动 → ready_check → 优雅停止 → 崩溃重启。

## 文件结构

```
apps/user/cpp-hello/
├── app.json         # 应用清单：cmd 指向 run.py（启动包装）
├── cpp-hello.cpp    # C++ 源码：跨平台 socket HTTP server，端口 8124
├── run.py           # 启动包装：按平台选可执行文件，用 subprocess.Popen 拉起 + 转发终止信号
├── build.bat        # Windows 编译脚本（g++ 或 MSVC cl）
├── build.sh         # Linux/macOS 编译脚本（g++ 或 clang++）
└── bin/             # 编译产物（gitignore 推荐）
    ├── cpp-hello.exe    # Windows
    └── cpp-hello        # Linux/macOS
```

## 部署约定

C++ 应用在 launcher 中的部署流程：

1. **源码即文档**：`app.json.changelog` 说明编译方式
2. **本机编译**：发布前在目标机器上跑 `build.bat` / `bash build.sh`，产物在 `bin/` 下
3. **启动包装**：`run.py` 负责跨平台选可执行文件 + 用 `subprocess.Popen` 拉起 + 转发 SIGTERM 给子进程
   - launcher 看到的 PID 是 Python 包装进程（可观测、可停止）
   - close_app 时 launcher 用 `taskkill /T /F` 或 `killpg` 递归杀整棵树，C++ 子进程不会成孤儿
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

# 应返回 {"ok": true, "url": "http://127.0.0.1:8124"}
# 浏览器打开 http://127.0.0.1:8124 看到 "Hello from C++!" 页面

# 优雅停止：launcher 发 SIGTERM（Linux）/ taskkill（Windows）
curl http://127.0.0.1:8000/api/close?id=cpp-hello
```

## 嵌入式部署场景

把 cpp-hello 当模板：

- 替换 `cpp-hello.cpp` 为你的 socket/串口/ROS2 节点实现
- 修改 `PORT` 和 `app.json` 里的 `port`
- 端口就绪探测由 launcher 统一做（TCP 轮询，超时 6s）；无端口的进程型应用启动即视为就绪
- 在目标板（如树莓派 / Jetson）上交叉编译，把 bin/ 拷贝过去
- 在 launcher 机器上拉取 zip 即可部署

## 优雅停止注意事项

launcher 停止应用用 `terminate()` + 2s 后强杀进程树兜底（Win `taskkill /F /T` / POSIX `killpg`）。
C++ 程序默认收到 SIGTERM 会直接退出（默认行为）。如果需要在退出前做资源清理：

```cpp
#include <csignal>
static std::atomic<bool> g_running{true};
void on_sigterm(int) { g_running = false; }
int main() {
    signal(SIGTERM, on_sigterm);
    // accept 用 select 设置超时，让主循环能周期性检查 g_running
}
```
