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
}
_status_lock = threading.Lock()


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
    """下载进度回调：更新状态。"""
    with _status_lock:
        _runtime_status["size_downloaded"] = downloaded
        _runtime_status["size_total"] = total
        _runtime_status["progress"] = int(downloaded * 100 / total) if total > 0 else 0


def _download_runtime(url, dest_zip, progress_cb=None):
    """下载运行时 zip 文件。返回 (ok, error_msg)。"""
    try:
        import urllib.request
        from urllib.error import URLError, HTTPError
        
        safe_print(f"[INFO] 开始下载运行时: {url}")
        
        # 创建临时文件
        dest_zip.parent.mkdir(parents=True, exist_ok=True)
        tmp_zip = dest_zip.with_suffix(".tmp")
        
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

        # Windows 下 Path.replace() 不能覆盖已存在的目录；先清掉旧的
        # 不完整 runtime，再把临时目录改成正式目录。
        if dest_dir.exists():
            if dest_dir.is_dir():
                shutil.rmtree(dest_dir)
            else:
                dest_dir.unlink()
        staging.replace(dest_dir)
        installed = True
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


def download_runtime_async(callback=None):
    """异步下载并部署运行时。
    
    参数:
        callback: 可选的回调函数，接收 (ok, error_msg) 参数
    
    状态变化:
        checking -> downloading -> extracting -> ready/error
    """
    def _worker():
        with _status_lock:
            if _runtime_status["downloading"] or _runtime_status["extracting"]:
                return  # 已在进行中
            _runtime_status["checking"] = True
            _runtime_status["error"] = None
        
        try:
            # 1. 检查是否已存在
            exists, _ = check_runtime()
            if exists:
                safe_print("[INFO] 运行时已存在，跳过下载")
                if callback:
                    callback(True, None)
                return
            
            with _status_lock:
                _runtime_status["checking"] = False
                _runtime_status["downloading"] = True
            
            # 2. 下载
            url = _runtime_zip_url()
            dest_zip = BASE / "runtime.zip.tmp"
            ok, err = _download_runtime(url, dest_zip, progress_cb=_download_progress)
            
            if not ok:
                with _status_lock:
                    _runtime_status["downloading"] = False
                    _runtime_status["error"] = err
                if callback:
                    callback(False, err)
                return
            
            with _status_lock:
                _runtime_status["downloading"] = False
                _runtime_status["extracting"] = True
            
            # 3. 解压
            dest_dir = _runtime_dir()
            ok, err = _extract_runtime(dest_zip, dest_dir)
            
            # 4. 清理临时 zip
            try:
                if dest_zip.exists():
                    dest_zip.unlink()
            except Exception:
                pass
            
            # 5. 更新状态
            with _status_lock:
                _runtime_status["extracting"] = False
                if ok:
                    _runtime_status["ready"] = True
                    _runtime_status["error"] = None
                else:
                    _runtime_status["ready"] = False
                    _runtime_status["error"] = err
            
            if callback:
                callback(ok, err)
                
        except Exception as e:
            err = f"运行时部署失败: {e}"
            safe_print(f"[ERR] {err}")
            with _status_lock:
                _runtime_status["checking"] = False
                _runtime_status["downloading"] = False
                _runtime_status["extracting"] = False
                _runtime_status["error"] = err
            if callback:
                callback(False, err)
    
    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()


def ensure_runtime():
    """确保运行时可用（启动时调用）。
    
    如果运行时不存在，自动触发后台下载。
    返回 (exists: bool, path: str or None)。
    """
    exists, path = check_runtime()
    if exists:
        return True, path
    
    # 不存在则启动后台下载
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
