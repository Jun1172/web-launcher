# apps/hello/main.py —— 测试应用：独立进程 :8110
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui;background:linear-gradient(135deg,#ff6b6b,#ffa500);
min-height:100vh;display:flex;flex-direction:column;align-items:center;
justify-content:center;color:#fff;text-align:center;padding:20px}
h1{font-size:48px;margin-bottom:20px}
p{font-size:18px;margin:10px 0;opacity:.9}
button{padding:14px 28px;font-size:16px;border:none;border-radius:12px;
background:#fff;color:#ff6b6b;cursor:pointer;margin-top:20px;
box-shadow:0 4px 12px rgba(0,0,0,.2)}
button:active{transform:scale(.96)}
#counter{font-size:72px;font-weight:700;margin:30px 0}
</style></head><body>
<h1>👋 你好，世界！</h1>
<p>我是从应用商店安装的独立应用</p>
<p style="opacity:.6">进程端口: 8110</p>
<div id="counter">0</div>
<button onclick="clickMe()">点我计数</button>
<p style="margin-top:40px;font-size:14px;opacity:.7">
  试试：卸载我 → 重装 → 升级版本</p>
<script>
let n=0;
function clickMe(){
  n++;document.getElementById('counter').textContent=n;
}
</script></body></html>"""

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html;charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML.encode())
    def log_message(self, *a): pass

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8110), H).serve_forever()