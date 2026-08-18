"""应用发布脚本
用法:
  python publish.py                     # 列出所有可发布的应用
  python publish.py <app_dir>           # 发布单个（例: apps/user/hello）
  python publish.py --all               # 一键发布所有应用
  python publish.py --system            # 一键发布所有系统应用
  python publish.py --user              # 一键发布所有用户应用
  python publish.py --list              # 仅列出，不发布
  python publish.py --launcher          # 打包并发布 launcher 主程序更新
"""
import argparse
import datetime
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

BASE = Path(__file__).parent.parent.resolve()
CONFIG_JSON = BASE / "config.json"
APPS_DIR = BASE / "apps"
SYSTEM_DIR = APPS_DIR / "system"
USER_DIR = APPS_DIR / "user"


def load_config():
    if CONFIG_JSON.exists():
        return json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
    return {}


CONFIG = load_config()
PUBLISH_CFG = CONFIG.get("publish", {})
SERVER = PUBLISH_CFG.get("server", "jun@172.18.119.215")
REMOTE = PUBLISH_CFG.get("remote_path", "/var/www/repo")
PACKAGES_DIR = PUBLISH_CFG.get("packages_dir", "packages")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def discover_apps(kind="all"):
    """返回 [app_dir, ...] 列表
    kind: 'all' | 'system' | 'user'
    """
    dirs = []
    if kind in ("all", "system"):
        if SYSTEM_DIR.exists():
            dirs += sorted([d for d in SYSTEM_DIR.iterdir() if d.is_dir() and (d / "app.json").exists()])
    if kind in ("all", "user"):
        if USER_DIR.exists():
            dirs += sorted([d for d in USER_DIR.iterdir() if d.is_dir() and (d / "app.json").exists()])
    return dirs


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
        kind = "SYSTEM" if d.parent.name == "system" else "USER  "
        rel = d.relative_to(BASE).as_posix()
        rows.append((kind, rel, meta.get("id", "?"), meta.get("version", "?"), meta.get("name", "?")))
    print(f"  {'类型':6} {'路径':30} {'id':12} {'版本':8} 名称")
    print(f"  {'-'*6} {'-'*30} {'-'*12} {'-'*8} {'-'*20}")
    for k, r, aid, v, n in rows:
        print(f"  {k:6} {r:30} {aid:12} {v:8} {n}")


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


def build_entry(meta, zip_path):
    """生成 index.json 里的单个 app 条目
    注意：env 故意不在白名单中（防密钥上传到远端仓库），由部署方本地填写
    """
    FIELDS = ("id", "name", "icon", "color", "version", "changelog",
              "port", "cmd", "dock", "system",
              "ready_check", "workdir", "stop_signal", "stop_timeout",
              "restart_policy", "requires", "released")
    entry = {k: meta[k] for k in FIELDS if k in meta}
    entry["pkg"] = f"{PACKAGES_DIR}/{zip_path.name}"
    entry["size"] = zip_path.stat().st_size
    entry["sha256"] = sha256(zip_path)
    entry.setdefault("released", datetime.datetime.now().isoformat())
    return entry


MAX_VERSIONS = 1   # 每个应用只保留最近 1 个历史版本（供回退），不过度复杂


def _add_to_versions(existing_entry: dict | None, new_entry: dict) -> list:
    """把 existing_entry 的版本信息存入 versions，返回合并后的 versions 列表。

    - existing_entry = 原 index.json 里的当前版本（若有）
    - versions 每元素: {version, pkg, sha256, changelog, released}
    - 规则: 若 existing_entry.version == new_entry.version，不重复保留；否则前置
    - 按时间倒序，超 MAX_VERSIONS 截断
    """
    versions = list((existing_entry or {}).get("versions", []) or [])
    if existing_entry and existing_entry.get("version") != new_entry["version"]:
        # 把旧当前版本降级为历史
        history = {
            "version": existing_entry.get("version"),
            "pkg": existing_entry.get("pkg"),
            "sha256": existing_entry.get("sha256"),
            "changelog": existing_entry.get("changelog", ""),
            "released": existing_entry.get("released", ""),
            "size": existing_entry.get("size"),
        }
        if history["version"] and history["pkg"]:
            # 去重（按 version）
            versions = [v for v in versions if v.get("version") != history["version"]]
            versions.insert(0, history)
    # 最新在前，超过上限删除
    return versions[:MAX_VERSIONS]


