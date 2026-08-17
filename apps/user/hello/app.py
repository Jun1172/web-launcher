"""hello —— 最简单的 demo 应用
- 单文件 HTTP 服务，端口写死 8110
- 验证：launcher 拉起进程 → iframe 嵌入 → 简单 JS 交互
"""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PORT = 8110

HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>👋 你好世界</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,"PingFang SC",sans-serif;
background:linear-gradient(160deg,#ff6b6b22,#fff);color:#222;
min-height:100vh;display:flex;flex-direction:column;align-items:center;
justify-content:center;padding:24px;text-align:center}
h1{font-size:28px;margin-bottom:8px}
.sub{color:#888;font-size:13px;margin-bottom:24px}
#time{font-size:48px;font-weight:200;font-variant-numeric:tabular-nums;
margin-bottom:28px;letter-spacing:2px}
button{padding:14px 36px;border:0;border-radius:14px;background:#ff6b6b;
color:#fff;font-size:16px;cursor:pointer;transition:transform .12s,background .15s;
box-shadow:0 6px 16px rgba(255,107,107,.35)}
button:active{transform:scale(.94)}
#count{font-size:64px;font-weight:700;color:#ff6b6b;margin-top:20px;
font-variant-numeric:tabular-nums}
.tip{margin-top:32px;font-size:12px;color:#aaa;max-width:320px;line-height:1.6}
</style></head><body>
<h1>👋 你好，世界！</h1>
<div class="sub">独立进程 :""" + str(PORT) + """ · 最简 demo</div>
<div id="time">--:--:--</div>
<button onclick="bump()">点我 +1</button>
<div id="count">0</div>
<div class="tip">这个 demo 验证 launcher 能成功拉起一个独立 Python HTTP 进程，
并通过 iframe 嵌入到桌面里。计数器状态仅存于内存，刷新即重置。</div>
<script>
let n=0;
const p=x=>String(x).padStart(2,'0');
function tick(){
  const d=new Date();
  document.getElementById('time').textContent=
    p(d.getHours())+':'+p(d.getMinutes())+':'+p(d.getSeconds());
}
tick();setInterval(tick,1000);
function bump(){n++;document.getElementById('count').textContent=n;}
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html;charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(HTML.encode("utf-8"))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"hello demo → http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
