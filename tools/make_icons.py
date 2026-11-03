# -*- coding: utf-8 -*-
"""批量生成应用图标（统一风格：深色磨砂底 + 应用色微光 + 细线图形）。

与系统应用图标同一设计语言：
- 底板 #222942 → #141a2c 深色渐变，左上角应用色 22% 微光晕染
- 图形 2.6px 细线，颜色 = 应用色提亮 45%（深色底上保证可读性）

用法:
    python tools/make_icons.py            # 生成全部（已存在 icon.svg 的会覆盖）
    python tools/make_icons.py --check    # 只检查哪些应用缺图标

新应用接入：在 GLYPHS 表里加一行（key = 应用目录名），重跑即可。
"""
import json
import sys
from pathlib import Path

ROOTS = [
    Path(r"c:\Users\jun\Desktop\xieyi\web-launcher\apps\etws"),
    Path(r"c:\Users\jun\Desktop\xieyi\web-launcher\apps\user"),
    Path(r"c:\Users\jun\Desktop\xieyi\web-launcher-apps\apps\game"),
    Path(r"c:\Users\jun\Desktop\xieyi\web-launcher-apps\apps\general"),
    Path(r"c:\Users\jun\Desktop\xieyi\web-launcher-apps\apps\ros"),
]

# ── 图形库：key = 应用目录名，value = <g> 内的 SVG 元素（64x64 视口）──
GLYPHS = {
    # ─── etws ───
    "ad-analysis":
        '<path d="M14 34h7l3-10 5 18 4-12 3 4h14"/>'
        '<circle cx="46" cy="19" r="3.5" fill="{c}" stroke="none"/>',
    "channel-analyse":
        '<path d="M21 16v32M32 16v32M43 16v32"/>'
        '<circle cx="21" cy="38" r="4"/><circle cx="32" cy="24" r="4"/><circle cx="43" cy="34" r="4"/>',
    "iq-monitor":
        '<path d="M14 32c5-6.5 11-9.5 18-9.5S45 25.5 50 32c-5 6.5-11 9.5-18 9.5S19 38.5 14 32z"/>'
        '<circle cx="32" cy="32" r="5.5"/>',
    "iq-record":
        '<circle cx="32" cy="32" r="16"/>'
        '<circle cx="32" cy="32" r="6.5" fill="{c}" stroke="none"/>',
    "iqcache-sync":
        '<path d="M20 27a13 13 0 0 1 22-5M44 37a13 13 0 0 1-22 5"/>'
        '<path d="M42 14v8h-8M22 50v-8h8"/>',
    "leixiang-monitor":
        '<path d="M32 22v26M24 48h16M32 22l-6 8M32 22l6 8"/>'
        '<path d="M18 30c-3-4-3-10 0-14M46 30c3-4 3-10 0-14" stroke-opacity="0.6"/>',
    "mqtt-monitor":
        '<rect x="20" y="20" width="24" height="24" rx="4"/>'
        '<path d="M26 20v-5M32 20v-5M38 20v-5M26 49v-5M32 49v-5M38 49v-5M20 26h-5M20 32h-5M20 38h-5M49 26h-5M49 32h-5M49 38h-5"/>'
        '<circle cx="32" cy="32" r="3.5" fill="{c}" stroke="none"/>',
    "noise-consistency":
        '<path d="M14 24h36" stroke-dasharray="4 4" stroke-opacity="0.55"/>'
        '<path d="M14 34c3-2.5 4.5 2.5 7.5 0s4.5 2.5 7.5 0 4.5 2.5 7.5 0 4.5 2.5 7.5 0 4.5 2.5 6 0"/>'
        '<path d="M14 44h36" stroke-dasharray="4 4" stroke-opacity="0.55"/>',
    "radar-viewer":
        '<circle cx="32" cy="32" r="17"/>'
        '<circle cx="32" cy="32" r="9" stroke-opacity="0.55"/>'
        '<path d="M32 32L44 20"/>'
        '<circle cx="39" cy="37" r="2.5" fill="{c}" stroke="none"/>'
        '<circle cx="25" cy="25" r="2" fill="{c}" stroke="none" fill-opacity="0.6"/>',
    "wave-tcp":
        '<path d="M14 26c4 0 4 12 8 12s4-12 8-12 4 12 8 12 4-12 8-12"/>'
        '<path d="M18 46h28M22 52h20" stroke-opacity="0.55"/>',
    "wave-udp":
        '<path d="M14 26c4 0 4 12 8 12s4-12 8-12 4 12 8 12 4-12 8-12"/>'
        '<circle cx="20" cy="47" r="3"/><circle cx="44" cy="47" r="3"/>'
        '<path d="M23 47h18" stroke-dasharray="3 3" stroke-opacity="0.7"/>',
    # ─── user ───
    "cpp-hello":
        '<path d="M25 21L14 32l11 11M39 21l11 11-11 11"/>',
    "cron-ui":
        '<rect x="15" y="18" width="34" height="30" rx="4"/>'
        '<path d="M15 26h34M24 14v6M40 14v6"/>'
        '<circle cx="32" cy="37" r="6.5"/><path d="M32 33.5V37l2.5 1.8"/>',
    "game2048":
        '<rect x="15" y="15" width="15" height="15" rx="3.5"/>'
        '<rect x="34" y="15" width="15" height="15" rx="3.5"/>'
        '<rect x="15" y="34" width="15" height="15" rx="3.5"/>'
        '<rect x="34" y="34" width="15" height="15" rx="3.5" fill="{c}" fill-opacity="0.35"/>',
    "hello":
        '<circle cx="32" cy="32" r="17"/>'
        '<circle cx="26" cy="28" r="1.8" fill="{c}" stroke="none"/>'
        '<circle cx="38" cy="28" r="1.8" fill="{c}" stroke="none"/>'
        '<path d="M24 37c2.5 3 5.5 4.5 8 4.5s5.5-1.5 8-4.5"/>',
    "log-viewer":
        '<path d="M19 14h18l8 8v28H19z"/>'
        '<path d="M37 14v8h8"/>'
        '<path d="M25 30h14M25 36h14M25 42h9"/>',
    "nixie-clock":
        '<rect x="23" y="12" width="18" height="40" rx="9"/>'
        '<path d="M27 12h-4M41 12h-4M27 52h-4M41 52h-4"/>'
        '<circle cx="32" cy="26" r="5"/><circle cx="32" cy="38" r="5"/>',
    "system-monitor":
        '<path d="M16 40a17 17 0 1 1 32 0"/>'
        '<path d="M32 40l8-10"/>'
        '<circle cx="32" cy="40" r="3"/>'
        '<path d="M16 46h32" stroke-opacity="0.55"/>',
    "todo":
        '<path d="M20 16l3 3 5-6M20 30l3 3 5-6M20 44l3 3 5-6"/>'
        '<path d="M34 17h14M34 31h14M34 45h14"/>',
    "weather":
        '<circle cx="40" cy="22" r="6"/><path d="M40 12v3M48 16l-2 2M50 22h-3" stroke-opacity="0.7"/>'
        '<path d="M20 42a8 8 0 0 1 2-15.7A10 10 0 0 1 41 30a7 7 0 0 1-1 14H20z"/>',
    # ─── game ───
    "breakout":
        '<rect x="16" y="14" width="9" height="5" rx="1.5"/><rect x="28" y="14" width="9" height="5" rx="1.5"/><rect x="40" y="14" width="9" height="5" rx="1.5"/>'
        '<circle cx="36" cy="34" r="3.5"/>'
        '<path d="M20 46h24"/>',
    "coin-flip":
        '<circle cx="32" cy="32" r="16"/>'
        '<circle cx="32" cy="32" r="10" stroke-opacity="0.6"/>'
        '<path d="M27 27l10 10M37 27L27 37"/>',
    "cyber-wood-fish":
        '<path d="M16 34c0-8 7-14 16-14s16 6 16 14c0 5-3 9-7 11H23c-4-2-7-6-7-11z"/>'
        '<path d="M16 34h32"/>'
        '<path d="M42 14l8-6M44 18l8-3" stroke-opacity="0.7"/>',
    "desktop-pet":
        '<ellipse cx="32" cy="38" rx="9" ry="7"/>'
        '<ellipse cx="21" cy="26" rx="3.5" ry="4.5"/><ellipse cx="30" cy="21" rx="3.5" ry="4.5"/>'
        '<ellipse cx="39" cy="21" rx="3.5" ry="4.5"/><ellipse cx="45" cy="27" rx="3.5" ry="4.5"/>',
    "flappy-bird":
        '<circle cx="30" cy="34" r="12"/>'
        '<path d="M22 30c-4-2-7-2-10 1M40 30l10-4-2 6z"/>'
        '<circle cx="33" cy="31" r="1.8" fill="{c}" stroke="none"/>'
        '<path d="M26 40c2 2 5 3 8 2"/>',
    "key-tester":
        '<rect x="15" y="18" width="34" height="28" rx="6"/>'
        '<rect x="23" y="26" width="18" height="12" rx="3"/>',
    "life":
        '<circle cx="21" cy="21" r="3" fill="{c}" stroke="none"/>'
        '<circle cx="32" cy="21" r="3"/><circle cx="43" cy="21" r="3" fill="{c}" stroke="none"/>'
        '<circle cx="21" cy="32" r="3"/><circle cx="32" cy="32" r="3" fill="{c}" stroke="none"/><circle cx="43" cy="32" r="3"/>'
        '<circle cx="21" cy="43" r="3" fill="{c}" stroke="none"/><circle cx="32" cy="43" r="3"/><circle cx="43" cy="43" r="3" fill="{c}" stroke="none"/>',
    "link-match":
        '<rect x="14" y="16" width="14" height="14" rx="3"/>'
        '<rect x="36" y="34" width="14" height="14" rx="3"/>'
        '<path d="M28 23h10v11"/>',
    "memory-match":
        '<rect x="15" y="20" width="18" height="24" rx="3.5" transform="rotate(-8 24 32)"/>'
        '<rect x="31" y="20" width="18" height="24" rx="3.5" transform="rotate(8 40 32)"/>'
        '<path d="M36 30l2 4 4 .5-3 3 .8 4.5-3.8-2-3.8 2 .8-4.5-3-3 4-.5z" fill="{c}" stroke="none"/>',
    "snake":
        '<path d="M16 42c0-6 5-8 10-8s10 2 10-4-5-8-10-8h-4"/>'
        '<circle cx="22" cy="22" r="4"/>'
        '<circle cx="46" cy="44" r="3.5" fill="{c}" stroke="none"/>'
        '<circle cx="21" cy="21" r="1.2" fill="{c}" stroke="none"/>',
    "sokoban":
        '<rect x="14" y="22" width="18" height="18" rx="2.5"/>'
        '<path d="M18 26l10 10M28 26L18 36"/>'
        '<circle cx="43" cy="41" r="7"/><circle cx="43" cy="41" r="2.5" fill="{c}" stroke="none"/>',
    "tetris":
        '<rect x="16" y="34" width="10" height="10" rx="2"/><rect x="27" y="34" width="10" height="10" rx="2"/>'
        '<rect x="38" y="34" width="10" height="10" rx="2"/><rect x="38" y="23" width="10" height="10" rx="2"/>',
    # ─── general ───
    "file-demo":
        '<path d="M20 14h16l8 8v28H20z"/>'
        '<path d="M36 14v8h8"/>'
        '<path d="M26 36l4 4 8-8"/>',
    "ip-scanner":
        '<circle cx="32" cy="32" r="4"/>'
        '<path d="M32 20a12 12 0 0 1 8.5 3.5M32 44a12 12 0 0 1-8.5-3.5" stroke-opacity="0.7"/>'
        '<circle cx="45" cy="25" r="3"/><circle cx="19" cy="39" r="3"/>',
    "json-tool":
        '<path d="M26 16c-6 0-7 4-7 9s1 7-3 7 3 2 3 7 1 9 7 9"/>'
        '<path d="M38 16c6 0 7 4 7 9s-1 7 3 7-3 2-3 7-1 9-7 9"/>',
    "lan-talk":
        '<path d="M14 20a6 6 0 0 1 6-6h12a6 6 0 0 1 6 6v6a6 6 0 0 1-6 6H24l-6 5v-5h-2a6 6 0 0 1-2-.4V20z"/>'
        '<path d="M42 30h4a6 6 0 0 1 6 6v4a6 6 0 0 1-6 6h-2v4l-5-4h-7" stroke-opacity="0.7"/>',
    "mqtt-debug":
        '<circle cx="32" cy="42" r="4" fill="{c}" stroke="none"/>'
        '<path d="M24 34a11 11 0 0 1 16 0M18 27a19 19 0 0 1 28 0" />',
    "net-diag":
        '<circle cx="32" cy="32" r="17"/>'
        '<path d="M15 32h34M32 15c-5 5-7 10-7 17s2 12 7 17c5-5 7-10 7-17s-2-12-7-17z"/>',
    "notes":
        '<rect x="17" y="14" width="30" height="34" rx="3"/>'
        '<path d="M17 14l8 8h-8zM24 30h16M24 36h16M24 42h10"/>',
    "ping-tool":
        '<path d="M14 32h8l4-11 7 22 4-11h13"/>',
    "port-scanner":
        '<rect x="15" y="18" width="10" height="10" rx="2"/><rect x="29" y="18" width="10" height="10" rx="2"/><rect x="43" y="18" width="10" height="10" rx="2" stroke-opacity="0.5"/>'
        '<rect x="15" y="34" width="10" height="10" rx="2"/><rect x="29" y="34" width="10" height="10" rx="2" stroke-opacity="0.5"/><rect x="43" y="34" width="10" height="10" rx="2"/>'
        '<path d="M13 50l38-38" stroke-opacity="0.7"/>',
    "proc-demo":
        '<rect x="24" y="12" width="16" height="10" rx="2.5"/>'
        '<rect x="12" y="38" width="16" height="10" rx="2.5"/><rect x="36" y="38" width="16" height="10" rx="2.5"/>'
        '<path d="M28 22v8h-8v8M36 22v8h8v8"/>',
    "tcp-debug":
        '<rect x="12" y="24" width="14" height="14" rx="3"/><rect x="38" y="24" width="14" height="14" rx="3"/>'
        '<path d="M26 31h12M34 27l4 4-4 4"/>',
    "udp-debug":
        '<rect x="12" y="24" width="14" height="14" rx="3"/><rect x="38" y="24" width="14" height="14" rx="3"/>'
        '<path d="M26 31h12" stroke-dasharray="3 3"/>'
        '<path d="M28 24l3-3M31 24l3-3M34 24l3-3" stroke-opacity="0.7"/>',
    # ─── ros ───
    "ros2-action":
        '<circle cx="32" cy="32" r="16"/><circle cx="32" cy="32" r="9"/>'
        '<circle cx="32" cy="32" r="3" fill="{c}" stroke="none"/>',
    "ros2-graph":
        '<circle cx="20" cy="20" r="5"/><circle cx="44" cy="20" r="5"/>'
        '<circle cx="20" cy="44" r="5"/><circle cx="44" cy="44" r="5"/>'
        '<path d="M25 20h14M25 44h14M20 25v14M44 25v14M24 24l16 16"/>',
    "ros2-monitor":
        '<rect x="14" y="14" width="36" height="24" rx="4"/>'
        '<path d="M26 47h12M32 38v9"/>'
        '<circle cx="22" cy="23" r="2" fill="{c}" stroke="none"/><circle cx="30" cy="23" r="2" fill="{c}" stroke="none" fill-opacity="0.7"/><circle cx="38" cy="23" r="2" fill="{c}" stroke="none" fill-opacity="0.4"/>'
        '<path d="M20 31h24" stroke-opacity="0.6"/>',
    "ros2-param":
        '<path d="M16 22h32M16 32h32M16 42h32"/>'
        '<circle cx="26" cy="22" r="4"/><circle cx="38" cy="32" r="4"/><circle cx="30" cy="42" r="4"/>',
    "ros2-service":
        '<rect x="12" y="24" width="14" height="14" rx="3"/><rect x="38" y="24" width="14" height="14" rx="3"/>'
        '<path d="M26 28h9M35 25l3 3-3 3M38 34h-9M29 31l-3 3 3 3"/>',
    "ros2-topic-inspector":
        '<path d="M14 24h30M44 20l6 4-6 4"/>'
        '<path d="M14 34h22M36 34h8" stroke-opacity="0.7"/>'
        '<path d="M14 44h30M44 40l6 4-6 4" stroke-opacity="0.85"/>',
    "ros2-type-studio":
        '<path d="M14 26c4 0 4 10 8 10s4-10 8-10 4 10 8 10 4-10 8-10"/>'
        '<path d="M18 44v6M26 42v8M34 45v5M42 41v9" stroke-opacity="0.7"/>',
}

