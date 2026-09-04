# -*- coding: utf-8 -*-
"""下载应用依赖 wheels，供离线部署使用。

产出 wheels/<平台标签>/ 目录，launcher 的 deps_installer 在装应用时会优先
从这里离线安装（pip install --no-index --find-links），无需联网。

依赖清单**不写死在脚本里**，而是自动扫描两个仓库所有 app.json 的 deps 字段：
    web-launcher/apps/*/*/app.json
    ../web-launcher-apps/apps/*/*/app.json   （存在时）

用法:
    python make_wheels.py                  # 按当前平台下载
    python make_wheels.py --platform win-x64
    python make_wheels.py --platform linux-arm64
    python make_wheels.py --deps paramiko requests   # 手动指定（跳过扫描）

说明:
    下载的 wheel 必须与内嵌 runtime 的 Python 版本、CPU 架构匹配，
    因此脚本会先探测 runtime/win-x64/python.exe 的真实版本（默认 3.11）。
    runtime 不存在时回退到 PY_VER 常量。
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WHEELS = HERE / "wheels"

# runtime 缺失时的回退版本（应与 make_runtime.py 的 PY_VER 保持一致）
PY_VER = "3.11.9"

# 平台标签 → pip 的 --platform 参数
PLATFORMS = {
    "win-x64": ["win_amd64"],
    "win-x86": ["win32"],
    "linux-x64": ["manylinux2014_x86_64", "manylinux_2_17_x86_64"],
    "linux-arm64": ["manylinux2014_aarch64", "manylinux_2_17_aarch64"],
}


def detect_platform():
    """按当前机器推断平台标签（与 launcher/deps_installer.py 保持一致）。"""
    if os.name == "nt":
        return "win-x64"
    import platform
    m = platform.machine().lower()
    if m.startswith(("aarch", "arm")) and sys.maxsize > 2 ** 32:
        return "linux-arm64"
    return "linux-x64"


def detect_python_tag():
    """探测内嵌 runtime 的 Python 版本标签，如 311。

    优先用 runtime/win-x64/python.exe 的真实版本，确保 wheel 与 runtime 匹配。
    """
    rt = HERE / "runtime" / "win-x64" / "python.exe"
    if rt.is_file():
        try:
            out = subprocess.run(
                [str(rt), "-c", "import sys;print('%d%d' % sys.version_info[:2])"],
                capture_output=True, text=True, timeout=30,
            )
            tag = (out.stdout or "").strip()
            if tag.isdigit():
                print("[信息] 检测到内嵌 runtime: Python %s.%s" % (tag[0], tag[1:]))
                return tag
        except Exception:
            pass
    tag = "".join(PY_VER.split(".")[:2])
    print("[信息] 未找到 runtime，回退到 make_runtime.py 的 PY_VER=%s (标签 %s)" % (PY_VER, tag))
    return tag


def collect_deps():
    """扫描两个仓库所有 app.json，汇总 deps 字段（去重、保序）。"""
    roots = [HERE / "apps"]
    sibling = HERE.parent / "web-launcher-apps" / "apps"
    if sibling.is_dir():
        roots.append(sibling)

    deps, sources = [], {}
    for root in roots:
        for aj in sorted(root.glob("*/*/app.json")):
            try:
                meta = json.loads(aj.read_text(encoding="utf-8"))
            except Exception as e:
                print("[警告] 跳过无法解析的 %s: %s" % (aj, e))
                continue
            for d in meta.get("deps") or []:
                d = str(d).strip()
                if d and d not in deps:
                    deps.append(d)
                    sources.setdefault(d, []).append(meta.get("id", aj.parent.name))

    return deps, sources


def main():
    ap = argparse.ArgumentParser(description="下载应用依赖 wheels 供离线部署")
    ap.add_argument("--platform", choices=sorted(PLATFORMS),
                    default=None, help="目标平台（默认按当前机器推断）")
    ap.add_argument("--deps", nargs="*", default=None,
                    help="手动指定依赖，跳过 app.json 扫描")
    ap.add_argument("--python-version", default=None,
                    help="目标 Python 标签，如 311（默认探测 runtime）")
    args = ap.parse_args()

    plat = args.platform or detect_platform()
    py_tag = args.python_version or detect_python_tag()
    out_dir = WHEELS / plat

    if args.deps:
        deps, sources = list(args.deps), {}
        print("[信息] 使用命令行指定的依赖: %s" % ", ".join(deps))
    else:
        deps, sources = collect_deps()

    if not deps:
        print("[完成] 没有任何应用声明 deps，无需下载 wheels。")
        print("       应用如需依赖，在 app.json 里加 \"deps\": [\"paramiko\"] 即可。")
        return 0

    print()
    print("目标平台 : %s" % plat)
    print("Python   : cp%s" % py_tag)
    print("输出目录 : %s" % out_dir)
    print("依赖清单 :")
    for d in deps:
        who = sources.get(d)
        print("   - %-24s %s" % (d, ("← " + ", ".join(who)) if who else "(命令行指定)"))
    print()

    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [sys.executable, "-m", "pip", "download",
           "-d", str(out_dir),
           "--only-binary=:all:",
           "--python-version", py_tag,
           "--implementation", "cp"] + deps

    # manylinux 需要按备选顺序试；Windows 只有一个标签
    for pip_plat in PLATFORMS[plat]:
        cmd = cmd + ["--platform", pip_plat]
        break
    # 其余备选平台作为 --platform 追加（pip 支持多个）
    for extra in PLATFORMS[plat][1:]:
        cmd = cmd + ["--platform", extra]

    print("[运行] %s\n" % " ".join(cmd))
    r = subprocess.run(cmd)

    if r.returncode != 0:
        print("\n[失败] pip download 返回 %d" % r.returncode)
        print("常见原因：该平台/Python 版本没有预编译 wheel（需 --no-binary 源码构建）。")
        return 1

    files = sorted(p for p in out_dir.iterdir() if p.is_file())
    total = sum(p.stat().st_size for p in files)
    print("\n[完成] %s：%d 个 wheel，%.1f MB" % (out_dir, len(files), total / 1048576.0))
    for p in files:
        print("   %s" % p.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
