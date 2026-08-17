# 示例应用B：番茄钟，独立进程 :8102
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{font-family:system-ui;padding:32px;background:#fff5f4;color:#222;text-align:center}
#c{font-size:72px;font-weight:700;margin:30px 0;font-variant-numeric:tabular-nums}
button{padding:12px 28px;border:0;border-radius:12px;background:#e74c3c;color:#fff;font-size:16px}
</style></head><body>
<h2>⏱️ 番茄钟 <small style="color:#999">独立进程 :8102</small></h2>
<div id="c">00:00:00</div>
<button onclick="t=!t">开始 / 暂停</button>
<script>
let t=false,s=0;
setInterval(()=>{if(t)s++;
const p=n=>String(n).padStart(2,'0');
document.getElementById('c').textContent=
  p(s/3600|0)+':'+p(s/60%60|0)+':'+p(s%60)},1000)
</script></body></html>"""

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html;charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML.encode())
    def log_message(self, *a): pass

ThreadingHTTPServer(("127.0.0.1", 8102), H).serve_forever()