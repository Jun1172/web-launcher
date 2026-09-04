# 服务器端-部署
## 安装 + 建目录
```
sudo apt update
sudo apt install -y nginx apache2-utils

sudo mkdir -p /var/www/repo/packages /var/www/repo/wheels
# 初始化空目录文件
echo '{"repo":"my-launcher-repo","updated":"","apps":[]}' | sudo tee /var/www/repo/index.json

# 目录归你（方便 scp 上传），nginx 只需读权限
sudo chown -R $USER:$USER /var/www/repo
chmod -R a+rX /var/www/repo
```

## 上 HTTPS
生成证书：
```
sudo mkdir -p /etc/nginx/ssl
sudo openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
    -keyout /etc/nginx/ssl/repo.key -out /etc/nginx/ssl/repo.crt \
    -subj "/CN=1.15.30.237"
```

## 写站点配置 /etc/nginx/conf.d/repo.conf
```
server {
    listen 80;

    # ── HTTPS 配置 ──
    listen 443 ssl;
    ssl_certificate /etc/nginx/ssl/repo.crt;
    ssl_certificate_key /etc/nginx/ssl/repo.key;

    server_name 1.15.30.237;  # <--- 你的公网 IP

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

    # 应用依赖 wheels（deps 内网在线安装源，按平台分子目录）
    # 文件名含版本号可长缓存；pip 会先请求索引再取包
    location /wheels/ {
        add_header Cache-Control "public, max-age=86400";
    }

    gzip on;
    gzip_types application/json;
}
```

## 检查 + 启动 + 开机自启
```
 # 语法检查，必须看到 syntax is ok
sudo nginx -t                
sudo systemctl reload nginx
sudo systemctl enable nginx
```

## 防火墙 / 云安全组：放行 80、443；SSH（22 或你改的端口）保持。
## 验证
```
# 检查 index.json (无需密码，加 -k 忽略证书)
curl -k -I https://1.15.30.237/index.json     
# 期望看到：HTTP/1.1 200 OK 且 Cache-Control: no-store

# 传个测试包后测试下载：
curl -k -O https://1.15.30.237/packages/test-0.1.0.zip
```
## 发布通道（SSH/scp，不暴露上传接口）
```
# 开发机一次配置免密：
ssh-keygen -t ed25519
ssh-copy-id 用户@1.15.30.237
```
然后 tools/publish.py 里 SERVER="用户@1.15.30.237"、REMOTE="/var/www/repo"，每次 python tools/publish.py apps/ocr 即完成上架。

## 客户端对接：launcher.py 顶部
```
import requests
import urllib3

# 禁用自签名证书的安全警告（可选，让控制台更干净）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

REPO_URL = "https://1.15.30.237"

# 发起请求时，必须加上 verify=False 忽略证书校验
# response = requests.get(f"{REPO_URL}/index.json", verify=False)
# file_data = requests.get(f"{REPO_URL}/packages/app.zip", verify=False)
```