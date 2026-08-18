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
.app-actions{flex-shrink:0;display:flex;gap:6px;align-items:center}
.btn{padding:8px 16px;border:none;border-radius:12px;font-size:12px;font-weight:600;cursor:pointer;transition:all .15s}
.btn:active{transform:scale(.95)}
.btn-install{background:#5b8cff;color:#fff}
.btn-upgrade{background:#00cec9;color:#fff}
.btn-uninstall{background:rgba(231,76,60,.9);color:#fff}
.btn-disabled{background:rgba(255,255,255,.12);color:rgba(255,255,255,.35);cursor:not-allowed}
.btn-system{background:rgba(255,255,255,.15);color:rgba(255,255,255,.5);cursor:not-allowed}
.btn-info{background:rgba(255,255,255,.1);color:#fff;border-radius:12px;padding:8px 10px;font-size:13px}
.btn-info:hover{background:rgba(255,255,255,.18)}
.btn:disabled{pointer-events:none}
.empty{text-align:center;padding:60px 20px;color:rgba(255,255,255,.4)}
.empty-icon{font-size:48px;margin-bottom:12px;opacity:.5}
.empty-text{font-size:14px}
.error{text-align:center;padding:40px 20px;color:#e74c3c;background:rgba(231,76,60,.1);border-radius:14px}
.refresh-btn{background:rgba(255,255,255,.15);border:none;color:#fff;border-radius:12px;padding:8px 14px;font-size:13px;cursor:pointer}

/* ── 详情弹窗 ── */
.modalMask{position:fixed;inset:0;z-index:999;background:rgba(0,0,0,.7);backdrop-filter:blur(6px);
display:none;align-items:center;justify-content:center;padding:24px;animation:fade .18s}
.modalMask.show{display:flex}
@keyframes fade{from{opacity:0}}
.modal{width:min(640px,98vw);max-height:90vh;background:#141938;border:1px solid rgba(255,255,255,.08);
border-radius:20px;padding:22px;display:flex;flex-direction:column;gap:14px;color:#fff;
box-shadow:0 24px 80px rgba(0,0,0,.7);overflow:hidden}
.modalHead{display:flex;align-items:center;gap:14px}
.modalHead .bigIcon{width:64px;height:64px;border-radius:18px;font-size:34px;
display:flex;align-items:center;justify-content:center;
background:linear-gradient(160deg,rgba(255,255,255,.2),rgba(255,255,255,.05))}
.modalHead .titleRow{flex:1;min-width:0}
.modalHead h2{font-size:18px;font-weight:600;display:flex;align-items:center;gap:8px}
.modalHead .metaTop{font-size:12px;opacity:.6;margin-top:4px}
.modalHead .x{background:none;border:0;color:rgba(255,255,255,.6);font-size:22px;cursor:pointer;
padding:2px 8px;border-radius:8px;align-self:flex-start}
.modalHead .x:hover{background:rgba(255,255,255,.1);color:#fff}

.verGrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
.verCell{background:rgba(255,255,255,.06);border-radius:12px;padding:10px 12px}
.verCell .lb{font-size:10px;opacity:.5;letter-spacing:1px;text-transform:uppercase;margin-bottom:3px}
.verCell .vl{font-size:14px;font-weight:600}
.verCell .sub{font-size:11px;opacity:.5;margin-top:2px}

.sectionBox{background:rgba(255,255,255,.06);border-radius:12px;padding:12px 14px}
.sectionBox h4{font-size:12px;font-weight:600;opacity:.7;margin-bottom:8px;letter-spacing:.5px}
.clArea{max-height:200px;overflow:auto;font-size:12.5px;line-height:1.9}
.clArea ul{padding-left:18px}

.verScroll{max-height:180px;overflow:auto;display:flex;flex-direction:column;gap:6px}
.verItem{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:10px;
background:rgba(255,255,255,.04);font-size:12.5px}
.verItem.current{border:1px solid rgba(0,206,201,.45);background:rgba(0,206,201,.08)}
.verItem .vi{opacity:.55;font-weight:600;min-width:70px}
.verItem .vr{flex:1;min-width:0}
.verItem .vr small{opacity:.5;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:2px}
.verItem button{padding:5px 10px;border:0;border-radius:8px;font-size:11px;font-weight:600;cursor:pointer}
.btnRollback{background:#f39c12;color:#000}
.btnCurrent{background:rgba(255,255,255,.1);color:#fff;cursor:default}

.modalFoot{display:flex;justify-content:flex-end;gap:8px;margin-top:auto}
.btnGhost{background:rgba(255,255,255,.1);color:#fff;border:0;padding:8px 16px;border-radius:12px;
font-size:12px;cursor:pointer;font-weight:600}

.__busy{position:fixed;left:50%;top:12px;transform:translateX(-50%);padding:8px 18px;
background:#5b8cff;border-radius:12px;font-size:13px;font-weight:600;z-index:9999;
box-shadow:0 6px 24px rgba(0,0,0,.4)}
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

<!-- 详情弹窗 -->
<div class="modalMask" id="detailMask" role="dialog">
  <div class="modal" id="detailBox">
    <div class="modalHead">
      <div class="bigIcon" id="dIcon">📦</div>
      <div class="titleRow">
        <h2 id="dName">应用名称 <span class="app-tag" id="dTag" style="display:none">系统</span></h2>
        <div class="metaTop" id="dMeta">版本信息…</div>
      </div>
      <button class="x" onclick="closeDetail()" aria-label="关闭">×</button>
    </div>
    <div class="verGrid" id="dVerGrid"></div>
    <div class="sectionBox">
      <h4>📋 更新说明 (Changelog)</h4>
      <div class="clArea"><ul id="dChangelog"></ul></div>
    </div>
    <div class="modalFoot">
      <button class="btnGhost" onclick="closeDetail()">关闭</button>
    </div>
  </div>
</div>

<script>
let repoApps=[],installedApps=[],currentTab='all',searchQuery='';

async function api(path){
  const r=await fetch(LAUNCHER_URL+path);
  return r.json();
}

/* ── 工具函数 ── */
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function clUL(text){if(!text)return'<li style="opacity:.4">暂无</li>';
  return String(text).split('\n').map(s=>s.trim().replace(/^[-•*]\s*/,'')).filter(Boolean)
    .map(s=>'<li>'+esc(s)+'</li>').join('')||'<li style="opacity:.4">暂无</li>';}
function fmtTime(s){if(!s)return'—';return s.replace('T',' ').slice(0,16);}
function fmtSize(n){if(!n)return'';return n<1024?(n+' B'):(n/1024).toFixed(1)+' KB';}
function setBusy(msg){
  document.querySelectorAll('#list button, .modalFoot button, .verItem button').forEach(b=>b.disabled=true);
  if(document.getElementById('__busy'))return;
  const label=document.createElement('div');label.id='__busy';label.textContent=msg;
  document.body.appendChild(label);}
function clearBusy(){
  document.querySelectorAll('#list button, .modalFoot button, .verItem button').forEach(b=>b.disabled=false);
  document.getElementById('__busy')?.remove();}

/* ── 主数据加载 ── */
async function loadData(){
  document.getElementById('sub').textContent='正在加载…';
  try{
    const [repo,apps]=await Promise.all([api('/api/repo'),api('/api/apps')]);
    if(repo.error){showError('连不上仓库：'+repo.error);return;}
    installedApps=apps;
    repoApps=repo.apps.map(m=>{
      const local=apps.find(a=>a.id===m.id);
      const system=!!(local&&local.system)||!!m.system;
      return{
        ...m,
        installed:!!local,
        system,
        upgradable:!!local&&compareVer(m.version,local.version)>0,
        localVersion:local?local.version:null,
        localReleased:local?local.released:null,
      };
    });
    document.getElementById('sub').textContent=`共 ${repoApps.length} 个应用 · 已安装 ${installedApps.filter(a=>!a.system).length} 个`;
    updateCounts();render();
  }catch(e){showError('加载失败：'+e.message+'<br>请确认 Launcher 正在运行');}
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
function switchTab(t){currentTab=t;
  document.querySelectorAll('.tab').forEach(el=>el.classList.toggle('active',el.dataset.tab===t));
  render();}
function filterApps(){searchQuery=document.getElementById('search').value.toLowerCase();render();}
function render(){
  let list=repoApps;
  if(currentTab==='installed')list=list.filter(a=>a.installed);
  else if(currentTab==='updates')list=list.filter(a=>a.upgradable);
  if(searchQuery)list=list.filter(a=>a.name.toLowerCase().includes(searchQuery));
  const box=document.getElementById('list');
  if(!list.length){
    const messages={all:'还没有应用，去发布第一个吧 🚀',installed:'没有安装任何应用',updates:'所有应用都是最新的 ✨'};
    box.innerHTML=`<div class="empty"><div class="empty-icon">📦</div><div class="empty-text">${messages[currentTab]}</div></div>`;
    return;}
  box.innerHTML='';list.forEach(app=>box.appendChild(renderCard(app)));
}

/* ── 应用卡片渲染 ── */
function renderCard(app){
  const d=document.createElement('div');d.className='app-card';
  const tag=app.system?'<span class="app-tag">系统</span>':'';
  const verInfo=app.installed
    ?(app.upgradable?`<span style="color:#00cec9">v${app.localVersion||'?'} → v${app.version}</span>`:`<span style="opacity:.45">v${app.version}</span>`)
    :`<span style="opacity:.45">v${app.version}</span>`;
  const desc=esc(app.changelog||'暂无描述');
  let action='';
  if(app.system && app.installed){
    action=app.upgradable
      ?`<button class="btn btn-upgrade" data-action="upgrade" data-id="${app.id}">升级</button>`
      :`<button class="btn btn-system" disabled title="系统应用不可卸载">✓ 系统应用</button>`;
  }else if(!app.installed){
    action=`<button class="btn btn-install" data-action="install" data-id="${app.id}">安装</button>`;
  }else if(app.upgradable){
    action=`<button class="btn btn-upgrade" data-action="upgrade" data-id="${app.id}">升级</button>
            <button class="btn btn-uninstall" data-action="uninstall" data-id="${app.id}">卸载</button>`;
  }else{
    action=`<button class="btn btn-disabled" disabled>✓ 已安装</button>
            <button class="btn btn-uninstall" data-action="uninstall" data-id="${app.id}">卸载</button>`;
  }
  d.innerHTML=`
    <div class="app-icon" style="background:linear-gradient(160deg,${app.color}33,${app.color}11)">${app.icon}</div>
    <div class="app-info">
      <div class="app-name">${esc(app.name)}${tag}</div>
      <div class="app-desc" title="${esc(app.changelog||'')}"
           style="white-space:pre-wrap;line-height:1.5">${desc}</div>
      <div class="app-meta">${verInfo} · ${fmtSize(app.size)}</div>
    </div>
    <div class="app-actions">
      <button class="btn-info" data-action="detail" data-id="${app.id}" title="查看详情 / 历史版本 / 回退">ⓘ 详情</button>
      ${action}
    </div>`;
  return d;
}

/* ── 详情弹窗：打开/关闭 ── */
let DETAIL_APP=null;
function openDetail(id){
  const app=repoApps.find(a=>a.id===id);if(!app)return;
  DETAIL_APP=app;
  document.getElementById('dIcon').textContent=app.icon||'📦';
  document.getElementById('dIcon').style.background=
    `linear-gradient(160deg,${app.color}33,${app.color}11)`;
  const tag=document.getElementById('dTag');tag.style.display=app.system?'inline-block':'none';
  document.getElementById('dName').innerHTML=esc(app.name)+' ';
  document.getElementById('dName').appendChild(tag);
  const curV=app.localVersion||'未安装';
  const latestV=app.version;
  const cells=[
    {lb:'当前安装版本',vl:curV,sub:app.localReleased?fmtTime(app.localReleased):(app.installed?'已安装':'—')},
    {lb:'最新版本',vl:'v'+latestV,sub:app.released?fmtTime(app.released):'—'},
    {lb:'类型',vl:app.system?'🛡️ 系统':'📦 用户',sub:app.installed?'已在设备中':'尚未安装'},
    {lb:'大小',vl:fmtSize(app.size),sub:app.id},
  ];
  document.getElementById('dVerGrid').innerHTML=cells.map(c=>`
    <div class="verCell">
      <div class="lb">${c.lb}</div>
      <div class="vl">${esc(String(c.vl))}</div>
      <div class="sub">${esc(String(c.sub))}</div>
    </div>`).join('');
  document.getElementById('dChangelog').innerHTML=clUL(app.changelog);
  document.getElementById('detailMask').classList.add('show');
}
function closeDetail(){document.getElementById('detailMask').classList.remove('show');DETAIL_APP=null;}
document.getElementById('detailMask').addEventListener('click',e=>{if(e.target.id==='detailMask')closeDetail();});
window.addEventListener('keydown',e=>{if(e.key==='Escape')closeDetail();});

/* ── 事件委托（安装/升级/卸载/详情）── */
document.addEventListener('click',async (e)=>{
  const btn=e.target.closest('button[data-action]');
  if(!btn)return;
  const id=btn.dataset.id, action=btn.dataset.action;

  // 详情打开（不走 busy 流程）
  if(action==='detail'){openDetail(id);return;}

  // 安装/升级
  if(action==='install'||action==='upgrade'){
    setBusy(action==='upgrade'?'升级中：下载 + 校验 + 重启应用…':'安装中…');
    try{
      const r=await api('/api/install?id='+encodeURIComponent(id));
      clearBusy();
      if(r.ok){
        if(id==='store' && action==='upgrade'){
          alert('✅ 应用商店升级完成，页面将刷新以载入新版本');
          setTimeout(()=>location.reload(),600);return;}
        loadData();
      }else alert('操作失败：'+r.msg);
    }catch(ex){
      clearBusy();
      if(action==='upgrade' && id==='store'){setTimeout(()=>location.reload(),600);return;}
      alert('请求失败：'+ex.message);
    }
    return;
  }

  // 卸载
  if(action==='uninstall'){
    if(!confirm('确认卸载该应用吗？\n\n• 运行中的进程将被关闭\n• 目录将被移至 .bak 备份'))return;
    setBusy('卸载中…');
    try{
      const r=await api('/api/uninstall?id='+encodeURIComponent(id));
      clearBusy();
      if(r.ok){loadData();} else alert('卸载失败：'+r.msg);
    }catch(ex){clearBusy();alert('请求失败：'+ex.message);}
    return;
  }
});

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
