"""frontend - 首页 HTML 资源、关于模态、stub 应用占位页

导出:
- render_home_html(title, version): 返回完整首页字符串
- stub_html(app_meta): 返回无进程应用的占位页

前端增强点（FR-4.1, FR-3.x）:
- 状态栏右侧 🗂️ 布局编辑按钮 → 布局/配色切换模态
- Toast 工具函数 showToast()
- 最近任务卡片：上滑跟手 + 淡出动画、全部清除确认、关闭后 toast

布局模板存放在 templates/layouts/<id>.html（_shared.js/_shared.css 为通用资源），
通过占位符替换注入动态数据，避免本文件中出现 300+ 行的内联字符串
（模块化维护性要求 FR-5.4）。
"""
import sys
from pathlib import Path

# 👇 【修复】明确区分打包态与开发态的模板路径，避免路径重复
if getattr(sys, 'frozen', False):
    # 打包态：PyInstaller 会将 --add-data 的文件解压到 sys._MEIPASS
    # 因为打包命令是 --add-data "launcher/templates;launcher/templates"
    # 所以临时目录下的结构是 sys._MEIPASS/launcher/templates
    _TEMPLATES_DIR = Path(sys._MEIPASS) / "launcher" / "templates"
else:
    # 开发态：__file__ 是 launcher/frontend.py
    # 模板就在同级的 templates 目录下
    _TEMPLATES_DIR = Path(__file__).parent / "templates"

_THEMES_DIR = _TEMPLATES_DIR / "themes"
_LAYOUTS_DIR = _TEMPLATES_DIR / "layouts"

# 主题注册表：id → {name, swatch}。
# 新增主题 = 在 themes/ 加 <id>.html + 在此注册一项。
# swatch 是前端主题按钮的预览色块（CSS background 值）。
THEMES = {
    "tech-dark": {"name": "深色科技", "swatch": "linear-gradient(135deg,#0b1120,#818cf8)"},
    "light-simple": {"name": "浅色简约", "swatch": "linear-gradient(135deg,#f1f5f9,#6366f1)"},
    "macos-dock": {"name": "macOS Dock", "swatch": "linear-gradient(135deg,#1d1d1f,#007aff)"},
}
DEFAULT_THEME = "tech-dark"

# 布局注册表：id → {name, icon}。
# 新增布局 = 在 layouts/ 加 <id>.html + 在此注册一项。
# 每个布局 HTML 须含 __SHARED_CSS__ / __SHARED_JS__ 占位符 + 实现 buildHome()。
LAYOUTS = {
    "grid": {"name": "九宫格", "icon": "🔲"},
    "list": {"name": "列表式", "icon": "📋"},
    "sidebar": {"name": "侧边栏", "icon": "📐"},
    "metro": {"name": "磁贴", "icon": "🧊"},
}
DEFAULT_LAYOUT = "grid"


def _get_all_theme_blocks() -> str:
    """拼接 themes/ 下所有已注册主题的 <style> 片段，注入到首页 <head>。

    顺序：按 THEMES 字典定义顺序。缺失的主题文件用空 <style> 占位，
    保证前端切换 data-theme 不会因变量缺失而崩。
    """
    parts = []
    for tid in THEMES:
        p = _THEMES_DIR / f"{tid}.html"
        try:
            parts.append(p.read_text(encoding="utf-8"))
        except OSError:
            parts.append(f"<style>/* 主题 {tid} 文件缺失 */</style>")
    return "\n".join(parts)


def _get_theme() -> str:
    """从 layout.json 读取用户选择的主题；非法或缺失回退 DEFAULT_THEME。"""
    from . import layout
    try:
        ly = layout.load_layout()
    except Exception:
        return DEFAULT_THEME
    t = ly.get("theme")
    return t if t in THEMES else DEFAULT_THEME


def _themes_json() -> str:
    """生成前端 THEMES 常量的 JSON 字符串。"""
    import json
    arr = [{"id": tid, "name": m["name"], "swatch": m["swatch"]} for tid, m in THEMES.items()]
    return json.dumps(arr, ensure_ascii=False)


def _get_layout() -> str:
    """从 layout.json 读取用户选择的布局；非法或缺失回退 DEFAULT_LAYOUT。"""
    from . import layout
    try:
        ly = layout.load_layout()
    except Exception:
        return DEFAULT_LAYOUT
    l = ly.get("layout")
    return l if l in LAYOUTS else DEFAULT_LAYOUT


def _get_shared_css() -> str:
    """读 layouts/_shared.css 内容（跨布局通用样式）。"""
    p = _LAYOUTS_DIR / "_shared.css"
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return "/* _shared.css 缺失 */"


def _get_shared_js() -> str:
    """读 layouts/_shared.js 内容（跨布局通用逻辑）。"""
    p = _LAYOUTS_DIR / "_shared.js"
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return "/* _shared.js 缺失 */"


def _layouts_json() -> str:
    """生成前端 LAYOUTS 常量的 JSON 字符串。"""
    import json
    arr = [{"id": lid, "name": m["name"], "icon": m.get("icon", "")} for lid, m in LAYOUTS.items()]
    return json.dumps(arr, ensure_ascii=False)

def _escape(s):
    """HTML 转义：防止 XSS / 布局错乱。"""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;") \
                    .replace(">", "&gt;").replace('"', "&quot;") \
                    .replace("'", "&#39;")


def stub_html(a):
    """无独立进程的 stub 应用占位页。"""
    color = a.get("color", "#888")
    icon = _escape(a.get("icon", "📦"))
    name = _escape(a.get("name", "应用"))
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{{font-family:system-ui;display:flex;flex-direction:column;align-items:center;
justify-content:center;height:100vh;margin:0;background:linear-gradient(160deg,{color}33,#fff)}}
.ic{{font-size:64px}}p{{color:#999;font-size:13px}}</style></head>
<body><div class="ic">{icon}</div><h2>{name}</h2><p>占位应用 · 待接入</p></body></html>"""


def render_home_html(title, version):
    """构造桌面首页完整 HTML（按 layout.json 的 layout 字段选 layouts/<id>.html）。"""
    esc_title = _escape(title)
    esc_ver = _escape(version)
    layout_id = _get_layout()
    tpl_path = _LAYOUTS_DIR / f"{layout_id}.html"
    try:
        tpl = tpl_path.read_text(encoding="utf-8")
    except OSError:
        # 指定布局模板缺失 → 回退到 grid
        tpl = (_LAYOUTS_DIR / "grid.html").read_text(encoding="utf-8")
    return (tpl
            .replace("__TITLE__", esc_title)
            .replace("__VERSION__", esc_ver)
            # 先注入共享资源（_shared.js 内部含 __THEMES__/__LAYOUTS__ 占位符，需在下面替换）
            .replace("__SHARED_CSS__", _get_shared_css())
            .replace("__SHARED_JS__", _get_shared_js())
            .replace("__THEME_BLOCKS__", _get_all_theme_blocks())
            # 再替换所有占位符（含共享资源里注入的）
            .replace("__THEME__", _get_theme())
            .replace("__THEMES__", _themes_json())
            .replace("__LAYOUTS__", _layouts_json()))
