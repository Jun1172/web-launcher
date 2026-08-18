"""frontend - 首页 HTML 资源、关于模态、stub 应用占位页

导出:
- render_home_html(title, version, changelog, released): 返回完整首页字符串
- stub_html(app_meta): 返回无进程应用的占位页

前端增强点（FR-4.1, FR-3.x）:
- 状态栏右侧 ⚙️ 齿轮按钮 → 关于模态
- 关于模态显示标题/版本/发布时间/Changelog 列表/检查更新按钮
- Toast 工具函数 showToast()
- 最近任务卡片：上滑跟手 + 淡出动画、全部清除确认、关闭后 toast

HTML 模板存放在 templates/home.html，通过占位符替换注入动态数据，
避免本文件中出现 300+ 行的内联字符串（模块化维护性要求 FR-5.4）。
"""
from pathlib import Path

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_HOME_TEMPLATE_PATH = _TEMPLATES_DIR / "home.html"

# 模板缓存（进程内只读，首次加载后不复用磁盘）
_HOME_TEMPLATE: str | None = None


def _get_home_template() -> str:
    """惰性读取并缓存首页模板 HTML。"""
    global _HOME_TEMPLATE
    if _HOME_TEMPLATE is None:
        _HOME_TEMPLATE = _HOME_TEMPLATE_PATH.read_text(encoding="utf-8")
    return _HOME_TEMPLATE


def _escape(s):
    """HTML 转义：防止 XSS / 布局错乱。"""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;") \
                    .replace(">", "&gt;").replace('"', "&quot;") \
                    .replace("'", "&#39;")


def _changelog_ul(text):
    """把 \\n 分隔的 changelog 文本转为 <ul><li>... 列表（每行转义）。"""
    if not text:
        return "<li style='opacity:.5'>暂无更新说明</li>"
    lines = [ln.strip("-• \t") for ln in text.split("\n") if ln.strip()]
    if not lines:
        return "<li style='opacity:.5'>暂无更新说明</li>"
    return "".join(f"<li>{_escape(ln)}</li>" for ln in lines)


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


def render_home_html(title, version, changelog, released):
    """构造桌面首页完整 HTML（从 templates/home.html 模板 + 占位符替换）。"""
    esc_title = _escape(title)
    esc_ver = _escape(version)
    esc_rel = _escape(released)
    cl_html = _changelog_ul(changelog)
    tpl = _get_home_template()
    return (tpl
            .replace("__TITLE__", esc_title)
            .replace("__VERSION__", esc_ver)
            .replace("__RELEASED__", esc_rel)
            .replace("__CHANGELOG_HTML__", cl_html))
