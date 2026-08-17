import json, socket, subprocess, sys, time, atexit, os, re
import hashlib, zipfile, shutil, base64, urllib.request, ssl
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

BASE = Path(__file__).parent
CONFIG_JSON = BASE / "config.json"
APPS_DIR = BASE / "apps"
SYSTEM_APPS_DIR = APPS_DIR / "system"
USER_APPS_DIR = APPS_DIR / "user"

def load_config():
    if CONFIG_JSON.exists():
        return json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
    return {}

CONFIG = load_config()

LAUNCHER_CFG = CONFIG.get("launcher", {})
REPO_CFG = CONFIG.get("repo", {})
PUBLISH_CFG = CONFIG.get("publish", {})
PORTS_CFG = CONFIG.get("ports", {})

LAUNCHER_HOST = LAUNCHER_CFG.get("host", "127.0.0.1")
LAUNCHER_PORT = LAUNCHER_CFG.get("port", 8000)
LAUNCHER_TITLE = LAUNCHER_CFG.get("title", "我的 Launcher")

REPO_URL = REPO_CFG.get("url", "")
REPO_AUTH = REPO_CFG.get("auth")
VERIFY_SSL = REPO_CFG.get("verify_ssl", False)

SSL_CTX = ssl.create_default_context()
if not VERIFY_SSL:
    SSL_CTX.check_hostname = False
    SSL_CTX.verify_mode = ssl.CERT_NONE

def resolve_cmd(e):
    cmd = e.get("cmd")
    if not cmd:
        return None
    cmd = [str(BASE / c) if not Path(c).is_absolute() else c for c in cmd]
    if cmd[0].lower().endswith((".py", ".pyw")):
        cmd = [sys.executable] + cmd
    return cmd

def _scan_apps(root, *, system):
    """扫描 root/*/app.json 加载应用清单"""
    apps = []
    if not root.exists():
        return apps
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        app_json = d / "app.json"
        if not app_json.exists():
            continue
        try:
            meta = json.loads(app_json.read_text(encoding="utf-8"))
            meta.setdefault("id", d.name)
            meta["system"] = system
            meta["cmd"] = resolve_cmd(meta)
            apps.append(meta)
        except (json.JSONDecodeError, KeyError) as e:
            print(f"⚠ 应用 {d.name} 加载失败: {e}")
    return apps

def load_system_apps():
    """系统应用：默认安装、可更新、不可卸载"""
    return _scan_apps(SYSTEM_APPS_DIR, system=True)

def load_user_apps():
    """用户应用：允许安装和卸载"""
    return _scan_apps(USER_APPS_DIR, system=False)

system_apps = []
user_apps = []
procs = {}
REGISTRY = []

def vt(v): return tuple(int(x) for x in re.findall(r"\d+", v or "0")[:3])

def is_system_app(aid):
    return any(a["id"] == aid for a in system_apps)

def is_user_app(aid):
    return any(a["id"] == aid for a in user_apps)

def rebuild_registry():
    global REGISTRY
    REGISTRY = system_apps + user_apps

def reload_apps():
    """重新扫描磁盘，刷新 system_apps / user_apps / REGISTRY"""
    global system_apps, user_apps
    system_apps = load_system_apps()
    user_apps = load_user_apps()
    rebuild_registry()

reload_apps()

def port_ready(port, timeout=6):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False

def open_app(app):
    if not app.get("cmd"):
        return True
    p = procs.get(app["id"])
    if p and p.poll() is None:
        return True
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    procs[app["id"]] = subprocess.Popen(app["cmd"], **kw)
    return port_ready(app["port"])

def close_app(aid):
    p = procs.pop(aid, None)
    if p and p.poll() is None:
        p.terminate()

def repo_get(path):
    req = urllib.request.Request(REPO_URL.rstrip("/") + "/" + path)
    if REPO_AUTH:
        req.add_header("Authorization", "Basic " + base64.b64encode(
            f"{REPO_AUTH[0]}:{REPO_AUTH[1]}".encode()).decode())
    return urllib.request.urlopen(req, timeout=20, context=SSL_CTX)

def repo_index():
    return json.loads(repo_get("index.json").read().decode("utf-8"))

