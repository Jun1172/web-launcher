"""config - 配置加载、路径常量、版本比较工具

职责单一：
- 读取 config.json 为模块级 CONFIG（全局单例）
- 暴露所有派生常量（LAUNCHER_* / REPO_* / PORTS_* / SSL_CTX / 路径 BASE/APPS_DIR/...）
- 提供版本号比较 vt() 与通用 load_config()、reload_config()
- launcher 自更新覆盖 config.json 后，调用 reload_config() 刷新全局变量

不依赖 launcher 其它模块，避免循环导入。
"""
import json
import ssl
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent   # 项目根（即 launcher.py 所在目录）
CONFIG_JSON = BASE / "config.json"
APPS_DIR = BASE / "apps"
SYSTEM_APPS_DIR = APPS_DIR / "system"
USER_APPS_DIR = APPS_DIR / "user"


def load_config():
    """从 CONFIG_JSON 读取 dict；不存在返回 {}。每次调用都会重新读磁盘。"""
    if CONFIG_JSON.exists():
        try:
            return json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


# ── 全局配置变量（reload_config 会重新赋值这些变量）──
CONFIG = {}
LAUNCHER_CFG = {}
REPO_CFG = {}
PUBLISH_CFG = {}
PORTS_CFG = {}
LAUNCHER_HOST = "127.0.0.1"
LAUNCHER_PORT = 8000
LAUNCHER_TITLE = "WebLauncher"
LAUNCHER_VERSION = "0.0.1"
LAUNCHER_CHANGELOG = ""
LAUNCHER_RELEASED = ""
REPO_URL = ""
REPO_AUTH = None
VERIFY_SSL = False
SSL_CTX = None


def reload_config():
    """重新从磁盘读取 config.json，刷新所有模块级全局变量。

    用于 launcher 自更新覆盖 config.json 后，使后续 API 读取到新版本号。
    """
    global CONFIG, LAUNCHER_CFG, REPO_CFG, PUBLISH_CFG, PORTS_CFG
    global LAUNCHER_HOST, LAUNCHER_PORT, LAUNCHER_TITLE, LAUNCHER_VERSION
    global LAUNCHER_CHANGELOG, LAUNCHER_RELEASED
    global REPO_URL, REPO_AUTH, VERIFY_SSL, SSL_CTX

    CONFIG = load_config()
    LAUNCHER_CFG = CONFIG.get("launcher", {})
    REPO_CFG = CONFIG.get("repo", {})
    PUBLISH_CFG = CONFIG.get("publish", {})
    PORTS_CFG = CONFIG.get("ports", {})

    LAUNCHER_HOST = LAUNCHER_CFG.get("host", "127.0.0.1")
    LAUNCHER_PORT = int(LAUNCHER_CFG.get("port", 8000))
    LAUNCHER_TITLE = LAUNCHER_CFG.get("title", "WebLauncher")
    LAUNCHER_VERSION = LAUNCHER_CFG.get("version", "0.0.1")
    LAUNCHER_CHANGELOG = LAUNCHER_CFG.get("changelog", "")
    LAUNCHER_RELEASED = LAUNCHER_CFG.get("released", "")

    REPO_URL = REPO_CFG.get("url", "")
    REPO_AUTH = REPO_CFG.get("auth")
    VERIFY_SSL = REPO_CFG.get("verify_ssl", False)

    SSL_CTX = ssl.create_default_context()
    if not VERIFY_SSL:
        SSL_CTX.check_hostname = False
        SSL_CTX.verify_mode = ssl.CERT_NONE


# 首次加载
reload_config()


def save_repo_config(url, auth_user, auth_pass, verify_ssl):
    """原子更新 config.json 的 repo 节，然后 reload_config()。

    auth_user 为空 → auth 设 None；否则设 [user, pass]。
    url 末尾的 / 会被去掉，避免 repo_get 拼接出双斜杠。
    """
    cfg = load_config()
    cfg["repo"] = {
        "url": str(url or "").rstrip("/"),
        "auth": [auth_user, auth_pass] if auth_user else None,
        "verify_ssl": bool(verify_ssl),
    }
    new_bytes = json.dumps(cfg, ensure_ascii=False, indent=2).encode("utf-8")
    tmp = CONFIG_JSON.with_suffix(".json.tmp.new")
    tmp.write_bytes(new_bytes)
    tmp.replace(CONFIG_JSON)  # 同盘原子替换
    reload_config()


def vt(version_str):
    """版本字符串 → 三元组 int，便于比较。缺段补 0，非数字忽略。

    例: vt('1.2.3') = (1, 2, 3); vt('1.0') = (1, 0, 0); vt(None) = (0, 0, 0)
    """
    parts = [int(x) for x in re.findall(r"\d+", version_str or "0")[:3]]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)
