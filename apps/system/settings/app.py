"""settings —— 系统设置（系统应用）

- 端口从 config.json 读取，默认 8104
- 管理仓库地址 / BASIC 认证 / SSL 证书校验
- 通过 Launcher 的 GET/POST /api/repo/config 读写 config.json 的 repo 节
- 保存后 Launcher 立即 reload_config()，无需重启
"""
import json
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

BASE = Path(__file__).parent.parent.parent.parent
CONFIG_JSON = BASE / "config.json"


def load_config():
    if CONFIG_JSON.exists():
        try:
            return json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


CONFIG = load_config()
PORT = CONFIG.get("ports", {}).get("settings", 8104)
LAUNCHER_HOST = CONFIG.get("launcher", {}).get("host", "127.0.0.1")
LAUNCHER_PORT = CONFIG.get("launcher", {}).get("port", 8000)
LAUNCHER_URL = f"http://{LAUNCHER_HOST}:{LAUNCHER_PORT}"

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>⚙️ 系统设置</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
background:linear-gradient(160deg,#0e1229 0%,#1c2347 100%);color:#fff;min-height:100vh;padding:16px}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;padding:0 4px}
.header h1{font-size:20px;font-weight:600}
.header .sub{font-size:12px;opacity:.6}
.card{background:rgba(255,255,255,.07);border-radius:18px;padding:18px;margin-bottom:14px}
.card h2{font-size:15px;font-weight:600;margin-bottom:14px;display:flex;align-items:center;gap:8px}
.card .desc{font-size:12px;opacity:.5;margin-bottom:14px;line-height:1.6}
.field{margin-bottom:14px}
.field label{display:block;font-size:12px;opacity:.7;margin-bottom:6px;font-weight:500}
.field input[type=text],.field input[type=password]{width:100%;padding:11px 14px;
background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.1);border-radius:12px;
color:#fff;font-size:14px;outline:none;transition:all .15s}
.field input:focus{background:rgba(255,255,255,.12);border-color:rgba(91,140,255,.6)}
.field input::placeholder{color:rgba(255,255,255,.35)}
.switch{display:flex;align-items:center;gap:10px;padding:8px 0}
.switch input{width:18px;height:18px;accent-color:#5b8cff;cursor:pointer}
.switch label{font-size:13px;opacity:.85;cursor:pointer}
.actions{display:flex;gap:10px;margin-top:6px}
.btn{padding:11px 22px;border:none;border-radius:12px;font-size:13px;font-weight:600;
cursor:pointer;transition:all .15s}
.btn:active{transform:scale(.96)}
.btn-primary{background:#5b8cff;color:#fff}
.btn-ghost{background:rgba(255,255,255,.12);color:#fff}
.btn:disabled{opacity:.5;cursor:not-allowed}
.toast{position:fixed;left:50%;top:16px;transform:translateX(-50%);padding:10px 20px;
border-radius:12px;font-size:13px;font-weight:600;z-index:9999;box-shadow:0 6px 24px rgba(0,0,0,.4);
animation:fade .18s}
.toast.ok{background:#27ae60}
.toast.err{background:#e74c3c}
.toast.info{background:#5b8cff}
@keyframes fade{from{opacity:0}}
.hint{font-size:11px;opacity:.45;margin-top:6px;line-height:1.6}
.current{font-size:12px;opacity:.55;margin-top:8px;padding:8px 10px;
background:rgba(255,255,255,.05);border-radius:10px}
.current code{color:#00cec9}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>⚙️ 系统设置</h1>
    <div class="sub" id="sub">正在加载…</div>
  </div>
</div>

<div class="card">
  <h2>📦 仓库配置</h2>
  <div class="desc">管理应用商店与 Launcher 自更新所用的仓库地址。保存后立即生效，无需重启 Launcher。切换仓库后请到应用商店刷新验证。</div>

  <div class="field">
    <label>仓库地址 (URL)</label>
    <input type="text" id="url" placeholder="https://example.com" autocomplete="off">
    <div class="hint">需含 http(s):// 前缀；末尾的 / 会被自动去掉。该地址下的 index.json 列出所有可安装应用。</div>
  </div>

  <div class="field">
    <label>BASIC 认证用户名（可选）</label>
    <input type="text" id="auth_user" placeholder="无需认证则留空" autocomplete="off">
  </div>

  <div class="field">
    <label>BASIC 认证密码（可选）</label>
    <input type="password" id="auth_pass" placeholder="无需认证则留空" autocomplete="new-password">
  </div>

  <div class="switch">
    <input type="checkbox" id="verify_ssl">
    <label for="verify_ssl">校验 SSL 证书（关闭可连自签证书仓库，但有中间人风险）</label>
  </div>

  <div class="actions">
    <button class="btn btn-primary" id="saveBtn">💾 保存配置</button>
    <button class="btn btn-ghost" id="testBtn">🔌 测试连接</button>
    <button class="btn btn-ghost" id="reloadBtn">⟳ 重新加载</button>
  </div>

  <div class="current" id="current"></div>
</div>

<script>
function toast(msg,type){
  const t=document.createElement('div');t.className='toast '+(type||'info');t.textContent=msg;
  document.body.appendChild(t);setTimeout(()=>t.remove(),2600);}

async function api(path,opts){
  const r=await fetch(LAUNCHER_URL+path,opts||{});
  return r.json();}

async function loadConfig(){
  document.getElementById('sub').textContent='正在加载…';
  try{
    const cfg=await api('/api/repo/config');
    document.getElementById('url').value=cfg.url||'';
    document.getElementById('auth_user').value=cfg.auth_user||'';
    document.getElementById('auth_pass').value=cfg.auth_pass||'';
    document.getElementById('verify_ssl').checked=!!cfg.verify_ssl;
    document.getElementById('current').innerHTML='当前生效：<code>'+String(cfg.url||'(空)').replace(/<\/?[^>]+>/g,'')+'</code> · SSL '+(cfg.verify_ssl?'✓ 校验':'✗ 跳过')+(cfg.auth_user?(' · 认证: '+cfg.auth_user):'');
    document.getElementById('sub').textContent='已加载当前配置';
  }catch(e){toast('加载失败：'+e.message,'err');document.getElementById('sub').textContent='加载失败';}}

async function saveConfig(){
  const body={
    url:document.getElementById('url').value.trim(),
    auth_user:document.getElementById('auth_user').value.trim(),
    auth_pass:document.getElementById('auth_pass').value,
    verify_ssl:document.getElementById('verify_ssl').checked};
  document.getElementById('saveBtn').disabled=true;
  try{
    const r=await api('/api/repo/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    if(r.ok){toast('✅ '+r.msg,'ok');loadConfig();}
    else{toast('保存失败：'+r.msg,'err');}
  }catch(e){toast('请求失败：'+e.message,'err');}
  finally{document.getElementById('saveBtn').disabled=false;}}

async function testConn(){
  document.getElementById('testBtn').disabled=true;
  toast('正在测试连接…','info');
  try{
    const r=await api('/api/repo');
    if(r.error){toast('❌ 连不上：'+r.error,'err');return;}
    const n=(r.apps||[]).length;
    toast('✅ 连接成功，仓库共 '+n+' 个应用','ok');
  }catch(e){toast('❌ 测试失败：'+e.message,'err');}
  finally{document.getElementById('testBtn').disabled=false;}}

document.getElementById('saveBtn').addEventListener('click',saveConfig);
document.getElementById('testBtn').addEventListener('click',testConn);
document.getElementById('reloadBtn').addEventListener('click',loadConfig);

loadConfig();
</script>
</body>
</html>"""


def render_page():
    inject = f"<script>window.LAUNCHER_URL='{LAUNCHER_URL}';</script>"
    return HTML.replace("</head>", inject + "</head>", 1)


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html;charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(render_page().encode("utf-8"))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
