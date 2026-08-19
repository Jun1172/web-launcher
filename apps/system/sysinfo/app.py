"""sysinfo —— 系统信息（系统应用）
- 端口从 config.json 读取，默认 8103
- 显示：CPU 使用率、内存使用率、Python/OS 版本、已安装应用、磁盘占用
- 新增「Launcher 系统更新」section：当前/最新版本对比、Changelog、立即更新
- 跨平台：Windows 用 ctypes + wmic，Linux 读 /proc，macOS 用 vm_stat/sysctl
"""
import json
import os
import platform
import shutil
import socket
import sys
import time
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

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
PORT = CONFIG.get("ports", {}).get("sysinfo", 8103)
LAUNCHER_HOST = CONFIG.get("launcher", {}).get("host", "127.0.0.1")
LAUNCHER_PORT = CONFIG.get("launcher", {}).get("port", 8000)
LAUNCHER_URL = f"http://{LAUNCHER_HOST}:{LAUNCHER_PORT}"

# 从 config.json 读取 launcher 版本（不再硬编码）
LAUNCHER_VERSION = CONFIG.get("launcher", {}).get("version", "0.0.1")
LAUNCHER_RELEASED = CONFIG.get("launcher", {}).get("released", "")
LAUNCHER_CHANGELOG = CONFIG.get("launcher", {}).get("changelog", "")


# ── 跨平台硬件信息采集 ───────────────────────────────────
def _win_cpu_sample():
    try:
        import ctypes

        class FILETIME(ctypes.Structure):
            _fields_ = [("low", ctypes.c_uint), ("high", ctypes.c_uint)]

        def ft_to_int(ft):
            return (ft.high << 32) | ft.low

        k = ctypes.windll.kernel32
        idle1, kern1, user1 = FILETIME(), FILETIME(), FILETIME()
        idle2, kern2, user2 = FILETIME(), FILETIME(), FILETIME()
        k.GetSystemTimes(ctypes.byref(idle1), ctypes.byref(kern1), ctypes.byref(user1))
        time.sleep(0.3)
        k.GetSystemTimes(ctypes.byref(idle2), ctypes.byref(kern2), ctypes.byref(user2))
        i = ft_to_int(idle2) - ft_to_int(idle1)
        ke = ft_to_int(kern2) - ft_to_int(kern1)
        u = ft_to_int(user2) - ft_to_int(user1)
        total = ke + u
        return round((1 - i / total) * 100, 1) if total > 0 else 0.0
    except Exception:
        return None


def _win_mem():
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(m)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return {
            "percent": m.dwMemoryLoad,
            "total": m.ullTotalPhys,
            "available": m.ullAvailPhys,
        }
    except Exception:
        return None


def _linux_cpu_sample():
    try:
        def read():
            with open("/proc/stat") as f:
                return list(map(int, f.readline().split()[1:]))
        a = read(); time.sleep(0.3); b = read()
        total = sum(b) - sum(a); idle = b[3] - a[3]
        return round((1 - idle / total) * 100, 1) if total > 0 else 0.0
    except Exception:
        return None


def _linux_mem():
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":")
                info[k.strip()] = int(v.split()[0]) * 1024
        total = info.get("MemTotal", 0)
        avail = info.get("MemAvailable", info.get("MemFree", 0))
        return {
            "percent": round((1 - avail / total) * 100, 1) if total else 0,
            "total": total,
            "available": avail,
        }
    except Exception:
        return None


def get_cpu_sample():
    s = platform.system()
    if s == "Windows": return _win_cpu_sample()
    if s == "Linux":   return _linux_cpu_sample()
    return None


def get_mem():
    s = platform.system()
    if s == "Windows": return _win_mem()
    if s == "Linux":   return _linux_mem()
    return None


def fmt_bytes(n):
    if n is None: return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024: return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def collect_static():
    return {
        "launcher_version": LAUNCHER_VERSION,
        "launcher_released": LAUNCHER_RELEASED,
        "launcher_changelog": LAUNCHER_CHANGELOG,
        "python_version": sys.version.split()[0],
        "os": f"{platform.system()} {platform.release()}",
        "os_machine": platform.machine(),
        "hostname": socket.gethostname(),
        "cpu_count": os.cpu_count() or 1,
        "processor": platform.processor() or "未知",
    }


