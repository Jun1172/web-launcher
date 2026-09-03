# -*- coding: utf-8 -*-
"""deps_installer - 应用依赖(wheels)自动安装到应用专属 site/ 目录。

流程(do_install 之后调用 install_app_deps):
    1. 读 app.json 的 deps: ["paramiko>=5.0", ...]; 无 deps 直接返回
    2. 已装检测: site/ 中存在全部 dist-info(name 匹配)则跳过
    3. 优先本地 wheels: <launcher 根>/wheels/<平台标签>/ 目录
       (离线部署: U 盘/发行包自带 wheels 时零网络安装)
    4. 在线安装: pip install --target site/ --index-url <repo>/wheels/simple
       (repo 服务器 1.15.30.237 托管内网 pip 源; 失败回退公网 pypi)
    5. 用随身 runtime 的 python 跑 pip(无 runtime 用当前解释器)

平台标签: win-x64 / linux-x64 / linux-arm64(鲲鹏)
"""
import os
import re
import subprocess
import sys

from . import config
from .config import BASE

PLATFORM_TAG = ("win-x64" if os.name == "nt" else
                "linux-arm64" if sys.maxsize > 2**32 and os.uname().machine.startswith(("aarch", "arm")) else
                "linux-x64")


def _py_index_url():
    """repo 服务器的内网 pip 源地址(跟 packages 同源)。"""
    return (config.REPO_URL or "").strip().rstrip("/") + "/wheels/simple"


def _pip_cmd():
    """跑 pip 用的命令: 优先随身 runtime python。"""
    from .process_manager import runtime_python
    rt = runtime_python()
    if rt:
        return [rt, "-m", "pip"]
    return [sys.executable, "-m", "pip"]


def _has_pip():
    try:
        subprocess.run(_pip_cmd() + ["--version"], capture_output=True,
                       timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception:
        return False


def _wheel_dir():
    """本地 wheels 目录(发行包自带 / 离线拷贝)。"""
    return os.path.join(BASE, "wheels", PLATFORM_TAG)


def _installed_ok(site_dir, deps):
    """site/ 是否已满足全部 deps(按包名查 dist-info)。"""
    have = set()
    if os.path.isdir(site_dir):
        for n in os.listdir(site_dir):
            m = re.match(r"([A-Za-z0-9_.\-]+?)-\d", n)
            if m:
                have.add(m.group(1).lower().replace("_", "-"))
    for d in deps:
        name = re.split(r"[<>=!~\s]", d.strip(), 1)[0].lower().replace("_", "-")
        if name and name not in have:
            return False
    return True


def _run_pip(args, timeout=300):
    """跑 pip, 返回 (ok, 输出)。"""
    cmd = _pip_cmd() + args
    kw = {"capture_output": True, "text": True, "timeout": timeout,
          "encoding": "utf-8", "errors": "replace"}
    if os.name == "nt":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run(cmd, **kw)
    return r.returncode == 0, (r.stdout or "") + (r.stderr or "")


def install_app_deps(app):
    """安装应用依赖到 <app_dir>/site/。返回 (ok, msg)。

    - 无 deps 字段: (True, "no-deps")
    - 已全部安装:   (True, "already")
    - 本地 wheels 完整: 离线装 (True, "offline")
    - 否则在线装: repo 源优先, 失败回退 pypi
    """
    deps = app.get("deps")
    if not deps:
        return True, "no-deps"
    app_dir = app.get("_dir")
    if not app_dir:
        return False, "应用目录未知"
    site = os.path.join(app_dir, "site")
    if _installed_ok(site, deps):
        return True, "already"
    if not _has_pip():
        return False, "无 pip 可用(缺少 runtime)"

    need = [str(d) for d in deps]
    # 1) 本地 wheels 离线安装
    wd = _wheel_dir()
    if os.path.isdir(wd):
        ok, out = _run_pip(["install", "--no-index", "--find-links", wd,
                            "--target", site, "--upgrade"] + need)
        if ok:
            return True, "offline"

    # 2) 在线: repo 内网源 → 公网回退
    idxs = [_py_index_url(), "https://pypi.tuna.tsinghua.edu.cn/simple"]
    for idx in idxs:
        ok, out = _run_pip(["install", "--target", site, "--upgrade",
                            "--index-url", idx] + need, timeout=600)
        if ok:
            return True, "online:" + idx.split("//", 1)[-1].split("/")[0]

    return False, out.strip()[-500:] if out else "安装失败"
