"""notes —— 便签 demo
- 端口 8112
- 验证：localStorage 持久化（关闭重开仍在） + 列表的增删改
"""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import os

PORT = int(os.environ.get("LAUNCHER_APP_PORT", 0))

HTML = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🗒️ 便签</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,"PingFang SC",sans-serif;
background:#fff8e7;color:#222;min-height:100vh;padding:20px}
h2{font-size:18px;margin-bottom:14px;color:#a86a1c}
.editor{display:flex;gap:8px;margin-bottom:16px}
.editor input{flex:1;padding:12px 14px;border:1px solid #e8d8b0;
border-radius:12px;font-size:14px;background:#fff;outline:none}
.editor input:focus{border-color:#f39c12}
.editor button{padding:12px 18px;border:0;border-radius:12px;background:#f39c12;
color:#fff;font-size:14px;cursor:pointer;transition:transform .1s}
.editor button:active{transform:scale(.94)}
.list{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
.note{background:#fff7d6;border-radius:14px;padding:14px 16px;box-shadow:0 2px 8px rgba(0,0,0,.06);
position:relative;transition:transform .12s,box-shadow .12s}
.note:hover{transform:translateY(-2px);box-shadow:0 6px 16px rgba(0,0,0,.1)}
.note .text{font-size:14px;line-height:1.5;word-break:break-all;white-space:pre-wrap;
cursor:text;min-height:20px}
.note .text[contenteditable=true]{background:#fffbe8;outline:2px solid #f39c12;border-radius:6px}
.note .meta{font-size:11px;color:#a89260;margin-top:8px;display:flex;justify-content:space-between}
.note .del{background:none;border:0;color:#e74c3c;cursor:pointer;font-size:14px;padding:2px 6px;
border-radius:6px}
.note .del:hover{background:#fdebea}
.empty{text-align:center;color:#bbb;padding:60px 20px;font-size:14px}
.empty .ic{font-size:42px;display:block;margin-bottom:8px}
.stats{font-size:12px;color:#a89260;margin-bottom:12px;opacity:.8}
</style></head><body>
<h2>🗒️ 便签 <small style="color:#bbb;font-size:12px">:8112 · localStorage</small></h2>
<div class="editor">
  <input id="inp" placeholder="写点什么，回车保存…" onkeydown="if(event.key==='Enter')add()">
  <button onclick="add()">+ 添加</button>
</div>
<div class="stats" id="stats"></div>
<div class="list" id="list"></div>

<script>
const KEY='notes_demo_v1';
let notes=load();

function load(){
  try{return JSON.parse(localStorage.getItem(KEY)||'[]')}
  catch(e){return []}
}
function save(){
  localStorage.setItem(KEY,JSON.stringify(notes));
  render();
}
function add(){
  const i=document.getElementById('inp');
  const v=i.value.trim();if(!v)return;
  notes.unshift({id:Date.now(),text:v,ts:Date.now()});
  i.value='';save();
}
function del(id){
  notes=notes.filter(n=>n.id!==id);save();
}
function editStart(id,el){
  el.contentEditable='true';el.focus();
  // 选中全部
  const r=document.createRange();r.selectNodeContents(el);
  const s=window.getSelection();s.removeAllRanges();s.addRange(r);
}
function editEnd(id,el){
  el.contentEditable='false';
  const v=el.textContent.trim();
  const n=notes.find(x=>x.id===id);
  if(n){n.text=v||n.text;n.ts=Date.now();}
  save();
}
function fmt(ts){
  const d=new Date(ts),p=x=>String(x).padStart(2,'0');
  const now=new Date();
  if(d.toDateString()===now.toDateString())return '今天 '+p(d.getHours())+':'+p(d.getMinutes());
  return (d.getMonth()+1)+'/'+d.getDate()+' '+p(d.getHours())+':'+p(d.getMinutes());
}
function render(){
  const list=document.getElementById('list');
  const stats=document.getElementById('stats');
  stats.textContent='共 '+notes.length+' 条 · 存于浏览器 localStorage';
  if(!notes.length){
    list.innerHTML='<div class="empty"><span class="ic">🗒️</span>还没有便签，写第一条吧</div>';
    return;
  }
  list.innerHTML='';
  notes.forEach(n=>{
    const d=document.createElement('div');d.className='note';
    d.innerHTML=`<div class="text" ondblclick="editStart(${n.id},this)"
      onblur="editEnd(${n.id},this)"></div>
      <div class="meta"><span>${fmt(n.ts)}</span>
      <button class="del" onclick="del(${n.id})">✕ 删除</button></div>`;
    d.querySelector('.text').textContent=n.text;
    list.appendChild(d);
  });
}
render();
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
    print(f"notes demo → http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
