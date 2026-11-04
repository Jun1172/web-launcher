# -*- coding: utf-8 -*-
"""把 web-launcher 应用转换为 AESA LAUNCHER（RadarDebugSoftware）格式的独立应用。

原理：
- Radar launcher 扫描 apps/ 一级子目录下的 manifest.json，以
  `python backend/main.py`（cwd=应用根）拉起子应用，注入
  LAUNCHER_EMBED / LAUNCHER_SUBAPP_WIDTH / LAUNCHER_SUBAPP_HEIGHT 等环境变量。
- 本工具为指定应用生成一份"转换副本"：manifest.json + backend/main.py shim
  + 应用文件全量拷贝。shim 分配端口 → 子进程运行 app.py（HTTP 服务）→
  pywebview 开窗口指向 http://127.0.0.1:<port>。原应用代码零改动。

用法：
    python tools/make_radar_app.py apps/etws/radar-viewer
    python tools/make_radar_app.py --app apps/etws/radar-viewer --out ../RadarDebugSoftware/apps
    python tools/make_radar_app.py --group etws          # 转换整个分组
    python tools/make_radar_app.py --all                 # 转换所有本地应用
    python tools/make_radar_app.py --app ... --slim      # 排除 docs/images/build

产物默认输出到 dist/radar-apps/<app-id>/（不影响 web-launcher 任何目录）。

前置条件：目标 launcher 的 python_runtime 解释器需已安装 pywebview。
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # web-launcher 仓库根
APPS_DIR = ROOT / "apps"
DEFAULT_OUT = ROOT / "dist" / "radar-apps"

# Radar scanner 的 id 校验规则（launcher/backend/core/scanner.py ID_PATTERN）
ID_PATTERN = re.compile(r"^[a-z0-9.-]+$")

# 始终排除：运行日志 / 缓存 / 版本控制
EXCLUDE_ALWAYS = {"__pycache__", ".git", ".gitignore", "logs"}
EXCLUDE_FILES = {"app-output.log"}
# --slim 额外排除：不影响运行的大体积目录
EXCLUDE_SLIM = {"docs", "doc", "images", "build"}

# ---------------------------------------------------------------
# 子应用 shim 模板（生成到 <out>/<id>/backend/main.py）
# 与 Radar 的子应用约定对齐：自包含、与 launcher 零共享代码。
# ---------------------------------------------------------------
SHIM_TEMPLATE = '''# -*- coding: utf-8 -*-
"""AESA LAUNCHER 子应用 shim —— 由 web-launcher tools/make_radar_app.py 自动生成。

装载约定：launcher 以 `python backend/main.py` 拉起（cwd=应用根），注入
LAUNCHER_EMBED / LAUNCHER_SUBAPP_WIDTH / LAUNCHER_SUBAPP_HEIGHT 等环境变量。

本 shim 职责：
1. 按 manifest.json 的 port（建议端口）分配可用端口，冲突自动回退随机端口
2. 子进程运行 app.py（HTTP 服务），注入 LAUNCHER_APP_PORT / site 依赖环境
3. 轮询端口就绪后，pywebview 开窗口指向 http://127.0.0.1:<port>
   （LAUNCHER_EMBED=1 时以隐藏窗口创建，配合 launcher 内嵌）
4. 窗口关闭后停止 HTTP 服务子进程

应用代码零改动；独立运行：python backend/main.py
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import webview

APP_ROOT = Path(__file__).resolve().parent.parent
READY_TIMEOUT = 15.0
CREATE_NO_WINDOW = 0x08000000


