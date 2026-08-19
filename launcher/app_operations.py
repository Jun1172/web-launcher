"""app_operations - 安装 / 卸载 / 版本回退 / Launcher 自更新
核心函数:
do_install(aid):              安装（升级）应用到最新版本
do_install_version(aid, ver): 安装指定版本（供回退用）
do_uninstall(aid):            卸载普通应用（受保护分组拒绝）
get_launcher_version_info():  读取本地+远端 launcher 版本，比较是否可升级
do_launcher_update():         下载远端 launcher zip → 校验 → bak → 覆盖
"""
import json
import shutil
import zipfile 
from pathlib import Path
from . import config
from .config import (
    BASE, CONFIG_JSON, APPS_DIR, SYSTEM_APPS_DIR, USER_APPS_DIR, vt,
)
from .app_registry import reload_apps
from .process_manager import close_app
from .repo import repo_get, repo_index, atomic_extract_zip

# ━━━━━━━━━━━━━━━━━━━━━ 核心配置 ━━━━━━━━━━━━━━━━━━━━━
# 定义哪些分组的应用是“受保护的”，不允许通过商店卸载
# 未来如果有 admin、dev 等分组也不允许卸载，直接往这里加即可
PROTECTED_GROUPS = {"system"}


# ━━━━━━━━━━━━━━━━━━━━━ 应用安装/更新 ━━━━━━━━━━━━━━━━━━━━━
def _resolve_pkg_meta(aid, version=None):
    """在 repo_index() 中查找 app 条目及指定或最新的元数据。
    返回 (success, meta_for_unpack, msg)。
    """
    try:
        idx = repo_index()
    except Exception as e:
        return False, None, f"连不上仓库: {e}"
        
    apps = idx.get("apps", [])
    match = next((m for m in apps if m["id"] == aid), None)
    if not match:
        return False, None, "仓库中不存在该 id"

    target_pkg = match.get("pkg")
    target_sha = match.get("sha256")
    target_ver = match.get("version", "0.0.1")
    
    # 核心改动：获取 group，兼容旧版 system 字段
    app_group = match.get("group")
    if app_group is None:
        app_group = "system" if match.get("system") else "user"
        
    is_protected = app_group in PROTECTED_GROUPS

    if version is not None:
        if version != match.get("version"):
            versions = match.get("versions", []) or []
            v_meta = next((v for v in versions if v.get("version") == version), None)
            if not v_meta:
                return False, None, f"仓库无此历史版本: {version}"
            target_pkg = v_meta.get("pkg")
            target_sha = v_meta.get("sha256")
            target_ver = version

    if not target_pkg:
        return False, None, "条目缺少 pkg 字段"

    meta = {
        "pkg": target_pkg,
        "sha256": target_sha,
        "version": target_ver,
        "group": app_group,         # <--- 传递 group 字符串
        "is_protected": is_protected # <--- 传递保护状态
    }
    return True, meta, "ok"

def do_install(aid):
    """安装/升级应用到最新版本。"""
    return do_install_version(aid, version=None)

def do_install_version(aid, version):
    """安装/升级/回退到指定 version。version=None 表示最新。"""
    if not aid:
        return False, "缺少 id"
        
    ok, meta, msg = _resolve_pkg_meta(aid, version=version)
    if not ok:
        return False, msg

    close_app(aid)
    try:
        data = repo_get(meta["pkg"]).read()
    except Exception as e:
        return False, f"下载失败: {e}"

    # 核心改动：目标根目录变为 APPS_DIR / group
    dest_root = APPS_DIR / meta["group"]
    target_dir = dest_root / aid
    
    ok, msg = atomic_extract_zip(data, target_dir, expected_sha256=meta["sha256"])
    if not ok:
        return False, msg
        
    reload_apps()
    return True, "ok"


# ━━━━━━━━━━━━━━━━━━━━━ 卸载 ━━━━━━━━━━━━━━━━━━━━━
def do_uninstall(aid):
    """卸载普通应用。受保护分组直接拒绝。"""
    if not aid:
        return False, "缺少 id"

    # 在 APPS_DIR 下递归查找应用目录（不限定具体分组目录）
    app_dir = None
    for d in APPS_DIR.rglob(aid):
        if d.is_dir() and (d / "app.json").exists():
            app_dir = d
            break

    if app_dir is None:
        return False, "未安装"

    # 核心改动：读取本地 app.json 判断是否受保护
    try:
        local_meta = json.loads((app_dir / "app.json").read_text(encoding="utf-8"))
        local_group = local_meta.get("group")
        if local_group is None:
            local_group = "system" if local_meta.get("system") else "user"
    except Exception:
        local_group = "user" # 读取失败默认放行

    if local_group in PROTECTED_GROUPS:
        return False, f"[{local_group}] 分组应用不可卸载"

    close_app(aid)
    shutil.rmtree(app_dir, ignore_errors=True)
    reload_apps()
    return True, "ok"


