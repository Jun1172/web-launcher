# 应用管理

应用分两类，按目录位置区分：

| 类型 | 目录 | 默认安装 | 接受更新 | 允许卸载 |
|------|------|:--------:|:--------:|:--------:|
| 系统应用 | `apps/system/<id>/` | ✅ | ✅ | ❌ |
| 用户应用 | `apps/user/<id>/`   | ❌（需从商店安装） | ✅ | ✅ |

> Launcher 启动时自动扫描这两个目录下的所有 `*/app.json`，无需手动注册。
> 用户应用如果直接放进 `apps/user/` 目录（像 demo 那样），launcher 也会识别为"已安装"。

## 应用目录结构

```
apps/<system|user>/<id>/
├── app.json    # 必需：清单
├── app.py      # 必需：HTTP 服务入口
└── README.md   # 推荐：应用介绍
```

`app.json` 字段说明见根目录 [README.md](../README.md#单个应用的结构)。

## 新建一个应用

最简模板（保存为 `apps/user/myapp/app.json`）：

```json
{
  "id": "myapp",
  "name": "我的应用",
  "icon": "✨",
  "color": "#9b59b6",
  "version": "1.0.0",
  "changelog": "第一个版本",
  "port": 8120,
  "cmd": ["apps/user/myapp/app.py"],
  "dock": false,
  "system": false
}
```

`apps/user/myapp/app.py`：

```python
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PORT = 8120
HTML = "<h1>Hello!</h1>"

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html;charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML.encode())
    def log_message(self, *a): pass

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
```

重启 launcher 后桌面就会看到新图标。

## 发布到远端仓库

```bash
python publish.py apps/user/myapp
```

脚本会：
1. 把 `apps/user/myapp/` 整个目录打成 `myapp-1.0.0.zip`
2. `scp` 上传到远端 `packages/` 目录
3. 拉取远端 `index.json`，更新该应用的条目（id、版本、sha256、size 等），再传回去
4. 删除本地临时 zip

发布完成后，客户端打开"应用商店"刷新即可看到 / 升级。

> ⚠️ `publish.py` 用 `arcname = f.relative_to(app_dir.parent)` 打包，
> 即包内顶层是 `<id>/...`。launcher 端 `do_install` 会自动识别这个结构，
> 解压到 `apps/user/<id>/`（用户应用）或 `apps/system/<id>/`（系统应用更新）。

## 端口分配约定

| 应用 | 端口 |
|------|------|
| store（应用商店） | 8100 |
| todo（待办清单） | 8101 |
| clock（番茄钟） | 8102 |
| hello（demo） | 8110 |
| calc（demo） | 8111 |
| notes（demo） | 8112 |
| weather（demo） | 8113 |

新应用建议从 8120 开始往上分配，避免和现有应用冲突。
