"""应用发布脚本
用法:
python publish.py                     # 列出所有可发布的应用
python publish.py <app_dir>           # 发布单个（例: apps/user/hello）
python publish.py --all               # 一键发布所有应用
python publish.py --system            # 一键发布所有系统应用
python publish.py --user              # 一键发布所有用户应用
python publish.py --group admin       # 一键发布指定分组的应用
python publish.py --list              # 仅列出，不发布
python publish.py --launcher          # 打包并发布 launcher 主程序更新
python publish.py --sync              # 对照远端 packages/ 清理 index.json 中失效条目

源码保护 (protect):
  app.json 里加 "protect": true 的应用, 发布时自动去源码化:
  - .py 编译为同位置 .pyc 入包(zip 内无 .py 源码)
  - .html/.htm 轻量压缩(去注释/空行)
  - app.json 的 cmd 改写为 ["python", "apps/xx/app.pyc"], 包内外一致
  安装端与 launcher 零改动(cmd 语义不变, LAUNCHER_APP_PORT 照常传递)。
  注意: pyc 绑定 Python 版本, 发布机的 Python 大版本需与部署机一致。
"""
import argparse
import datetime
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).parent.resolve()
CONFIG_JSON = BASE / "config.json"
APPS_DIR = BASE / "apps"

# 复用 launcher 包的公共逻辑，避免重复实现
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
from launcher.app_registry import _find_all_app_dirs, derive_group

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
            check=False, capture_output=True, timeout=15,
        )
    except Exception as e:
        print(f"  ⚠ ssh mkdir 失败（可能目录已存在）: {e}")

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
    all_dirs = _find_all_app_dirs()
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


def _rewrite_cmd_pyc(cmd):
    """["apps/x/app.py"] -> ["python", "apps/x/app.pyc"]
    .pyc 没有文件关联, 必须显式带解释器; 已带 python 前缀的只换后缀。"""
    out = []
    for part in cmd:
        if isinstance(part, str) and part.endswith(".py"):
            if not out or out[0] not in ("python", "python3", "py"):
                out.append("python")
            part = part[:-3] + ".pyc"
        out.append(part)
    return out


def build_pyc_stage(app_dir):
    """把 app_dir 内容编译/复制到临时目录: .py -> 同位置 .pyc(源码不落副本),
    .html/.htm 压缩, 其余原样。返回 staging Path(调用方负责清理)。"""
    import py_compile
    import tempfile
    stage = Path(tempfile.mkdtemp(prefix="publish_pyc_"))
    for f in app_dir.rglob("*"):
        if not f.is_file():
            continue
        if ".venv" in f.parts or "__pycache__" in f.parts or f.suffix == ".pyc":
            continue
        rel = f.relative_to(app_dir)
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
    return stage


def build_entry(meta, zip_path):
    """生成 index.json 里的单个 app 条目"""
    # 白名单：只保留实际生效的字段（system 已废弃，group 为分组来源）
    FIELDS = ("id", "name", "icon", "color", "version", "changelog",
              "port", "cmd", "dock", "group", "released")
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

    zip_name = f"{meta['id']}-{meta['version']}.zip"
    
    # 核心改动：根据 group 决定图标
    group = derive_group(meta)
    kind_tag = "🛡️" if group == "system" else "📦"
    print(f"{kind_tag} 打包 {meta['name']} v{meta['version']} (id={meta['id']}, group={group})...")

    # ---- 源码保护: protect=true 时 .py 编译为 .pyc 出包, 页面压缩, cmd 改写 ----
    protect = bool(meta.get("protect"))
    pkg_meta = meta
    stage = None
    if protect:
        stage = build_pyc_stage(app_dir)
        pkg_meta = dict(meta)
        pkg_meta["cmd"] = _rewrite_cmd_pyc(meta.get("cmd") or [])
        # 包内 app.json 同步改写, 保证安装后 cmd 指向存在的 .pyc
        (stage / "app.json").write_text(
            json.dumps(pkg_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("   🔒 源码保护: pyc 模式(不含 .py 源码, 页面已压缩)")

    src_root = stage if stage else app_dir
    app_rel = app_dir.relative_to(APPS_DIR.parent)  # 如 apps/etws/iqcache-sync
    zip_path = BASE / zip_name
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for f in src_root.rglob("*"):
                if not f.is_file():
                    continue
                if ".venv" in f.parts or f.name == "__pycache__":
                    continue
                if not protect and f.suffix == ".pyc":
                    continue  # 未保护的应用维持原逻辑: 不带 pyc 缓存
                if f.name.endswith(".zip.tmp") or f.name == zip_name:
                    continue
                arcname = (app_rel / f.relative_to(src_root)) if stage else f.relative_to(APPS_DIR.parent)
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
        print(f"🚀 上传 {zip_name} → {SERVER}:{REMOTE}/{PACKAGES_DIR}/")
        try:
            subprocess.run(
                ["scp", str(zip_path), f"{SERVER}:{REMOTE}/{PACKAGES_DIR}/"],
                check=True, capture_output=True, text=True, timeout=120,
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
    )
    print(f"   ✓ index.json 更新完成（{len(index.get('apps', []))} 个应用）")


def _list_remote_packages():
    """ssh 列出远端 packages/ 目录下所有文件名（不含路径）。失败抛异常。"""
    result = subprocess.run(
        ["ssh", SERVER, f"ls -1 {REMOTE}/{PACKAGES_DIR}/"],
        check=True, capture_output=True, text=True, timeout=30,
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
    g.add_argument("--system", action="store_true", help="仅发布系统应用 (等同于 --group system)")
    g.add_argument("--user", action="store_true", help="仅发布用户应用 (等同于 --group user)")
    g.add_argument("--group", type=str, help="仅发布指定分组的应用 (例: --group admin)")
    g.add_argument("--list", action="store_true", help="列出所有可发布的应用")
    g.add_argument("--launcher", action="store_true", help="打包并发布 launcher 主程序更新")
    g.add_argument("--sync", action="store_true", help="对照远端 packages/ 清理 index.json 中失效条目")

    parser.add_argument("--dry-run", action="store_true", help="只打包不上传（测试打包）；--sync 时只预览不写远端")
    parser.add_argument("--yes", "-y", action="store_true", help="跳过交互确认（配合 --sync）")
    parser.add_argument("--changelog", type=str, default="", help="launcher 更新说明（配合 --launcher 使用）")
    return parser.parse_args()

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
    for app_dir in _find_all_app_dirs():
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
    print(f"   ✓ {zip_path.name} ({zip_path.stat().st_size} bytes, "
          f"sha256={sha256(zip_path)[:12]}...)")
          
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
        
        if not _verify_upload(entry["pkg"]):
            print(f"  ⚠ HTTP 验证失败，文件可能不可访问")

        print("📋 更新远端 index.json...")
        index, index_tmp = ensure_index()
        index["launcher"] = entry
        index["updated"] = datetime.datetime.now().isoformat()
        write_and_upload_index(index, index_tmp)

    try:
        zip_path.unlink()
    except OSError:
        pass

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
    has_filter = any([args.app_dir, args.all, args.system, args.user, args.group, args.list])
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

    # 核心改动：解析 kind
    if args.group:
        kind = args.group
    elif args.system:
        kind = "system"
    elif args.user:
        kind = "user"
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