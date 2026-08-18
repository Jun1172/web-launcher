"""http_handler - Launcher HTTP 路由

路由表:
  GET /                         → 首页 HTML（frontend.render_home_html）
  GET /api/apps                 → 已安装应用 + running 标记
  GET /api/repo                 → 仓库应用 + 本地版本/可升级对比（含 versions 供回退）
  GET /api/install?id=xxx       → 安装/升级到最新版本
  GET /api/install-version?id=xx&version=yyy → 安装指定版本（回退）
  GET /api/uninstall?id=xxx     → 卸载用户应用
  GET /api/open?id=xxx          → 启动应用进程 + 返回 iframe URL
  GET /api/close?id=xxx         → 关闭应用进程树
  GET /api/launcher/version     → launcher 本地 + 远端版本对比
  GET /api/launcher/update      → 执行 launcher 自更新
  GET /stub?id=xxx              → stub 占位页
"""
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from . import config
from . import app_registry
from .config import vt
from .app_registry import find_app
from .process_manager import open_app as pm_open_app, procs
from .app_operations import (
    do_install, do_uninstall,
    get_launcher_version_info, do_launcher_update,
)
from .repo import repo_index
from .frontend import render_home_html, stub_html


class Handler(BaseHTTPRequestHandler):
    """Launcher HTTP 请求处理器。"""

    # ── 公共响应辅助 ──
    def _json(self, o):
        b = json.dumps(o, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json;charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b)

    def _html(self, html_text, status=200):
        b = html_text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html;charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    # 屏蔽默认 stderr 日志
    def log_message(self, fmt, *args):  # noqa: A002  # BaseHTTP 原签名
        pass

    # ── 路由 ──
    def do_GET(self):  # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        path = u.path

        # ── 首页 ──
        if path == "/":
            self._html(render_home_html(
                config.LAUNCHER_TITLE, config.LAUNCHER_VERSION,
                config.LAUNCHER_CHANGELOG, config.LAUNCHER_RELEASED,
            ))
            return

        # ── 应用列表（带运行状态）──
        if path == "/api/apps":
            self._json([
                {**a, "running": (procs.get(a["id"]) is not None
                                  and procs[a["id"]].poll() is None)}
                for a in app_registry.REGISTRY
            ])
            return

        # ── 仓库应用对比 ──
        if path == "/api/repo":
            try:
                idx = repo_index()
            except Exception as ex:
                self._json({"error": str(ex), "apps": []})
                return
            local_map = {a["id"]: a for a in (app_registry.system_apps + app_registry.user_apps)}
            sys_ids = {s["id"] for s in app_registry.system_apps}
            out = []
            for m in idx.get("apps", []):
                aid = m["id"]
                loc = local_map.get(aid)
                system = (aid in sys_ids) or bool(m.get("system"))
                loc_v = loc.get("version") if loc else None
                remote_v = m.get("version", "0")
                out.append({
                    **m,
                    "local": loc_v,
                    "system": system,
                    "installed": loc is not None,
                    "upgradable": bool(loc_v) and vt(remote_v) > vt(loc_v),
                })
            self._json({"apps": out})
            return

        # ── 安装/升级到最新 ──
        if path == "/api/install":
            aid = q.get("id", [None])[0]
            ok, msg = do_install(aid)
            self._json({"ok": ok, "msg": msg})
            return

        # ── 卸载 ──
        if path == "/api/uninstall":
            aid = q.get("id", [None])[0]
            ok, msg = do_uninstall(aid)
            self._json({"ok": ok, "msg": msg})
            return

        # ── 启动应用 ──
        if path == "/api/open":
            aid = q.get("id", [None])[0]
            app = find_app(aid)
            if not app:
                self._json({"ok": False, "url": None})
                return
            ok = pm_open_app(app)
            # 有 cmd 无 port 的后台进程：返回空 URL（前端不跳转 iframe，保持在桌面）
            has_cmd = bool(app.get("cmd"))
            has_port = app.get("port") is not None
            if not has_cmd:
                url = f"/stub?id={app['id']}"
            elif has_port:
                url = f"http://127.0.0.1:{app['port']}"
            else:
                url = None  # 后台进程，无页面可跳转
            self._json({"ok": ok, "url": url if ok else None})
            return

        # ── 关闭应用（进程树）──
        if path == "/api/close":
            from .process_manager import close_app
            aid = q.get("id", [None])[0]
            close_app(aid)
            self._json({"ok": True})
            return

        # ── Launcher 版本检查 ──
        if path == "/api/launcher/version":
            self._json(get_launcher_version_info())
            return

        # ── Launcher 自更新 ──
        if path == "/api/launcher/update":
            ok, msg, restart = do_launcher_update()
            self._json({"ok": ok, "msg": msg, "restart": restart})
            return

        # ── stub 占位页 ──
        if path == "/stub":
            aid = q.get("id", [None])[0]
            app = find_app(aid)
            if not app:
                self._html("Not Found", status=404)
                return
            self._html(stub_html(app))
            return

        # ── 404 fallback: 重定向回首页 ──
        self._html(render_home_html(
            config.LAUNCHER_TITLE, config.LAUNCHER_VERSION,
            config.LAUNCHER_CHANGELOG, config.LAUNCHER_RELEASED,
        ))
