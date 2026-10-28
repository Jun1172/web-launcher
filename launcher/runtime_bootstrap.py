# -*- coding: utf-8 -*-
"""runtime_bootstrap - 运行时自动下载与部署

职责：
- 启动时检查全局 runtime 是否存在（runtime/win-x64/python.exe）
- 不存在则从服务器自动下载 runtime.zip 并解压
- 提供前端 API 查询下载状态/手动触发下载

运行时来源：
- 服务器: https://1.15.30.237/runtime.zip (13MB)
- 本地生成: python tools/make_runtime.py

使用场景：
- 普通用户首次运行 launcher 时自动下载，无需手动部署
- standalone 应用自带 runtime，不受此影响
"""
import os
import sys
import zipfile
import tempfile
import threading
import time
from pathlib import Path

from .config import BASE, REPO_URL, safe_print, SSL_CTX
from .process_manager import runtime_python

# 运行时状态
_runtime_status = {
    "checking": False,      # 正在检查
    "downloading": False,   # 正在下载
    "extracting": False,    # 正在解压
    "ready": None,          # 是否就绪（True/False/None=未检查）
    "error": None,          # 错误信息
    "progress": 0,          # 下载进度 0-100
    "size_downloaded": 0,   # 已下载字节数
    "size_total": 0,        # 总字节数
    "speed_bps": 0,         # runtime 当前速度
    "wheels_downloading": False,
    "wheels_progress": 0,
    "wheels_size_downloaded": 0,
    "wheels_size_total": 0,
    "wheels_speed_bps": 0,
    "wheels_ready": None,
    "wheels_error": None,
}
_status_lock = threading.Lock()
_progress_started = {"runtime": None, "wheels": None}


def _runtime_dir():
    """全局运行时目录：runtime/win-x64（Windows）或 runtime/linux-x64（Linux）。"""
    if os.name == "nt":
        return BASE / "runtime" / "win-x64"
    return BASE / "runtime" / "linux-x64"


def _runtime_exe():
    """运行时 python 可执行文件路径。"""
    rd = _runtime_dir()
    if os.name == "nt":
        return rd / "python.exe"
    return rd / "bin" / "python3"


def _runtime_zip_url():
    """运行时下载地址：从 repo 配置推断，或使用默认值。"""
    base = (REPO_URL or "https://1.15.30.237").rstrip("/")
    return f"{base}/runtime.zip"


def _platform_tag():
    """返回当前平台目录名，与 deps_installer/publish.py 保持一致。"""
    if os.name == "nt":
        return "win-x64"
    machine = os.uname().machine.lower()
    if sys.maxsize > 2 ** 32 and machine.startswith(("aarch", "arm")):
        return "linux-arm64"
    return "linux-x64"


def _wheels_zip_url():
    """平台 wheels 压缩包下载地址。"""
    base = (REPO_URL or "https://1.15.30.237").rstrip("/")
    return f"{base}/wheels-{_platform_tag()}.zip"


def _wheels_dir():
    """本地平台 wheels 目录。"""
    return BASE / "wheels" / _platform_tag()


def check_runtime():
    """检查运行时是否存在且有效。返回 (exists: bool, path: str or None)。"""
    import shutil

    exe = _runtime_exe()
    exists = exe.is_file()
    staging = _runtime_dir().with_name(_runtime_dir().name + ".download")
    with _status_lock:
        # 只在不在下载/解压状态时更新状态和清理上次残留的临时目录。
        busy = _runtime_status["downloading"] or _runtime_status["extracting"]
        if not busy:
            _runtime_status["ready"] = exists
            _runtime_status["error"] = None if exists else "运行时未部署"
            _runtime_status["checking"] = False
    if not busy and staging.exists():
        try:
            shutil.rmtree(staging)
            safe_print(f"[INFO] 已清理残留运行时临时目录: {staging}")
        except OSError as e:
            safe_print(f"[WARN] 清理运行时临时目录失败: {e}")
    return exists, str(exe) if exists else None


def get_runtime_status():
    """获取运行时状态（前端 API 用）。返回状态字典副本。"""
    with _status_lock:
        return dict(_runtime_status)


