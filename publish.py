"""应用发布脚本（在仓库根目录手动运行）
用法:
python publish.py                     # 列出所有可发布的应用
python publish.py <app_dir>           # 发布单个（例: apps/user/hello）
python publish.py --all               # 一键发布所有应用
python publish.py --group admin       # 一键发布指定分组的应用
python publish.py --list              # 仅列出，不发布
python publish.py --launcher          # 打包并发布 launcher 主程序更新
python publish.py --sync              # 对照远端 packages/ 清理 index.json 中失效条目

源码保护 (protect):
  app.json 里加 "protect": true 的应用, 发布时自动去源码化:
  - .py 编译为同位置 .pyc 入包(zip 内无业务 .py 源码)
  - .html/.htm 轻量压缩(去注释/空行)
  - cmd 指向的入口 .py 生成几行 runpy 启动器(加载同目录 .pyc),
    cmd 保持原样 —— 与未保护应用同构, 走 .py 文件关联启动,
    不要求部署机 PATH 里有 python 命令
  安装端与 launcher 零改动(cmd 语义不变, LAUNCHER_APP_PORT 照常传递)。
  注意: pyc 绑定 Python 版本, 发布机的 Python 大版本需与部署机一致。

打包排除 (exclude):
  build/ data/ site/ .git/ __pycache__/ .venv/ 永不入包；
  应用可在 app.json 加 "exclude": ["cpp", "wrapper"] 追加排除
  （任一上级目录名命中即排除整个子树，防止源码/产物外泄）。
"""
import argparse
import ast
import datetime
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

# 本脚本位于仓库根目录
BASE = Path(__file__).resolve().parent
CONFIG_JSON = BASE / "config.json"
APPS_DIR = BASE / "apps"

# 打包排除：以下顶层目录/文件名永不入包（编译产物、运行数据、依赖缓存等）。
# 应用还可在 app.json 里加 "exclude": ["cpp", "wrapper"] 追加自定义排除
#（相对应用目录的顶层目录/文件名，任一上级目录命中即排除整个子树）。
ALWAYS_EXCLUDE = {"build", "data", "site", ".git", "__pycache__", ".venv"}


def app_excludes(meta):
    """合并默认排除与 app.json 的 exclude 字段。"""
    ex = set(ALWAYS_EXCLUDE)
    for e in (meta or {}).get("exclude") or []:
        e = str(e).strip().strip("/").replace("\\", "/")
        if e:
            ex.add(e)
    return ex


def detect_app_icon_file(app_dir, meta):
    """自动识别 App 图标文件，允许不改 app.json 也能发布图标。"""
    names = [str(meta.get("icon_file") or "").strip(),
             "icon.png", "icon.svg", "icon.webp", "icon.jpg", "icon.jpeg"]
    for name in names:
        if not name:
            continue
        p = Path(name)
        if p.is_absolute() or ".." in p.parts:
            continue
        if (Path(app_dir) / p).is_file():
            return p.as_posix()
    return None


