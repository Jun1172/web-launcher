"""http_handler - Launcher HTTP 路由

路由表:
  GET /                         → 首页 HTML（frontend.render_home_html）
  GET /api/apps                 → 已安装应用 + running 标记
  GET /api/repo                 → 仓库应用 + 本地版本/可升级对比
  GET /api/install?id=xxx       → 安装/升级到最新版本
  GET /api/uninstall?id=xxx     → 卸载用户应用
  GET /api/open?id=xxx          → 启动应用进程 + 返回 iframe URL
  GET /api/close?id=xxx         → 关闭应用进程树
  GET /api/launcher/version     → launcher 本地 + 远端版本对比
  GET /api/launcher/update      → 执行 launcher 自更新
  GET /api/repo/config          → 读取仓库地址/认证/SSL 配置
  POST /api/repo/config         → 保存仓库配置（原子写 config.json + reload）
  GET /stub?id=xxx              → stub 占位页
"""
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from . import config
from . import app_registry
from .config import vt
from .app_registry import find_app
from .process_manager import open_app as pm_open_app, get_port as pm_get_port, procs
from .app_operations import (
    do_install, do_uninstall,
    get_launcher_version_info, do_launcher_update,
)
from .repo import repo_index
from .frontend import render_home_html, stub_html

# /api/apps 允许暴露的应用字段白名单（避免把 app.json 中 env 等敏感字段发给前端）
APP_FIELDS = ("id", "name", "icon", "color", "version", "cmd",
              "port", "dock", "group", "system", "changelog",
              "released", "port_conflict")


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
            ))
            return

        # ── 应用列表（带运行状态 + 实际端口）──
        if path == "/api/apps":
            self._json([
                {k: a[k] for k in APP_FIELDS if k in a} | {
                    "running": (procs.get(a["id"]) is not None
                                and procs[a["id"]].poll() is None),
                    "actual_port": pm_get_port(a["id"]),
                }
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
                # system 只由本地 apps/system 目录决定，不取仓库元数据
                # （否则仓库 index.json 标 system:true 的用户应用会被误判为不可卸载）
                system = aid in sys_ids
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

        # ── 仓库配置（供 settings 应用读写）──
        if path == "/api/repo/config":
            auth = config.REPO_AUTH
            self._json({
                "url": config.REPO_URL,
                "auth_user": auth[0] if auth else "",
                "auth_pass": auth[1] if auth else "",
                "verify_ssl": config.VERIFY_SSL,
            })
            return

        # ── 用户布局配置（dock / hidden / theme / layout 覆盖层）──
        if path == "/api/layout":
            from . import layout
            from .frontend import DEFAULT_THEME, DEFAULT_LAYOUT
            ly = layout.load_layout()
            # dock=None 表示 layout.json 未保存过，前端用 app.json 默认值显示
            self._json({
                "dock": ly.get("dock"),
                "hidden": ly.get("hidden", []),
                "theme": ly.get("theme", DEFAULT_THEME),
                "layout": ly.get("layout", DEFAULT_LAYOUT),
            })
            return

        # ── UI 配置（窗口按钮 / 动效开关，源自 config.json 的 ui 节）──
        if path == "/api/ui/config":
            # 每次从磁盘读取，使 config.json 修改即时生效（无需重启 launcher）
            cfg = config.load_config()
            ui = cfg.get("ui", {})
            self._json({
                "show_window_buttons": ui.get("show_window_buttons", True),
                "fx_enabled": ui.get("fx_enabled", True),
                "fx_particle_count": ui.get("fx_particle_count", 38),
            })
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
                self._json({"ok": False, "url": None, "reason": "应用不存在"})
                return
            # launcher 分配端口 + 启动 + 等待就绪，返回结构化结果 {"ok","running","port"}
            result = pm_open_app(app)
            if not app.get("cmd"):
                # stub 应用（无进程，纯占位页）
                self._json({"ok": True, "url": f"/stub?id={app['id']}", "reason": None})
            elif result["ok"]:
                port = result.get("port")
                # 有端口则返回 iframe URL，无端口应用返回 url=None
                self._json({"ok": True,
                            "url": f"http://127.0.0.1:{port}" if port else None,
                            "reason": None})
            else:
                # 启动失败（进程崩溃/端口被占/正在启动中）
                self._json({"ok": False, "url": None,
                            "reason": result.get("reason")
                                      or "应用启动失败（进程崩溃或端口被占）"})
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

        # ── 404 fallback ──
        self._html(
            "<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<title>404 Not Found</title></head>"
            "<body style='font-family:system-ui;display:flex;align-items:center;"
            "justify-content:center;height:100vh;margin:0;color:#888'>"
            "<div style='text-align:center'><h1 style='margin:0'>404</h1>"
            "<p>页面不存在</p></div></body></html>",
            status=404,
        )

    def do_POST(self):  # noqa: N802
        u = urlparse(self.path)
        path = u.path
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(body.decode("utf-8") or "{}")
        except Exception:
            self._json({"ok": False, "msg": "请求体不是合法 JSON"})
            return

        # ── 保存仓库配置 ──
        if path == "/api/repo/config":
            url = str(data.get("url", "") or "")
            auth_user = str(data.get("auth_user", "") or "")
            auth_pass = str(data.get("auth_pass", "") or "")
            verify_ssl = bool(data.get("verify_ssl", False))
            try:
                config.save_repo_config(url, auth_user, auth_pass, verify_ssl)
                self._json({"ok": True, "msg": "已保存，配置已实时刷新"})
            except Exception as e:
                self._json({"ok": False, "msg": f"保存失败: {e}"})
            return

        # ── 保存用户布局配置（支持部分更新：dock/hidden/theme/layout 任一可选）──
        if path == "/api/layout":
            from . import layout
            from .frontend import THEMES, LAYOUTS
            dock = data.get("dock")
            hidden = data.get("hidden")
            theme = data.get("theme")
            layout_id = data.get("layout")
            # dock/hidden 若提供则必须为数组；theme 必须在 THEMES 中；layout 必须在 LAYOUTS 中
            if dock is not None and not isinstance(dock, list):
                self._json({"ok": False, "msg": "dock 必须为数组"}); return
            if hidden is not None and not isinstance(hidden, list):
                self._json({"ok": False, "msg": "hidden 必须为数组"}); return
            if theme is not None and theme not in THEMES:
                self._json({"ok": False, "msg": f"未知主题: {theme}"}); return
            if layout_id is not None and layout_id not in LAYOUTS:
                self._json({"ok": False, "msg": f"未知布局: {layout_id}"}); return
            try:
                layout.save_layout(dock, hidden, theme, layout_id)
                # dock/hidden 变化才需要刷新注册表；theme/layout 仅影响前端渲染
                if dock is not None or hidden is not None:
                    app_registry.reload_apps()
                self._json({"ok": True, "msg": "已保存"})
            except Exception as e:
                self._json({"ok": False, "msg": f"保存失败: {e}"})
            return

        self._json({"ok": False, "msg": "未知 POST 路由"})