def _download_progress(downloaded, total):
    """更新 runtime 下载进度、大小和速度。"""
    now = time.monotonic()
    if _progress_started["runtime"] is None:
        _progress_started["runtime"] = now
    elapsed = max(now - _progress_started["runtime"], 0.001)
    with _status_lock:
        _runtime_status["size_downloaded"] = downloaded
        _runtime_status["size_total"] = total
        _runtime_status["progress"] = int(downloaded * 100 / total) if total > 0 else 0
        _runtime_status["speed_bps"] = int(downloaded / elapsed)


def _wheels_download_progress(downloaded, total):
    """更新 wheels 下载进度、大小和速度。"""
    now = time.monotonic()
    if _progress_started["wheels"] is None:
        _progress_started["wheels"] = now
    elapsed = max(now - _progress_started["wheels"], 0.001)
    with _status_lock:
        _runtime_status["wheels_size_downloaded"] = downloaded
        _runtime_status["wheels_size_total"] = total
        _runtime_status["wheels_progress"] = int(downloaded * 100 / total) if total > 0 else 0
        _runtime_status["wheels_speed_bps"] = int(downloaded / elapsed)


def _download_runtime(url, dest_zip, progress_cb=None, label="运行时"):
    """下载 zip 文件。返回 (ok, error_msg)。"""
    try:
        import urllib.request
        from urllib.error import URLError, HTTPError
        
        safe_print(f"[INFO] 开始下载{label}: {url}")
        
        # 创建临时文件
        dest_zip.parent.mkdir(parents=True, exist_ok=True)
        tmp_zip = dest_zip.with_name(dest_zip.name + ".download")
        
        def _report_hook(count, block_size, total_size):
            downloaded = count * block_size
            if progress_cb:
                progress_cb(downloaded, total_size)
        
        # 使用 SSL_CTX 忽略证书验证（如果配置了 verify_ssl=false）
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=SSL_CTX)
        )
        urllib.request.install_opener(opener)
        
        urllib.request.urlretrieve(url, tmp_zip, reporthook=_report_hook)
        tmp_zip.rename(dest_zip)
        
        safe_print(f"[INFO] 运行时下载完成: {dest_zip}")
        return True, None
        
    except HTTPError as e:
        err = f"下载失败 (HTTP {e.code}): {e.reason}"
        safe_print(f"[ERR] {err}")
        return False, err
    except URLError as e:
        err = f"下载失败 (网络错误): {e.reason}"
        safe_print(f"[ERR] {err}")
        return False, err
    except Exception as e:
        err = f"下载失败: {e}"
        safe_print(f"[ERR] {err}")
        return False, err


def _install_staged_dir(staging, dest_dir):
    """把临时目录安装到正式目录，兼容 Windows 杀毒软件短暂占用。"""
    import shutil

    staging = Path(staging)
    dest_dir = Path(dest_dir)
    last_error = None
    for attempt in range(8):
        try:
            dest_dir.parent.mkdir(parents=True, exist_ok=True)
            if dest_dir.exists() and not dest_dir.is_dir():
                dest_dir.unlink()
            # 不依赖 Windows 目录 rename；允许目标目录已存在并覆盖同名文件。
            shutil.copytree(staging, dest_dir, dirs_exist_ok=True)
            break
        except PermissionError as e:
            last_error = e
            if attempt < 7:
                time.sleep(1)
            else:
                raise last_error

    # 复制成功后，临时目录清理失败不应判定运行时安装失败；杀毒软件释放
    # 文件句柄后，下次启动还会再次清理残留目录。
    for attempt in range(3):
        try:
            shutil.rmtree(staging)
            return
        except PermissionError:
            if attempt < 2:
                time.sleep(1)
    safe_print(f"[WARN] 临时目录暂时无法清理，将在下次启动时重试: {staging}")