def do_install(aid):
    if not aid:
        return False, "缺少 id"
    try:
        meta = next(m for m in repo_index().get("apps", []) if m["id"] == aid)
    except StopIteration:
        return False, "仓库中不存在"
    # 系统应用走更新流程；用户应用走安装流程
    is_system = is_system_app(aid) or meta.get("system", False)
    close_app(aid)
    data = repo_get(meta["pkg"]).read()
    if meta.get("sha256") and hashlib.sha256(data).hexdigest() != meta["sha256"]:
        return False, "sha256 校验失败"
    dest_root = SYSTEM_APPS_DIR if is_system else USER_APPS_DIR
    dest_root.mkdir(parents=True, exist_ok=True)
    tmp = dest_root / f"{aid}.zip.tmp"
    tmp.write_bytes(data)
    with zipfile.ZipFile(tmp) as z:
        bad = [n for n in z.namelist() if n.startswith("/") or ".." in n]
        if bad:
            return False, "zip 包含非法路径"
        # 兼容 zip 内顶层为 <aid>/ 或直接为文件的两种结构
        names = z.namelist()
        top_dirs = {n.split("/", 1)[0] for n in names if "/" in n}
        if top_dirs == {aid}:
            # 标准结构：包内已有 <aid>/ 顶层目录，直接解压到 dest_root
            target = dest_root / aid
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            z.extractall(dest_root)
        else:
            # 扁平结构：包内是文件列表，解压到 dest_root/<aid>/
            target = dest_root / aid
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            target.mkdir(parents=True, exist_ok=True)
            z.extractall(target)
    tmp.unlink()
    reload_apps()
    return True, "ok"

def do_uninstall(aid):
    if not aid:
        return False, "缺少 id"
    if is_system_app(aid):
        return False, "系统应用不可卸载"
    app_dir = USER_APPS_DIR / aid
    if not app_dir.exists():
        return False, "未安装"
    close_app(aid)
    shutil.rmtree(app_dir, ignore_errors=True)
    reload_apps()
    return True, "ok"

