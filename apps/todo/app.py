# 示例应用A：纯标准库的"Web化"应用，只起服务、不开窗口
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{font-family:system-ui;padding:32px;background:#f6f8ff;color:#222}
input{padding:10px;border:1px solid #ddd;border-radius:10px;width:60%}
button{padding:10px 16px;border:0;border-radius:10px;background:#5b8cff;color:#fff}
li{margin:10px 0;padding:10px;background:#fff;border-radius:10px;
box-shadow:0 1px 4px rgba(0,0,0,.08);cursor:pointer}
</style></head><body>
<h2>📝 待办清单 <small style="color:#999">独立进程 :8101</small></h2>
<input id="t" placeholder="输入待办，点添加"><button onclick="add()">添加</button>
<ul id="list"></ul>
<script>
function add(){const i=document.getElementById('t');if(!i.value)return;
const li=document.createElement('li');li.textContent=i.value;li.title='点击删除';
li.onclick=()=>li.remove();document.getElementById('list').appendChild(li);i.value=''}
</script></body></html>"""

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html;charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML.encode())
    def log_message(self, *a): pass

ThreadingHTTPServer(("127.0.0.1", 8101), H).serve_forever()