def collect_dynamic():
    mem = get_mem(); cpu = get_cpu_sample()
    try:
        usage = shutil.disk_usage(str(BASE))
        disk = {
            "total": usage.total, "used": usage.used, "free": usage.free,
            "percent": round(usage.used / usage.total * 100, 1) if usage.total else 0,
        }
    except Exception:
        disk = None
    return {
        "cpu_percent": cpu, "mem": mem, "disk": disk,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def scan_installed_apps():
    apps_dir = BASE / "apps"
    result = {"system": [], "user": []}
    for kind, key in (("system", "system"), ("user", "user")):
        d = apps_dir / kind
        if not d.exists(): continue
        for sub in sorted(d.iterdir()):
            if not sub.is_dir(): continue
            j = sub / "app.json"
            if not j.exists(): continue
            try:
                m = json.loads(j.read_text(encoding="utf-8"))
                result[key].append({
                    "id": m.get("id", sub.name),
                    "name": m.get("name", sub.name),
                    "version": m.get("version", "?"),
                    "icon": m.get("icon", ""),
                    "port": m.get("port"),
                    "changelog": m.get("changelog", ""),
                })
            except Exception:
                pass
    return result


def proxy_launcher_api(path):
    """访问 Launcher 的 API（版本检查 / 自更新），透传 JSON 结果。失败返回 error 字段。"""
    try:
        with urllib.request.urlopen(LAUNCHER_URL + path, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


STATIC_INFO = collect_static()

HTML = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>📊 系统信息</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
background:#0e1229;color:#fff;min-height:100vh;padding:20px}
h2{font-size:18px;margin-bottom:14px;display:flex;align-items:center;gap:8px}
.refresh{background:rgba(255,255,255,.15);border:0;color:#fff;border-radius:10px;
padding:6px 14px;font-size:12px;cursor:pointer;margin-left:auto}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px;margin-bottom:14px}
.card{background:rgba(255,255,255,.07);border-radius:14px;padding:14px}
.card .ic{font-size:22px;margin-bottom:6px}
.card .label{font-size:11px;opacity:.6;text-transform:uppercase;letter-spacing:1px}
.card .value{font-size:22px;font-weight:600;margin-top:4px;font-variant-numeric:tabular-nums}
.card .sub{font-size:11px;opacity:.5;margin-top:3px}
.bar{height:6px;background:rgba(255,255,255,.1);border-radius:3px;margin-top:8px;overflow:hidden}
.bar i{display:block;height:100%;border-radius:3px;transition:width .4s}
.section{background:rgba(255,255,255,.05);border-radius:14px;padding:14px;margin-bottom:12px}
.section h3{font-size:13px;opacity:.7;margin-bottom:10px;font-weight:500}
.row{display:flex;justify-content:space-between;padding:7px 0;font-size:13px;
border-bottom:1px solid rgba(255,255,255,.06)}
.row:last-child{border:0}
.row .k{opacity:.6}
.row .v{font-weight:500;font-variant-numeric:tabular-nums;text-align:right;max-width:60%;word-break:break-all}
.app-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px}
.app-item{display:flex;align-items:center;gap:8px;background:rgba(255,255,255,.05);
border-radius:10px;padding:8px 10px;font-size:12px}
.app-item .ai{font-size:18px}
.app-item .an{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.app-item .av{opacity:.5;font-size:11px}
.tag{display:inline-block;padding:2px 8px;border-radius:6px;font-size:10px;margin-left:6px}
.tag.sys{background:rgba(0,206,201,.2);color:#00cec9}
.tag.usr{background:rgba(91,140,255,.2);color:#5b8cff}
.section-title{display:flex;align-items:center;gap:6px;margin-bottom:8px;font-size:13px;opacity:.8}
.section-title .n{background:rgba(255,255,255,.15);padding:1px 8px;border-radius:8px;font-size:11px}

/* ── Launcher 更新 section ── */
.upd-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-bottom:10px}
.upd-cell{background:rgba(255,255,255,.06);border-radius:12px;padding:12px}
.upd-cell .lb{font-size:11px;opacity:.55;margin-bottom:4px;text-transform:uppercase;letter-spacing:1px}
.upd-cell .vl{font-size:18px;font-weight:600}
.upd-cell .sub{font-size:11px;opacity:.5;margin-top:4px}
.upd-cell.badge-new{border:1px solid #e74c3c55;background:rgba(231,76,60,.08)}
.cl-box{background:rgba(0,0,0,.25);border-radius:10px;padding:10px 14px;
max-height:200px;overflow:auto;font-size:12.5px;line-height:1.9}
.cl-box ul{padding-left:18px}
.cl-box .hd{font-size:11px;opacity:.55;margin-bottom:4px}
.upd-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:12px}
.btn{padding:8px 16px;border:0;border-radius:12px;cursor:pointer;font-size:12px;font-weight:600}
.btn-primary{background:#e74c3c;color:#fff}
.btn-ok{background:#2ecc71;color:#fff}
.btn-muted{background:rgba(255,255,255,.12);color:#fff}
.btn:disabled{opacity:.5;cursor:not-allowed}
.status-line{padding:8px 12px;border-radius:10px;font-size:12.5px;margin-top:10px;line-height:1.7}
.status-line.ok{background:rgba(46,204,113,.12);color:#2ecc71}
.status-line.warn{background:rgba(231,76,60,.12);color:#e74c3c}
.status-line.info{background:rgba(91,140,255,.12);color:#9bb8ff}
</style></head><body>
<h2>📊 系统信息 <button class="refresh" onclick="load()">⟳ 刷新</button></h2>

<div class="cards" id="dyn"></div>

<div class="section">
  <h3>📋 版本与系统</h3>
  <div id="static"></div>
</div>

<div class="section">
  <h3>🔄 Launcher 系统更新</h3>
  <div class="upd-grid" id="updGrid"></div>
  <div class="cl-box" id="updCl"><div class="hd">📋 远端更新说明</div><ul id="updClList"></ul></div>
  <div id="updStatus"></div>
  <div class="upd-actions">
    <button class="btn btn-muted" onclick="checkLauncher()">🔍 检查更新</button>
    <button id="btnUpd" class="btn btn-primary" onclick="doUpdate()" disabled>⬆️ 立即更新</button>
  </div>
</div>

<div class="section">
  <h3>🎮 已安装应用</h3>
  <div class="section-title">🛡️ 系统应用 <span class="n" id="sysN">0</span></div>
  <div class="app-list" id="sysApps" style="margin-bottom:12px"></div>
  <div class="section-title">📦 用户应用 <span class="n" id="usrN">0</span></div>
  <div class="app-list" id="usrApps"></div>
</div>

<script>
const STATIC=__STATIC_JSON__;
const LAUNCHER_URL=__LAUNCHER_URL_JSON__;

/* ── 工具 ── */
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function clUL(text){if(!text)return'<li style="opacity:.4">暂无</li>';
  return String(text).split('\n').map(s=>s.trim().replace(/^[-•*]\s*/,'')).filter(Boolean)
    .map(s=>'<li>'+esc(s)+'</li>').join('')||'<li style="opacity:.4">暂无</li>';}
function fmtBytes(n){if(n==null)return'—';const u=['B','KB','MB','GB','TB'];let i=0;
  while(Math.abs(n)>=1024&&i<u.length-1){n/=1024;i++;}return n.toFixed(1)+' '+u[i];}
function barColor(p){return p<50?'#2ecc71':p<80?'#f39c12':'#e74c3c';}
function setBusy(msg){document.querySelectorAll('.btn').forEach(b=>b.disabled=true);
  const s=document.createElement('div');s.id='__busy';
  s.style.cssText='position:fixed;left:50%;top:12px;transform:translateX(-50%);'+
    'padding:8px 18px;background:#5b8cff;border-radius:12px;font-size:13px;'+
    'font-weight:600;z-index:999;box-shadow:0 6px 24px rgba(0,0,0,.4)';
  s.textContent=msg;document.body.appendChild(s);}
function clearBusy(){document.querySelectorAll('.btn').forEach(b=>b.disabled=false);
  document.getElementById('__busy')?.remove();}

/* ── 静态（版本与系统）── */
function renderStatic(){
  const rows=[
    ['Launcher 版本',STATIC.launcher_version+(STATIC.launcher_released?' · '+STATIC.launcher_released:'')],
    ['Python 版本',STATIC.python_version],
    ['操作系统',STATIC.os+' ('+STATIC.os_machine+')'],
    ['主机名',STATIC.hostname],
    ['CPU 核心',STATIC.cpu_count+' 核'],
    ['处理器',STATIC.processor],
  ];
  document.getElementById('static').innerHTML=rows.map(r=>
    `<div class="row"><span class="k">${r[0]}</span><span class="v">${esc(r[1])}</span></div>`
  ).join('');
}

/* ── 动态硬件信息 ── */
function renderDyn(d){
  const cpuP=d.cpu_percent; const mem=d.mem||{},disk=d.disk||{};
  const cards=[
    {ic:'⚡',label:'CPU 使用率',value:cpuP==null?'—':cpuP+'%',sub:STATIC.cpu_count+' 核',
     bar:cpuP,color:barColor(cpuP||0)},
    {ic:'💾',label:'内存',value:mem.percent==null?'—':mem.percent+'%',
     sub:fmtBytes(mem.available)+' 可用 / '+fmtBytes(mem.total),
     bar:mem.percent,color:barColor(mem.percent||0)},
    {ic:'📀',label:'磁盘',value:disk.percent==null?'—':disk.percent+'%',
     sub:fmtBytes(disk.free)+' 可用 / '+fmtBytes(disk.total),
     bar:disk.percent,color:barColor(disk.percent||0)},
    {ic:'🕐',label:'采集时间',value:d.timestamp,sub:'刷新即更新',bar:null},
  ];
  document.getElementById('dyn').innerHTML=cards.map(c=>`
    <div class="card">
      <div class="ic">${c.ic}</div>
      <div class="label">${c.label}</div>
      <div class="value">${c.value}</div>
      <div class="sub">${c.sub}</div>
      ${c.bar!=null?`<div class="bar"><i style="width:${Math.min(100,c.bar)}%;background:${c.color}"></i></div>`:''}
    </div>`).join('');
}

/* ── 应用列表 ── */
function renderApps(apps){
  const render=(list,tag,boxId,nId)=>{
    document.getElementById(nId).textContent=list.length;
    document.getElementById(boxId).innerHTML=list.length?list.map(a=>
      `<div class="app-item" title="${esc(a.changelog||a.name)}"><span class="ai">${a.icon||'📦'}</span>
       <span class="an">${esc(a.name)}<span class="tag ${tag}">${tag==='sys'?'系统':'用户'}</span></span>
       <span class="av">v${esc(a.version||'?')}</span></div>`
    ).join(''):'<div style="opacity:.4;font-size:12px;padding:8px">无</div>';
  };
  render(apps.system,'sys','sysApps','sysN');
  render(apps.user,'usr','usrApps','usrN');
}

/* ── Launcher 系统更新 UI ── */
let UPD=null;
function renderLauncherUpdate(d){
  UPD=d||null;
  const grid=document.getElementById('updGrid');
  const status=document.getElementById('updStatus');
  const btn=document.getElementById('btnUpd');
  const local=STATIC.launcher_version;
  const remote=d?.remote||'—';
  const releasedR=d?.released_remote||'—';
  const upgradable=!!(d&&d.upgradable);
  const err=d?.error;

  grid.innerHTML=`
    <div class="upd-cell">
      <div class="lb">当前版本</div>
      <div class="vl">v${esc(local)}</div>
      <div class="sub">${esc(STATIC.launcher_released||'发布时间未知')}</div>
    </div>
    <div class="upd-cell ${upgradable?'badge-new':''}">
      <div class="lb">最新版本</div>
      <div class="vl">${err?'—':('v'+esc(remote))} ${upgradable?'✨':''}</div>
      <div class="sub">${esc(releasedR)}</div>
    </div>
    <div class="upd-cell">
      <div class="lb">状态</div>
      <div class="vl" style="font-size:15px">${
        err?'⚠️ 连不上仓库':
        upgradable?'🔴 发现新版本':
        (d&&d.remote?'✅ 已是最新':'ℹ️ 无远端信息')
      }</div>
      <div class="sub">${err?esc(err):(upgradable?'建议尽快备份后更新':'无需操作')}</div>
    </div>`;

  document.getElementById('updClList').innerHTML=
    d?.changelog_remote?clUL(d.changelog_remote):
    `<li style="opacity:.4">${err?'（等待仓库连接后加载远端 Changelog）':'远端暂无更新说明'}</li>`;

  btn.disabled=!upgradable;
  btn.className='btn '+(upgradable?'btn-primary':'btn-muted');
  btn.textContent=upgradable?'⬆️ 立即更新':'已是最新版本';
  status.className='status-line '+(err?'warn':(upgradable?'warn':'ok'));
  status.innerHTML=err?
    `⚠️ 仓库连接失败：${esc(err)}<br><small>请检查 config.json repo.url / 证书配置，或网络是否可达</small>`
    :(upgradable
      ?`🔴 检测到新版本 v${esc(remote)}。<br><small>点击「立即更新」将下载、校验、备份并覆盖文件，更新完成后请手动重启 Launcher。</small>`
      :`✅ 当前 v${esc(local)} 已是最新版本`);
}

async function checkLauncher(){
  const st=document.getElementById('updStatus');
  st.className='status-line info';st.textContent='🔍 正在连接 Launcher 检查更新…';
  const d=await fetch(LAUNCHER_URL+'/api/launcher/version').then(r=>r.json()).catch(e=>({error:e.message}));
  renderLauncherUpdate(d);
}

async function doUpdate(){
  if(!confirm('确认立即更新 Launcher？\n\n• 将自动备份当前文件为 .bak\n• 版本号/Changelog 更新后实时生效\n• launcher 代码逻辑需重启进程才能生效'))return;
  setBusy('更新中：下载 + 校验 + 备份 + 覆盖…');
  try{
    const r=await fetch(LAUNCHER_URL+'/api/launcher/update');
    const d=await r.json();
    clearBusy();
    const st=document.getElementById('updStatus');
    if(d.ok){
      st.className='status-line ok';
      st.innerHTML='✅ '+esc(d.msg||'更新成功')+
        (d.restart?'<br><b style="color:#ffd54f">建议关闭并重新打开 Launcher 以载入新代码逻辑</b>':'');
      // 更新后重新检查版本，刷新显示（版本号已通过 reload_config 实时刷新）
      setTimeout(()=>checkLauncher(),600);
    }else{
      st.className='status-line warn';
      st.textContent='❌ '+esc(d.msg||'更新失败');
      alert('更新失败：'+d.msg);
    }
  }catch(e){clearBusy();alert('请求失败：'+e.message);}
}

/* ── 主入口 ── */
async function load(){
  try{
    const r=await fetch('/api/info');
    const d=await r.json();
    renderDyn(d.dynamic);
    renderApps(d.apps);
  }catch(e){console.error(e);}
}
renderStatic();
load();
checkLauncher();
setInterval(load,3000);
</script></body></html>"""


def render_page():
    """注入 STATIC_INFO 与 LAUNCHER_URL。"""
    static_js = json.dumps(STATIC_INFO, ensure_ascii=False)
    launcher_url_js = json.dumps(LAUNCHER_URL, ensure_ascii=False)
    out = HTML.replace("__STATIC_JSON__", static_js, 1)
    out = out.replace("__LAUNCHER_URL_JSON__", launcher_url_js, 1)
    return out


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/info":
            # 👇 新增：动态读取最新配置，确保更新后无需重启也能显示新版本
            current_config = load_config()
            dynamic_static = {
                "launcher_version": current_config.get("launcher", {}).get("version", "0.0.1"),
                "launcher_released": current_config.get("launcher", {}).get("released", ""),
                "launcher_changelog": current_config.get("launcher", {}).get("changelog", ""),
                "python_version": sys.version.split()[0],
                "os": f"{platform.system()} {platform.release()}",
                "os_machine": platform.machine(),
                "hostname": socket.gethostname(),
                "cpu_count": os.cpu_count() or 1,
                "processor": platform.processor() or "未知",
            }
            
            data = {
                "static": dynamic_static,  # 👈 使用动态获取的数据
                "dynamic": collect_dynamic(),
                "apps": scan_installed_apps(),
            }
            b = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json;charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                self.wfile.write(b)
            except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
                pass  # 👈 优雅忽略客户端提前断开连接的报错
            return
        if u.path == "/api/launcher-version":
            # 兼容保留：直接代理到 Launcher
            self.send_response(200)
            self.send_header("Content-Type", "application/json;charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(proxy_launcher_api("/api/launcher/version"),
                                        ensure_ascii=False).encode("utf-8"))
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html;charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(render_page().encode("utf-8"))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"sysinfo → http://127.0.0.1:{PORT}  (Launcher v{LAUNCHER_VERSION})")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
