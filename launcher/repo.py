"""repo - 仓库下载通信

职责：
- repo_get(path): 带 BASIC 认证地从远端 REPO_URL 读取原始二进制
- repo_index(): 解析 index.json 为 dict
"""
import base64
import json
import urllib.request
from urllib.parse import urlparse

from . import config


def repo_get(path):
    """从 REPO_URL/<path> 拉取二进制内容；返回 urllib response（支持 .read()）。"""
    base_url = (config.REPO_URL or "").strip().rstrip("/")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("仓库地址未配置或格式无效，请在系统设置中填写 http(s):// 地址")
    url = base_url + "/" + path.lstrip("/")
    req = urllib.request.Request(url)
    if config.REPO_AUTH:
        token = base64.b64encode(f"{config.REPO_AUTH[0]}:{config.REPO_AUTH[1]}".encode()).decode()
        req.add_header("Authorization", "Basic " + token)
    return urllib.request.urlopen(req, timeout=20, context=config.SSL_CTX)


def repo_index():
    """读取远端 index.json，返回 dict。失败抛异常由调用方处理。"""
    return json.loads(repo_get("index.json").read().decode("utf-8"))