def alloc_port(preferred: int) -> int:
    """优先使用建议端口，被占则分配随机端口（与 web-launcher 同策略）。"""
    if preferred:
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", preferred))
            s.close()
            return preferred
        except OSError:
            pass
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_ready(port: int, timeout: float) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def stop_server(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            flags = CREATE_NO_WINDOW
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, timeout=5, creationflags=flags,
            )
        else:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def main() -> None:
    with open(APP_ROOT / "manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)

    port = alloc_port(int(manifest.get("port") or 0))

    env = os.environ.copy()
    env["LAUNCHER_APP_PORT"] = str(port)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    site = APP_ROOT / "site"
    if site.is_dir():
        env["LAUNCHER_APP_SITE"] = str(site)
        pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (str(site) + os.pathsep + pp) if pp else str(site)

    log_path = APP_ROOT / "logs" / "app-server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log_path, "a", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(
            [sys.executable, str(APP_ROOT / "app.py")],
            cwd=str(APP_ROOT),
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
    finally:
        handle.close()

    if not wait_ready(port, READY_TIMEOUT):
        print("[shim] 应用服务端口就绪超时，进程退出。日志: %s" % log_path, flush=True)
        stop_server(proc)
        sys.exit(1)

    embedded = os.environ.get("LAUNCHER_EMBED") == "1"
    width = int(os.environ.get("LAUNCHER_SUBAPP_WIDTH", 1024))
    height = int(os.environ.get("LAUNCHER_SUBAPP_HEIGHT", 700))

    try:
        webview.create_window(
            manifest.get("name", "app"),
            "http://127.0.0.1:%d" % port,
            width=width,
            height=height,
            hidden=embedded,
        )
        webview.start()
    finally:
        stop_server(proc)


if __name__ == "__main__":
    main()
'''


def find_apps(root: Path) -> list[Path]:
    """递归收集所有含 app.json 的应用目录。"""
    return sorted(p.parent for p in root.glob("**/app.json")
                  if not any(part.startswith(".") or part == "__pycache__"
                             for part in p.relative_to(root).parts))


def resolve_targets(args) -> list[Path]:
    """按 CLI 参数解析待转换应用目录列表（去重）。"""
    targets: list[Path] = []
    if args.app:
        p = Path(args.app)
        if not p.is_absolute():
            p = (ROOT / p)
        if not (p / "app.json").is_file():
            print(f"[ERROR] 应用目录不存在或缺少 app.json: {p}")
            sys.exit(1)
        targets.append(p.resolve())
    if args.group:
        gd = APPS_DIR / args.group
        if not gd.is_dir():
            print(f"[ERROR] 分组目录不存在: {gd}")
            sys.exit(1)
        targets.extend(find_apps(gd))
    if args.all:
        targets.extend(find_apps(APPS_DIR))
    if not targets:
        print("[ERROR] 请用位置参数 / --app / --group / --all 指定要转换的应用。")
        sys.exit(1)
    # 去重保序
    seen, uniq = set(), []
    for t in targets:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def copy_app(src: Path, dst: Path, slim: bool) -> tuple[int, int]:
    """拷贝应用文件，返回 (文件数, 跳过数)。"""
    excludes = set(EXCLUDE_ALWAYS) | (EXCLUDE_SLIM if slim else set())
    n_files = n_skip = 0
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        if any(part in excludes for part in rel.parts):
            n_skip += 1
            continue
        if item.is_file():
            if item.name in EXCLUDE_FILES or item.suffix == ".pyc":
                n_skip += 1
                continue
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            n_files += 1
        elif item.is_dir():
            (dst / rel).mkdir(parents=True, exist_ok=True)
    return n_files, n_skip


def convert(app_dir: Path, out_root: Path, slim: bool, force: bool) -> bool:
    """转换单个应用，成功返回 True。"""
    with open(app_dir / "app.json", "r", encoding="utf-8") as f:
        meta = json.load(f)

    app_id = str(meta.get("id") or app_dir.name)
    if not ID_PATTERN.match(app_id):
        print(f"[ERROR] {app_dir.name}: id 不满足目标格式 ^[a-z0-9.-]+$ -> {app_id}")
        return False

    dst = out_root / app_id
    if dst.exists():
        if not force:
            print(f"[SKIP] {app_id}: 目标已存在（--force 覆盖）: {dst}")
            return False
        shutil.rmtree(dst)
    dst.mkdir(parents=True)

    n_files, n_skip = copy_app(app_dir, dst, slim)

    # manifest.json：Radar scanner 必填 id/name/entry；port 供 shim 使用
    manifest = {
        "id": app_id,
        "name": str(meta.get("name") or app_id),
        "version": str(meta.get("version") or "0.0.0"),
        "icon": "icon.svg" if (dst / "icon.svg").is_file() else "icon.png",
        "entry": "app.py",          # 占位：scanner 校验文件存在；实际加载走 http url
        "port": meta.get("port"),
        "group": meta.get("group"),
        "generator": "web-launcher tools/make_radar_app.py",
    }
    if not (dst / manifest["icon"]).is_file():
        manifest["icon"] = ""       # scanner 回退字母头像
    with open(dst / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")

    # backend/main.py shim
    backend = dst / "backend"
    backend.mkdir(exist_ok=True)
    with open(backend / "main.py", "w", encoding="utf-8", newline="\n") as f:
        f.write(SHIM_TEMPLATE)

    # 产物自检：模拟 Radar scanner 的校验规则
    errs = []
    if not (dst / "app.py").is_file():
        errs.append("entry 指向的 app.py 不存在")
    if not ID_PATTERN.match(manifest["id"]):
        errs.append("id 非法")
    import py_compile
    try:
        py_compile.compile(str(backend / "main.py"), doraise=True)
    except py_compile.PyCompileError as e:
        errs.append(f"shim 编译失败: {e}")

    status = "OK" if not errs else "FAIL"
    print(f"[{status}] {app_id}: {n_files} 个文件 -> {dst}"
          + ("" if not errs else "\n       " + "\n       ".join(errs)))
    return not errs


def main() -> int:
    # 管道输出统一 UTF-8：工具箱按 utf-8 读取子进程输出（Windows 默认 GBK 会乱码）
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="web-launcher 应用 -> AESA LAUNCHER 转换器")
    ap.add_argument("app_path", nargs="?", help="应用目录路径，如 apps/etws/radar-viewer")
    ap.add_argument("--app", dest="app", help="同位置参数")
    ap.add_argument("--group", help="转换整个分组，如 etws")
    ap.add_argument("--all", action="store_true", help="转换 apps/ 下所有应用")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出根目录（默认 dist/radar-apps）")
    ap.add_argument("--slim", action="store_true", help="排除 docs/images/build 等非运行目录")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的产物")
    args = ap.parse_args()

    if args.app_path and not args.app:
        args.app = args.app_path

    out_root = Path(args.out)
    if not out_root.is_absolute():
        out_root = (ROOT / out_root).resolve()

    targets = resolve_targets(args)
    print(f"转换 {len(targets)} 个应用 -> {out_root}" + ("（slim 模式）" if args.slim else ""))

    ok = 0
    for t in targets:
        try:
            if convert(t, out_root, args.slim, args.force):
                ok += 1
        except Exception as e:
            print(f"[ERROR] {t.name}: {e}")
    print(f"完成: {ok}/{len(targets)} 成功。"
          f"将产物目录拷入 RadarDebugSoftware/apps/ 即可被其 launcher 扫描。")
    return 0 if ok == len(targets) else 1


if __name__ == "__main__":
    sys.exit(main())
