# 🌐 仓库服务器搭建

远端仓库是一个 HTTP 静态目录，提供应用 zip 包下载和 `index.json` 索引。Launcher 通过 HTTP 拉取索引、下载安装包。

---

## 仓库结构

```
/var/www/repo/
├── index.json              # 应用清单 + launcher 元信息
└── packages/
    ├── hello-1.0.0.zip
    ├── weather-1.0.0.zip
    └── launcher-1.0.2.zip  # launcher 自更新包
```

### index.json 结构

```json
{
  "repo": "my-launcher-repo",
  "updated": "2026-08-18T16:00:00",
  "apps": [
    {
      "id": "hello",
      "name": "你好世界",
      "version": "1.0.0",
      "pkg": "packages/hello-1.0.0.zip",
      "sha256": "abc123...",
      "size": 4096,
      "group": "user",
      "changelog": "...",
      "released": "..."
    }
  ],
  "launcher": {
    "version": "1.0.2",
    "pkg": "packages/launcher-1.0.2.zip",
    "sha256": "def456...",
    "size": 12345
  }
}
```

> `index.json` 由 [publish.py](../publish.py) 自动维护，不要手工编辑。

---

## Nginx 服务器搭建

### 1. 安装 + 建目录

```bash
sudo apt update
sudo apt install -y nginx apache2-utils

sudo mkdir -p /var/www/repo/packages
# 初始化空目录文件
echo '{"repo":"my-launcher-repo","updated":"","apps":[]}' | sudo tee /var/www/repo/index.json

# 目录归你（方便 scp 上传），nginx 只需读权限
sudo chown -R $USER:$USER /var/www/repo
chmod -R a+rX /var/www/repo
```

### 2. 上 HTTPS（自签名证书）

```bash
sudo mkdir -p /etc/nginx/ssl
sudo openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout /etc/nginx/ssl/repo.key -out /etc/nginx/ssl/repo.crt \
    -subj "/CN=1.15.30.237"
```

### 3. 写站点配置

编辑 `/etc/nginx/conf.d/repo.conf`：

```nginx
server {
    listen 80;

    # ── HTTPS 配置 ──
    listen 443 ssl;
    ssl_certificate /etc/nginx/ssl/repo.crt;
    ssl_certificate_key /etc/nginx/ssl/repo.key;

    server_name 1.15.30.237;  # 你的公网 IP

    root /var/www/repo;

    # 目录文件：永远不缓存，客户端每次拿最新
    location = /index.json {
        add_header Cache-Control "no-store";
        add_header Access-Control-Allow-Origin *;   # 方便调试，可删
    }

    # 安装包：版本号命名=内容不可变，放心长缓存
    location /packages/ {
        add_header Cache-Control "public, max-age=31536000, immutable";
    }

    gzip on;
    gzip_types application/json;
}
```

### 4. 检查 + 启动 + 开机自启

```bash
# 语法检查，必须看到 syntax is ok
sudo nginx -t

sudo systemctl reload nginx
sudo systemctl enable nginx
```

### 5. 防火墙 / 云安全组

放行 80、443 端口。SSH（22 或你改的端口）保持。

### 6. 验证

```bash
# 检查 index.json (无需密码，加 -k 忽略证书)
curl -k -I https://1.15.30.237/index.json
# 期望看到：HTTP/1.1 200 OK 且 Cache-Control: no-store

# 传个测试包后测试下载：
curl -k -O https://1.15.30.237/packages/test-0.1.0.zip
```

---

## 发布通道（SSH/scp）

### SSH 免密配置

```bash
# 开发机一次配置免密：
ssh-keygen -t ed25519
ssh-copy-id 用户@1.15.30.237
```

### config.json 配置发布参数

编辑项目根的 [config.json](../config.json)：

```json
{
  "publish": {
    "server": "ubuntu@1.15.30.237",
    "remote_path": "/var/www/repo",
    "packages_dir": "packages"
  }
}
```

### 发布命令

`publish.py` 在项目根目录运行：

