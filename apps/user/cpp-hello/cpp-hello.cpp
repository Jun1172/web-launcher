// cpp-hello —— 跨平台 C++ HTTP server demo
// 读取 LAUNCHER_APP_PORT 环境变量获取端口（由 launcher 分配），默认 8124
// 用最朴素的 socket API，不依赖任何第三方库（验证 C++ 应用部署链路）
//
// 编译：
//   Windows: build.bat  (cl 或 g++)
//   Linux/Mac: bash build.sh  (g++ 或 clang++)
//
// 编译产物：bin/cpp-hello.exe (Windows) / bin/cpp-hello (Linux/Mac)

#include <iostream>
#include <sstream>
#include <string>
#include <cstring>
#include <cstdlib>
#include <thread>
#include <vector>
#include <atomic>
#include <chrono>

#ifdef _WIN32
#  include <winsock2.h>
#  include <ws2tcpip.h>
#  pragma comment(lib, "ws2_32.lib")
   typedef int socklen_t;
#  define SHUT_SEND SD_SEND
#else
#  include <sys/socket.h>
#  include <netinet/in.h>
#  include <unistd.h>
#  include <arpa/inet.h>
#  include <sys/time.h>
#  define closesocket(s) close(s)
#  define SHUT_SEND SHUT_WR
#endif

static int get_port() {
    const char* env = std::getenv("LAUNCHER_APP_PORT");
    if (env && *env) {
        int p = std::atoi(env);
        if (p > 0) return p;
    }
    return 8124;
}
static std::atomic<int> g_req_count{0};
static std::atomic<bool> g_running{true};

static std::string html_page() {
    std::ostringstream ss;
    ss << u8R"HTML(<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
body{font-family:system-ui;background:linear-gradient(160deg,#0e1229,#1c2347);color:#fff;
display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;margin:0}
.ic{font-size:72px;margin-bottom:14px}
h1{font-size:24px;margin-bottom:6px}
p{color:rgba(255,255,255,.55);font-size:13px}
.badge{margin-top:20px;padding:8px 16px;background:rgba(255,255,255,.08);border-radius:12px;
font-family:monospace;font-size:12px}
</style></head><body>
<div class="ic">🦾</div>
<h1>Hello from C++!</h1>
<p>跨平台 socket HTTP server demo</p>
<div class="badge">已处理 <b>)HTML";
    ss << g_req_count.load();
    ss << u8R"HTML(</b> 次请求</div>
</body></html>)HTML";
    return ss.str();
}

static void handle_client(int client) {
    // 设置接收超时（1秒），避免 recv 永久阻塞
#ifdef _WIN32
    DWORD rcvtime = 1000;
    setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, (const char*)&rcvtime, sizeof(rcvtime));
#else
    struct timeval tv;
    tv.tv_sec = 1;
    tv.tv_usec = 0;
    setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
#endif

    // 循环读取请求直到看到 \r\n\r\n（HTTP 请求头结束）或超时
    char buf[8192];
    std::string req;
    while (true) {
        int n = recv(client, buf, sizeof(buf), 0);
        if (n <= 0) break;
        req.append(buf, n);
        if (req.find("\r\n\r\n") != std::string::npos) break;
    }

    std::string body = html_page();
    std::string resp =
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "Content-Length: " + std::to_string(body.size()) + "\r\n"
        "Connection: close\r\n"
        "Cache-Control: no-store\r\n"
        "\r\n" + body;
    send(client, resp.c_str(), (int)resp.size(), 0);

    // 优雅关闭：先关闭发送端（FIN），再等待对方关闭，最后 closesocket
    // 这样接收缓冲区不会残留未读数据，避免 Windows 发送 RST
    shutdown(client, SHUT_SEND);
    while (true) {
        int n = recv(client, buf, sizeof(buf), 0);
        if (n <= 0) break;
    }
    closesocket(client);
    g_req_count++;
}

int main() {
#ifdef _WIN32
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
        std::cerr << "WSAStartup failed" << std::endl;
        return 1;
    }
#endif

    int port = get_port();

    int srv = socket(AF_INET, SOCK_STREAM, 0);
    if (srv < 0) {
        std::cerr << "socket() failed" << std::endl;
        return 1;
    }

    // SO_REUSEADDR，避免重启时端口占用
    int yes = 1;
    setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, (const char*)&yes, sizeof(yes));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port = htons(port);

    if (bind(srv, (sockaddr*)&addr, sizeof(addr)) < 0) {
        std::cerr << "bind() failed on port " << port << std::endl;
        closesocket(srv);
        return 1;
    }

    if (listen(srv, 16) < 0) {
        std::cerr << "listen() failed" << std::endl;
        closesocket(srv);
        return 1;
    }

    std::cout << "[cpp-hello] listening on http://127.0.0.1:" << port << std::endl;

    while (g_running) {
        sockaddr_in cli{};
        socklen_t clilen = sizeof(cli);
        int client = accept(srv, (sockaddr*)&cli, &clilen);
        if (client < 0) continue;
        // 每连接一个线程（demo 不做线程池）
        std::thread(handle_client, client).detach();
    }

    closesocket(srv);
#ifdef _WIN32
    WSACleanup();
#endif
    return 0;
}
