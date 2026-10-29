"""frontend - 首页 HTML 资源与 stub 应用占位页

导出:
- render_home_html(title, version): 返回完整首页字符串
- stub_html(app_meta): 返回无进程应用的占位页

布局模板存放在 templates/layouts/<id>.html（_shared.js/_shared.css 为通用资源），
主题存放在 templates/themes/<id>.html；通过占位符替换注入动态数据，
避免本文件中出现大段内联字符串。
"""
import json
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

# 供 http_handler 等外部模块使用的模板根目录（打包态/开发态均已正确解析）
TEMPLATES_DIR = _TEMPLATES_DIR

# emoji 字体子集（Noto Color Emoji COLRv1，由 tools/make_emoji_font.py 生成）。
# 注入各页面的 @font-face 块：解决老 Win10/Server 缺 Segoe UI Emoji 时的图标豆腐块。
EMOJI_FONTFACE = (
    '@font-face{font-family:"EmojiFallback";'
    'src:url("/font/emoji.woff2") format("woff2");'
    'font-display:block}'
)
FONT_STACK = '"EmojiFallback", system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif'

# 主题注册表：id → {name, swatch}。
# 新增主题 = 在 themes/ 加 <id>.html + 在此注册一项。
# swatch 是前端主题按钮的预览色块（CSS background 值）。
THEMES = {
    "tech-dark": {"name": "深空靛蓝", "swatch": "linear-gradient(135deg,#05070d,#6078ff)"},
    "aurora-pro": {"name": "深空青", "swatch": "linear-gradient(135deg,#04090c,#2dc8be)"},
    "light-simple": {"name": "晨雾浅灰", "swatch": "linear-gradient(135deg,#f4f6fa,#5a78e6)"},
    "light-warm": {"name": "暖沙米白", "swatch": "linear-gradient(135deg,#faf7f2,#c2703d)"},
    "light-mint": {"name": "薄荷浅青", "swatch": "linear-gradient(135deg,#f3faf7,#0e9f7a)"},
    "macos-dock": {"name": "暗夜紫", "swatch": "linear-gradient(135deg,#0a0810,#be8cff)"},
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


def _get_theme(ly: dict) -> str:
    """从 layout.json 内容取用户选择的主题；非法或缺失回退 DEFAULT_THEME。"""
    t = ly.get("theme")
    return t if t in THEMES else DEFAULT_THEME


def _themes_json() -> str:
    """生成前端 THEMES 常量的 JSON 字符串。"""
    arr = [{"id": tid, "name": m["name"], "swatch": m["swatch"]} for tid, m in THEMES.items()]
    return json.dumps(arr, ensure_ascii=False)


def _get_layout(ly: dict) -> str:
    """从 layout.json 内容取用户选择的布局；非法或缺失回退 DEFAULT_LAYOUT。"""
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
    name = _escape(a.get("name", "应用"))
    aid = _escape(a.get("id", ""))
    icon_file = a.get("icon_file")
    if icon_file:
        icon = (f'<img src="/api/app-icon?id={aid}" alt="" '
                f'style="width:64px;height:64px;object-fit:contain" '
                f'onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'block\'">'
                f'<span style="display:none">{_escape(a.get("icon", "📦"))}</span>')
    else:
        icon = _escape(a.get("icon", "📦"))
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
{EMOJI_FONTFACE}
body{{font-family:{FONT_STACK};display:flex;flex-direction:column;align-items:center;
justify-content:center;height:100vh;margin:0;background:linear-gradient(160deg,{color}33,#fff)}}
.ic{{font-size:64px;display:flex;align-items:center;justify-content:center}}p{{color:#999;font-size:13px}}</style></head>
<body><div class="ic">{icon}</div><h2>{name}</h2><p>占位应用 · 待接入</p></body></html>"""


def render_home_html(title, version):
    """构造桌面首页完整 HTML（按 layout.json 的 layout 字段选 layouts/<id>.html）。"""
    from . import layout
    try:
        ly = layout.load_layout()  # 主题与布局共用一次读取
    except Exception:
        ly = {}
    esc_title = _escape(title)
    esc_ver = _escape(version)
    layout_id = _get_layout(ly)
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
            .replace("__THEME__", _get_theme(ly))
            .replace("__THEMES__", _themes_json())
            .replace("__LAYOUTS__", _layouts_json()))
