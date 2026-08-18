#!/usr/bin/env python3
"""launcher_updater.py —— 独立 Launcher 检查 / 更新工具"""
import argparse
import base64
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

def now_tag(): return datetime.now().strftime("%Y%m%d-%H%M%S")
def vt(version_str):
    parts = [int(x) for x in re.findall(r"\d+", version_str or "0")][:3]
    while len(parts) < 3: parts.append(0)
    return tuple(parts)
def platform_tag():
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin": system = "macos"
    if machine in ("amd64", "x86_64"): machine = "x86_64"
    elif machine in ("arm64", "aarch64"): machine = "arm64"
    return f"{system}-{machine}"
def load_config(base: Path):
    config_path = base / "config.json"
    if not config_path.exists(): return {}
    try: return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception: return {}
def repo_join(base_url, path): return str(base_url).rstrip("/") + "/" + str(path).lstrip("/")
def make_ssl_ctx(verify_ssl):
    ctx = ssl.create_default_context()
    if not verify_ssl: ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    return ctx
def http_get(url, repo_cfg):
    req = urllib.request.Request(url)
    auth = repo_cfg.get("auth")
    if auth and isinstance(auth, (list, tuple)) and len(auth) >= 2 and auth[0]:
        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", "Basic " + token)
    ctx = make_ssl_ctx(repo_cfg.get("verify_ssl", False))
    with urllib.request.urlopen(req, timeout=60, context=ctx) as r: return r.read()
def get_index(cfg):
    repo_cfg = cfg.get("repo", {})
    repo_url = repo_cfg.get("url", "")
    if not repo_url: raise RuntimeError("config.json 中未配置 repo.url")
    url = repo_join(repo_url, "index.json")
    data = http_get(url, repo_cfg)
    return json.loads(data.decode("utf-8"))
def verify_sha(data: bytes, expected_sha: str | None, name="更新包"):
    if not expected_sha: return
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected_sha:
        raise RuntimeError(f"{name} sha256 校验失败：期望 {expected_sha[:12]}… 实际 {actual[:12]}…")
def port_open(host, port):
    try:
        with socket.create_connection((host, int(port)), timeout=0.5): return True
    except OSError: return False
def normalize_host(host):
    if host in ("0.0.0.0", "::", ""): return "127.0.0.1"
    return host

def request_shutdown(host, port):
    url = f"http://{host}:{port}/api/launcher/shutdown"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3) as r: return r.status == 200
    except Exception: return False

def force_kill_port(port):
    """Windows 下强杀占用指定端口的进程（兜底方案）"""
    if os.name != "nt": return
    try:
        cmd = f'netstat -ano | findstr ":{port} "'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        pids = set()
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[-1].isdigit(): pids.add(parts[-1])
        for pid in pids:
            print(f"   ⚠ HTTP 通知无效，强制结束进程 PID: {pid}")
            subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
    except Exception as e:
        print(f"   ⚠ 强杀进程失败: {e}")

def ensure_launcher_stopped(base: Path, cfg, wait=False, stop=False, timeout=120):
    launcher_cfg = cfg.get("launcher", {})
    host = normalize_host(launcher_cfg.get("host", "127.0.0.1"))
    port = int(launcher_cfg.get("port", 8000))

    if not port_open(host, port): return True

    if stop:
        print("⏳ 尝试通知 Launcher 优雅退出...")
        if request_shutdown(host, port):
            print("   ✓ 已发送关闭指令，等待进程退出...")
            wait = True
        else:
            print("   ⚠ 通知失败，尝试强制结束...")
            force_kill_port(port)
            return not port_open(host, port)

    if not wait:
        print(f"⚠ Launcher 正在运行：http://{host}:{port}")
        print("请先停止 Launcher，或使用 --stop / --wait 参数。")
        return False

    print(f"⏳ 等待 Launcher 退出：http://{host}:{port}")
    end = time.time() + timeout
    while time.time() < end:
        if not port_open(host, port):
            time.sleep(1)
            return True
        time.sleep(1)
        
    # 超时兜底：如果等了这么久还没死，直接强杀
    print("   ⚠ 等待超时，强制结束占用端口的进程...")
    force_kill_port(port)
    time.sleep(1)
    return not port_open(host, port)

def pick_source(meta):
    src = meta.get("source") or {}
    pkg = src.get("pkg") or meta.get("pkg")
    sha = src.get("sha256") or meta.get("sha256")
    return pkg, sha

def detect_mode(base: Path):
    has_source = (base / "launcher.py").exists() or (base / "launcher").exists()
    exe = base / ("launcher.exe" if os.name == "nt" else "launcher")
    if exe.exists() and not has_source: return "binary"
    return "source"

