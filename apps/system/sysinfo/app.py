"""sysinfo —— 系统信息（系统应用）
- 端口从 config.json 读取，默认 8103
- 显示：CPU 使用率、内存使用率、Python/OS 版本、已安装应用、磁盘占用
- 跨平台：Windows 用 ctypes + wmic，Linux 读 /proc，macOS 用 vm_stat/sysctl
"""
import json
import os
import platform
import shutil
import socket
import sys
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

BASE = Path(__file__).parent.parent.parent.parent
CONFIG_JSON = BASE / "config.json"


def load_config():
    if CONFIG_JSON.exists():
        return json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
    return {}


CONFIG = load_config()
PORT = CONFIG.get("ports", {}).get("sysinfo", 8103)
LAUNCHER_VERSION = "1.0.0"


# ── 跨平台硬件信息采集 ───────────────────────────────────
def _win_cpu_sample():
    """Windows: 用 GetSystemTimes 采样 CPU 空闲率，反推使用率"""
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
    """Windows: GlobalMemoryStatusEx 拿内存"""
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
    """Linux: 读 /proc/stat 两次采样"""
    try:
        def read():
            with open("/proc/stat") as f:
                return list(map(int, f.readline().split()[1:]))
        a = read()
        time.sleep(0.3)
        b = read()
        total = sum(b) - sum(a)
        idle = b[3] - a[3]
        return round((1 - idle / total) * 100, 1) if total > 0 else 0.0
    except Exception:
        return None


def _linux_mem():
    """Linux: 读 /proc/meminfo"""
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
    """返回 CPU 使用率（百分比），失败返回 None"""
    s = platform.system()
    if s == "Windows":
        return _win_cpu_sample()
    if s == "Linux":
        return _linux_cpu_sample()
    # macOS 暂不支持，留给以后扩展
    return None


def get_mem():
    """返回 {'percent', 'total', 'available'}，失败返回 None"""
    s = platform.system()
    if s == "Windows":
        return _win_mem()
    if s == "Linux":
        return _linux_mem()
    return None


def fmt_bytes(n):
    """字节数 → 人类可读"""
    if n is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def collect_static():
    """静态信息（一次采集即可）"""
    return {
        "launcher_version": LAUNCHER_VERSION,
        "python_version": sys.version.split()[0],
        "os": f"{platform.system()} {platform.release()}",
        "os_machine": platform.machine(),
        "hostname": socket.gethostname(),
        "cpu_count": os.cpu_count() or 1,
        "processor": platform.processor() or "未知",
    }


def collect_dynamic():
    """动态信息（每次刷新重新采集）"""
    mem = get_mem()
    cpu = get_cpu_sample()
    # 磁盘占用（项目目录）
    try:
        usage = shutil.disk_usage(str(BASE))
        disk = {
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "percent": round(usage.used / usage.total * 100, 1) if usage.total else 0,
        }
    except Exception:
        disk = None
    return {
        "cpu_percent": cpu,
        "mem": mem,
        "disk": disk,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def scan_installed_apps():
    """扫描已安装应用列表（system + user）"""
    apps_dir = BASE / "apps"
    result = {"system": [], "user": []}
    for kind, key in (("system", "system"), ("user", "user")):
        d = apps_dir / kind
        if not d.exists():
            continue
        for sub in sorted(d.iterdir()):
            if not sub.is_dir():
                continue
            j = sub / "app.json"
            if not j.exists():
                continue
            try:
                m = json.loads(j.read_text(encoding="utf-8"))
                result[key].append({
                    "id": m.get("id", sub.name),
                    "name": m.get("name", sub.name),
                    "version": m.get("version", "?"),
                    "icon": m.get("icon", ""),
                    "port": m.get("port"),
                })
            except Exception:
                pass
    return result


STATIC_INFO = collect_static()

HTML = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>📊 系统信息</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,"PingFang SC",sans-serif;
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
.row .v{font-weight:500;font-variant-numeric:tabular-nums;text-align:right;max-width:60%;
word-break:break-all}
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
</style></head><body>
<h2>📊 系统信息 <button class="refresh" onclick="load()">⟳ 刷新</button></h2>

<div class="cards" id="dyn"></div>

<div class="section">
  <h3>📋 版本与系统</h3>
  <div id="static"></div>
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
function fmtBytes(n){
  if(n==null)return '—';
  const u=['B','KB','MB','GB','TB'];let i=0;
  while(Math.abs(n)>=1024&&i<u.length-1){n/=1024;i++;}
  return n.toFixed(1)+' '+u[i];
}
function barColor(p){return p<50?'#2ecc71':p<80?'#f39c12':'#e74c3c';}
function renderStatic(){
  const rows=[
    ['Launcher 版本',STATIC.launcher_version],
    ['Python 版本',STATIC.python_version],
    ['操作系统',STATIC.os+' ('+STATIC.os_machine+')'],
    ['主机名',STATIC.hostname],
    ['CPU 核心',STATIC.cpu_count+' 核'],
    ['处理器',STATIC.processor],
  ];
  document.getElementById('static').innerHTML=rows.map(r=>
    `<div class="row"><span class="k">${r[0]}</span><span class="v">${r[1]}</span></div>`
  ).join('');
}
function renderDyn(d){
  const cpuP=d.cpu_percent;
  const mem=d.mem||{},disk=d.disk||{};
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
function renderApps(apps){
  const render=(list,tag,boxId,nId)=>{
    document.getElementById(nId).textContent=list.length;
    document.getElementById(boxId).innerHTML=list.length?list.map(a=>
      `<div class="app-item"><span class="ai">${a.icon}</span>
       <span class="an">${a.name}<span class="tag ${tag}">${tag==='sys'?'系统':'用户'}</span></span>
       <span class="av">v${a.version}</span></div>`
    ).join(''):'<div style="opacity:.4;font-size:12px;padding:8px">无</div>';
  };
  render(apps.system,'sys','sysApps','sysN');
  render(apps.user,'usr','usrApps','usrN');
}
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
setInterval(load,3000);
</script></body></html>"""


def render_page():
    """把 STATIC_INFO 注入到页面"""
    static_js = json.dumps(STATIC_INFO, ensure_ascii=False)
    return HTML.replace("__STATIC_JSON__", static_js, 1)


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
        self.send_response(200)
        self.send_header("Content-Type", "text/html;charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(render_page().encode("utf-8"))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"sysinfo → http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
