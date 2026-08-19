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

LAUNCHER_VERSION = CONFIG.get("launcher", {}).get("version", "0.0.1")
LAUNCHER_RELEASED = CONFIG.get("launcher", {}).get("released", "")
LAUNCHER_CHANGELOG = CONFIG.get("launcher", {}).get("changelog", "")


# ── 跨平台硬件信息采集 ───────────────────────────────────
def _win_cpu_sample():
    try:
        import ctypes
        class FILETIME(ctypes.Structure):
            _fields_ = [("low", ctypes.c_uint), ("high", ctypes.c_uint)]
        def ft_to_int(ft): return (ft.high << 32) | ft.low
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
                ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(m)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return {"percent": m.dwMemoryLoad, "total": m.ullTotalPhys, "available": m.ullAvailPhys}
    except Exception:
        return None

def _linux_cpu_sample():
    try:
        def read():
            with open("/proc/stat") as f: return list(map(int, f.readline().split()[1:]))
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
        return {"percent": round((1 - avail / total) * 100, 1) if total else 0, "total": total, "available": avail}
    except Exception:
        return None

def get_cpu_sample():
    s = platform.system()
    if s == "Windows": return _win_cpu_sample()
    if s == "Linux": return _linux_cpu_sample()
    return None

def get_mem():
    s = platform.system()
    if s == "Windows": return _win_mem()
    if s == "Linux": return _linux_mem()
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
    try:
        with urllib.request.urlopen(LAUNCHER_URL + path, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}

STATIC_INFO = collect_static()

# ── 全新旗舰级毛玻璃 UI 模板 ──
HTML = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>📊 系统信息</title>
<style>
:root {
    --glass-bg: rgba(255, 255, 255, 0.05);
    --glass-bg-hover: rgba(255, 255, 255, 0.09);
    --glass-border: rgba(255, 255, 255, 0.08);
    --glass-border-hover: rgba(255, 255, 255, 0.18);
    --text-primary: #f8fafc;
    --text-secondary: #94a3b8;
    --accent: #818cf8;
    --accent-glow: rgba(129, 140, 248, 0.3);
    --success: #34d399;
    --warning: #fbbf24;
    --danger: #f87171;
}
* { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
body {
    font-family: system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
    -webkit-font-smoothing: antialiased;
    color: var(--text-primary);
    background-color: #0b1120;
    background-image: 
        radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.15) 0px, transparent 50%),
        radial-gradient(at 100% 0%, rgba(168, 85, 247, 0.15) 0px, transparent 50%),
        radial-gradient(at 100% 100%, rgba(236, 72, 153, 0.1) 0px, transparent 50%);
    background-attachment: fixed;
    min-height: 100vh;
    padding: 24px;
}
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }

header { display:flex; align-items:center; justify-content:space-between; margin-bottom:24px; padding:0 4px; }
header h1 { font-size:20px; font-weight:600; display:flex; align-items:center; gap:10px; letter-spacing:-0.5px; }
.btn-refresh {
    background: var(--glass-bg); border: 1px solid var(--glass-border); color: var(--text-primary);
    border-radius: 10px; padding: 8px 16px; font-size: 13px; font-weight: 500; cursor: pointer;
    display: flex; align-items: center; gap: 6px; transition: all 0.2s ease;
}
.btn-refresh:hover { background: var(--glass-bg-hover); border-color: var(--glass-border-hover); transform: translateY(-1px); }
.btn-refresh:active { transform: scale(0.96); }

/* 核心指标区 */
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }
.metric-card {
    background: var(--glass-bg); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
    border: 1px solid var(--glass-border); border-radius: 16px; padding: 20px;
    transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); position: relative; overflow: hidden;
}
.metric-card::before {
    content: ''; position: absolute; top: 0; left: -100%; width: 50%; height: 100%;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent);
    transform: skewX(-25deg); transition: left 0.5s;
}
.metric-card:hover::before { left: 150%; }
.metric-card:hover { background: var(--glass-bg-hover); border-color: var(--glass-border-hover); transform: translateY(-4px); }
.m-header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.m-icon { font-size: 24px; }
.m-label { font-size: 12px; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 1px; font-weight: 600; }
.m-value { font-size: 28px; font-weight: 700; font-variant-numeric: tabular-nums; margin-bottom: 4px; }
.m-sub { font-size: 12px; color: var(--text-secondary); margin-bottom: 12px; }
.progress-bg { height: 6px; background: rgba(255,255,255,0.08); border-radius: 3px; overflow: hidden; }
.progress-fill { height: 100%; border-radius: 3px; transition: width 0.6s cubic-bezier(0.34, 1.56, 0.64, 1), background 0.3s; }