def _extract_runtime(zip_path, dest_dir):
    """安全解压 runtime.zip 到 runtime/<平台>/，返回 (ok, error_msg)。"""
    import shutil

    dest_dir = Path(dest_dir)
    platform_name = dest_dir.name  # win-x64 / linux-x64
    staging = dest_dir.with_name(dest_dir.name + ".download")
    installed = False

    try:
        safe_print(f"[INFO] 开始解压运行时: {zip_path}")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)

        extracted = 0
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue

                # 兼容三种历史/发布结构：
                #   python.exe ...                 （当前标准）
                #   win-x64/python.exe ...         （兼容）
                #   runtime/win-x64/python.exe ... （兼容旧手工压包）
                name = info.filename.replace("\\", "/").lstrip("/")
                prefixes = (
                    f"runtime/{platform_name}/",
                    f"{platform_name}/",
                    "runtime/",
                )
                for prefix in prefixes:
                    if name.startswith(prefix):
                        name = name[len(prefix):]
                        break

                parts = Path(name).parts
                if not name or ".." in parts:
                    raise ValueError(f"zip 包含非法路径: {info.filename}")

                target = staging.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted += 1

        expected = staging / ("python.exe" if os.name == "nt" else Path("bin") / "python3")
        if not expected.is_file():
            raise ValueError(f"zip 中未找到运行时解释器: {expected.relative_to(staging)}")

        # Windows 下目录可能被 Defender/索引服务短暂占用，不能依赖目录 rename。
        _install_staged_dir(staging, dest_dir)
        installed = True
        final_expected = dest_dir / ("python.exe" if os.name == "nt" else Path("bin") / "python3")
        if not final_expected.is_file():
            raise ValueError(f"运行时安装后未找到解释器: {final_expected}")
        safe_print(f"[INFO] 运行时解压完成: {dest_dir} ({extracted} 文件)")
        return True, None

    except zipfile.BadZipFile as e:
        err = f"解压失败 (zip 文件损坏): {e}"
        safe_print(f"[ERR] {err}")
        return False, err
    except Exception as e:
        err = f"解压失败: {e}"
        safe_print(f"[ERR] {err}")
        return False, err
    finally:
        # 失败时一定清理临时目录；成功时 staging 已改名，不存在。
        if not installed and staging.exists():
            try:
                shutil.rmtree(staging)
            except OSError as e:
                safe_print(f"[WARN] 清理临时运行时目录失败: {e}")


def _extract_wheels(zip_path):
    """安全解压平台 wheels 包到 wheels/<平台>/。"""
    import shutil

    dest_dir = _wheels_dir()
    staging = dest_dir.with_name(dest_dir.name + ".download")
    installed = False
    try:
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)
        count = 0
        with zipfile.ZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename.replace("\\", "/").lstrip("/")
                parts = Path(name).parts
                if not name or ".." in parts or Path(name).suffix.lower() != ".whl":
                    raise ValueError(f"wheels 包含非法文件: {info.filename}")
                target = staging.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                count += 1
        if count == 0:
            raise ValueError("wheels 包为空")
        _install_staged_dir(staging, dest_dir)
        installed = True
        safe_print(f"[INFO] wheels 解压完成: {dest_dir} ({count} 个 wheel)")
        return True, None
    except zipfile.BadZipFile as e:
        err = f"wheels 解压失败 (zip 文件损坏): {e}"
        safe_print(f"[ERR] {err}")
        return False, err
    except Exception as e:
        err = f"wheels 解压失败: {e}"
        safe_print(f"[ERR] {err}")
        return False, err
    finally:
        if not installed and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _download_wheels_if_needed():
    """下载并部署 wheels；服务器没有 wheels 包时不阻断运行时启动。"""
    wheel_dir = _wheels_dir()
    if wheel_dir.is_dir() and any(wheel_dir.glob("*.whl")):
        with _status_lock:
            _runtime_status["wheels_ready"] = True
            _runtime_status["wheels_error"] = None
        return True, None

    with _status_lock:
        _runtime_status["wheels_downloading"] = True
        _runtime_status["wheels_progress"] = 0
        _runtime_status["wheels_size_downloaded"] = 0
        _runtime_status["wheels_size_total"] = 0
        _runtime_status["wheels_speed_bps"] = 0
        _runtime_status["wheels_error"] = None
    _progress_started["wheels"] = time.monotonic()
    zip_path = BASE / f"wheels-{_platform_tag()}.zip.tmp"
    ok, err = _download_runtime(
        _wheels_zip_url(), zip_path,
        progress_cb=_wheels_download_progress,
        label="wheels")
    if ok:
        ok, err = _extract_wheels(zip_path)
    try:
        zip_path.unlink(missing_ok=True)
    except OSError:
        pass
    with _status_lock:
        _runtime_status["wheels_downloading"] = False
        _runtime_status["wheels_ready"] = bool(ok)
        _runtime_status["wheels_error"] = err
    if not ok:
        # wheels 是可选的增量资源；没有依赖的 App 仍可正常运行。
        safe_print(f"[WARN] wheels 自动部署未完成: {err}")
    return ok, err


