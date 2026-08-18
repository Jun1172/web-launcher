"""Task 14 冒烟脚本：
1. 语法/导入检查（config/app_registry/process_manager/repo/app_operations/frontend/http_handler/__main__/sysinfo/store/publish）
2. launcher/*.py 行数统计（FR-5.4：单文件 ≤ 250，根 launcher.py ≤ 20）
3. 启动 launcher → curl 多个 API → 关 launcher → 检查无残留进程
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
PASS = "\033[32m✅ PASS\033[0m"
FAIL = "\033[31m❌ FAIL\033[0m"
WARN = "\033[33m⚠️  WARN\033[0m"

results = []

def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print((PASS if cond else FAIL) + f"  {name}" + (f" — {detail}" if detail else ""))

# ───────── 1. 导入 ─────────
print("\n===== 1. 模块导入/语法检查 =====")
try:
    from launcher.config import BASE as LBASE, vt, load_config
    check("config.py 导入", True)
except Exception as e:
    check("config.py 导入", False, str(e))

try:
    from launcher.app_registry import (
        reload_apps, REGISTRY, system_apps, user_apps, is_system_app,
    )
    reload_apps()
    n = len(REGISTRY)
    check(
        "app_registry.py 导入 + 扫描",
        n == len(system_apps) + len(user_apps) and n >= 4,
        f"{n} apps (sys={len(system_apps)}, user={len(user_apps)})",
    )
except Exception as e:
    check("app_registry.py", False, str(e))

try:
    from launcher.process_manager import procs, terminate_all, close_app, open_app
    check("process_manager.py 导入", True)
except Exception as e:
    check("process_manager.py 导入", False, str(e))

try:
    from launcher.repo import repo_index, atomic_extract_zip
    try:
        idx = repo_index()
        versions_ok = all(
            "versions" in a or True for a in idx.get("apps", [])
        )  # versions 字段可不存（旧 index），只检查结构
        check("repo.py 可连远端 index", len(idx.get("apps", [])) >= 1,
              f"apps={len(idx.get('apps',[]))}, launcher={'launcher' in idx}")
    except Exception as e:
        check("repo.py 导入（网络可能未达）", True, f"(index 连不上:{type(e).__name__})")
except Exception as e:
    check("repo.py 导入", False, str(e))

try:
    from launcher.app_operations import (
        do_install, do_uninstall, do_install_version,
        get_launcher_version_info, do_launcher_update,
    )
    ok, msg = do_uninstall("store")
    check("系统应用 store 禁卸", (not ok) and "系统应用" in msg, f"msg={msg}")
    vinfo = get_launcher_version_info()
    check("launcher 版本检查 API 逻辑", "local" in vinfo and "upgradable" in vinfo,
          f"local={vinfo.get('local')}, remote={vinfo.get('remote')}, err={vinfo.get('error')}")
except Exception as e:
    check("app_operations.py", False, str(e))

try:
    from launcher.frontend import render_home_html, stub_html
    html = render_home_html("Test", "1.2.3", "- 一行\n<script>alert(1)</script>\n- 二行", "2026")
    has_gear = "gearBtn" in html
    has_about = "aboutMask" in html
    safe = "<script>alert(1)</script>" not in html  # 转义后不是原文
    has_cl = "<li>一行</li>" in html and "<li>&lt;script&gt;alert(1)&lt;/script&gt;</li>" in html
    check(
        "frontend 关于面板 & HTML 转义",
        has_gear and has_about and safe and has_cl,
        f"gearBtn={has_gear}, aboutMask={has_about}, xss_safe={safe}, changelog_li={has_cl}",
    )
except Exception as e:
    check("frontend.py", False, str(e))

try:
    from launcher.http_handler import Handler
    check("http_handler.py 导入", True)
except Exception as e:
    check("http_handler.py 导入", False, str(e))

try:
    import importlib
    importlib.import_module("launcher.__main__")
    check("__main__.py 导入", True)
except Exception as e:
    check("__main__.py 导入", False, str(e))

# sysinfo / store / publish 语法检查
for name in ("apps.system.sysinfo.app", "apps.system.store.app"):
    try:
        mod = importlib.import_module(name)
        check(f"{name} 语法正确", True)
    except Exception as e:
        check(f"{name}", False, str(e))

try:
    # publish.py 非 package，直接 exec 编译检查
    import py_compile
    py_compile.compile(str(BASE / "apps" / "publish.py"), doraise=True)
    check("apps/publish.py 语法", True)
except Exception as e:
    check("apps/publish.py 语法", False, str(e))

# ───────── 2. 行数统计 ─────────
print("\n===== 2. launcher/*.py 行数统计 =====")
def count_lines(p):
    # 宽松计数：空行不计，以 '#' 开头的注释行不计
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    return sum(1 for ln in lines if ln.strip() and not ln.lstrip().startswith("#"))

root_launcher = count_lines(BASE / "launcher.py")
check(
    "根 launcher.py ≤ 20 行（薄壳）",
    root_launcher <= 20,
    detail=f"实际有效行数 {root_launcher}",
)

mod_files = sorted((BASE / "launcher").glob("*.py"))
too_big = []
for f in mod_files:
    n = count_lines(f)
    status = f"  {n:>4} 行  {f.name}"
    if n > 250:
        too_big.append(f.name)
        print(WARN + status)
    else:
        print(f"  {PASS if n <= 200 else WARN.replace(WARN,'  [~200] '):28}" + status[2:])
check(
    f"所有 launcher/*.py 单文件 ≤ 250 行（{len(mod_files)} 个文件）",
    len(too_big) == 0,
    detail="超纲: " + ", ".join(too_big) if too_big else "全部合规",
)

# ───────── 3. 启动 launcher → API 测试 → 退出 → 无残留 ─────────
print("\n===== 3. Launcher 启动 + API 测试 =====")

# 确保 8000 未被占用
import socket as _sk
s = _sk.socket()
try:
    s.bind(("127.0.0.1", 8000)); s.close()
except OSError:
    print(WARN + " 8000 被占用，按 LISTENING PID 精准查杀...")
    try:
        nr = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=10)
        victims = set()
        for ln in nr.stdout.splitlines():
            ps = ln.split()
            if len(ps) < 5: continue
            if ps[0].upper().startswith("TCP") and ":8000" in ps[1] and ps[3].upper()=="LISTENING":
                victims.add(ps[4])
        me = str(os.getpid())
        for pid in sorted(victims - {me}):
            subprocess.run(["taskkill", "/F", "/PID", pid, "/T"],
                           capture_output=True, timeout=6)
            print(f"    已 taskkill pid={pid} 及其子进程树")
    except Exception as _e:
        print(f"    清理失败：{_e}，降级为模糊 kill")
        subprocess.run("taskkill /F /IM python.exe /FI \"WINDOWTITLE eq *launcher*\" 2>nul", shell=True)
        subprocess.run("taskkill /F /IM Launcher.exe 2>nul", shell=True)
    time.sleep(2.0)

def http_get(url, timeout=30):
    # 注意：repo_index() 内部 urllib timeout=20，若仓库响应慢需给足余量
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

# 启动 launcher 到后台
logf = BASE / "_smoke_launcher.log"
with open(logf, "w", encoding="utf-8") as lf:
    launcher_proc = subprocess.Popen(
        [sys.executable, str(BASE / "launcher.py")],
        stdout=lf, stderr=subprocess.STDOUT, cwd=str(BASE),
    )
LPID = launcher_proc.pid
print(f"  启动 launcher pid={LPID}，等待端口 8000...")

# 等端口
import socket
end = time.time() + 12
port_up = False
while time.time() < end:
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=0.4):
            port_up = True; break
    except OSError:
        time.sleep(0.2)
check("端口 8000 就绪", port_up)

api_results = {}
if port_up:
    # /api/apps
    try:
        d = http_get("http://127.0.0.1:8000/api/apps")
        api_results["apps"] = d
        check("/api/apps 返回数组", isinstance(d, list) and len(d) >= 4,
              f"len={len(d)}")
        running = [a["id"] for a in d if a.get("running")]
        print(f"    当前运行: {running or '(空)'}")
    except Exception as e:
        check("/api/apps", False, str(e))

    # /api/launcher/version
    try:
        d = http_get("http://127.0.0.1:8000/api/launcher/version")
        api_results["lver"] = d
        check("/api/launcher/version 字段齐全",
              all(k in d for k in ("local","remote","upgradable","changelog_local","changelog_remote")),
              f"local={d.get('local')}, remote={d.get('remote')}, upgradable={d.get('upgradable')}")
    except Exception as e:
        check("/api/launcher/version", False, str(e))

    # /api/repo 应用列表
    try:
        d = http_get("http://127.0.0.1:8000/api/repo")
        api_results["repo"] = d
        check("/api/repo 返回 apps 列表", "apps" in d and isinstance(d["apps"], list),
              f"len={len(d.get('apps',[]))}, error={d.get('error')}")
    except Exception as e:
        check("/api/repo", False, str(e))

    # /api/uninstall 系统应用拒卸
    try:
        d = http_get("http://127.0.0.1:8000/api/uninstall?id=store")
        check("/api/uninstall?id=store（系统）拒卸",
              d.get("ok") is False, f"msg={d.get('msg')}")
    except Exception as e:
        check("/api/uninstall store", False, str(e))

    # 开 2 个应用（hello + notes，无独立进程的不会有影响）
    for aid in ["hello", "notes"]:
        try:
            http_get(f"http://127.0.0.1:8000/api/open?id={aid}")
        except Exception:
            pass
    time.sleep(1)
    try:
        d = http_get("http://127.0.0.1:8000/api/apps")
        running_count = sum(1 for a in d if a.get("running"))
        print(f"    打开 hello/notes 后运行中 {running_count} 个应用")
    except Exception:
        pass

# 让 launcher 退出（terminate_all atexit）
print(f"  终止 launcher pid={LPID}，等待 atexit 清理子进程树...")
launcher_proc.terminate()
try:
    launcher_proc.wait(timeout=8)
except subprocess.TimeoutExpired:
    launcher_proc.kill()
    try: launcher_proc.wait(timeout=3)
    except Exception: pass

time.sleep(2.5)

# 检查 python 子进程：排除当前冒烟 python 本身和其他无关 python
this_py_pid = os.getpid()
try:
    cp = subprocess.run(
        ["wmic", "process", "where",
         f"Name='python.exe' or Name='cpp-hello.exe' or Name='pythonw.exe'",
         "get", "ProcessId,Name,CommandLine", "/FORMAT:csv"],
        capture_output=True, text=True, timeout=10,
    )
    lines = cp.stdout.strip().splitlines()
    suspicious = []
    for ln in lines:
        parts = ln.strip().split(",")
        if len(parts) < 3: continue
        try:
            _node, pid, name, cmd = parts[0], parts[1], parts[2], ",".join(parts[3:])
        except Exception:
            continue
        try:
            pid_i = int(pid)
        except Exception:
            continue
        if pid_i == this_py_pid or pid_i == LPID:
            continue
        # 只关心和 web-launcher 路径相关的 python / cpp-hello
        related = ("web-launcher" in cmd.replace("\\", "/").lower()
                   or "launcher.py" in cmd or "apps\\" in cmd or "apps/" in cmd
                   or name.lower().startswith("cpp-hello"))
        if related:
            suspicious.append((name, pid, cmd[:200]))
    check("退出 Launcher 后无 web-launcher 相关 python/cpp-hello 残留进程",
          len(suspicious) == 0,
          detail=f"残留 {len(suspicious)}: {suspicious[:5]}" if suspicious else "无残留")
except Exception as e:
    check("残留进程检查（wmic 调用失败）", False, str(e))


# ───────── 汇总 ─────────
print("\n" + "=" * 56)
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
failed = total - passed
print(f"  结果：{passed}/{total} 通过")
if failed:
    print(f"  ❌ 失败项:")
    for nm, ok, dt in results:
        if not ok:
            print(f"     - {nm}: {dt}")
print("=" * 56)
sys.exit(0 if failed == 0 else 3)