# ━━━━━━━━━━━━━━━━━━━━━ Launcher 版本信息 ━━━━━━━━━━━━━━━━━━━━━
def get_launcher_version_info():
    """读取本地 config 与远端 index.json['launcher'] 对比。"""
    out = {
        "local": config.LAUNCHER_VERSION,
        "remote": None,
        "upgradable": False,
        "changelog_local": config.LAUNCHER_CHANGELOG,
        "changelog_remote": "",
        "released_local": config.LAUNCHER_RELEASED,
        "released_remote": "",
        "error": None,
    }
    try:
        idx = repo_index()
    except Exception as e:
        out["error"] = str(e)
        return out

    launcher_meta = idx.get("launcher") or {}
    remote_ver = launcher_meta.get("version")
    out["remote"] = remote_ver
    out["changelog_remote"] = launcher_meta.get("changelog", "")
    out["released_remote"] = launcher_meta.get("released", "")

    if remote_ver and vt(remote_ver) > vt(config.LAUNCHER_VERSION):
        out["upgradable"] = True
    return out

def _atomic_overwrite_file(src_bytes: bytes, target: Path):
    """直接覆盖 target 文件（不保留 .bak）。"""
    tmp = target.with_suffix(target.suffix + ".tmp.new")
    tmp.write_bytes(src_bytes)
    if target.exists():
        target.unlink()
    shutil.move(str(tmp), str(target))

def do_launcher_update():
    """下载远端 launcher 更新 → 校验 → 执行。"""
    import sys
    is_frozen = getattr(sys, "frozen", False)
    try:
        idx = repo_index()
    except Exception as e:
        return False, f"连不上仓库: {e}", False

    meta = idx.get("launcher")
    if not meta:
        return False, "远端无 launcher 发布", False

    # ── 编译态：下载 binary ──
    if is_frozen:
        binary_pkg = meta.get("binary") or meta.get("pkg")
        if not binary_pkg:
            return False, "远端无 launcher 二进制包", False
        sha = meta.get("sha256")
        try:
            data = repo_get(binary_pkg).read()
        except Exception as e:
            return False, f"下载失败: {e}", False
            
        if sha:
            import hashlib
            if hashlib.sha256(data).hexdigest() != sha:
                return False, "sha256 校验失败", False

        exe_dir = Path(sys.executable).parent
        new_exe = exe_dir / "launcher.new"
        new_exe.write_bytes(data)

        from . import updater
        ok, msg = updater.launch_self_update(
            f"{config.REPO_URL.rstrip('/')}/{binary_pkg}"
        )
        if ok:
            return True, "更新已下载，程序将自动重启", True
        return False, msg, False

    # ── 开发态：下载 zip ──
    pkg = meta.get("pkg")
    if not pkg:
        return False, "远端无 launcher zip 包", False
    sha = meta.get("sha256")
    try:
        data = repo_get(pkg).read()
    except Exception as e:
        return False, f"下载失败: {e}", False

    import hashlib
    if sha and hashlib.sha256(data).hexdigest() != sha:
        return False, "launcher 包 sha256 校验失败", False

    tmp_root = BASE / ".launcher-update.tmp"
    if tmp_root.exists():
        shutil.rmtree(tmp_root, ignore_errors=True)
    tmp_root.mkdir()
    zip_tmp = tmp_root / "pkg.zip"
    zip_tmp.write_bytes(data)
    
    try:
        with zipfile.ZipFile(zip_tmp) as z:
            bad = [n for n in z.namelist() if n.startswith("/") or ".." in n]
            if bad:
                return False, "launcher 包含非法路径", False
            z.extractall(tmp_root / "unzipped")
    except Exception as e:
        return False, f"launcher 解压失败: {e}", False
        
    unzipped = tmp_root / "unzipped"

    lp = unzipped / "launcher.py"
    if lp.exists():
        try:
            _atomic_overwrite_file(lp.read_bytes(), BASE / "launcher.py")
        except Exception as e:
            return False, f"覆盖 launcher.py 失败: {e}", False

    remote_pkg = unzipped / "launcher"
    if remote_pkg.exists():
        local_pkg = BASE / "launcher"
        try:
            if local_pkg.exists():
                shutil.rmtree(local_pkg, ignore_errors=True)
            shutil.copytree(remote_pkg, local_pkg)
        except Exception as e:
            return False, f"覆盖 launcher/ 包目录失败: {e}", False

    cfg_path = BASE / "config.json"
    remote_cfg_p = unzipped / "config.json"
    if remote_cfg_p.exists() and cfg_path.exists():
        try:
            local_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            remote_cfg = json.loads(remote_cfg_p.read_text(encoding="utf-8"))
            merged = dict(local_cfg)
            merged["launcher"] = remote_cfg.get("launcher", local_cfg.get("launcher", {}))
            new_bytes = json.dumps(merged, ensure_ascii=False, indent=2).encode("utf-8")
            _atomic_overwrite_file(new_bytes, cfg_path)
        except Exception as e:
            return False, f"合并 config.json 失败: {e}", False

    # 覆盖 apps/* 下的所有应用（递归处理任意子目录），不保留 .bak
    apps_in_zip = unzipped / "apps"
    if apps_in_zip.exists() and apps_in_zip.is_dir():
        for sub_dir in apps_in_zip.iterdir():
            if not sub_dir.is_dir():
                continue
            for app_sub in sub_dir.iterdir():
                if not app_sub.is_dir():
                    continue
                target = APPS_DIR / sub_dir.name / app_sub.name
                try:
                    if target.exists():
                        shutil.rmtree(target, ignore_errors=True)
                    shutil.copytree(app_sub, target)
                except Exception as e:
                    print(f"⚠ 更新应用 {app_sub.name} 失败: {e}")

    shutil.rmtree(tmp_root, ignore_errors=True)
    config.reload_config()
    return True, "✅ 更新完成，版本号已实时刷新；launcher 代码需重启生效", True