def download_runtime_async(callback=None):
    """异步下载并部署 runtime 与平台 wheels。

    runtime 下载失败会返回失败；wheels 是增量资源，缺少时记录警告但不阻断
    没有第三方依赖的应用启动。
    """
    def _worker():
        with _status_lock:
            if (_runtime_status["downloading"] or _runtime_status["extracting"]
                    or _runtime_status["wheels_downloading"]):
                return
            _runtime_status["checking"] = True
            _runtime_status["error"] = None

        runtime_ok = False
        runtime_err = None
        try:
            # 1. 检查全局 runtime；已有则跳过 runtime 下载，但继续检查 wheels。
            exists, _ = check_runtime()
            if exists:
                safe_print("[INFO] 运行时已存在，跳过 runtime 下载")
                runtime_ok = True
            else:
                with _status_lock:
                    _runtime_status["checking"] = False
                    _runtime_status["downloading"] = True
                    _runtime_status["progress"] = 0
                    _runtime_status["size_downloaded"] = 0
                    _runtime_status["size_total"] = 0
                    _runtime_status["speed_bps"] = 0
                _progress_started["runtime"] = time.monotonic()

                dest_zip = BASE / "runtime.zip.tmp"
                runtime_ok, runtime_err = _download_runtime(
                    _runtime_zip_url(), dest_zip, progress_cb=_download_progress)
                if runtime_ok:
                    with _status_lock:
                        _runtime_status["downloading"] = False
                        _runtime_status["extracting"] = True
                    runtime_ok, runtime_err = _extract_runtime(dest_zip, _runtime_dir())
                try:
                    dest_zip.unlink(missing_ok=True)
                except OSError:
                    pass

                with _status_lock:
                    _runtime_status["downloading"] = False
                    _runtime_status["extracting"] = False
                    _runtime_status["ready"] = bool(runtime_ok)
                    _runtime_status["error"] = runtime_err

            if not runtime_ok:
                if callback:
                    callback(False, runtime_err)
                return

            with _status_lock:
                _runtime_status["checking"] = False
                _runtime_status["ready"] = True

            # 2. runtime 就绪后自动下载平台 wheels。
            _download_wheels_if_needed()
            if callback:
                callback(True, None)

        except Exception as e:
            err = f"运行时部署失败: {e}"
            safe_print(f"[ERR] {err}")
            with _status_lock:
                _runtime_status["checking"] = False
                _runtime_status["downloading"] = False
                _runtime_status["extracting"] = False
                _runtime_status["wheels_downloading"] = False
                _runtime_status["ready"] = False
                _runtime_status["error"] = err
            if callback:
                callback(False, err)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()


def ensure_runtime():
    """确保 runtime 可用，并后台同步下载平台 wheels。

    返回 (runtime_exists: bool, path: str or None)。
    """
    exists, path = check_runtime()
    # 即使 runtime 已存在，也要触发 wheels 检查/下载。
    if exists:
        download_runtime_async()
        return True, path

    safe_print("[INFO] 检测到运行时缺失，启动自动下载")
    download_runtime_async()
    return False, None


# 启动时自动检查（可选，由 __main__.py 决定是否调用）
if __name__ == "__main__":
    # 测试代码：直接运行此模块可手动触发下载
    print("检查运行时...")
    exists, path = check_runtime()
    if exists:
        print(f"✓ 运行时已就绪: {path}")
    else:
        print("✗ 运行时缺失，开始下载...")
        download_runtime_async(callback=lambda ok, err: print("完成" if ok else f"失败: {err}"))
        while True:
            time.sleep(0.5)
            status = get_runtime_status()
            if status["ready"]:
                print("✓ 运行时部署完成")
                break
            if status["error"]:
                print(f"✗ {status['error']}")
                break