SVG_TPL = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#222942"/><stop offset="1" stop-color="#141a2c"/>
    </linearGradient>
    <radialGradient id="tint" cx="0.3" cy="0.2" r="0.9">
      <stop offset="0" stop-color="{color}" stop-opacity="0.22"/><stop offset="1" stop-color="{color}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="64" height="64" rx="15" fill="url(#bg)"/>
  <rect width="64" height="64" rx="15" fill="url(#tint)"/>
  <g fill="none" stroke="{glyph_color}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round">
    {glyph}
  </g>
</svg>
"""


def lighten(hex_color, ratio=0.45):
    """应用色与白色按比例混合，深色底板上保证细线可读。"""
    h = (hex_color or "#888888").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        r, g, b = 136, 136, 136
    r = round(r + (255 - r) * ratio)
    g = round(g + (255 - g) * ratio)
    b = round(b + (255 - b) * ratio)
    return "#%02x%02x%02x" % (r, g, b)


def main():
    check_only = "--check" in sys.argv
    made, skipped, missing = [], [], []
    for root in ROOTS:
        if not root.is_dir():
            continue
        for app_dir in sorted(p for p in root.iterdir() if (p / "app.json").is_file()):
            name = app_dir.name
            try:
                meta = json.loads((app_dir / "app.json").read_text(encoding="utf-8"))
            except Exception:
                continue
            color = meta.get("color", "#888888")
            glyph = GLYPHS.get(name)
            if not glyph:
                missing.append(f"{root.name}/{name}")
                continue
            if check_only:
                made.append(f"{root.name}/{name}")
                continue
            svg = SVG_TPL.format(color=color, glyph_color=lighten(color),
                                 glyph=glyph.replace("{c}", lighten(color)))
            (app_dir / "icon.svg").write_text(svg, encoding="utf-8")
            made.append(f"{root.name}/{name}")

    print(f"{'涉及' if check_only else '已生成'} {len(made)} 个图标")
    if missing:
        print(f"⚠ 缺少图形定义的 {len(missing)} 个应用（在 GLYPHS 表中补充后重跑）:")
        for m in missing:
            print("   -", m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