def collect_local_module_files(app_dir):
    """收集 App 引用的仓库内本地 Python 模块，并随 App 一起打包。

    例如 apps/game/breakout/app.py 引用 general.shared 时，解析为
    apps/general/shared.py，发布到 App 包内部的 general/shared.py。
    只收集实际 import 到的 .py 与包初始化文件，不把整个兄弟 App 目录带进去。
    """
    app_dir = Path(app_dir).resolve()
    app_files = {p.resolve() for p in app_dir.rglob("*.py")}
    pending = list(app_files)
    seen = set()
    result = []

    def add_module(module):
        if not module or module.startswith("."):
            return
        parts = [p for p in module.split(".") if p]
        if not parts:
            return
        base = APPS_DIR.joinpath(*parts)
        candidates = []
        py_file = base.with_suffix(".py")
        if py_file.is_file():
            candidates.append(py_file)
        init_file = base / "__init__.py"
        if init_file.is_file():
            candidates.append(init_file)
        # 让包级 import 同时带上已明确导入的子模块。
        for p in candidates:
            p = p.resolve()
            if p not in seen and p not in app_files:
                seen.add(p)
                pending.append(p)
                result.append(p)

        # 保留父包 __init__.py（如果存在）。
        for i in range(1, len(parts)):
            init = APPS_DIR.joinpath(*parts[:i], "__init__.py")
            if init.is_file():
                init = init.resolve()
                if init not in seen and init not in app_files:
                    seen.add(init)
                    pending.append(init)
                    result.append(init)

    while pending:
        source = pending.pop()
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    add_module(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                module = node.module or ""
                add_module(module)
                # from general import shared -> 还要解析 general.shared.py
                for alias in node.names:
                    if alias.name != "*" and module:
                        add_module(module + "." + alias.name)

    return result


def is_excluded(rel, ex):
    """rel（相对应用目录的 Path）任一级目录或文件名命中排除集即排除。"""
    return any(part in ex for part in rel.parts)
# 复用 launcher 包的公共逻辑，避免重复实现
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
from launcher.app_registry import find_all_app_dirs, derive_group

def load_config():
    if CONFIG_JSON.exists():
        return json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
    return {}

CONFIG = load_config()
PUBLISH_CFG = CONFIG.get("publish", {})
REPO_CFG = CONFIG.get("repo", {})
SERVER = PUBLISH_CFG.get("server", "ubuntu@1.15.30.237")
REMOTE = PUBLISH_CFG.get("remote_path", "/var/www/repo")
PACKAGES_DIR = PUBLISH_CFG.get("packages_dir", "packages")

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()

def _ensure_remote_dirs():
    """确保远端 packages/ 目录存在（scp 不会自动创建多级目录）。"""
    try:
        subprocess.run(
            ["ssh", SERVER, f"mkdir -p {REMOTE}/{PACKAGES_DIR}"],
            check=False, capture_output=True, timeout=30,
        )
    except Exception as e:
        print(f"  ⚠ ssh mkdir 失败（可能目录已存在）: {e}")


def upload_app_wheels(meta):
    """应用声明 deps 时, 下载对应 wheels 并上传到 repo /wheels/<平台>/。

    存放约定: /var/www/repo/wheels/win-x64/*.whl
    launcher 端 deps_installer 通过 --find-links 读取该平台目录。
    依赖只需在服务器存一份, 所有 APP 共享。
    """
    deps = meta.get("deps")
    if not deps:
        return True
    plat = "win-x64" if sys.platform == "win32" else "linux-x64"
    stage = BASE / f".wheels-{plat}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    need = [str(d) for d in deps]
    #wheels_python: 按部署机 Python 版本下载 wheels(默认按发布机当前解释器) add 261023
    wp = str(PUBLISH_CFG.get("wheels_python", "")).strip()
    cross = []
    if wp:
        cross = ["--python-version", wp, "--implementation", "cp", "--platform",
                 "win_amd64" if sys.platform == "win32" else "manylinux2014_x86_64"]
        print(f"   🎯 wheels 目标 Python: {wp}")
    print(f"   📥 下载依赖 wheels: {', '.join(need)}")
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "download", "--only-binary", ":all:",
             "--dest", str(stage)] + cross + need,
            capture_output=True, text=True, timeout=600, encoding="utf-8", errors="replace",
        )
        if r.returncode != 0:
            print(f"   ❌ wheels 下载失败: {(r.stderr or r.stdout or '')[-300:]}")
            return False
    except subprocess.TimeoutExpired:
        print("   ❌ wheels 下载超时")
        return False
    whls = sorted(stage.glob("*.whl"))
    if not whls:
        print("   ⚠ 未下载到任何 wheel, 跳过")
        return True
    print(f"   ✓ {len(whls)} 个 wheel: {', '.join(w.name for w in whls)}")
    try:
        subprocess.run(
            ["ssh", SERVER, f"mkdir -p {REMOTE}/wheels/{plat}"],
            check=False, capture_output=True, timeout=30)
        subprocess.run(
            ["scp", *[str(w) for w in whls], f"{SERVER}:{REMOTE}/wheels/{plat}/"],
            check=True, capture_output=True, text=True, timeout=300,
            encoding="utf-8", errors="replace",
        )
        print(f"   ✓ wheels 已上传 → {REMOTE}/wheels/{plat}/")
    except Exception as e:
        print(f"   ⚠ wheels 上传失败(应用包仍会发布, 安装端将回退在线源): {e}")
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return True

def _wheel_platform():
    """返回 (平台目录名, pip platform 参数)。"""
    if sys.platform == "win32":
        return "win-x64", "win_amd64"
    import platform
    machine = platform.machine().lower()
    if machine.startswith(("aarch", "arm")) and sys.maxsize > 2 ** 32:
        return "linux-arm64", "manylinux2014_aarch64"
    return "linux-x64", "manylinux2014_x86_64"


