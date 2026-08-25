"""app_operations - 安装 / 卸载 / Launcher 自更新
核心函数:
do_install(aid):              安装（升级）应用到最新版本
do_uninstall(aid):            卸载普通应用（受保护分组拒绝）
get_launcher_version_info():  读取本地+远端 launcher 版本，比较是否可升级
do_launcher_update():         下载远端 launcher zip → 校验 → bak → 覆盖
"""
import json
import shutil
import urllib.request
import zipfile 
from pathlib import Path
from . import config
from .config import BASE, APPS_DIR, vt
from .app_registry import reload_apps, derive_group
from .process_manager import close_app
from .repo import repo_get, repo_index
from .zipio import atomic_extract_zip

# ━━━━━━━━━━━━━━━━━━━━━ 核心配置 ━━━━━━━━━━━━━━━━━━━━━
# 定义哪些分组的应用是“受保护的”，不允许通过商店卸载
# 未来如果有 admin、dev 等分组也不允许卸载，直接往这里加即可
PROTECTED_GROUPS = {"system"}


# ━━━━━━━━━━━━━━━━━━━━━ 应用安装/更新 ━━━━━━━━━━━━━━━━━━━━━
def _resolve_pkg_meta(aid):
    """在 repo_index() 中查找 app 条目最新的元数据。
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
    app_group = derive_group(match)

    if not target_pkg:
        return False, None, "条目缺少 pkg 字段"

    meta = {
        "pkg": target_pkg,
        "sha256": target_sha,
        "version": target_ver,
        "group": app_group,
    }
    return True, meta, "ok"

def do_install(aid):
    """安装/升级应用到最新版本。"""
    if not aid:
        return False, "缺少 id"
        
    ok, meta, msg = _resolve_pkg_meta(aid)
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
        local_group = derive_group(local_meta)
    except Exception:
        local_group = "user"  # 读取失败默认放行

    if local_group in PROTECTED_GROUPS:
        return False, f"[{local_group}] 分组应用不可卸载"

    close_app(aid)
    shutil.rmtree(app_dir, ignore_errors=True)
    reload_apps()
    return True, "ok"


# ━━━━━━━━━━━━━━━━━━━━━ Launcher 版本信息 ━━━━━━━━━━━━━━━━━━━━━
def get_launcher_version_info():
    """读取 Launcher 版本；exe 模式查 Gitee Release，源码模式查 repo index。"""
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
    if getattr(__import__("sys"), "frozen", False):
        try:
            release = _gitee_latest_release()
            remote_ver = release["version"]
            out.update({
                "remote": remote_ver,
                "changelog_remote": release["changelog"],
                "released_remote": release["released"],
                "source": "gitee-release",
                "asset": release["asset_name"],
            })
            out["upgradable"] = vt(remote_ver) > vt(config.LAUNCHER_VERSION)
        except Exception as e:
            out["error"] = str(e)
        return out

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


def _gitee_latest_release():
    """读取 Gitee 最新 Release，并选择配置的 exe 附件。"""
    cfg = config.GITEE_CFG or {}
    repo = str(cfg.get("repo", "")).strip().strip("/")
    if not repo or "/" not in repo:
        raise ValueError("Gitee 仓库未配置，请填写 owner/repository")
    api_url = f"https://gitee.com/api/v5/repos/{repo}/releases/latest"
    req = urllib.request.Request(api_url, headers={"User-Agent": "WebLauncher"})
    with urllib.request.urlopen(req, timeout=15) as response:
        release = json.loads(response.read().decode("utf-8"))
    tag = str(release.get("tag_name") or "").strip()
    version = tag.lstrip("vV")
    if not version:
        raise ValueError("Gitee 最新 Release 缺少 tag_name")
    assets = release.get("assets") or []
    wanted = cfg.get("release_asset", "launcher.exe")
    asset = next((a for a in assets if a.get("name") == wanted), None)
    if asset is None:
        asset = next((a for a in assets if str(a.get("name", "")).lower().endswith(".exe")), None)
    if not asset or not asset.get("browser_download_url"):
        raise ValueError("Gitee 最新 Release 没有可下载的 exe 附件")
    return {
        "version": version,
        "changelog": release.get("body") or release.get("name") or "",
        "released": release.get("created_at") or "",
        "asset_name": asset.get("name"),
        "asset_url": asset["browser_download_url"],
    }

def _atomic_overwrite_file(src_bytes: bytes, target: Path):
    """直接覆盖 target 文件（不保留 .bak）。"""
    tmp = target.with_suffix(target.suffix + ".tmp.new")
    tmp.write_bytes(src_bytes)
    if target.exists():
        target.unlink()
    shutil.move(str(tmp), str(target))

def do_launcher_update():
    """下载远端 launcher 更新 → 校验 → 执行。

    编译态（PyInstaller）走 _update_frozen（二进制替换 + 重启）；
    开发态走 _update_dev（zip 覆盖源码 + 合并 config + reload）。
    """
    import sys
    import sys
    if getattr(sys, "frozen", False):
        try:
            return _update_frozen_release(_gitee_latest_release())
        except Exception as e:
            return False, f"Gitee Release 更新失败: {e}", False

    try:
        idx = repo_index()
    except Exception as e:
        return False, f"连不上仓库: {e}", False

    meta = idx.get("launcher")
    if not meta:
        return False, "远端无 launcher 发布", False

    if getattr(sys, "frozen", False):
        return _update_frozen(meta)
    return _update_dev(meta)


def _update_frozen(meta):
    """编译态：下载二进制 → 校验 → 安排替换重启。"""
    import hashlib
    binary_pkg = meta.get("binary") or meta.get("pkg")
    if not binary_pkg:
        return False, "远端无 launcher 二进制包", False
    sha = meta.get("sha256")
    try:
        data = repo_get(binary_pkg).read()
    except Exception as e:
        return False, f"下载失败: {e}", False

    if sha and hashlib.sha256(data).hexdigest() != sha:
        return False, "sha256 校验失败", False

    import sys
    new_exe = Path(sys.executable).parent / "launcher.new"
    new_exe.write_bytes(data)

    from . import updater
    ok, msg = updater.launch_self_update(new_exe)
    if ok:
        return True, "更新已下载，程序将自动重启", True
    return False, msg, False


def _update_frozen_release(release):
    """从 Gitee Release 下载 launcher.exe，并安排替换重启。"""
    import hashlib
    try:
        req = urllib.request.Request(release["asset_url"], headers={"User-Agent": "WebLauncher"})
        with urllib.request.urlopen(req, timeout=60) as response:
            data = response.read()
    except Exception as e:
        return False, f"下载 Gitee Release 失败: {e}", False
    if not data.startswith(b"MZ"):
        return False, "下载的 Release 附件不是有效的 Windows exe", False
    new_exe = Path(__import__("sys").executable).parent / "launcher.new"
    new_exe.write_bytes(data)
    from . import updater
    ok, msg = updater.launch_self_update(new_exe)
    if ok:
        return True, f"已下载 Gitee Release v{release['version']}，程序将自动重启", True
    return False, msg, False


def _update_dev(meta):
    """开发态：下载 zip → 校验 → 覆盖源码 → 合并 config → reload。"""
    import hashlib
    pkg = meta.get("pkg")
    if not pkg:
        return False, "远端无 launcher zip 包", False
    sha = meta.get("sha256")
    try:
        data = repo_get(pkg).read()
    except Exception as e:
        return False, f"下载失败: {e}", False

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

    # 覆盖 launcher.py
    lp = unzipped / "launcher.py"
    if lp.exists():
        try:
            _atomic_overwrite_file(lp.read_bytes(), BASE / "launcher.py")
        except Exception as e:
            return False, f"覆盖 launcher.py 失败: {e}", False

    # 覆盖 launcher/ 包目录
    remote_pkg = unzipped / "launcher"
    if remote_pkg.exists():
        local_pkg = BASE / "launcher"
        try:
            if local_pkg.exists():
                shutil.rmtree(local_pkg, ignore_errors=True)
            shutil.copytree(remote_pkg, local_pkg)
        except Exception as e:
            return False, f"覆盖 launcher/ 包目录失败: {e}", False

    # 合并 config.json（保留本地 repo/publish，用远端 launcher 节）
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

    # 覆盖 apps/*（递归任意子目录）
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
                    from .config import safe_print
                    safe_print(f"[WARN] 更新应用 {app_sub.name} 失败: {e}")

    shutil.rmtree(tmp_root, ignore_errors=True)
    config.reload_config()
    return True, "✅ 更新完成，版本号已实时刷新；launcher 代码需重启生效", True