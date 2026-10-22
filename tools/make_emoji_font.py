# -*- coding: utf-8 -*-
"""make_emoji_font - 重新生成 launcher 内置 emoji 字体子集

背景：
  桌面图标是 app.json 的 emoji 字符，渲染依赖系统 Segoe UI Emoji 字体。
  老 Win10 / Windows Server 的该字体缺失或字形陈旧（不随系统更新），
  新 emoji 显示为豆腐块（前科：🦾 → cpp-hello changelog）。
  方案：随 launcher 打包一个 Noto Color Emoji COLRv1 子集（woff2，~85KB），
  经 @font-face("EmojiFallback") 注入页面，不再依赖目标机字体。

用法（需要 fonttools + brotli）：
  pip install fonttools brotli
  python tools/make_emoji_font.py

流程：
  1. 扫描 launcher 源码 + templates + 全部 app.json，收集实际用到的 emoji 码点
  2. 从 tools/fonts/NotoColorEmoji-COLRv1.ttf 子集化（缺失时自动从
     google/fonts 仓库下载，约 24MB）
  3. 输出 launcher/templates/fonts/emoji-subset.woff2
     （由 http_handler 的 /font/emoji.woff2 路由 + _shared.css 的 @font-face 消费）

新增应用图标后重跑本脚本即可覆盖新码点。
"""
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # web-launcher/
SRC_FULL = ROOT / "tools" / "fonts" / "NotoColorEmoji-COLRv1.ttf"
OUT_WOFF2 = ROOT / "launcher" / "templates" / "fonts" / "emoji-subset.woff2"
DOWNLOAD_URL = ("https://raw.githubusercontent.com/google/fonts/main/"
                "ofl/notocoloremoji/NotoColorEmoji-Regular.ttf")

# emoji/符号扫描范围： arrows..misc symbols(2190-2BFF)、supplemental symbols(1F000-1FBFF)
# 以及 VS16/ZWJ/Keycap 组合符；CJK/全角等中文文本字符不在此范围，不会误收。
EMOJI_RANGES = [(0x2190, 0x2BFF), (0x1F000, 0x1FBFF)]
VS_ZWJ = {0xFE0F, 0x200D, 0x20E3}


def is_emoji_char(ch):
    cp = ord(ch)
    if cp in VS_ZWJ:
        return True
    return any(a <= cp <= b for a, b in EMOJI_RANGES)


def scan_chars():
    """扫描 launcher 源码、模板与全部 app.json，收集实际用到的 emoji 字符。"""
    files = [ROOT / "launcher" / f for f in (
        "frontend.py", "http_handler.py", "app_registry.py", "app_operations.py",
        "updater.py", "layout.py", "config.py", "__main__.py",
        "process_manager.py", "repo.py", "zipio.py", "deps_installer.py",
    )]
    files += list((ROOT / "launcher" / "templates").rglob("*"))
    files += list(ROOT.glob("apps/*/*/app.json"))
    found = set()
    for p in files:
        if not p.is_file() or p.suffix in (".pyc", ".bin", ".png", ".jpg",
                                           ".ico", ".pdf", ".db", ".woff2"):
            continue
        try:
            txt = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found.update(ch for ch in txt if is_emoji_char(ch))
    # VS16 / ZWJ 兜底（FE0F 序列如 ⏱️ ⚙️ 🛰️ 🌤️）
    found.update(chr(c) for c in VS_ZWJ)
    return sorted(found)


def ensure_full_font():
    if SRC_FULL.is_file() and SRC_FULL.stat().st_size > 1024 * 1024:
        return
    print(f"[下载] 完整字体不存在，从 {DOWNLOAD_URL} 下载（约 24MB）...")
    SRC_FULL.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(DOWNLOAD_URL, SRC_FULL)
    print(f"[下载] 完成 -> {SRC_FULL}")


def build(chars):
    from fontTools.subset import Subsetter, Options, load_font, save_font

    opts = Options()
    opts.flavor = "woff2"
    opts.layout_features = ["*"]        # 保留 GSUB（VS16 序列/ligature）
    opts.hinting = False
    opts.ignore_missing_unicodes = True  # 排版符号(→ ≤ 制表符) Noto 有意不做，交给系统字体

    font = load_font(str(SRC_FULL), opts)
    ss = Subsetter(options=opts)
    ss.populate(text="".join(chars))
    ss.subset(font)
    OUT_WOFF2.parent.mkdir(parents=True, exist_ok=True)
    save_font(font, str(OUT_WOFF2), opts)
    print(f"[输出] {OUT_WOFF2}  ({OUT_WOFF2.stat().st_size // 1024} KB, {len(chars)} 字符)")


def verify(chars):
    from fontTools.ttLib import TTFont
    f = TTFont(str(OUT_WOFF2))
    cmap = f.getBestCmap()
    missing = [f"U+{ord(c):04X}({c})" for c in chars
               if ord(c) not in cmap and ord(c) not in VS_ZWJ]
    # VS16 无 cmap 条目属正常（变体选择子经 GSUB 处理）
    print(f"[校验] 字形数 {f['maxp'].numGlyphs} | COLR {'有' if 'COLR' in f else '无'}")
    if missing:
        print("[校验] 以下码点无字形（如为排版符号可忽略，emoji 则需检查）:")
        for m in missing:
            print("   ", m)
    else:
        print("[校验] 全部 emoji 码点均已覆盖")


def main():
    chars = scan_chars()
    print(f"[扫描] 收集到 {len(chars)} 个字符: {''.join(chars)}")
    ensure_full_font()
    build(chars)
    verify(chars)


if __name__ == "__main__":
    sys.exit(main())
