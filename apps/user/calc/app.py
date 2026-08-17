"""calc —— 计算器 demo
- 端口 8111
- 验证：复杂前端交互（按钮网格 / 表达式求值 / 历史记录）
"""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PORT = 8111

HTML = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🧮 计算器</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,"PingFang SC",sans-serif;
background:#1c2347;color:#fff;min-height:100vh;display:flex;
flex-direction:column;align-items:center;padding:24px}
.wrap{width:100%;max-width:340px}
h2{font-size:18px;margin-bottom:14px;opacity:.85}
.screen{background:rgba(255,255,255,.07);border-radius:16px;padding:18px 20px;
margin-bottom:14px;text-align:right;min-height:96px;display:flex;
flex-direction:column;justify-content:flex-end}
.expr{font-size:13px;opacity:.55;min-height:18px;word-break:break-all}
.cur{font-size:40px;font-weight:300;font-variant-numeric:tabular-nums;
word-break:break-all}
.keys{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
button{padding:18px 0;border:0;border-radius:14px;background:rgba(255,255,255,.1);
color:#fff;font-size:18px;cursor:pointer;transition:transform .1s,background .15s}
button:active{transform:scale(.93)}
button.op{background:rgba(155,89,182,.55)}
button.eq{background:#9b59b6}
button.clr{background:rgba(231,76,60,.7)}
button.span2{grid-column:span 2}
.hist{margin-top:14px;background:rgba(0,0,0,.18);border-radius:12px;
padding:10px 14px;font-size:12px;opacity:.6;max-height:120px;overflow:auto}
.hist div{padding:3px 0;border-bottom:1px dashed rgba(255,255,255,.1)}
.hist div:last-child{border:0}
.hist .empty{opacity:.5}
</style></head><body>
<div class="wrap">
  <h2>🧮 计算器 <small style="opacity:.5">:8111</small></h2>
  <div class="screen">
    <div class="expr" id="expr">&nbsp;</div>
    <div class="cur" id="cur">0</div>
  </div>
  <div class="keys">
    <button class="clr" onclick="clr()">C</button>
    <button onclick="bs()">⌫</button>
    <button class="op" onclick="op('%')">%</button>
    <button class="op" onclick="op('/')">÷</button>

    <button onclick="num('7')">7</button>
    <button onclick="num('8')">8</button>
    <button onclick="num('9')">9</button>
    <button class="op" onclick="op('*')">×</button>

    <button onclick="num('4')">4</button>
    <button onclick="num('5')">5</button>
    <button onclick="num('6')">6</button>
    <button class="op" onclick="op('-')">−</button>

    <button onclick="num('1')">1</button>
    <button onclick="num('2')">2</button>
    <button onclick="num('3')">3</button>
    <button class="op" onclick="op('+')">+</button>

    <button class="span2" onclick="num('0')">0</button>
    <button onclick="dot()">.</button>
    <button class="eq" onclick="eq()">=</button>
  </div>
  <div class="hist" id="hist"><div class="empty">暂无历史</div></div>
</div>
<script>
let cur='0',expr='',justEq=false;
const $=id=>document.getElementById(id);
function render(){
  $('cur').textContent=cur;
  $('expr').innerHTML=expr?expr.replace(/\*/g,'×').replace(/\//g,'÷').replace(/-/g,'−'):'&nbsp;';
}
function num(d){
  if(justEq){cur='0';expr='';justEq=false;}
  cur=cur==='0'?d:cur+d;
  render();
}
function dot(){
  if(justEq){cur='0';expr='';justEq=false;}
  if(!cur.includes('.'))cur+='.';
  render();
}
function op(o){
  if(expr&&!justEq){
    eq(true);
  }
  expr=(cur+(o==='*'?'×':o==='/'?'÷':o==='-'?'−':o));
  cur='0';justEq=false;render();
}
function eq(silent){
  if(!expr)return;
  try{
    const fullExpr=expr+cur;
    const e=fullExpr.replace(/×/g,'*').replace(/÷/g,'/').replace(/−/g,'-');
    if(!/^[0-9+\-*/%.()\s]+$/.test(e))throw 0;
    const r=Function('"use strict";return ('+e+')')();
    if(!isFinite(r))throw 0;
    const out=String(Number(r.toFixed(10)));
    if(!silent)addHist(fullExpr.replace(/×/g,'×').replace(/÷/g,'÷').replace(/−/g,'−')+' = '+out);
    cur=out;expr='';justEq=true;
  }catch(e){
    if(!silent){addHist((expr+cur)+' = 错误');cur='Error';expr='';justEq=true;}
  }
  render();
}
function clr(){cur='0';expr='';justEq=false;render();}
function bs(){
  if(justEq){clr();return;}
  cur=cur.length>1?cur.slice(0,-1):'0';
  render();
}
function addHist(line){
  const h=$('hist');
  if(h.querySelector('.empty'))h.innerHTML='';
  const d=document.createElement('div');d.textContent=line;
  h.prepend(d);
  while(h.children.length>10)h.removeChild(h.lastChild);
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
    print(f"calc demo → http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