def build_wheels_bundle():
    """汇总所有 App 的 deps，生成供终端自动下载的 wheels 包。

    返回 {zip, stage, platform, files}；没有任何 deps 时返回 None。
    stage 在发布流程结束后由调用方清理。
    """
    deps, sources = [], {}
    for app_dir in find_all_app_dirs():
        try:
            meta = json.loads((app_dir / "app.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        for dep in meta.get("deps") or []:
            dep = str(dep).strip()
            if dep and dep not in deps:
                deps.append(dep)
                sources.setdefault(dep, []).append(meta.get("id", app_dir.name))

    if not deps:
        print("   ℹ 没有 App 声明 deps，不生成 wheels 包")
        return None

    plat, pip_plat = _wheel_platform()
    stage = BASE / f".launcher-wheels-{plat}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    wp = str(PUBLISH_CFG.get("wheels_python", "")).strip()
    cmd = [sys.executable, "-m", "pip", "download",
           "--only-binary", ":all:", "--dest", str(stage),
           "--platform", pip_plat, "--implementation", "cp"]
    if wp:
        cmd += ["--python-version", wp]
    cmd += deps
    print(f"   📦 汇总 wheels ({plat}): {', '.join(deps)}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            detail = (r.stderr or r.stdout or "").strip()[-800:]
            raise RuntimeError(f"wheels 下载失败: {detail}")
        files = sorted(stage.glob("*.whl"))
        if not files:
            raise RuntimeError("未下载到任何 wheel 文件")
        zip_path = BASE / f"wheels-{plat}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for wheel in files:
                z.write(wheel, wheel.name)
        print(f"   ✓ wheels 包已生成: {zip_path.name} ({len(files)} 个 wheel)")
        return {"zip": zip_path, "stage": stage, "platform": plat, "files": files}
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def cleanup_wheels_bundle(bundle):
    """清理 wheels 发布临时文件。"""
    if not bundle:
        return
    shutil.rmtree(bundle["stage"], ignore_errors=True)
    try:
        bundle["zip"].unlink()
    except OSError:
        pass


def _verify_upload(pkg_path):
    """上传后通过 HTTP HEAD 验证文件是否可访问。返回 True/False。"""
    import urllib.request, ssl
    url = REPO_CFG.get("url", "").rstrip("/") + "/" + pkg_path
    ctx = ssl.create_default_context()
    if not REPO_CFG.get("verify_ssl", False):
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        req = urllib.request.Request(url, method="HEAD")
        urllib.request.urlopen(req, timeout=10, context=ctx)
        return True
    except Exception as e:
        print(f"  ⚠ HTTP 验证失败 ({pkg_path}): {e}")
        return False

def discover_apps(kind="all"):
    """返回 [app_dir, ...] 列表
    kind: 'all' | 任意分组名 (如 'system', 'user', 'admin')
    通过 app.json 的 group 字段判断类型，兼容旧版 system 字段
    """
    all_dirs = find_all_app_dirs()
    if kind == "all":
        return all_dirs

    result = []
    for d in all_dirs:
        try:
            meta = json.loads((d / "app.json").read_text(encoding="utf-8"))
            app_group = derive_group(meta)
        except Exception:
            continue
        if kind == app_group:
            result.append(d)
    return result

def print_apps_table(apps):
    """打印应用清单表格"""
    if not apps:
        print("  （没有找到任何应用）")
        return
    rows = []
    for d in apps:
        try:
            meta = json.loads((d / "app.json").read_text(encoding="utf-8"))
        except Exception as e:
            meta = {"id": d.name, "name": f"⚠ app.json 损坏: {e}"}
        
        # 核心改动：显示 group 而不是 SYSTEM/USER
        group = derive_group(meta)
            
        rel = d.relative_to(BASE).as_posix()
        rows.append((group.upper(), rel, meta.get("id", "?"), meta.get("version", "?"), meta.get("name", "?")))
        
    print(f"  {'分组':8} {'路径':30} {'id':12} {'版本':8} 名称")
    print(f"  {'-'*8} {'-'*30} {'-'*12} {'-'*8} {'-'*20}")
    for k, r, aid, v, n in rows:
        print(f"  {k:8} {r:30} {aid:12} {v:8} {n}")

def ensure_index():
    """下载远端 index.json，如果不存在就初始化一个空的，返回 index dict 和本地临时文件"""
    index_tmp = BASE / "_index.json"
    try:
        subprocess.run(
            ["scp", f"{SERVER}:{REMOTE}/index.json", str(index_tmp)],
            check=True, capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        index = json.loads(index_tmp.read_text(encoding="utf-8"))
    except subprocess.CalledProcessError:
        print(f"  远端 index.json 不存在，将初始化一个空的")
        index = {"repo": "my-launcher-repo", "updated": "", "apps": []}
    return index, index_tmp

# ============================== 源码保护 (protect) ==============================

def _minify_html_text(text):
    """轻量 HTML 压缩: 去 <!-- --> 注释 / 行尾空白 / 空行。保守策略, 不改语义。"""
    import re
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return "\n".join(ln.rstrip() for ln in text.splitlines() if ln.strip())


def _launcher_py(entry_name):
    """protect 启动器: 与原入口同名 .py, 内部 runpy 加载同目录 .pyc。
    启动器本身只有几行样板, 核心逻辑全部在 .pyc 中。"""
    return (
        "# -*- coding: utf-8 -*-\n"
        "# protected app launcher: core logic in {0}.pyc (compiled)\n"
        "import os, sys, runpy\n"
        "_d = os.path.dirname(os.path.abspath(__file__))\n"
        "sys.path.insert(0, _d)\n"
        "runpy.run_path(os.path.join(_d, '{0}.pyc'), run_name='__main__')\n"
    ).format(entry_name)


def _check_pyc_python_version():
    """protect 出包的 .pyc 绑定 Python 大版本：校验当前解释器与内嵌 runtime 一致。
    不一致时给出醒目警告（部署机 runtime 读不了会直接导致应用打不开）。"""
    rt = BASE / "runtime" / "win-x64" / "python.exe"
    cur = "%d.%d" % sys.version_info[:2]
    if not rt.exists():
        print(f"   ⚠ 未找到内嵌 runtime（{rt.relative_to(BASE)}），无法校验 pyc 版本；"
              f"当前用 Python {cur} 编译，请确认与部署机 runtime 大版本一致")
        return
    try:
        out = subprocess.run([str(rt), "-c",
                              "import sys;print('%d.%d' % sys.version_info[:2])"],
                             capture_output=True, text=True, timeout=30)
        rt_ver = (out.stdout or "").strip()
    except Exception:
        return
    if rt_ver and rt_ver != cur:
        print(f"   ⚠⚠ pyc 版本不匹配：当前 Python {cur}，内嵌 runtime {rt_ver} —— "
              f"打出的包在部署机上会打不开！请用 runtime 的 python 运行本脚本：")
        print(f"      runtime\\win-x64\\python.exe publish.py ...")


def build_pyc_stage(app_dir, meta=None):
    """把 app_dir 内容编译/复制到临时目录: .py -> 同位置 .pyc(源码不落副本),
    .html/.htm 压缩, 其余原样; 并对 cmd 指向的每个入口 .py 生成同名 runpy
    启动器(内容仅几行样板), 使 cmd 保持 .py 形式即可运行 —— 与未保护应用
    完全同构(走文件关联), 不依赖部署机 PATH 里有 python 命令。
    返回 staging Path(调用方负责清理)。"""
    import py_compile
    import tempfile
    meta = meta or {}
    _check_pyc_python_version()
    # cmd 形如 "apps/<group>/<app>/app.py", 相对仓库根;
    # 用 app_dir 相对仓库根的前缀精确剥掉, 得到相对 app_dir 的入口路径
    try:
        app_rel_root = app_dir.resolve().relative_to(APPS_DIR.parent.resolve()).as_posix()
    except ValueError:
        app_rel_root = ""
    entries = []
    for part in (meta.get("cmd") or []):
        if isinstance(part, str) and part.endswith(".py"):
            rel = part.replace("\\", "/")
            if app_rel_root and rel.startswith(app_rel_root + "/"):
                entries.append(rel[len(app_rel_root) + 1:])
            else:
                entries.append(rel.rsplit("/", 1)[-1])  # 兜底: 取文件名
    stage = Path(tempfile.mkdtemp(prefix="publish_pyc_"))
    ex = app_excludes(meta)
    for f in app_dir.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(app_dir)
        if is_excluded(rel, ex):
            continue
        if f.suffix == ".pyc":
            continue
        dst = stage / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if f.suffix == ".py":
            py_compile.compile(str(f), cfile=str(dst.with_suffix(".pyc")),
                               dfile=rel.as_posix(), doraise=True)
        elif f.suffix.lower() in (".html", ".htm"):
            # newline="\n": 避免 Windows 下 \r\n 转写抵消压缩收益
            dst.write_text(_minify_html_text(f.read_text(encoding="utf-8")),
                           encoding="utf-8", newline="\n")
        else:
            shutil.copy2(f, dst)
    # cmd 入口生成启动器(核心在 pyc, 启动器仅样板)
    for rel in entries:
        entry = stage / rel
        if entry.with_suffix(".pyc").is_file() and not entry.is_file():
            stem = entry.stem
            entry.parent.mkdir(parents=True, exist_ok=True)
            entry.write_text(_launcher_py(stem), encoding="utf-8", newline="\n")
    return stage


def build_entry(meta, zip_path):
    """生成 index.json 里的单个 app 条目"""
    # 白名单：只保留实际生效的字段（system 已废弃，group 为分组来源）
    FIELDS = ("id", "name", "icon", "icon_file", "color", "version", "changelog",
              "port", "cmd", "dock", "group", "released", "standalone")
    entry = {k: meta[k] for k in FIELDS if k in meta}

    # 兼容处理：如果旧配置没有 group，自动推断并写入
    entry.setdefault("group", derive_group(meta))
        
    entry["pkg"] = f"{PACKAGES_DIR}/{zip_path.name}"
    entry["size"] = zip_path.stat().st_size
    entry["sha256"] = sha256(zip_path)
    entry.setdefault("released", datetime.datetime.now().isoformat())
    return entry

def publish_one(app_dir, *, upload=True, index_override=None):
    """发布单个应用"""
    app_dir = Path(app_dir)
    if not app_dir.is_absolute():
        app_dir = (BASE / app_dir).resolve()
    app_json = app_dir / "app.json"
    
    if not app_json.exists():
        print(f"❌ 错误: {app_json} 不存在，应用必须包含 app.json")
        return False, None, None
    try:
        meta = json.loads(app_json.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ {app_json} 解析失败: {e}")
        return False, None, None
        
    for required in ("id", "version"):
        if required not in meta:
            print(f"❌ app.json 缺少字段: {required}")
            return False, None, None

    icon_file = detect_app_icon_file(app_dir, meta)
    if icon_file:
        meta["icon_file"] = icon_file
    else:
        meta.pop("icon_file", None)
    zip_name = f"{meta['id']}-{meta['version']}.zip"
    
    # 核心改动：根据 group 决定图标
    group = derive_group(meta)
    kind_tag = "🛡️" if group == "system" else "📦"
    print(f"{kind_tag} 打包 {meta['name']} v{meta['version']} (id={meta['id']}, group={group})...")

    # ---- 源码保护: protect=true 时 .py 编译为 .pyc 出包, 入口生成启动器 ----
    protect = bool(meta.get("protect"))
    standalone = bool(meta.get("standalone"))
    pkg_meta = meta
    stage = None
    if protect:
        stage = build_pyc_stage(app_dir, meta)
        # cmd 保持 .py 形式(包内已有同名 runpy 启动器), app.json 无需改写
        print("   🔒 源码保护: pyc + 启动器(核心逻辑在 .pyc, cmd 不变)")

    src_root = stage if stage else app_dir
    ex = app_excludes(meta)
    app_rel = app_dir.relative_to(APPS_DIR.parent)  # 如 apps/etws/iqcache-sync
    zip_path = BASE / zip_name
    local_module_files = collect_local_module_files(app_dir)
    if local_module_files:
        print("   🔗 自动收集本地模块: " + ", ".join(
            p.relative_to(APPS_DIR).as_posix() for p in local_module_files))
    
    # ---- standalone 应用: runtime 打进应用包 ----
    runtime_dir = BASE / "runtime"
    plat = "win-x64" if sys.platform == "win32" else "linux-x64"
    
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            # 应用代码
            for f in src_root.rglob("*"):
                if not f.is_file():
                    continue
                if not stage and is_excluded(f.relative_to(app_dir), ex):
                    continue  # stage 路径在 build_pyc_stage 已过滤
                if not protect and f.suffix == ".pyc":
                    continue  # 未保护的应用维持原逻辑: 不带 pyc 缓存
                if f.name.endswith(".zip.tmp") or f.name == zip_name:
                    continue
                arcname = (app_rel / f.relative_to(src_root)) if stage else f.relative_to(APPS_DIR.parent)
                z.write(f, arcname.as_posix())
            
            # 本地公共模块放进当前 App 内部，避免安装器把多个 apps/ 前缀混在一个包里。
            # 例如 apps/general/shared.py -> apps/game/breakout/general/shared.py。
            for f in local_module_files:
                rel = f.relative_to(APPS_DIR)
                arcname = app_rel / rel
                z.write(f, arcname.as_posix())
            
            # standalone: runtime 打进应用包 (apps/<group>/<id>/runtime/<plat>/...)
            if standalone:
                if not runtime_dir.exists():
                    print(f"   ⚠ standalone=true 但未找到 runtime/ 目录，跳过")
                else:
                    rt_platform = runtime_dir / plat
                    if not rt_platform.exists():
                        print(f"   ⚠ 未找到 runtime/{plat}/，跳过")
                    else:
                        rt_files = list(rt_platform.rglob("*"))
                        rt_count = sum(1 for f in rt_files if f.is_file())
                        print(f"   🧬 standalone: 打包 runtime/{plat}/ ({rt_count} 文件)")
                        for f in rt_files:
                            if f.is_file():
                                # 存放路径: apps/<group>/<id>/runtime/<plat>/...
                                arcname = app_rel / "runtime" / plat / f.relative_to(rt_platform)
                                z.write(f, arcname.as_posix())
    finally:
        if stage:
            shutil.rmtree(stage, ignore_errors=True)

    print(f"   ✓ {zip_name} ({zip_path.stat().st_size} bytes, sha256={sha256(zip_path)[:12]}...)")
    entry = build_entry(pkg_meta, zip_path)
    
    index = index_override
    index_tmp = None
    
    if upload:
        _ensure_remote_dirs()
        upload_app_wheels(pkg_meta)
        print(f"🚀 上传 {zip_name} → {SERVER}:{REMOTE}/{PACKAGES_DIR}/")
        try:
            subprocess.run(
                ["scp", str(zip_path), f"{SERVER}:{REMOTE}/{PACKAGES_DIR}/"],
                check=True, capture_output=True, text=True, timeout=120,
                encoding="utf-8", errors="replace",
            )
        except subprocess.CalledProcessError as e:
            print(f"❌ 上传失败: {e.stderr or e.stdout or e}")
            zip_path.unlink(missing_ok=True)
            return False, None, None
        print(f"   ✓ 上传完成")
        
        if not _verify_upload(entry["pkg"]):
            print(f"  ⚠ 上传后 HTTP 验证失败，文件可能不可访问")

        if index is None:
            print("📋 更新远端 index.json...")
            index, index_tmp = ensure_index()

        index["apps"] = [a for a in index.get("apps", []) if a["id"] != meta["id"]] + [entry]
        index["updated"] = datetime.datetime.now().isoformat()

    try:
        zip_path.unlink()
    except OSError:
        pass

    if upload and index is not None:
        return True, index, entry
    return True, None, None

def write_and_upload_index(index, index_tmp=None):
    """写入本地 index_tmp 并上传到远端"""
    if index_tmp is None:
        index_tmp = BASE / "_index.json"
    index_tmp.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"📋 上传更新后的 index.json → {SERVER}:{REMOTE}/index.json")
    subprocess.run(
        ["scp", str(index_tmp), f"{SERVER}:{REMOTE}/index.json"],
        check=True, capture_output=True, text=True, timeout=30,
        encoding="utf-8", errors="replace",
    )
    print(f"   ✓ index.json 更新完成（{len(index.get('apps', []))} 个应用）")


def _list_remote_packages():
    """ssh 列出远端 packages/ 目录下所有文件名（不含路径）。失败抛异常。"""
    result = subprocess.run(
        ["ssh", SERVER, f"ls -1 {REMOTE}/{PACKAGES_DIR}/"],
        check=True, capture_output=True, text=True, timeout=30,
        encoding="utf-8", errors="replace",
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def sync_remote(*, dry_run=False, yes=False):
    """对照远端 packages/ 实际文件清单，从 index.json 移除指向失效包的条目。

    处理对象：
      - apps[].pkg            → 文件不存在则整个条目移除
      - launcher.pkg          → 不存在则整个 launcher 节点移除
      - launcher.binary       → 不存在则只移除 binary/binary_sha256/binary_size 子字段
    """
    print("📋 拉取远端 index.json...")
    index, index_tmp = ensure_index()

    print("📦 列出远端 packages/ 实际文件...")
    try:
        remote_files = _list_remote_packages()
    except subprocess.CalledProcessError as e:
        print(f"❌ ssh ls 失败: {e.stderr or e.stdout or e}")
        try: index_tmp.unlink()
        except OSError: pass
        return False
    except Exception as e:
        print(f"❌ 列出远端文件失败: {e}")
        try: index_tmp.unlink()
        except OSError: pass
        return False
    print(f"   ✓ 远端 packages/ 共 {len(remote_files)} 个文件")

    def _fname(pkg_path):
        return (pkg_path or "").rsplit("/", 1)[-1] if pkg_path else ""

    apps_before = index.get("apps", [])
    apps_after = []
    removed_apps = []
    for m in apps_before:
        fname = _fname(m.get("pkg"))
        if fname and fname not in remote_files:
            removed_apps.append((m.get("id", "?"), fname))
        else:
            apps_after.append(m)

    removed_launcher = []
    launcher_meta = index.get("launcher")
    if launcher_meta:
        pkg_fname = _fname(launcher_meta.get("pkg"))
        if pkg_fname and pkg_fname not in remote_files:
            removed_launcher.append(("pkg", pkg_fname))
            launcher_meta = None
        else:
            binary_fname = _fname(launcher_meta.get("binary"))
            if binary_fname and binary_fname not in remote_files:
                removed_launcher.append(("binary", binary_fname))
                for k in ("binary", "binary_sha256", "binary_size"):
                    launcher_meta.pop(k, None)

    print(f"\n📊 index.json apps: {len(apps_before)} → {len(apps_after)}"
          f"（移除 {len(removed_apps)} 个）")
    if removed_apps:
        print("🗑 移除的 app 条目:")
        for aid, fname in removed_apps:
            print(f"   - {aid:20} {fname}")
    if removed_launcher:
        print("🗑 launcher 节点调整:")
        for key, fname in removed_launcher:
            print(f"   - {key}: {fname}")

    if not removed_apps and not removed_launcher:
        print("✓ index.json 与 packages/ 一致，无需同步")
        try: index_tmp.unlink()
        except OSError: pass
        return True

    if dry_run:
        print("\n[--dry-run] 未实际修改远端 index.json")
        try: index_tmp.unlink()
        except OSError: pass
        return True

    if not yes:
        try:
            ans = input("\n确认同步并覆盖远端 index.json？[y/N]: ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("y", "yes"):
            print("已取消")
            try: index_tmp.unlink()
            except OSError: pass
            return False

    index["apps"] = apps_after
    if launcher_meta is not None:
        index["launcher"] = launcher_meta
    elif "launcher" in index:
        del index["launcher"]
    index["updated"] = datetime.datetime.now().isoformat()

    write_and_upload_index(index, index_tmp)
    print("✅ 同步完成")
    return True

def parse_args():
    parser = argparse.ArgumentParser(
        description="应用发布工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python publish.py apps/user/hello                    发布单个 app\n"
               "  python publish.py --all                               发布所有应用\n"
               "  python publish.py --group admin                       发布 admin 分组应用\n"
               "  python publish.py --sync                              清理 index.json 失效条目\n"
               "  python publish.py --sync --dry-run                    仅预览不写远端\n"
    )
    g = parser.add_mutually_exclusive_group()
    g.add_argument("app_dir", nargs="?", help="要发布的单个应用路径")
    g.add_argument("--all", action="store_true", help="发布所有应用")
    g.add_argument("--group", type=str, help="仅发布指定分组的应用 (例: --group admin)")
    g.add_argument("--list", action="store_true", help="列出所有可发布的应用")
    g.add_argument("--launcher", action="store_true", help="打包并发布 launcher 主程序更新")
    g.add_argument("--sync", action="store_true", help="对照远端 packages/ 清理 index.json 中失效条目")

    parser.add_argument("--dry-run", action="store_true", help="只打包不上传（测试打包）；--sync 时只预览不写远端")
    parser.add_argument("--yes", "-y", action="store_true", help="跳过交互确认（配合 --sync）")
    parser.add_argument("--changelog", type=str, default="", help="launcher 更新说明（配合 --launcher 使用）")
    return parser.parse_args()

def build_runtime_zip() -> Path | None:
    """生成供 Launcher 自动下载的独立 runtime.zip。

    runtime.zip 只包含当前发布平台目录的内容（如 python.exe、Lib/），
    不带 runtime/win-x64/ 外层目录；安装端会直接解压到 runtime/<平台>/。
    """
    plat = "win-x64" if sys.platform == "win32" else "linux-x64"
    runtime_platform_dir = BASE / "runtime" / plat
    if not runtime_platform_dir.is_dir():
        print(f"   ⚠ 未找到 runtime/{plat}/，不生成 runtime.zip")
        return None

    zip_path = BASE / "runtime.zip"
    file_count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in runtime_platform_dir.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(runtime_platform_dir).as_posix())
                file_count += 1
    print(f"   🧬 独立 runtime.zip 已生成: {plat}/ ({file_count} 文件)")
    return zip_path


def build_launcher_zip(version: str, changelog: str) -> Path:
    """把 launcher 基础文件打包成 zip"""
    include_patterns = [
        "launcher.py", "config.json", "README.md",
        "apps/README.md",
    ]
    
    launcher_pkg_dir = BASE / "launcher"
    launcher_pkg_files = []
    if launcher_pkg_dir.exists():
        for p in launcher_pkg_dir.rglob("*"):
            if p.is_file() and not (p.suffix == ".pyc" or p.name == "__pycache__"):
                launcher_pkg_files.append(p.relative_to(BASE))

    # 核心改动：打包所有 group=="system" 的应用
    system_files = []
    for app_dir in find_all_app_dirs():
        try:
            meta = json.loads((app_dir / "app.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        
        app_group = derive_group(meta)
        if app_group != "system":
            continue
            
        for p in app_dir.rglob("*"):
            if p.is_file() and not (p.suffix == ".pyc" or p.name == "__pycache__" or ".venv" in p.parts):
                system_files.append(p.relative_to(BASE))

    files = [Path(p) for p in include_patterns if (BASE / p).exists()]
    files += launcher_pkg_files
    files += system_files

    # 内嵌 Python runtime 随 launcher 分发(存在即入包) add 261023
    runtime_dir = BASE / "runtime"
    if runtime_dir.exists():
        for p in runtime_dir.rglob("*"):
            if p.is_file():
                files.append(p.relative_to(BASE))
        print(f"   🧬 内嵌 runtime 已入包: runtime/ ({len(files)} 文件总计)")

    zip_path = BASE / f"launcher-{version}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            full = BASE / rel
            if rel == Path("config.json"):
                try:
                    cfg = json.loads(full.read_text(encoding="utf-8"))
                except Exception:
                    cfg = {}
                safe_cfg = {
                    "launcher": cfg.get("launcher", {}),
                    "repo": {"url": cfg.get("repo", {}).get("url", ""), "verify_ssl": cfg.get("repo", {}).get("verify_ssl", False)},
                }
                z.writestr(rel.as_posix(), json.dumps(safe_cfg, ensure_ascii=False, indent=2))
                continue
            z.write(full, rel.as_posix())
    return zip_path

def publish_launcher(*, upload: bool, changelog: str = ""):
    """发布 launcher 主程序更新"""
    version = CONFIG.get("launcher", {}).get("version")
    if not version:
        print("❌ config.json 的 launcher.version 未配置，无法发布 launcher 更新")
        return False
        
    print(f"🚀 Launcher 更新: v{version}")
    if changelog:
        print(f"   更新说明: {changelog}")

    zip_path = build_launcher_zip(version, changelog)
    runtime_zip_path = build_runtime_zip()
    try:
        wheels_bundle = build_wheels_bundle()
    except Exception as e:
        print(f"❌ 无法生成 wheels 包，取消 Launcher 发布: {e}")
        zip_path.unlink(missing_ok=True)
        if runtime_zip_path:
            runtime_zip_path.unlink(missing_ok=True)
        return False
    print(f"   ✓ {zip_path.name} ({zip_path.stat().st_size} bytes, "
          f"sha256={sha256(zip_path)[:12]}...)")
    if runtime_zip_path:
        print(f"   ✓ {runtime_zip_path.name} ({runtime_zip_path.stat().st_size} bytes, "
              f"sha256={sha256(runtime_zip_path)[:12]}...)")
    if wheels_bundle:
        wheels_zip_path = wheels_bundle["zip"]
        print(f"   ✓ {wheels_zip_path.name} ({wheels_zip_path.stat().st_size} bytes, "
              f"sha256={sha256(wheels_zip_path)[:12]}...)")

    entry = {
        "version": version,
        "changelog": changelog,
        "pkg": f"{PACKAGES_DIR}/{zip_path.name}",
        "size": zip_path.stat().st_size,
        "sha256": sha256(zip_path),
        "released": datetime.datetime.now().isoformat(),
    }

    index = None
    index_tmp = None
    if upload:
        _ensure_remote_dirs()
        print(f"🚀 上传 {zip_path.name} → {SERVER}:{REMOTE}/{PACKAGES_DIR}/")
        try:
            subprocess.run(
                ["scp", str(zip_path), f"{SERVER}:{REMOTE}/{PACKAGES_DIR}/"],
                check=True, capture_output=True, text=True, timeout=180,
            )
        except subprocess.CalledProcessError as e:
            print(f"❌ 上传失败: {e.stderr or e.stdout or e}")
            zip_path.unlink(missing_ok=True)
            return False
        print(f"   ✓ 上传完成")

        # runtime.zip 不登记到 index.json，Launcher 启动时直接访问仓库根目录。
        if runtime_zip_path:
            print(f"🚀 上传 {runtime_zip_path.name} → {SERVER}:{REMOTE}/")
            try:
                subprocess.run(
                    ["scp", str(runtime_zip_path), f"{SERVER}:{REMOTE}/"],
                    check=True, capture_output=True, text=True, timeout=180,
                    encoding="utf-8", errors="replace",
                )
            except subprocess.CalledProcessError as e:
                print(f"❌ runtime.zip 上传失败: {e.stderr or e.stdout or e}")
                zip_path.unlink(missing_ok=True)
                runtime_zip_path.unlink(missing_ok=True)
                return False
            print("   ✓ runtime.zip 上传完成")
            if not _verify_upload("runtime.zip"):
                print("  ⚠ runtime.zip HTTP 验证失败，自动下载可能仍不可用")

        # wheels 单独上传到平台目录，并上传压缩包供新 Launcher 自动部署。
        if wheels_bundle:
            wheel_dir = f"{REMOTE}/wheels/{wheels_bundle['platform']}"
            print(f"🚀 上传 {len(wheels_bundle['files'])} 个 wheels → {SERVER}:{wheel_dir}/")
            try:
                subprocess.run(
                    ["ssh", SERVER, f"mkdir -p {wheel_dir}"],
                    check=True, capture_output=True, text=True, timeout=30,
                    encoding="utf-8", errors="replace",
                )
                subprocess.run(
                    ["scp", *[str(p) for p in wheels_bundle["files"]],
                     f"{SERVER}:{wheel_dir}/"],
                    check=True, capture_output=True, text=True, timeout=300,
                    encoding="utf-8", errors="replace",
                )
                print("   ✓ wheels 平铺文件上传完成")
                wheels_zip = wheels_bundle["zip"]
                print(f"🚀 上传 {wheels_zip.name} → {SERVER}:{REMOTE}/")
                subprocess.run(
                    ["scp", str(wheels_zip), f"{SERVER}:{REMOTE}/"],
                    check=True, capture_output=True, text=True, timeout=180,
                    encoding="utf-8", errors="replace",
                )
                print("   ✓ wheels 压缩包上传完成")
                if not _verify_upload(wheels_zip.name):
                    print("  ⚠ wheels 压缩包 HTTP 验证失败，自动部署可能仍不可用")
            except subprocess.CalledProcessError as e:
                print(f"❌ wheels 上传失败: {e.stderr or e.stdout or e}")
                zip_path.unlink(missing_ok=True)
                if runtime_zip_path:
                    runtime_zip_path.unlink(missing_ok=True)
                cleanup_wheels_bundle(wheels_bundle)
                return False

        print("📋 更新远端 index.json...")
        index, index_tmp = ensure_index()
        index["launcher"] = entry
        index["updated"] = datetime.datetime.now().isoformat()
        write_and_upload_index(index, index_tmp)

    try:
        zip_path.unlink()
    except OSError:
        pass
    if runtime_zip_path:
        try:
            runtime_zip_path.unlink()
        except OSError:
            pass
    cleanup_wheels_bundle(wheels_bundle)

    print("✅ launcher 更新发布完成！" if upload else "✅ launcher 打包完成（未上传）")
    return True

def main():
    args = parse_args()
    
    if args.launcher:
        ok = publish_launcher(
            upload=not args.dry_run,
            changelog=args.changelog,
        )
        sys.exit(0 if ok else 4)

    if args.sync:
        ok = sync_remote(dry_run=args.dry_run, yes=args.yes)
        sys.exit(0 if ok else 5)

    # 核心改动：支持 --group 参数
    has_filter = any([args.app_dir, args.all, args.group, args.list])
    if args.list or not has_filter:
        print("📋 可发布的应用清单:")
        print_apps_table(discover_apps("all"))
        v = CONFIG.get("launcher", {}).get("version", "未配置")
        print(f"\n🖥️  Launcher 本地版本: {v}")
        print("   发布更新: python publish.py --launcher --changelog \"说明\"")
        if args.list:
            return
        print("\n用法:")
        print("  发布单个  : python publish.py apps/user/hello")
        print("  发布全部  : python publish.py --all")
        print("  分组发布  : python publish.py --group admin")
        print("  只打包    : python publish.py apps/user/hello --dry-run")
        sys.exit(0)

    upload = not args.dry_run
    
    if args.app_dir:
        ok, index, _ = publish_one(args.app_dir, upload=upload)
        if not ok:
            sys.exit(2)
        if upload and index is not None:
            write_and_upload_index(index)
        print("✅ 发布完成！" if upload else "✅ 打包完成（未上传）")
        return

    # 解析发布范围：--group 指定分组，否则 --all
    if args.group:
        kind = args.group
    else:
        kind = "all"
        
    apps = discover_apps(kind)
    if not apps:
        print(f"⚠ 没有找到分组为 {kind!r} 的应用")
        sys.exit(1)
        
    print(f"🚀 开始批量发布 (group={kind})，共 {len(apps)} 个应用:")
    print_apps_table(apps)
    print()

    index = None
    index_tmp = None
    if upload:
        print("📋 拉取远端 index.json...")
        index, index_tmp = ensure_index()

    success, failed = 0, 0
    for i, d in enumerate(apps, 1):
        print(f"\n[{i}/{len(apps)}]", end=" ")
        try:
            ok, new_index, _ = publish_one(d, upload=upload, index_override=index)
            if ok:
                if upload and new_index is not None:
                    index = new_index  
                success += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ 发布异常: {e}")
            failed += 1

    if upload and index is not None:
        print()
        write_and_upload_index(index, index_tmp)

    print(f"\n{'='*40}\n批量发布完成: ✅ 成功 {success} 个 · ❌ 失败 {failed} 个")
    if failed:
        sys.exit(3)

if __name__ == "__main__":
    main()