def cmd_check(base: Path, args):
    cfg = load_config(base)
    try: index = get_index(cfg)
    except Exception as e: print(f"❌ 读取仓库失败：{e}"); return 2
    meta = index.get("launcher") or {}
    local_version = cfg.get("launcher", {}).get("version", "0.0.1")
    remote_version = meta.get("version", "")
    mode = args.mode if args.mode != "auto" else detect_mode(base)
    print(f"本地版本：{local_version} | 远端版本：{remote_version or '未知'} | 模式：{mode}")
    if not remote_version: return 2
    if vt(remote_version) > vt(local_version): print("✅ 发现新版本")
    elif vt(remote_version) == vt(local_version): print("✅ 当前已是最新版本")
    return 0

def update_source(base: Path, cfg, meta, args):
    repo_cfg = cfg.get("repo", {})
    pkg, sha = pick_source(meta)
    if not pkg: raise RuntimeError("远端没有可用的 launcher 源码包")
    url = repo_join(repo_cfg.get("url", ""), pkg)
    print(f"⬇ 下载源码包：{pkg}")
    data = http_get(url, repo_cfg)
    verify_sha(data, sha, "launcher 源码包")

    with tempfile.TemporaryDirectory(prefix="launcher-update-") as td_name:
        td = Path(td_name)
        zip_path = td / "launcher.zip"
        zip_path.write_bytes(data)
        extract_dir = td / "extract"
        extract_dir.mkdir()
        with zipfile.ZipFile(zip_path) as z: z.extractall(extract_dir)
        root = extract_dir
        if not (root / "launcher.py").exists():
            subs = [d for d in root.iterdir() if d.is_dir()]
            if len(subs) == 1: root = subs[0]

        for item in ["launcher.py", "launcher"]:
            src = root / item
            dest = base / item
            if src.exists():
                if dest.exists():
                    if dest.is_dir(): shutil.rmtree(dest, ignore_errors=True)
                    else: dest.unlink()
                if src.is_dir(): shutil.copytree(src, dest)
                else: shutil.copy2(src, dest)
                print(f"   ✓ {item}")

        # 合并 config
        remote_cfg_p = root / "config.json"
        if remote_cfg_p.exists():
            local_cfg_p = base / "config.json"
            # 👇 修复：显式指定 utf-8，防止 Windows 默认使用 GBK 导致中文解码失败
            local_cfg = json.loads(local_cfg_p.read_text(encoding="utf-8")) if local_cfg_p.exists() else {}
            remote_cfg = json.loads(remote_cfg_p.read_text(encoding="utf-8"))
            
            local_cfg["launcher"] = remote_cfg.get("launcher", local_cfg.get("launcher", {}))
            local_cfg_p.write_text(json.dumps(local_cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            print("   ✓ config.json")

def cmd_update(base: Path, args):
    cfg = load_config(base)
    try: index = get_index(cfg)
    except Exception as e: print(f"❌ 读取仓库失败：{e}"); return 2
    meta = index.get("launcher") or {}
    local_version = cfg.get("launcher", {}).get("version", "0.0.1")
    remote_version = meta.get("version", "")
    if not remote_version: return 2
    if vt(remote_version) <= vt(local_version) and not args.force:
        print(f"✅ 当前已是最新：本地 {local_version}，远端 {remote_version}")
        return 0
    mode = args.mode if args.mode != "auto" else detect_mode(base)
    print(f"准备更新：{local_version} -> {remote_version} (模式: {mode})")

    if not ensure_launcher_stopped(base, cfg, wait=args.wait, stop=args.stop, timeout=args.timeout):
        return 3

    try:
        if mode == "source": update_source(base, cfg, meta, args)
        else: raise RuntimeError("当前脚本仅演示源码更新逻辑")
    except Exception as e:
        print(f"❌ 更新失败：{e}"); return 1

    print("✅ 更新完成")
    if args.restart:
        kwargs = {"creationflags": 0x00000008} if os.name == "nt" else {"start_new_session": True}
        subprocess.Popen([sys.executable, str(base / "launcher.py")], cwd=str(base), **kwargs)
        print("🚀 已重启 Launcher")
    return 0

def main():
    parser = argparse.ArgumentParser(description="独立 Launcher 更新工具")
    parser.add_argument("action", choices=["check", "update"])
    parser.add_argument("--base", default=".")
    parser.add_argument("--mode", choices=["auto", "source", "binary"], default="auto")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--stop", action="store_true", help="通知 Launcher 优雅退出")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    base = Path(args.base).resolve()
    if args.action == "check": sys.exit(cmd_check(base, args))
    else: sys.exit(cmd_update(base, args))

if __name__ == "__main__":
    main()