"""layout - 用户级布局覆盖（layout.json）

职责：
- 读写 BASE/layout.json（dock / hidden 两个数组）
- apply_layout(apps)：把 layout.json 覆盖到 app.json 扫描结果上

加载顺序：
  app_registry 扫描 app.json → apply_layout 覆盖 dock / 过滤 hidden
app.json 的 dock 字段降级为"出厂默认值"，仅当 layout.json 未覆盖时使用。
"""
import json
from pathlib import Path

from .config import BASE

LAYOUT_JSON = BASE / "layout.json"


def load_layout():
    """读 layout.json；不存在或损坏返回 {}。"""
    if not LAYOUT_JSON.exists():
        return {}
    try:
        return json.loads(LAYOUT_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_layout(dock, hidden):
    """原子写 layout.json。dock/hidden 为 list[str]；None 表示保留旧值。

    返回写入后的完整 dict。
    """
    cur = load_layout()
    if dock is not None:
        cur["dock"] = [str(x) for x in dock if x]
    if hidden is not None:
        cur["hidden"] = [str(x) for x in hidden if x]
    cur["version"] = 1
    tmp = LAYOUT_JSON.with_suffix(".json.tmp.new")
    tmp.write_bytes(json.dumps(cur, ensure_ascii=False, indent=2).encode("utf-8"))
    tmp.replace(LAYOUT_JSON)  # 同盘原子替换
    return cur


def apply_layout(apps):
    """根据 layout.json 调整 apps 列表：覆盖 dock 字段、过滤 hidden。

    返回新列表（不修改入参）。layout.json 不存在时原样返回。
    """
    layout = load_layout()
    has_dock = "dock" in layout
    has_hidden = "hidden" in layout
    if not has_dock and not has_hidden:
        return list(apps)

    dock_set = set(layout.get("dock") or [])
    hidden_set = set(layout.get("hidden") or [])
    out = []
    for a in apps:
        aid = a.get("id")
        if aid in hidden_set:
            continue
        b = dict(a)
        if has_dock:
            b["dock"] = aid in dock_set
        out.append(b)
    return out