def stub_html(a):
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{{font-family:system-ui;display:flex;flex-direction:column;align-items:center;
justify-content:center;height:100vh;margin:0;background:linear-gradient(160deg,{a['color']}33,#fff)}}
.ic{{font-size:64px}}p{{color:#999;font-size:13px}}</style></head>
<body><div class="ic">{a['icon']}</div><h2>{a['name']}</h2><p>占位应用 · 待接入</p></body></html>"""

HTML = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>""" + LAUNCHER_TITLE + r"""</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{height:100%;overflow:hidden}
body{font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
background:radial-gradient(130% 130% at 15% 0%,#33406f 0%,#1c2347 45%,#0e1229 100%);
color:#fff;user-select:none}
#statusbar{position:fixed;top:0;left:0;right:0;height:30px;z-index:90;
display:flex;justify-content:space-between;align-items:center;padding:0 16px;
font-size:12.5px;font-weight:600;pointer-events:none;mix-blend-mode:difference}
.sbR{display:flex;align-items:center;gap:8px}
#netIcon{width:15px;height:15px}
#netIcon .slash{display:none}
#netIcon.off .slash{display:block}
#netIcon.off .arc{opacity:.3}
#batt{width:22px;height:11px;border:1.5px solid #fff;border-radius:3px;position:relative}
#batt i{position:absolute;inset:1px;background:#7CFC9A;border-radius:1px;transition:width .3s}
#batt b{position:absolute;right:-4px;top:2px;width:2px;height:5px;background:#fff;border-radius:1px}
#home{position:absolute;inset:0;display:flex;flex-direction:column;
padding:40px 0 0;transition:.25s;touch-action:none}
#home.dim{opacity:0;transform:scale(1.08);pointer-events:none}
#cw{text-align:center;margin-bottom:18px}
#cwTime{font-size:44px;font-weight:200;letter-spacing:2px}
#cwDate{font-size:12px;opacity:.7;margin-top:2px}
#pager{flex:1;overflow:hidden}
#screens{display:flex;height:100%;transition:transform .25s cubic-bezier(.2,.8,.2,1)}
.screen{flex:0 0 100%;display:grid;grid-template-columns:repeat(4,1fr);
gap:26px 6px;align-content:start;padding:10px 22px}
.icon{display:flex;flex-direction:column;align-items:center;gap:7px;cursor:pointer}
.tile{position:relative;width:58px;height:58px;border-radius:15px;font-size:29px;
display:flex;align-items:center;justify-content:center;
background:linear-gradient(160deg,rgba(255,255,255,.22),rgba(255,255,255,.06)),var(--c);
box-shadow:0 8px 18px rgba(0,0,0,.35);transition:transform .12s}
.icon:active .tile{transform:scale(.88)}
.name{font-size:12px;opacity:.92;max-width:70px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tile.running::after{content:"";position:absolute;bottom:-11px;left:50%;
transform:translateX(-50%);width:5px;height:5px;border-radius:50%;background:#7CFC9A}
.tile.system::before{content:"";position:absolute;top:4px;right:4px;width:5px;height:5px;border-radius:50%;background:#00cec9}
#dots{display:flex;justify-content:center;gap:6px;padding:8px 0 12px}
#dots i{width:6px;height:6px;border-radius:50%;background:rgba(255,255,255,.35);transition:.2s}
#dots i.on{background:#fff;transform:scale(1.2)}
#dock{margin:0 16px 26px;height:78px;border-radius:24px;background:rgba(255,255,255,.13);
backdrop-filter:blur(20px);display:flex;align-items:center;justify-content:space-evenly}
#dock .name{display:none}
.panel{position:fixed;inset:0;z-index:60;background:rgba(10,14,30,.85);backdrop-filter:blur(14px);
transform:translateY(100%);transition:transform .28s cubic-bezier(.2,.8,.2,1);
display:flex;flex-direction:column;padding:46px 0 24px}
.panel.show{transform:translateY(0)}
.pHead{display:flex;justify-content:space-between;align-items:center;padding:0 22px 12px;font-size:15px}
.pHead span{display:flex;gap:8px}
.pHead button{background:rgba(255,255,255,.15);border:none;color:#fff;border-radius:14px;
padding:6px 12px;cursor:pointer;font-size:12px}
#rCards{flex:1;display:flex;gap:14px;overflow-x:auto;padding:10px 22px;align-items:center;touch-action:pan-x}
.card{position:relative;flex:0 0 150px;height:210px;border-radius:18px;background:rgba(255,255,255,.1);
display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;
cursor:pointer;transition:transform .2s,opacity .2s}
.card .x{position:absolute;top:8px;right:10px;background:none;border:none;color:rgba(255,255,255,.7);
font-size:15px;cursor:pointer}
.card .st{font-size:11px;color:rgba(255,255,255,.55)}
.rTip{text-align:center;color:rgba(255,255,255,.45);font-size:12px;padding-top:12px}
.rEmpty{flex:1;display:flex;align-items:center;justify-content:center;color:rgba(255,255,255,.4);font-size:14px}
.page{position:absolute;inset:0;background:#fff;display:none;flex-direction:column;
z-index:40;padding-top:30px}
.page.show{display:flex;animation:op .3s cubic-bezier(.25,.9,.3,1)}
@keyframes op{from{transform:scale(.4);opacity:0;border-radius:30px}}
.bar{height:44px;background:#1c2347;color:#fff;display:flex;align-items:center;
justify-content:space-between;padding:0 14px;font-size:13px}
.bar button{background:none;border:none;color:#fff;font-size:13px;cursor:pointer;padding:6px 10px}
.page iframe{flex:1;border:0;width:100%}
.loading{flex:1;display:flex;align-items:center;justify-content:center;color:#888;font-size:14px}
.gz{position:absolute;left:0;right:0;bottom:0;height:16px;z-index:5}
#homeBar{position:fixed;left:50%;bottom:8px;transform:translateX(-50%);width:130px;height:5px;
border-radius:3px;background:#fff;mix-blend-mode:difference;z-index:99;cursor:pointer}
</style></head><body>

<div id="statusbar">
  <span id="sbTime">--:--</span>
  <span class="sbR">
    <svg id="netIcon" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         stroke-width="2" stroke-linecap="round">
      <path class="arc" d="M2 8.5C5 5.9 8.4 4.5 12 4.5s7 1.4 10 4"/>
      <path class="arc" d="M5.5 12.5c2-1.8 4.2-2.7 6.5-2.7s4.5.9 6.5 2.7"/>
      <path class="arc" d="M9 16.3c1-.9 2-1.3 3-1.3s2 .4 3 1.3"/>
      <circle cx="12" cy="19.5" r="1.8" fill="currentColor" stroke="none"/>
      <path class="slash" d="M4 4l16 16"/>
    </svg>
    <span id="batt"><i id="battFill"></i><b></b></span><span id="battPct"></span>
  </span>
</div>

<div id="home">
  <div id="cw"><div id="cwTime">--:--</div><div id="cwDate"></div></div>
  <div id="pager"><div id="screens"></div></div>
  <div id="dots"></div>
  <div id="dock"></div>
</div>

<!-- 最近任务面板（上拉手势打开） -->
<div id="recents" class="panel">
  <div class="pHead"><span>最近任务</span>
    <span><button id="clearAll">全部清除</button><button id="closeR">▼ 收起</button></span></div>
  <div id="rCards"></div>
  <div class="rTip">上滑卡片清除单个 · 空白处下滑关闭 · 点卡片回到应用</div>
</div>

<div id="pages"></div>
<div id="homeBar"></div>

<script>
const PAGE=16;
let APPS=[],pageIdx=0,screenCount=0,current=null,recentsOpen=false,suppress=false;
const pages={},openedOrder=[];
const $=id=>document.getElementById(id);

function tick(){
  const d=new Date(),p=n=>String(n).padStart(2,'0');
  $('sbTime').textContent=p(d.getHours())+':'+p(d.getMinutes());
  $('cwTime').textContent=$('sbTime').textContent;
  $('cwDate').textContent=`${d.getMonth()+1}月${d.getDate()}日 周${'日一二三四五六'[d.getDay()]}`;
}
tick();setInterval(tick,1000);
const setNet=()=>$('netIcon').classList.toggle('off',!navigator.onLine);
addEventListener('online',setNet);addEventListener('offline',setNet);setNet();
if(navigator.getBattery)navigator.getBattery().then(b=>{
  const up=()=>{$('battFill').style.width=(b.level*100)+'%';
    $('battFill').style.background=b.charging?'#ffd54f':'#7CFC9A';
    $('battPct').textContent=Math.round(b.level*100)+'%'+(b.charging?'⚡':'');};
  up();b.addEventListener('levelchange',up);b.addEventListener('chargingchange',up);
});

function buildHome(){
  const homeApps=APPS.filter(a=>!a.dock);
  screenCount=Math.max(1,Math.ceil(homeApps.length/PAGE));
  const sc=$('screens');sc.innerHTML='';
  for(let s=0;s<screenCount;s++){
    const d=document.createElement('div');d.className='screen';
    homeApps.slice(s*PAGE,(s+1)*PAGE).forEach(a=>d.appendChild(iconEl(a)));
    sc.appendChild(d);
  }
  const dk=$('dock');dk.innerHTML='';
  APPS.filter(a=>a.dock).forEach(a=>dk.appendChild(iconEl(a)));
  const dots=$('dots');dots.innerHTML='';
  for(let i=0;i<screenCount;i++)dots.appendChild(document.createElement('i'));
  gotoPage(0);updateDots();
}
function iconEl(a){
  const d=document.createElement('div');d.className='icon';d.dataset.id=a.id;
  const sys=a.system?'<div class="tile system" style="--c:'+a.color+'">'+a.icon+'</div>':
    '<div class="tile" style="--c:'+a.color+'">'+a.icon+'</div>';
  d.innerHTML=sys+'<div class="name">'+a.name+'</div>';
  return d;
}
function gotoPage(i){
  pageIdx=Math.max(0,Math.min(screenCount-1,i));
  $('screens').style.transform=`translateX(${-pageIdx*$('pager').clientWidth}px)`;
  [...$('dots').children].forEach((d,j)=>d.classList.toggle('on',j===pageIdx));
}
addEventListener('resize',()=>gotoPage(pageIdx));
function updateDots(){
  const run={};APPS.forEach(a=>run[a.id]=a.running);
  document.querySelectorAll('.icon').forEach(el=>{
    const tile=el.querySelector('.tile');
    if(tile){
      tile.classList.toggle('running',!!run[el.dataset.id]);
      tile.classList.toggle('system',!!APPS.find(a=>a.id===el.dataset.id && a.system));
    }
  });
}

async function openApp(a){
  let pg=pages[a.id];
  if(!pg){
    pg=document.createElement('div');pg.className='page';
    pg.innerHTML=`<div class="bar"><span>${a.icon} ${a.name}</span>
      <span><button onclick="goHome()">🏠 回桌面</button>
      <button onclick="killApp('${a.id}')">✕ 退出</button></span></div>
      <div class="loading">正在拉起进程，等待端口就绪…</div>
      <iframe style="display:none"></iframe><div class="gz"></div>`;
    document.body.appendChild(pg);pages[a.id]=pg;openedOrder.push(a.id);
  }
  pg.classList.add('show');$('home').classList.add('dim');current=a.id;
  const wasRunning=a.running;
  const j=await (await fetch('/api/open?id='+a.id)).json();
  const iframe=pg.querySelector('iframe'),ld=pg.querySelector('.loading');
  if(j.ok&&(!wasRunning||!iframe.src)){
    iframe.src=j.url+(j.url.includes('?')?'&':'?')+'t='+Date.now();
    iframe.onload=()=>{ld.style.display='none';iframe.style.display='block';};
  }else{ld.style.display='none';iframe.style.display='block';}
  poll();
}
function goHome(){
  if(recentsOpen)return closeRecents();
  if(!current)return;
  pages[current].classList.remove('show');
  $('home').classList.remove('dim');current=null;
}
async function killApp(id){
  await fetch('/api/close?id='+id);
  if(pages[id]){pages[id].remove();delete pages[id];
    openedOrder.splice(openedOrder.indexOf(id),1);}
  if(current===id){current=null;$('home').classList.remove('dim');}
  if(recentsOpen)renderRecents();
  poll();
}

/* ── 最近任务 ── */
function openRecents(){recentsOpen=true;renderRecents();$('recents').classList.add('show');}
function closeRecents(){recentsOpen=false;$('recents').classList.remove('show');}
function renderRecents(){
  const box=$('rCards');box.innerHTML='';
  if(!openedOrder.length){box.innerHTML='<div class="rEmpty">没有运行中的应用</div>';return;}
  openedOrder.slice().reverse().forEach(id=>{
    const a=APPS.find(x=>x.id===id);if(!a)return;
    const c=document.createElement('div');c.className='card';
    c.innerHTML=`<button class="x">✕</button>
      <div class="tile" style="--c:${a.color}">${a.icon}</div>
      <div class="name">${a.name}</div><div class="st">${a.running?'进程运行中':'页面保活中'}</div>`;
    c.onclick=()=>{if(suppress)return;closeRecents();openApp(a);};
    c.querySelector('.x').onclick=e=>{e.stopPropagation();killApp(id);};
    let sy=null;
    c.addEventListener('pointerdown',e=>{sy=e.clientY;});
    c.addEventListener('pointerup',e=>{if(sy!==null&&e.clientY-sy<-50)killApp(id);sy=null;});
    box.appendChild(c);
  });
}
$('clearAll').onclick=()=>{[...openedOrder].forEach(killApp);};
$('closeR').onclick=closeRecents;

/* ── 手势：上拉打开最近任务 ── */
let drag=null;
addEventListener('pointerdown',e=>{
  if(e.target.closest('#homeBar,button,.bar,#statusbar,.card'))return;
  drag={x:e.clientX,y:e.clientY,dx:0,dy:0,axis:null};
  if(!recentsOpen&&e.target.setPointerCapture)
    e.target.setPointerCapture(e.pointerId);
});
addEventListener('pointermove',e=>{
  if(!drag)return;
  drag.dx=e.clientX-drag.x;drag.dy=e.clientY-drag.y;
  if(!drag.axis&&(Math.abs(drag.dx)>8||Math.abs(drag.dy)>8))
    drag.axis=Math.abs(drag.dx)>Math.abs(drag.dy)?'h':'v';
  if(!recentsOpen&&!current&&drag.axis==='h'){
    $('screens').style.transition='none';
    $('screens').style.transform=
      `translateX(${-pageIdx*$('pager').clientWidth+drag.dx}px)`;
  }
});
addEventListener('pointerup',e=>{
  if(!drag)return;
  const{dx,dy,axis}=drag;drag=null;
  suppress=!!axis&&(Math.abs(dx)>8||Math.abs(dy)>8);
  if(recentsOpen){if(axis==='v'&&dy>70)closeRecents();return;}
  if(!current){
    if(axis==='v'&&dy<-60){openRecents();return;}
    if(axis==='h'){if(dx<-60)gotoPage(pageIdx+1);else if(dx>60)gotoPage(pageIdx-1);else gotoPage(pageIdx);}
  }else{
    if(axis==='v'&&dy<-50)openRecents();
  }
});
document.addEventListener('click',e=>{
  if(suppress){suppress=false;return;}
  const ic=e.target.closest('.icon');if(!ic)return;
  const a=APPS.find(x=>x.id===ic.dataset.id);if(a)openApp(a);
});
$('homeBar').onclick=()=>{if(recentsOpen)closeRecents();else openRecents();};
addEventListener('keydown',e=>{if(e.key==='Escape')goHome();});

async function poll(){
  const prev=APPS.map(a=>a.id).join(',');
  APPS=await (await fetch('/api/apps')).json();
  const cur=APPS.map(a=>a.id).join(',');
  // 应用列表变化（安装/卸载）时重建桌面图标
  if(prev!==cur && prev.length){buildHome();}
  updateDots();
  if(recentsOpen)renderRecents();
}
poll().then(()=>{buildHome();setInterval(poll,2000);});
</script></body></html>"""

class Handler(BaseHTTPRequestHandler):
    def _json(self, o):
        b = json.dumps(o).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/apps":
            self._json([{**a, "running": procs.get(a["id"]) is not None
                         and procs[a["id"]].poll() is None} for a in REGISTRY])
        elif u.path == "/api/repo":
            try:
                # 用磁盘扫描结果（system_apps + user_apps）作为本地版本来源
                local_apps = {a["id"]: a for a in (system_apps + user_apps)}
                loc = {aid: a.get("version") for aid, a in local_apps.items()}
                sys_ids = {s["id"] for s in system_apps}
                out = [{**m, "local": loc.get(m["id"]),
                        "system": m["id"] in sys_ids or m.get("system", False),
                        "installed": m["id"] in local_apps,
                        "upgradable": bool(loc.get(m["id"]))
                        and vt(m.get("version", "0")) > vt(loc.get(m["id"]))}
                       for m in repo_index().get("apps", [])]
                self._json({"apps": out})
            except Exception as ex:
                self._json({"error": str(ex), "apps": []})
        elif u.path == "/api/install":
            ok, msg = do_install(parse_qs(u.query).get("id", [None])[0])
            self._json({"ok": ok, "msg": msg})
        elif u.path == "/api/uninstall":
            ok, msg = do_uninstall(parse_qs(u.query).get("id", [None])[0])
            self._json({"ok": ok, "msg": msg})
        elif u.path == "/api/open":
            app = next((a for a in REGISTRY
                        if a["id"] == parse_qs(u.query).get("id", [None])[0]), None)
            if not app:
                self._json({"ok": False, "url": None})
                return
            ok = open_app(app)
            if app.get("cmd"):
                url = f"http://127.0.0.1:{app['port']}"
            else:
                url = f"/stub?id={app['id']}"
            self._json({"ok": ok, "url": url if ok else None})
        elif u.path == "/api/close":
            close_app(parse_qs(u.query).get("id", [None])[0])
            self._json({"ok": True})
        elif u.path == "/stub":
            app = next((a for a in REGISTRY
                        if a["id"] == parse_qs(u.query).get("id", [None])[0]), None)
            if not app:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html;charset=utf-8")
            self.end_headers()
            self.wfile.write(stub_html(app).encode())
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html;charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML.encode())

    def log_message(self, *a):
        pass

if __name__ == "__main__":
    atexit.register(lambda: [p.terminate() for p in procs.values() if p.poll() is None])
    print(f"Launcher 已就绪: http://{LAUNCHER_HOST}:{LAUNCHER_PORT}")
    try:
        ThreadingHTTPServer((LAUNCHER_HOST, LAUNCHER_PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        pass