```bash
# 列出所有可发布的应用
python publish.py --list

# 发布单个应用
python publish.py apps/user/hello

# 一键发布所有应用
python publish.py --all

# 只发系统应用 / 用户应用
python publish.py --system
python publish.py --user

# 发布指定分组
python publish.py --group etws

# 只打包不上传（测试）
python publish.py apps/user/hello --dry-run
```

### 发布 Launcher 自身更新

```bash
# 1. 修改 config.json 的 launcher.version（如 1.0.3）
# 2. 发布
python publish.py --launcher --changelog "修复 X，新增 Y"

# 同时打包二进制（需先配置 PyInstaller，见 Build Standalone EXE）
python publish.py --launcher --build --changelog "..."
```

客户端在状态栏右上角 ⚙️ `v1.0.2` 胶囊可见，有新版本时红点闪烁，点击「立即更新」即可 OTA。

---

## 发布流程详解

以 `python publish.py apps/user/hello` 为例：

```
1. 读取 apps/user/hello/app.json，校验 id / version 字段

2. 打包 zip
   ├── 顶层结构统一为 apps/<group>/<id>/...
   ├── 自动排除 .venv / .pyc / __pycache__
   └── 输出 hello-1.0.0.zip

3. 计算 sha256（用于客户端校验）

4. 构建 index.json 条目
   ├── 字段白名单：id/name/icon/color/version/changelog/port/cmd/dock/group/...
   ├── 兼容：group 缺失时按 system 字段推导
   ├── 加上 pkg / size / sha256 / released
   └── env 字段不进 index.json（防密钥泄漏）

5. ssh mkdir -p 远端 packages/ 目录

6. scp 上传 zip → 远端 packages/

7. HTTP HEAD 验证文件可访问
   └── 失败：警告但不阻塞

8. 拉取远端 index.json（如不存在则初始化空）

9. 合并 index
   ├── 用同 id 覆盖旧条目（保留唯一）
   └── 更新 updated 时间戳

10. scp 上传 index.json

11. 清理本地临时 zip
```

### 批量发布

`python publish.py --all` / `--system` / `--user` / `--group <name>` 按分组批量发布，所有应用共用一个 index 临时文件，最后一次 scp 上传 index.json。

---

## Launcher 自更新包

`publish.py --launcher` 打包的不是单个应用，而是 launcher 自身的更新包：

```
launcher-1.0.2.zip
├── launcher.py
├── launcher/           # 整个包目录
├── config.json         # 脱敏后（去掉 publish 节）
├── README.md
├── apps/publish.py
├── apps/README.md
└── apps/system/...    # 所有 group=system 的应用源码
```

**关键脱敏**：[publish.py#build_launcher_zip](../publish.py) 对 config.json 做了脱敏处理：

```python
safe_cfg = {
    "launcher": cfg.get("launcher", {}),
    "repo": {"url": ..., "verify_ssl": ...},  # 去掉 auth
    "ports": cfg.get("ports", {}),
}
```

- 去掉 `publish` 节（不泄露 SSH 服务器地址）
- 去掉 `repo.auth`（不泄露 BASIC 认证凭据）

详见 [Self Update](Self-Update)。

---

## 客户端对接

### Launcher 端配置

在 [config.json](../config.json) 的 `repo` 节配置仓库地址：

```json
{
  "repo": {
    "url": "https://1.15.30.237",
    "auth": null,
    "verify_ssl": false
  }
}
```

- 自签名证书：`verify_ssl: false`
- 需 BASIC 认证：`auth: ["user", "pass"]`

### 通过 settings 应用配置

桌面点 ⚙️ settings → 改仓库 URL / 认证 / SSL → 保存。POST `/api/repo/config` 原子写 config.json + 立即刷新内存。

### Python 客户端代码示例

如果需要在 launcher 之外直接访问仓库（如独立工具）：

```python
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

REPO_URL = "https://1.15.30.237"

# 拉取索引
response = requests.get(f"{REPO_URL}/index.json", verify=False)
index = response.json()

# 下载安装包
file_data = requests.get(f"{REPO_URL}/packages/hello-1.0.0.zip", verify=False)
```