def publish_one(app_dir, *, upload=True, index_override=None):
    """发布单个应用
    - upload=False: 只打包不上传（测试用）
    - index_override: 传入的 index dict（批量发布时共用一个）；不传时会自己拉远端
    返回 (success, index_dict_or_None, entry_or_None)
    """
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
    kind_tag = "🛡️" if (app_dir.parent.name == "system" or meta.get("system")) else "📦"

    print(f"{kind_tag} 打包 {meta['name']} v{meta['version']} (id={meta['id']})...")

    # 打包：把 app 目录以 "apps/{system|user}/<id>/" 的 arcname 写入 zip
    zip_path = BASE / zip_name
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in app_dir.rglob("*"):
            if not f.is_file():
                continue
            if ".venv" in f.parts or f.suffix == ".pyc" or f.name == "__pycache__":
                continue
            if f.name.endswith(".zip.tmp") or f.name == zip_name:
                continue
            arcname = f.relative_to(APPS_DIR.parent)  # e.g. apps/user/hello/app.json
            z.write(f, arcname.as_posix())
    print(f"   ✓ {zip_name} ({zip_path.stat().st_size} bytes, sha256={sha256(zip_path)[:12]}...)")

    entry = build_entry(meta, zip_path)
    index = index_override
    index_tmp = None

    if upload:
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

        # 拉 / 更新 index
        if index is None:
            print("📋 更新远端 index.json...")
            index, index_tmp = ensure_index()
        # 合并 entry：原当前版本降级为历史 versions
        old_entry = next((a for a in index.get("apps", []) if a["id"] == meta["id"]), None)
        entry["versions"] = _add_to_versions(old_entry, entry)
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


def parse_args():
    parser = argparse.ArgumentParser(
        description="应用发布工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python publish.py apps/user/hello                    发布单个 app\n"
               "  python publish.py --all                               发布所有应用\n"
               "  python publish.py --system                            发布全部系统应用\n"
               "  python publish.py --user                              发布全部用户应用\n"
               "  python publish.py --list                              列出所有应用\n"
               "  python publish.py --launcher --changelog \"修复 bug\"  发布 launcher 更新\n",
    )
    g = parser.add_mutually_exclusive_group()
    g.add_argument("app_dir", nargs="?", help="要发布的单个应用路径")
    g.add_argument("--all", action="store_true", help="发布所有应用")
    g.add_argument("--system", action="store_true", help="仅发布系统应用")
    g.add_argument("--user", action="store_true", help="仅发布用户应用")
    g.add_argument("--list", action="store_true", help="列出所有可发布的应用")
    g.add_argument("--launcher", action="store_true", help="打包并发布 launcher 主程序更新")
    parser.add_argument("--dry-run", action="store_true", help="只打包不上传（测试打包）")
    parser.add_argument("--changelog", type=str, default="", help="launcher 更新说明（配合 --launcher 使用）")
    return parser.parse_args()


def build_launcher_zip(version: str, changelog: str) -> Path:
    """把 launcher 基础文件打包成 zip：
    包含: launcher.py, config.json（去除 publish 等敏感字段）, apps 骨架, 基础工具
    返回 zip 文件路径（BASE/launcher-<version>.zip）
    """
    # launcher 核心文件（相对 BASE）
    include_patterns = [
        "launcher.py",
        "config.json",
        "README.md",
        "apps/publish.py",
        "apps/README.md",
    ]
    # apps/system/ 系统应用目录骨架（每个系统应用的全部文件）
    system_apps_dir = APPS_DIR / "system"
    system_files = []
    if system_apps_dir.exists():
        for p in system_apps_dir.rglob("*"):
            if p.is_file() and not (p.suffix == ".pyc" or p.name == "__pycache__" or ".venv" in p.parts):
                system_files.append(p.relative_to(BASE))

    files = [Path(p) for p in include_patterns if (BASE / p).exists()]
    files += system_files

    zip_path = BASE / f"launcher-{version}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in files:
            full = BASE / rel
            # config.json 特别处理：去掉 publish/server 等敏感字段，只保留客户端需要的
            if rel == Path("config.json"):
                try:
                    cfg = json.loads(full.read_text(encoding="utf-8"))
                except Exception:
                    cfg = {}
                # 只保留客户端安全字段
                safe_cfg = {
                    "launcher": cfg.get("launcher", {}),
                    "repo": {"url": cfg.get("repo", {}).get("url", ""), "verify_ssl": cfg.get("repo", {}).get("verify_ssl", False)},
                    "ports": cfg.get("ports", {}),
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

        print("📋 更新远端 index.json...")
        index, index_tmp = ensure_index()
        # launcher 同样支持历史版本回退
        old_launcher = index.get("launcher") or None
        entry["versions"] = _add_to_versions(old_launcher, entry)
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

    # --launcher
    if args.launcher:
        ok = publish_launcher(upload=not args.dry_run, changelog=args.changelog)
        sys.exit(0 if ok else 4)

    # 列出所有 / 无参数时列出
    if args.list or (not any([args.app_dir, args.all, args.system, args.user, args.list])):
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
        print("  系统应用  : python publish.py --system")
        print("  用户应用  : python publish.py --user")
        print("  只打包    : python publish.py apps/user/hello --dry-run")
        print("  Launcher  : python publish.py --launcher --changelog \"说明\"")
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

    kind = "all" if args.all else ("system" if args.system else "user")
    apps = discover_apps(kind)
    if not apps:
        print(f"⚠ 没有找到类型为 {kind!r} 的应用")
        sys.exit(1)

    print(f"🚀 开始批量发布 ({kind})，共 {len(apps)} 个应用:")
    print_apps_table(apps)
    print()

    # 拉一次 index，批量发布共用
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
                    index = new_index  # 合并 entry 已经在 publish_one 里做了
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