/* 布局网格 */
.grid-layout { display: grid; grid-template-columns: 1fr; gap: 20px; }
@media (min-width: 900px) { .grid-layout { grid-template-columns: 1.2fr 1fr; } }

/* 通用区块 */
.section {
    background: var(--glass-bg); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
    border: 1px solid var(--glass-border); border-radius: 18px; padding: 20px;
}
.section-title {
    font-size: 14px; font-weight: 600; color: var(--text-secondary); margin-bottom: 16px;
    display: flex; align-items: center; gap: 8px; text-transform: uppercase; letter-spacing: 0.5px;
}
.section-title .badge {
    background: rgba(255,255,255,0.1); padding: 2px 8px; border-radius: 6px; font-size: 11px; color: var(--text-primary);
}

/* 信息行 */
.info-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 10px 0; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 13px;
}
.info-row:last-child { border-bottom: none; }
.info-row .k { color: var(--text-secondary); }
.info-row .v { font-weight: 500; font-variant-numeric: tabular-nums; text-align: right; max-width: 65%; word-break: break-all; }

/* 应用列表 */
.app-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; margin-bottom: 20px; }
.app-grid:last-child { margin-bottom: 0; }
.app-item {
    display: flex; align-items: center; gap: 10px; background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.05); border-radius: 12px; padding: 10px 12px;
    transition: all 0.2s ease; cursor: default;
}
.app-item:hover { background: rgba(255,255,255,0.07); border-color: var(--glass-border-hover); }
.app-icon { font-size: 20px; flex-shrink: 0; }
.app-info { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.app-name { font-size: 13px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: flex; align-items: center; gap: 6px; }
.app-ver { font-size: 11px; color: var(--text-secondary); margin-top: 2px; }
.tag { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 600; flex-shrink: 0; }
.tag.sys { background: rgba(52, 211, 153, 0.15); color: var(--success); }
.tag.usr { background: rgba(129, 140, 248, 0.15); color: var(--accent); }

/* 更新区块 */
.upd-compare { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px; }
.upd-cell {
    background: rgba(0,0,0,0.2); border: 1px solid var(--glass-border); border-radius: 12px; padding: 14px; text-align: center;
}
.upd-cell.new-ver { border-color: rgba(248, 113, 113, 0.3); background: rgba(248, 113, 113, 0.05); }
.upd-cell .lb { font-size: 11px; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 6px; }
.upd-cell .vl { font-size: 20px; font-weight: 700; font-variant-numeric: tabular-nums; }
.upd-cell .sub { font-size: 11px; color: var(--text-secondary); margin-top: 4px; }

.cl-box {
    background: rgba(0,0,0,0.25); border: 1px solid var(--glass-border); border-radius: 12px;
    padding: 14px; max-height: 180px; overflow-y: auto; font-size: 12.5px; line-height: 1.7; color: var(--text-secondary);
}
.cl-box ul { padding-left: 18px; }
.cl-box .hd { font-size: 11px; color: var(--text-secondary); margin-bottom: 8px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }

.upd-actions { display: flex; gap: 10px; margin-top: 16px; }
.btn {
    flex: 1; padding: 10px 16px; border: 0; border-radius: 10px; cursor: pointer;
    font-size: 13px; font-weight: 600; transition: all 0.2s ease; display: flex; align-items: center; justify-content: center; gap: 6px;
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none !important; }
.btn-primary { background: var(--accent); color: #fff; box-shadow: 0 4px 12px var(--accent-glow); }
.btn-primary:hover:not(:disabled) { background: #6366f1; transform: translateY(-2px); box-shadow: 0 6px 16px var(--accent-glow); }
.btn-muted { background: rgba(255,255,255,0.08); color: var(--text-primary); border: 1px solid var(--glass-border); }
.btn-muted:hover:not(:disabled) { background: var(--glass-bg-hover); border-color: var(--glass-border-hover); }

.status-line {
    padding: 12px 14px; border-radius: 10px; font-size: 12.5px; line-height: 1.6; margin-top: 14px;
    border: 1px solid transparent;
}
.status-line.ok { background: rgba(52, 211, 153, 0.1); color: var(--success); border-color: rgba(52, 211, 153, 0.2); }
.status-line.warn { background: rgba(248, 113, 113, 0.1); color: var(--danger); border-color: rgba(248, 113, 113, 0.2); }
.status-line.info { background: rgba(129, 140, 248, 0.1); color: var(--accent); border-color: rgba(129, 140, 248, 0.2); }

/* Toast */
.__toast {
    position:fixed; left:50%; top:24px; transform:translateX(-50%); z-index:9999;
    padding:10px 20px; background: rgba(20, 25, 45, 0.9); backdrop-filter: blur(12px);
    border: 1px solid var(--glass-border); color: var(--text-primary); border-radius:12px;
    font-size:13px; font-weight:500; box-shadow: 0 12px 24px rgba(0,0,0,0.4);
    animation: fadePop 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
@keyframes fadePop { from { transform:translateX(-50%) translateY(-20px); opacity:0; } }
</style></head><body>

<header>
  <h1>📊 系统信息</h1>
  <button class="btn-refresh" onclick="load(true)">⟳ 刷新数据</button>
</header>

<div class="metrics" id="dynMetrics"></div>

<div class="grid-layout">
  <!-- 左侧：系统信息 + 应用 -->
  <div style="display:flex; flex-direction:column; gap:20px;">
    <div class="section">
      <div class="section-title">🖥️ 版本与系统环境</div>
      <div id="staticInfo"></div>
    </div>
    
    <div class="section">
      <div class="section-title">🛡️ 系统应用 <span class="badge" id="sysN">0</span></div>
      <div class="app-grid" id="sysApps"></div>
      
      <div class="section-title" style="margin-top:24px;">📦 用户应用 <span class="badge" id="usrN">0</span></div>
      <div class="app-grid" id="usrApps"></div>
    </div>
  </div>

  <!-- 右侧：Launcher 更新 -->
  <div class="section" style="height:fit-content; position:sticky; top:24px;">
    <div class="section-title">🚀 Launcher 系统更新</div>
    <div class="upd-compare" id="updGrid"></div>
    <div class="cl-box">
      <div class="hd">📋 远端更新说明</div>
      <ul id="updClList" style="margin:0;"></ul>
    </div>
    <div id="updStatus"></div>
    <div class="upd-actions">
      <button class="btn btn-muted" onclick="checkLauncher()">🔍 检查更新</button>
      <button id="btnUpd" class="btn btn-primary" onclick="doUpdate()" disabled>⬆️ 立即更新</button>
    </div>
  </div>
</div>

<script>
const STATIC = __STATIC_JSON__;
const LAUNCHER_URL = __LAUNCHER_URL_JSON__;

function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function clUL(text){
  if(!text) return '<li style="opacity:.4">暂无更新说明</li>';
  return String(text).split('\n').map(s=>s.trim().replace(/^[-•*]\s*/,'')).filter(Boolean)
    .map(s=>'<li>'+esc(s)+'</li>').join('') || '<li style="opacity:.4">暂无更新说明</li>';
}
function fmtBytes(n){
  if(n==null) return '—';
  const u=['B','KB','MB','GB','TB']; let i=0;
  while(Math.abs(n)>=1024 && i<u.length-1){ n/=1024; i++; }
  return n.toFixed(1)+' '+u[i];
}
function barColor(p){ return p<50 ? 'var(--success)' : p<80 ? 'var(--warning)' : 'var(--danger)'; }

function showToast(msg){
  const d=document.createElement('div'); d.className='__toast'; d.textContent=msg;
  document.body.appendChild(d);
  setTimeout(()=>{ d.style.transition='opacity 0.2s'; d.style.opacity='0'; setTimeout(()=>d.remove(), 200); }, 2500);
}

function renderStatic(){
  const rows = [
    ['Launcher 版本', STATIC.launcher_version + (STATIC.launcher_released ? ' · ' + STATIC.launcher_released : '')],
    ['Python 版本', STATIC.python_version],
    ['操作系统', STATIC.os + ' (' + STATIC.os_machine + ')'],
    ['主机名', STATIC.hostname],
    ['CPU 核心', STATIC.cpu_count + ' 核'],
    ['处理器', STATIC.processor],
  ];
  document.getElementById('staticInfo').innerHTML = rows.map(r => 
    `<div class="info-row"><span class="k">${r[0]}</span><span class="v">${esc(r[1])}</span></div>`
  ).join('');
}

function renderDyn(d){
  const cpuP = d.cpu_percent; 
  const mem = d.mem || {}; 
  const disk = d.disk || {};
  
  const cards = [
    { ic:'⚡', label:'CPU 使用率', value: cpuP==null ? '—' : cpuP+'%', sub: STATIC.cpu_count+' 核心', bar: cpuP },
    { ic:'💾', label:'内存占用', value: mem.percent==null ? '—' : mem.percent+'%', sub: fmtBytes(mem.available)+' 可用 / '+fmtBytes(mem.total), bar: mem.percent },
    { ic:'📀', label:'磁盘空间', value: disk.percent==null ? '—' : disk.percent+'%', sub: fmtBytes(disk.free)+' 可用 / '+fmtBytes(disk.total), bar: disk.percent },
  ];
  
  document.getElementById('dynMetrics').innerHTML = cards.map(c => `
    <div class="metric-card">
      <div class="m-header">
        <span class="m-icon">${c.ic}</span>
        <span class="m-label">${c.label}</span>
      </div>
      <div class="m-value">${c.value}</div>
      <div class="m-sub">${c.sub}</div>
      ${c.bar != null ? `<div class="progress-bg"><div class="progress-fill" style="width:${Math.min(100, c.bar)}%; background:${barColor(c.bar)}"></div></div>` : ''}
    </div>
  `).join('');
}

function renderApps(apps){
  const renderList = (list, tagClass, tagName, boxId, nId) => {
    document.getElementById(nId).textContent = list.length;
    document.getElementById(boxId).innerHTML = list.length ? list.map(a => `
      <div class="app-item" title="${esc(a.changelog || a.name)}">
        <span class="app-icon">${a.icon || '📦'}</span>
        <div class="app-info">
          <span class="app-name">${esc(a.name)} <span class="tag ${tagClass}">${tagName}</span></span>
          <span class="app-ver">v${esc(a.version || '?')}</span>
        </div>
      </div>
    `).join('') : '<div style="opacity:.4; font-size:12px; padding:8px 0;">暂无应用</div>';
  };
  renderList(apps.system, 'sys', '系统', 'sysApps', 'sysN');
  renderList(apps.user, 'usr', '用户', 'usrApps', 'usrN');
}

let UPD = null;
function renderLauncherUpdate(d){
  UPD = d || null;
  const local = STATIC.launcher_version;
  const remote = d?.remote || '—';
  const releasedR = d?.released_remote || '—';
  const upgradable = !!(d && d.upgradable);
  const err = d?.error;

  document.getElementById('updGrid').innerHTML = `
    <div class="upd-cell">
      <div class="lb">当前版本</div>
      <div class="vl">v${esc(local)}</div>
      <div class="sub">${esc(STATIC.launcher_released || '发布时间未知')}</div>
    </div>
    <div class="upd-cell ${upgradable ? 'new-ver' : ''}">
      <div class="lb">最新版本</div>
      <div class="vl">${err ? '—' : ('v' + esc(remote))} ${upgradable ? '✨' : ''}</div>
      <div class="sub">${esc(releasedR)}</div>
    </div>
  `;

  document.getElementById('updClList').innerHTML = d?.changelog_remote 
    ? clUL(d.changelog_remote) 
    : `<li style="opacity:.4">${err ? '（等待仓库连接后加载）' : '远端暂无更新说明'}</li>`;

  const btn = document.getElementById('btnUpd');
  btn.disabled = !upgradable;
  btn.className = 'btn ' + (upgradable ? 'btn-primary' : 'btn-muted');
  btn.textContent = upgradable ? '⬆️ 立即更新' : '已是最新版本';

  const status = document.getElementById('updStatus');
  if (err) {
    status.className = 'status-line warn';
    status.innerHTML = `⚠️ 仓库连接失败：${esc(err)}<br><small>请检查 config.json 中的 repo.url 或网络配置</small>`;
  } else if (upgradable) {
    status.className = 'status-line warn';
    status.innerHTML = `🔴 检测到新版本 v${esc(remote)}。<br><small>点击「立即更新」将自动备份并覆盖文件，完成后建议重启 Launcher。</small>`;
  } else {
    status.className = 'status-line ok';
    status.innerHTML = `✅ 当前 v${esc(local)} 已是最新版本，无需操作。`;
  }
}

async function checkLauncher(){
  const st = document.getElementById('updStatus');
  st.className = 'status-line info';
  st.textContent = '🔍 正在连接 Launcher 检查更新…';
  
  try {
    const r = await fetch(LAUNCHER_URL + '/api/launcher/version');
    const d = await r.json();
    renderLauncherUpdate(d);
  } catch(e) {
    renderLauncherUpdate({ error: e.message });
  }
}

async function doUpdate(){
  if(!confirm('确认立即更新 Launcher？\n\n• 将自动备份当前文件为 .bak\n• 版本号/Changelog 更新后实时生效\n• 核心代码逻辑需手动重启 Launcher 进程才能完全生效')) return;
  
  const btn = document.getElementById('btnUpd');
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = '⏳ 更新中…';
  showToast('正在下载并校验更新…');
  
  try {
    const r = await fetch(LAUNCHER_URL + '/api/launcher/update');
    const d = await r.json();
    
    const st = document.getElementById('updStatus');
    if(d.ok){
      st.className = 'status-line ok';
      st.innerHTML = '✅ ' + esc(d.msg || '更新成功') + 
        (d.restart ? '<br><b style="color:var(--warning); margin-top:6px; display:inline-block;">⚠️ 建议关闭并重新打开 Launcher 以载入新代码逻辑</b>' : '');
      showToast('更新成功！');
      setTimeout(() => checkLauncher(), 800);
    } else {
      st.className = 'status-line warn';
      st.textContent = '❌ ' + esc(d.msg || '更新失败');
      showToast('更新失败：' + (d.msg || '未知错误'));
      btn.disabled = false;
      btn.textContent = originalText;
    }
  } catch(e) {
    showToast('请求失败：' + e.message);
    btn.disabled = false;
    btn.textContent = originalText;
  }
}

async function load(showToastMsg = false){
  try {
    const r = await fetch('/api/info');
    const d = await r.json();
    renderDyn(d.dynamic);
    renderApps(d.apps);
    if(showToastMsg) showToast('数据已刷新');
  } catch(e) {
    console.error(e);
    if(showToastMsg) showToast('刷新失败，请检查服务状态');
  }
}

// 初始化
renderStatic();
load();
checkLauncher();
setInterval(load, 5000); // 5秒轮询一次动态数据，降低频率减轻负担
</script></body></html>"""


def render_page():
    static_js = json.dumps(STATIC_INFO, ensure_ascii=False)
    launcher_url_js = json.dumps(LAUNCHER_URL, ensure_ascii=False)
    out = HTML.replace("__STATIC_JSON__", static_js, 1)
    out = out.replace("__LAUNCHER_URL_JSON__", launcher_url_js, 1)
    return out


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/info":
            data = {
                "static": STATIC_INFO,
                "dynamic": collect_dynamic(),
                "apps": scan_installed_apps(),
            }
            b = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json;charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b)
            return
        if u.path == "/api/launcher-version":
            self.send_response(200)
            self.send_header("Content-Type", "application/json;charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(proxy_launcher_api("/api/launcher/version"), ensure_ascii=False).encode("utf-8"))
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