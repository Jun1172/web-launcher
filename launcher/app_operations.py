"""app_operations - 安装 / 卸载 / 版本回退 / Launcher 自更新

核心函数:
- do_install(aid):              安装（升级）应用到最新版本
- do_install_version(aid, ver): 安装指定版本（供回退用）
- do_uninstall(aid):            卸载用户应用（系统应用拒绝）
- get_launcher_version_info():  读取本地+远端 launcher 版本，比较是否可升级
- do_launcher_update():         下载远端 launcher zip → 校验 → bak → 覆盖

所有写入操作使用原子替换 + 备份，与 AC-2/NFR-2 一致。
"""
import json
import shutil
from pathlib import Path

from . import config
from .config import (
    BASE, CONFIG_JSON, SYSTEM_APPS_DIR, USER_APPS_DIR, vt,
)
from .app_registry import (
    is_system_app, is_user_app, reload_apps,
)
from .process_manager import close_app
from .repo import repo_get, repo_index, atomic_extract_zip


# ───────────────────── 应用安装/更新 ─────────────────────

def _resolve_pkg_meta(aid, version=None):
    """在 repo_index() 中查找 app 条目及指定或最新的 {pkg, sha256, version, system}。

    返回 (success, meta_for_unpack, msg)。
    meta_for_unpack 含 {pkg, sha256, version, system}。
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
    system_flag = is_system_app(aid) or bool(match.get("system"))

    if version is not None:
        # 指定版本：从 versions 列表中查找（若无 versions 且 version == latest 则直用）
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
        "system": system_flag,
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

    # 先关进程 → 下载 → 原子替换 → reload
    close_app(aid)
    try:
        data = repo_get(meta["pkg"]).read()
    except Exception as e:
        return False, f"下载失败: {e}"

    dest_root = SYSTEM_APPS_DIR if meta["system"] else USER_APPS_DIR
    target_dir = dest_root / aid
    ok, msg = atomic_extract_zip(data, target_dir, expected_sha256=meta["sha256"])
    if not ok:
        return False, msg

    reload_apps()
    return True, "ok"


# ───────────────────── 卸载 ─────────────────────

def do_uninstall(aid):
    """卸载用户应用。系统应用直接拒绝。"""
    if not aid:
        return False, "缺少 id"
    if is_system_app(aid):
        return False, "系统应用不可卸载"
    app_dir = USER_APPS_DIR / aid
    if not app_dir.exists():
        return False, "未安装"
    close_app(aid)
    shutil.rmtree(app_dir, ignore_errors=True)
    reload_apps()
    return True, "ok"


# ───────────────────── Launcher 版本信息 ─────────────────────

def get_launcher_version_info():
    """读取本地 config 与远端 index.json['launcher'] 对比。

    返回 {local, remote, upgradable, changelog_local, changelog_remote, released_local, released_remote}
    失败时 error 字段说明。
    """
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
    """下载远端 launcher 更新 → 校验 → 执行。返回 (ok, msg, restart_needed)。

    两种模式：
    - frozen（编译为 .exe）: 下载 binary + 用 updater 替换 + 自动重启
    - 开发态（python）: 下载 zip + 覆盖文件 + 提示手动重启
    """
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
        # 写入 launcher.new
        exe_dir = Path(sys.executable).parent
        new_exe = exe_dir / "launcher.new"
        new_exe.write_bytes(data)
        # 安排自更新
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

    # 1. 解压到 BASE / .launcher-tmp.new
    import zipfile
    import tempfile
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

    # 2. 备份 + 覆盖 launcher.py
    lp = unzipped / "launcher.py"
    if lp.exists():
        try:
            _atomic_overwrite_file(lp.read_bytes(), BASE / "launcher.py")
        except Exception as e:
            return False, f"覆盖 launcher.py 失败: {e}", False

    # 2b. 覆盖 launcher/ 包目录（核心代码模块 + templates），不保留 .bak
    remote_pkg = unzipped / "launcher"
    if remote_pkg.exists():
        local_pkg = BASE / "launcher"
        try:
            if local_pkg.exists():
                shutil.rmtree(local_pkg, ignore_errors=True)
            shutil.copytree(remote_pkg, local_pkg)
        except Exception as e:
            return False, f"覆盖 launcher/ 包目录失败: {e}", False

    # 3. 备份 + 覆盖 config.json（保留本地 ports/host 等私有字段，仅更新 launcher 部分）
    cfg_path = BASE / "config.json"
    remote_cfg_p = unzipped / "config.json"
    if remote_cfg_p.exists() and cfg_path.exists():
        try:
            local_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            remote_cfg = json.loads(remote_cfg_p.read_text(encoding="utf-8"))
            merged = dict(local_cfg)
            # 仅合并 launcher 节（更新 version/changelog/released）
            merged["launcher"] = remote_cfg.get("launcher", local_cfg.get("launcher", {}))
            new_bytes = json.dumps(merged, ensure_ascii=False, indent=2).encode("utf-8")
            _atomic_overwrite_file(new_bytes, cfg_path)
        except Exception as e:
            return False, f"合并 config.json 失败: {e}", False

    # 4. 覆盖 apps/system/* （只覆盖远端存在的那些系统应用），不保留 .bak
    sys_dir = unzipped / "apps" / "system"
    if sys_dir.exists():
        for sub in sys_dir.iterdir():
            if not sub.is_dir():
                continue
            target = SYSTEM_APPS_DIR / sub.name
            try:
                if target.exists():
                    shutil.rmtree(target, ignore_errors=True)
                shutil.copytree(sub, target)
            except Exception as e:
                print(f"⚠ 更新系统应用 {sub.name} 失败: {e}")

    # 5. 清理临时目录
    shutil.rmtree(tmp_root, ignore_errors=True)

    # 6. 刷新 config 全局变量，使后续 API 立即返回新版本号/changelog
    config.reload_config()
    return True, "✅ 更新完成，版本号已实时刷新；launcher 代码需重启生效", True
