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

from .config import APPS_DIR, SYSTEM_APPS_DIR, safe_print

# 模块级全局注册表（所有视图共享）
system_apps = []
user_apps = []
REGISTRY = []


def derive_group(meta):
    """从 app.json 元数据推导分组：group 字段为唯一来源，缺省视为 "user"。

    system 字段已废弃，不再是判定依据。返回 str。
    """
    return meta.get("group") or "user"


def resolve_cmd(meta, app_dir):
    """把 app.json 里的 cmd 字段解析为实际 Popen 参数列表。

    规则：
    - 相对路径 → 相对 BASE 展开
    - 后缀 .py / .pyw → 自动前缀 Python 解释器
      开发态用 sys.executable（同一个 python.exe）；
      打包态 sys.executable 是 launcher.exe（不能当解释器），改用系统 python
    - 没有 cmd 字段 → 返回 None（代表是纯占位 stub 应用，无独立进程）
    """
    cmd = meta.get("cmd")
    if not cmd:
        return None
    out = []
    for c in cmd:
        p = Path(c)
        # app_dir = <root>/apps/<group>/<id>，cmd 是 <root> 相对路径。
        out.append(str(app_dir.parents[2] / p) if not p.is_absolute() else str(p))
    if out[0].lower().endswith((".py", ".pyw")):
        # 打包后 sys.executable 是 launcher.exe，用它跑 app.py 会弹新窗口（又跑一次 main）
        # 改用系统 python 命令；用户系统需装 Python 才能跑 .py app
        interpreter = "python" if getattr(sys, "frozen", False) else sys.executable
        out = [interpreter] + out
    return out


def _find_all_app_dirs():
    """扫描内置 system 与 exe 同级 apps 下的客户应用。"""
    dirs = []
    roots = [SYSTEM_APPS_DIR]
    if APPS_DIR != SYSTEM_APPS_DIR:
        roots.append(APPS_DIR)
    seen = set()
    for root in roots:
        if not root.exists():
            continue
        for app_json in sorted(root.rglob("app.json")):
            d = app_json.parent
            if d.name.endswith((".bak", ".tmp.new", ".zip.tmp")) or d in seen:
                continue
            # 外部 apps/system 不覆盖 exe 内置系统应用。
            if root == APPS_DIR and d.is_relative_to(APPS_DIR / "system"):
                continue
            seen.add(d)
            dirs.append(d)
    return dirs


def _scan_all_apps():
    """递归扫描 APPS_DIR 下所有 app.json，返回 [{meta with id, system, cmd resolved}, ...]。"""
    apps = []
    for d in _find_all_app_dirs():
        try:
            meta = json.loads((d / "app.json").read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError) as e:
            safe_print(f"[WARN] 应用 {d.name} 加载失败: {e}")
            continue
        meta.setdefault("id", d.name)
        # group 为唯一判定来源；system 字段已废弃。system 标记从 group 派生，
        # 仅供 load_system_apps / load_user_apps 内部筛选使用。
        g = derive_group(meta)
        meta["group"] = g
        meta["system"] = (g == "system")
        meta["cmd"] = resolve_cmd(meta, d)
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
    """基于 system_apps + user_apps 重建 REGISTRY，并检测端口冲突。"""
    global REGISTRY
    REGISTRY = system_apps + user_apps
    _mark_port_conflicts(REGISTRY)


def _mark_port_conflicts(apps):
    """扫描 apps 列表，给 port 重复的应用标记 port_conflict: True。

    多个 app.json 写同一 port 时，全部标记为冲突，前端会显示 ⚠️ 角标。
    """
    port_map = {}
    for a in apps:
        p = a.get("port")
        if p:
            port_map.setdefault(p, []).append(a["id"])
    conflict_ids = {aid for aids in port_map.values() if len(aids) > 1 for aid in aids}
    for a in apps:
        if a["id"] in conflict_ids:
            a["port_conflict"] = True
        elif "port_conflict" in a:
            del a["port_conflict"]  # 清除上次标记，避免 reload 后残留
    if conflict_ids:
        safe_print(f"[WARN] 端口冲突: {conflict_ids}")


def reload_apps():
    """重新扫描磁盘，刷新三个全局列表。启动时调用、安装/卸载后调用。

    扫描完后调用 layout.apply_layout 覆盖 dock / 过滤 hidden
    （layout.json 是用户级覆盖层，app.json 的 dock 是出厂默认）。
    """
    global system_apps, user_apps
    from . import layout  # 延迟导入避免循环
    system_apps = layout.apply_layout(load_system_apps())
    user_apps = layout.apply_layout(load_user_apps())
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
