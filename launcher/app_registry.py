"""app_registry - 应用扫描与注册表维护

职责：
- 递归扫描 apps/ 下所有含 app.json 的目录，生成应用清单（通过 metadata.system 标记类型）
- 维护模块级全局变量 system_apps / user_apps / REGISTRY
- 提供 reload_apps() / is_system_app() / is_user_app() / resolve_cmd() 等接口

依赖 launcher.config 提供 APPS_DIR 与 sys.executable；不依赖进程/仓库模块。
"""
import json
import sys
from pathlib import Path

from .config import BASE, APPS_DIR

# 模块级全局注册表（所有视图共享）
system_apps = []
user_apps = []
REGISTRY = []


def resolve_cmd(meta):
    """把 app.json 里的 cmd 字段解析为实际 Popen 参数列表。

    规则：
    - 相对路径 → 相对 BASE 展开
    - 后缀 .py / .pyw → 自动前缀 sys.executable（确保用同一个解释器）
    - 没有 cmd 字段 → 返回 None（代表是纯占位 stub 应用，无独立进程）
    """
    cmd = meta.get("cmd")
    if not cmd:
        return None
    out = []
    for c in cmd:
        p = Path(c)
        out.append(str(BASE / p) if not p.is_absolute() else str(p))
    if out[0].lower().endswith((".py", ".pyw")):
        out = [sys.executable] + out
    return out


def _find_all_app_dirs():
    """递归扫描 APPS_DIR 下所有含 app.json 的目录，返回 [app_dir, ...]。"""
    dirs = []
    if not APPS_DIR.exists():
        return dirs
    for app_json in sorted(APPS_DIR.rglob("app.json")):
        d = app_json.parent
        if d.name.endswith((".bak", ".tmp.new", ".zip.tmp")):
            continue
        dirs.append(d)
    return dirs


def _scan_all_apps():
    """递归扫描 APPS_DIR 下所有 app.json，返回 [{meta with id, system, cmd resolved}, ...]。"""
    apps = []
    for d in _find_all_app_dirs():
        try:
            meta = json.loads((d / "app.json").read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError) as e:
            print(f"⚠ 应用 {d.name} 加载失败: {e}")
            continue
        meta.setdefault("id", d.name)
        meta["system"] = bool(meta.get("system"))
        meta["cmd"] = resolve_cmd(meta)
        meta.setdefault("version", "0.0.1")
        meta.setdefault("changelog", "")
        meta.setdefault("released", "")
        apps.append(meta)
    return apps


def load_system_apps():
    """扫描所有目录，筛选 system:true 的应用。"""
    return [a for a in _scan_all_apps() if a.get("system")]


def load_user_apps():
    """扫描所有目录，筛选 system:false 的应用。"""
    return [a for a in _scan_all_apps() if not a.get("system")]


def rebuild_registry():
    """基于 system_apps + user_apps 重建 REGISTRY。"""
    global REGISTRY
    REGISTRY = system_apps + user_apps


def reload_apps():
    """重新扫描磁盘，刷新三个全局列表。启动时调用、安装/卸载后调用。"""
    global system_apps, user_apps
    system_apps = load_system_apps()
    user_apps = load_user_apps()
    rebuild_registry()


def is_system_app(aid):
    return any(a["id"] == aid for a in system_apps)


def is_user_app(aid):
    return any(a["id"] == aid for a in user_apps)


def find_app(aid):
    """根据 id 在 REGISTRY 中查找应用元数据；找不到返回 None。"""
    for a in REGISTRY:
        if a["id"] == aid:
            return a
    return None


# 首次导入即刷新注册表（与原 launcher.py 行为一致）
reload_apps()
