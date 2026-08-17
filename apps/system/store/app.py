import json
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

BASE = Path(__file__).parent.parent.parent
CONFIG_JSON = BASE / "config.json"

def load_config():
    if CONFIG_JSON.exists():
        return json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
    return {}

CONFIG = load_config()
LAUNCHER_HOST = CONFIG.get("launcher", {}).get("host", "127.0.0.1")
LAUNCHER_PORT = CONFIG.get("launcher", {}).get("port", 8000)
PORT = CONFIG.get("ports", {}).get("store", 8100)
LAUNCHER_URL = f"http://{LAUNCHER_HOST}:{LAUNCHER_PORT}"

HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🛒 应用商店</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
background:linear-gradient(160deg,#0e1229 0%,#1c2347 100%);color:#fff;min-height:100vh;padding:16px}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;padding:0 4px}
.header h1{font-size:20px;font-weight:600}
.header .sub{font-size:12px;opacity:.6}
.tabs{display:flex;gap:4px;background:rgba(255,255,255,.1);border-radius:12px;padding:4px;margin-bottom:16px}
.tab{flex:1;text-align:center;padding:10px;border-radius:10px;font-size:13px;cursor:pointer;transition:all .2s}
.tab.active{background:rgba(255,255,255,.2);font-weight:600}
.tab .count{display:inline-block;background:rgba(255,255,255,.2);padding:1px 7px;border-radius:10px;font-size:11px;margin-left:6px}
.search{width:100%;padding:12px 16px;background:rgba(255,255,255,.08);border:none;border-radius:14px;color:#fff;font-size:14px;margin-bottom:16px;outline:none}
.search::placeholder{color:rgba(255,255,255,.4)}
.search:focus{background:rgba(255,255,255,.12)}
.app-list{display:flex;flex-direction:column;gap:10px}
.app-card{display:flex;align-items:center;gap:14px;padding:14px;background:rgba(255,255,255,.07);border-radius:18px;transition:background .15s}
.app-card:hover{background:rgba(255,255,255,.11)}
.app-icon{width:52px;height:52px;border-radius:14px;display:flex;align-items:center;justify-content:center;font-size:26px;flex-shrink:0}
.app-info{flex:1;min-width:0}
.app-name{font-size:15px;font-weight:600;display:flex;align-items:center;gap:8px}
.app-tag{font-size:10px;padding:2px 8px;border-radius:8px;background:rgba(0,206,201,.2);color:#00cec9;font-weight:500}
.app-desc{font-size:12px;opacity:.55;margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.app-meta{font-size:11px;opacity:.4;margin-top:2px}
.app-actions{flex-shrink:0}
.btn{padding:8px 16px;border:none;border-radius:12px;font-size:12px;font-weight:600;cursor:pointer;transition:all .15s}
.btn:active{transform:scale(.95)}
.btn-install{background:#5b8cff;color:#fff}
.btn-upgrade{background:#00cec9;color:#fff}
.btn-uninstall{background:rgba(231,76,60,.9);color:#fff}
.btn-disabled{background:rgba(255,255,255,.12);color:rgba(255,255,255,.35);cursor:not-allowed}
.btn-system{background:rgba(255,255,255,.15);color:rgba(255,255,255,.5);cursor:not-allowed}
.btn:disabled{pointer-events:none}
.empty{text-align:center;padding:60px 20px;color:rgba(255,255,255,.4)}
.empty-icon{font-size:48px;margin-bottom:12px;opacity:.5}
.empty-text{font-size:14px}
.error{text-align:center;padding:40px 20px;color:#e74c3c;background:rgba(231,76,60,.1);border-radius:14px}
.refresh-btn{background:rgba(255,255,255,.15);border:none;color:#fff;border-radius:12px;padding:8px 14px;font-size:13px;cursor:pointer}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>🛒 应用商店</h1>
    <div class="sub" id="sub">正在加载…</div>
  </div>
  <button class="refresh-btn" onclick="loadData()">⟳ 刷新</button>
</div>

<div class="tabs">
  <div class="tab active" data-tab="all" onclick="switchTab('all')">全部 <span class="count" id="cntAll">0</span></div>
  <div class="tab" data-tab="installed" onclick="switchTab('installed')">已安装 <span class="count" id="cntInstalled">0</span></div>
  <div class="tab" data-tab="updates" onclick="switchTab('updates')">可更新 <span class="count" id="cntUpdates">0</span></div>
</div>

<input class="search" id="search" placeholder="🔍 搜索应用…" oninput="filterApps()">

<div class="app-list" id="list"></div>

<script>
let repoApps=[],installedApps=[],currentTab='all',searchQuery='';

async function api(path){
  const r=await fetch(LAUNCHER_URL+path);
  return r.json();
}

async function loadData(){
  document.getElementById('sub').textContent='正在加载…';
  try{
    const [repo,apps]=await Promise.all([
      api('/api/repo'),
      api('/api/apps')
    ]);
    if(repo.error){showError('连不上仓库：'+repo.error);return;}
    
    installedApps=apps;
    repoApps=repo.apps.map(m=>{
      const local=apps.find(a=>a.id===m.id);
      const system=local&&local.system;
      return{
        ...m,
        installed:!!local,
        system:!!system,
        upgradable:!!local&&!system && compareVer(m.version,local.version)>0,
        localVersion:local?local.version:null
      };
    });
    document.getElementById('sub').textContent=`共 ${repoApps.length} 个应用 · 已安装 ${installedApps.filter(a=>!a.system).length} 个`;
    updateCounts();
    render();
  }catch(e){
    showError('加载失败：'+e.message+'<br>请确认 Launcher 正在运行');
  }
}

function compareVer(a,b){
  const pa=(a||'0').split('.').map(n=>parseInt(n)||0);
  const pb=(b||'0').split('.').map(n=>parseInt(n)||0);
  for(let i=0;i<3;i++){if((pa[i]||0)>(pb[i]||0))return 1;if((pa[i]||0)<(pb[i]||0))return-1;}
  return 0;
}

function updateCounts(){
  document.getElementById('cntAll').textContent=repoApps.length;
  document.getElementById('cntInstalled').textContent=repoApps.filter(a=>a.installed).length;
  document.getElementById('cntUpdates').textContent=repoApps.filter(a=>a.upgradable).length;
}

function switchTab(t){
  currentTab=t;
  document.querySelectorAll('.tab').forEach(el=>el.classList.toggle('active',el.dataset.tab===t));
  render();
}

function filterApps(){
  searchQuery=document.getElementById('search').value.toLowerCase();
  render();
}

function render(){
  let list=repoApps;
  if(currentTab==='installed')list=list.filter(a=>a.installed);
  else if(currentTab==='updates')list=list.filter(a=>a.upgradable);
  if(searchQuery)list=list.filter(a=>a.name.toLowerCase().includes(searchQuery));
  
  const box=document.getElementById('list');
  if(!list.length){
    const messages={all:'还没有应用，去发布第一个吧 🚀',installed:'没有安装任何应用',updates:'所有应用都是最新的 ✨'};
    box.innerHTML=`<div class="empty"><div class="empty-icon">📦</div><div class="empty-text">${messages[currentTab]}</div></div>`;
    return;
  }
  
  box.innerHTML='';
  list.forEach(app=>box.appendChild(renderCard(app)));
}

function renderCard(app){
  const d=document.createElement('div');d.className='app-card';
  const tag=app.system?'<span class="app-tag">系统</span>':'';
  const verInfo=app.installed
    ?(app.upgradable?`<span style="color:#00cec9">${app.localVersion} → ${app.version}</span>`:`<span style="opacity:.45">v${app.version}</span>`)
    :`<span style="opacity:.45">v${app.version}</span>`;
  
  let action='';
  if(app.system && app.installed){
    if(app.upgradable){
      action=`<button class="btn btn-upgrade" onclick="doInstall('${app.id}')">升级</button>`;
    }else{
      action=`<button class="btn btn-system" disabled>✓ 系统应用</button>`;
    }
  }else if(!app.installed){
    action=`<button class="btn btn-install" onclick="doInstall('${app.id}')">安装</button>`;
  }else if(app.upgradable){
    action=`<button class="btn btn-upgrade" onclick="doInstall('${app.id}')">升级</button>
            <button class="btn btn-uninstall" onclick="doUninstall('${app.id}')">卸载</button>`;
  }else{
    action=`<button class="btn btn-disabled" disabled>✓ 已安装</button>
            <button class="btn btn-uninstall" onclick="doUninstall('${app.id}')">卸载</button>`;
  }
  
  d.innerHTML=`
    <div class="app-icon" style="background:linear-gradient(160deg,${app.color}33,${app.color}11)">${app.icon}</div>
    <div class="app-info">
      <div class="app-name">${app.name}${tag}</div>
      <div class="app-desc">${app.changelog||'暂无描述'}</div>
      <div class="app-meta">${verInfo} · ${app.size?(app.size<1024?app.size+' B':(app.size/1024).toFixed(1)+' KB'):''}</div>
    </div>
    <div class="app-actions" style="display:flex;gap:6px">${action}</div>
  `;
  return d;
}

async function doInstall(id){
  try{
    const r=await api('/api/install?id='+encodeURIComponent(id));
    if(r.ok){loadData();}
    else{alert('安装失败：'+r.msg);}
  }catch(e){alert('请求失败：'+e.message);}
}

async function doUninstall(id){
  if(!confirm('确定要卸载这个应用吗？'))return;
  try{
    const r=await api('/api/uninstall?id='+encodeURIComponent(id));
    if(r.ok){loadData();}
    else{alert('卸载失败：'+r.msg);}
  }catch(e){alert('请求失败：'+e.message);}
}

function showError(msg){
  document.getElementById('list').innerHTML=`<div class="error">${msg}</div>`;
}

loadData();
</script>
</body>
</html>"""

def render_page():
    """把 LAUNCHER_URL 注入到前端 JS 全局变量"""
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