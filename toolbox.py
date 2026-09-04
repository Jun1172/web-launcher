# -*- coding: utf-8 -*-
"""WebLauncher 统一工具箱（桌面窗口 / HTTP 双模式）

把散落在两个仓库里的开发 / 发布脚本（运行、打包、发布、重建产物、清理）
集中到一个带界面的入口里：每个工具有中文名称与说明，点一下就能跑，
并在界面里实时看到输出。

两种运行模式（自动选择）：
  - 桌面窗口：本机装了 pywebview + WebView2 时，弹出一个原生桌面窗口。
  - HTTP 模式：没有 GUI 环境时，自动起一个本地 HTTP 服务并在浏览器打开，
              通过 SSE 把脚本输出流式推回页面（用 --http 可强制）。

所有工具定义都在同目录的 tools.json 里，想增删改工具只动那个 JSON 即可。

用法:
    python toolbox.py            # 优先桌面窗口，不行则自动转 HTTP
    python toolbox.py --http     # 强制 HTTP 模式（浏览器打开）
    python toolbox.py --port 8799
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

import urllib.parse
import http.server

HERE = Path(__file__).resolve().parent
TOOLS_FILE = HERE / "tools.json"
HTML_FILE = HERE / "tools" / "toolbox.html"

# ---------------------------------------------------------------------------
# 加载清单，解析各仓库根目录（相对 toolbox.py 所在仓库根）
# ---------------------------------------------------------------------------
def load_manifest():
    data = json.loads(TOOLS_FILE.read_text(encoding="utf-8"))
    repos = data.get("repos", {})
    repo_dirs = {}
    missing = []
    for name, rel in repos.items():
        d = (HERE / rel).resolve()
        repo_dirs[name] = d
        if not d.is_dir():
            missing.append(name)
    data["_missing_repos"] = missing
    tools = {t["id"]: t for t in data.get("tools", [])}
    return data, repo_dirs, tools


MANIFEST, REPO_DIRS, TOOLS_BY_ID = load_manifest()


def render_html():
    """读 HTML 模板，把工具清单注入占位符。"""
    html = HTML_FILE.read_text(encoding="utf-8")
    return html.replace("/*__TOOLS__*/", json.dumps(MANIFEST, ensure_ascii=False))


# ---------------------------------------------------------------------------
# 核心：执行一个工具，并通过 emit(stream, text) 把输出流式回传
# ---------------------------------------------------------------------------
def run_tool_core(tool, args, emit):
    """运行 tool，逐行把输出交给 emit。返回 (returncode, ok)。"""
    repo = tool.get("repo")
    repo_dir = REPO_DIRS.get(repo)
    if repo_dir is None or not repo_dir.is_dir():
        emit("system", "✗ 仓库目录不存在，无法运行：%s" % repo)
        return -1, False

    cmd = list(tool.get("cmd", []))
    if not cmd:
        emit("system", "✗ 工具未定义 cmd")
        return -1, False

    if cmd[0].endswith(".bat"):
        full = ["cmd", "/c"] + cmd
    else:
        full = [sys.executable] + cmd
    full += [str(a) for a in (args or [])]

    emit("system", "$ cd %s" % repo_dir)
    emit("system", "$ %s" % " ".join(full))
    try:
        p = subprocess.Popen(
            full, cwd=str(repo_dir),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
    except Exception as e:
        emit("system", "✗ 启动失败: %s" % e)
        return -1, False

    for line in p.stdout:
        emit("stdout", line.rstrip("\n"))
    rc = p.wait()
    ok = rc == 0
    emit("system", "=== 结束 (rc=%d, %s) ===" % (rc, "成功" if ok else "失败"))
    return rc, ok


# ---------------------------------------------------------------------------
# 桌面窗口模式（pywebview）
# ---------------------------------------------------------------------------
def _gui_emit(tool_id, stream, text):
    try:
        import webview
        js = "window.TB.appendLine(%s,%s,%s);" % (
            json.dumps(tool_id), json.dumps(stream), json.dumps(text))
        for w in webview.windows:
            w.evaluate_js(js)
    except Exception:
        pass


def _gui_done(tool_id, ok, rc):
    try:
        import webview
        js = "window.TB.setDone(%s,%s,%d);" % (
            json.dumps(tool_id), "true" if ok else "false", rc)
        for w in webview.windows:
            w.evaluate_js(js)
    except Exception:
        pass


class Api:
    """暴露给前端 JS 的接口。run_tool 立即返回，真正工作在后台线程里跑，
    这样流式输出能通过 evaluate_js 实时推回页面（而不是等全部跑完才显示）。"""

    def run_tool(self, tool_id, args=None):
        tool = TOOLS_BY_ID.get(tool_id)
        if not tool:
            return {"ok": False, "rc": -1}

        def worker():
            def emit(stream, text):
                _gui_emit(tool_id, stream, text)
            rc, ok = run_tool_core(tool, args or [], emit)
            _gui_done(tool_id, ok, rc)

        threading.Thread(target=worker, daemon=True).start()
        return {"started": True}


def start_gui():
    import webview
    html = render_html()
    webview.create_window(
        MANIFEST.get("title", "WebLauncher 工具箱"),
        html=html, js_api=Api(),
        width=1120, height=780, resizable=True, text_select=True,
    )
    webview.start()


# ---------------------------------------------------------------------------
# HTTP 模式（无 GUI 时回退；流式用 SSE）
# ---------------------------------------------------------------------------
class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, ctype, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/run":
            self._handle_run(parsed)
        else:
            self._send(200, "text/html; charset=utf-8", render_html())

    def _handle_run(self, parsed):
        qs = urllib.parse.parse_qs(parsed.query)
        tool_id = qs.get("tool", [""])[0]
        try:
            args = json.loads(qs.get("args", ["[]"])[0])
        except Exception:
            args = []
        tool = TOOLS_BY_ID.get(tool_id)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def emit(stream, text):
            payload = json.dumps({"stream": stream, "text": text}, ensure_ascii=False)
            try:
                self.wfile.write(("data: %s\n\n" % payload).encode("utf-8"))
                self.wfile.flush()
            except Exception:
                pass

        if not tool:
            emit("system", "✗ 未知工具: %s" % tool_id)
            self.wfile.write(b'data: {"done":true,"ok":false,"rc":-1}\n\n')
            self.wfile.flush()
            return

        rc, ok = run_tool_core(tool, args, emit)
        self.wfile.write(("data: %s\n\n" % json.dumps(
            {"done": True, "ok": ok, "rc": rc}, ensure_ascii=False)).encode("utf-8"))
        self.wfile.flush()

    def log_message(self, *a):
        pass


def start_http(port, open_browser=True):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = "http://127.0.0.1:%d/" % port
    print("[INFO] 工具箱已启动（HTTP 模式）: %s" % url)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[STOP] 已关闭工具箱")
    finally:
        server.shutdown()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="WebLauncher 统一工具箱")
    ap.add_argument("--http", action="store_true", help="强制 HTTP 模式（浏览器打开）")
    ap.add_argument("--port", type=int, default=8799, help="HTTP 模式监听端口")
    ap.add_argument("--no-browser", action="store_true", help="HTTP 模式不自动开浏览器")
    args = ap.parse_args()

    http_mode = args.http
    if not http_mode:
        try:
            import webview  # noqa: F401
        except ImportError:
            http_mode = True
            print("[INFO] 未检测到 pywebview，自动切换到 HTTP 模式")

    if http_mode:
        start_http(args.port, open_browser=not args.no_browser)
    else:
        start_gui()


if __name__ == "__main__":
    main()
