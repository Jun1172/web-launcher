"""system-monitor —— 系统监控 demo
- 端口 8130
- 实时采集：CPU 使用率、内存使用率、网络流量
- TOP 10 进程列表
- 跨平台：Windows 用 ctypes/psutil(若装了)/wmic，Linux 读 /proc
- 前端：Canvas 折线图 + setInterval 轮询 /api/stats
"""
import json
import os
import platform
import sys
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

PORT = 8130
IS_WIN = platform.system() == "Windows"

# ── 优先用 psutil，没装就走原生方案 ──────────────────────────
try:
    import psutil
    HAVE_PSUTIL = True
except ImportError:
    HAVE_PSUTIL = False

# ── CPU 采样 ───────────────────────────────────────────────
_prev_cpu = None  # (idle_t, total_t)


def _win_cpu_sample():
    """Windows: GetSystemTimes 采样 CPU 空闲率，反推使用率"""
    try:
        import ctypes

        class FILETIME(ctypes.Structure):
            _fields_ = [("low", ctypes.c_uint), ("high", ctypes.c_uint)]

        idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
        ctypes.windll.kernel32.GetSystemTimeAsFileTime(ctypes.byref(idle))
        # GetSystemTimes：返回 idle/kernel/user 总时间
        ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
        idle_t = idle.high << 32 | idle.low
        kernel_t = kernel.high << 32 | kernel.low
        user_t = user.high << 32 | user.low
        total_t = kernel_t + user_t
        return idle_t, total_t
    except Exception:
        return None, None


def sample_cpu():
    """返回当前 CPU 使用率（0~100）"""
    global _prev_cpu
    if HAVE_PSUTIL:
        return psutil.cpu_percent(interval=None)
    if IS_WIN:
        idle_t, total_t = _win_cpu_sample()
        if idle_t is None or _prev_cpu is None or _prev_cpu[1] == total_t:
            _prev_cpu = (idle_t, total_t)
            return 0.0
        idle_delta = idle_t - _prev_cpu[0]
        total_delta = total_t - _prev_cpu[1]
        _prev_cpu = (idle_t, total_t)
        if total_delta <= 0:
            return 0.0
        return max(0.0, min(100.0, (1 - idle_delta / total_delta) * 100))
    # Linux: /proc/stat 第一行是总 CPU
    try:
        with open("/proc/stat") as f:
            line = f.readline()
        parts = line.split()[1:]
        vals = [int(x) for x in parts[:4]]  # user,nice,system,idle
        idle_t = vals[3]
        total_t = sum(vals)
        if _prev_cpu is None or _prev_cpu[1] == total_t:
            _prev_cpu = (idle_t, total_t)
            return 0.0
        idle_delta = idle_t - _prev_cpu[0]
        total_delta = total_t - _prev_cpu[1]
        _prev_cpu = (idle_t, total_t)
        if total_delta <= 0:
            return 0.0
        return max(0.0, min(100.0, (1 - idle_delta / total_delta) * 100))
    except Exception:
        return 0.0


# ── 内存 ───────────────────────────────────────────────────
def sample_mem():
    """返回 (used_pct, total_bytes, used_bytes)"""
    if HAVE_PSUTIL:
        m = psutil.virtual_memory()
        return m.percent, m.total, m.used
    if IS_WIN:
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_uint),
                    ("dwMemoryLoad", ctypes.c_uint),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            total = stat.ullTotalPhys
            used = total - stat.ullAvailPhys
            return stat.dwMemoryLoad, total, used
        except Exception:
            return 0.0, 0, 0
    # Linux: /proc/meminfo
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.strip().split()[0]) * 1024
        total = info.get("MemTotal", 0)
        avail = info.get("MemAvailable", info.get("MemFree", 0))
        used = total - avail
        return (used / total * 100 if total else 0.0), total, used
    except Exception:
        return 0.0, 0, 0


# ── 网络 ───────────────────────────────────────────────────
_prev_net = (0, 0, 0)  # (ts, bytes_in, bytes_out)


def sample_net():
    """返回 (in_rate_bytes_per_sec, out_rate_bytes_per_sec)"""
    global _prev_net
    if HAVE_PSUTIL:
        cur = psutil.net_io_counters()
        bytes_in, bytes_out = cur.bytes_recv, cur.bytes_sent
    elif IS_WIN:
        try:
            import ctypes

            class MIB_IFROW(ctypes.Structure):
                _fields_ = [
                    ("wszName", ctypes.c_wchar * 256),
                    ("dwIndex", ctypes.c_uint),
                    ("dwType", ctypes.c_uint),
                    ("dwMtu", ctypes.c_uint),
                    ("dwSpeed", ctypes.c_uint),
                    ("dwPhysAddrLen", ctypes.c_uint),
                    ("bPhysAddr", ctypes.c_ubyte * 8),
                    ("dwAdminStatus", ctypes.c_uint),
                    ("dwOperStatus", ctypes.c_uint),
                    ("dwLastChange", ctypes.c_uint),
                    ("dwInOctets", ctypes.c_uint),
                    ("dwInUcastPkts", ctypes.c_uint),
                    ("dwInNUcastPkts", ctypes.c_uint),
                    ("dwInDiscards", ctypes.c_uint),
                    ("dwInErrors", ctypes.c_uint),
                    ("dwInUnknownProtos", ctypes.c_uint),
                    ("dwOutOctets", ctypes.c_uint),
                    ("dwOutUcastPkts", ctypes.c_uint),
                    ("dwOutNUcastPkts", ctypes.c_uint),
                    ("dwOutDiscards", ctypes.c_uint),
                    ("dwOutErrors", ctypes.c_uint),
                    ("dwOutQLen", ctypes.c_uint),
                    ("dwDescrLen", ctypes.c_uint),
                    ("bDescr", ctypes.c_ubyte * 256),
                ]
            size = ctypes.c_uint(0)
            ctypes.windll.iphlpapi.GetIfTable(None, ctypes.byref(size), False)
            buf = (ctypes.c_ubyte * size.value)()
            n_entries = ctypes.c_uint(0)
            ctypes.windll.iphlpapi.GetIfTable(buf, ctypes.byref(n_entries), False)
            bytes_in = bytes_out = 0
            row_size = ctypes.sizeof(MIB_IFROW)
            for i in range(n_entries.value):
                row = MIB_IFROW.from_buffer(buf, i * row_size)
                # 跳过 loopback（type=24）和 down 的接口
                if row.dwOperStatus != 1 or row.dwType == 24:
                    continue
                bytes_in += row.dwInOctets
                bytes_out += row.dwOutOctets
        except Exception:
            bytes_in, bytes_out = 0, 0
    else:
        try:
            with open("/proc/net/dev") as f:
                next(f)  # 跳过两行表头
                bytes_in = bytes_out = 0
                for line in f:
                    parts = line.split(":")
                    if len(parts) != 2:
                        continue
                    name = parts[0].strip()
                    if name in ("lo",):
                        continue
                    data = parts[1].split()
                    bytes_in += int(data[0])
                    bytes_out += int(data[8])
        except Exception:
            bytes_in, bytes_out = 0, 0
    now = time.time()
    if _prev_net[0] == 0:
        _prev_net = (now, bytes_in, bytes_out)
        return 0.0, 0.0
    dt = now - _prev_net[0]
    if dt <= 0:
        return 0.0, 0.0
    in_rate = (bytes_in - _prev_net[1]) / dt
    out_rate = (bytes_out - _prev_net[2]) / dt
    _prev_net = (now, bytes_in, bytes_out)
    return max(0.0, in_rate), max(0.0, out_rate)


# ── TOP 进程 ───────────────────────────────────────────────
def top_procs(limit=10):
    """返回 [{pid, name, cpu, mem}] 列表"""
    if HAVE_PSUTIL:
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                procs.append({
                    "pid": p.info["pid"],
                    "name": p.info["name"],
                    "cpu": p.info["cpu_percent"] or 0.0,
                    "mem": p.info["memory_percent"] or 0.0,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        procs.sort(key=lambda x: x["cpu"], reverse=True)
        return procs[:limit]
    if IS_WIN:
        # 用 wmic 命令，按 WorkingSet 排序
        import subprocess
        try:
            out = subprocess.check_output(
                ["wmic", "process", "get",
                 "ProcessId,Name,WorkingSetSize",
                 "/format:csv"],
                text=True, stderr=subprocess.DEVNULL, timeout=2)
            rows = [r for r in out.splitlines() if r.strip() and "," in r][1:]
            procs = []
            for r in rows:
                parts = r.split(",")
                if len(parts) < 3:
                    continue
                try:
                    node, name, ws, pid = parts
                    procs.append({
                        "pid": int(pid),
                        "name": name,
                        "cpu": 0.0,  # wmic 不直接给 cpu，留 0
                        "mem": float(ws),
                    })
                except (ValueError, IndexError):
                    continue
            procs.sort(key=lambda x: x["mem"], reverse=True)
            return procs[:limit]
        except Exception:
            return []
    # Linux: ps 命令
    try:
        import subprocess
        out = subprocess.check_output(
            ["ps", "-eo", "pid,comm,%cpu,%mem", "--sort=-pcpu"],
            text=True, stderr=subprocess.DEVNULL, timeout=2)
        rows = out.splitlines()[1:]
        procs = []
        for r in rows[:limit]:
            parts = r.split(None, 3)
            if len(parts) < 4:
                continue
            try:
                procs.append({
                    "pid": int(parts[0]),
                    "name": parts[1],
                    "cpu": float(parts[2]),
                    "mem": float(parts[3]),
                })
            except ValueError:
                continue
        return procs
    except Exception:
        return []


# ── 启动后台 CPU 采样（让第一次拿数据也是有效差值）─────────
if not HAVE_PSUTIL:
    sample_cpu()
    sample_net()


# ── HTTP 服务 ─────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a, **k):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _html(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(HTML.encode("utf-8"))

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            self._html()
        elif u.path == "/api/stats":
            cpu = sample_cpu()
            mem_pct, mem_total, mem_used = sample_mem()
            in_rate, out_rate = sample_net()
            self._json({
                "ts": int(time.time()),
                "cpu": round(cpu, 1),
                "mem_pct": round(mem_pct, 1),
                "mem_total": mem_total,
                "mem_used": mem_used,
                "net_in": int(in_rate),
                "net_out": int(out_rate),
                "has_psutil": HAVE_PSUTIL,
            })
        elif u.path == "/api/top":
            self._json({"procs": top_procs(10)})
        else:
            self.send_response(404)
            self.end_headers()


HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>📈 系统监控</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
body{background:linear-gradient(160deg,#0e1229 0%,#1c2347 100%);color:#fff;min-height:100vh;padding:14px;font-size:14px}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;padding:0 4px}
.header h1{font-size:18px;font-weight:600}
.header .meta{font-size:12px;opacity:.6}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:14px}
.kpi{background:rgba(255,255,255,.07);border-radius:14px;padding:12px}
.kpi .label{font-size:11px;opacity:.6;margin-bottom:6px}
.kpi .val{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums}
.kpi .sub{font-size:11px;opacity:.5;margin-top:2px}
.kpi.cpu .val{color:#5b8cff}
.kpi.mem .val{color:#2ecc71}
.kpi.net .val{color:#f39c12}
.card{background:rgba(255,255,255,.06);border-radius:14px;padding:12px;margin-bottom:12px}
.card h2{font-size:13px;font-weight:600;margin-bottom:8px;display:flex;justify-content:space-between}
.card h2 .legend{display:flex;gap:10px;font-size:11px;font-weight:400;opacity:.7}
.card h2 .legend span{display:flex;align-items:center;gap:4px}
.card h2 .legend i{width:10px;height:10px;border-radius:3px;display:inline-block}
canvas{width:100%;height:120px;display:block}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid rgba(255,255,255,.06)}
th{opacity:.5;font-weight:500;font-size:11px}
td.num{font-variant-numeric:tabular-nums;text-align:right}
.tag{display:inline-block;padding:1px 6px;border-radius:6px;font-size:10px;background:rgba(91,140,255,.2);color:#5b8cff}
.warn{color:#e74c3c}
</style>
</head>
<body>
<div class="header">
  <h1>📈 系统监控</h1>
  <div class="meta" id="meta">采集中…</div>
</div>
<div class="kpis">
  <div class="kpi cpu"><div class="label">CPU</div><div class="val" id="kCpu">—</div><div class="sub" id="kCpuSub">使用率</div></div>
  <div class="kpi mem"><div class="label">内存</div><div class="val" id="kMem">—</div><div class="sub" id="kMemSub">使用率</div></div>
  <div class="kpi net"><div class="label">网络 ↓↑</div><div class="val" id="kNet">—</div><div class="sub" id="kNetSub">KB/s</div></div>
</div>
<div class="card">
  <h2>CPU / 内存 趋势 <span class="legend">
    <span><i style="background:#5b8cff"></i>CPU%</span>
    <span><i style="background:#2ecc71"></i>MEM%</span>
  </span></h2>
  <canvas id="chart"></canvas>
</div>
<div class="card">
  <h2>TOP 进程 <span class="legend"><span id="topMeta"></span></span></h2>
  <table>
    <thead><tr><th>PID</th><th>名称</th><th class="num">CPU%</th><th class="num">内存</th></tr></thead>
    <tbody id="topBody"></tbody>
  </table>
</div>
<script>
const $=id=>document.getElementById(id);
const fmtB=b=>{if(!b)return '0 B';const u=['B','KB','MB','GB','TB'];const i=Math.floor(Math.log(b)/Math.log(1024));return (b/Math.pow(1024,i)).toFixed(i?1:0)+' '+u[i];};
const fmtR=b=>{const k=b/1024;return k>1024?(k/1024).toFixed(1)+' MB/s':k.toFixed(1)+' KB/s';};

// 折线图
const cv=$('chart'),ctx=cv.getContext('2d');
const W=600,H=120,N=60;
const cpuHist=[],memHist=[];
function resize(){const r=cv.getBoundingClientRect();cv.width=r.width*devicePixelRatio;cv.height=H*devicePixelRatio;ctx.scale(devicePixelRatio,devicePixelRatio);}
addEventListener('resize',resize);resize();
function draw(){
  const w=cv.width/devicePixelRatio;
  ctx.clearRect(0,0,w,H);
  // 网格
  ctx.strokeStyle='rgba(255,255,255,.06)';ctx.lineWidth=1;
  for(let i=0;i<=4;i++){const y=i*H/4;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();}
  // 数据线
  function line(arr,color){
    if(arr.length<2)return;
    ctx.strokeStyle=color;ctx.lineWidth=2;ctx.beginPath();
    arr.forEach((v,i)=>{
      const x=i*w/(N-1);
      const y=H-(v/100)*H;
      i?ctx.lineTo(x,y):ctx.moveTo(x,y);
    });
    ctx.stroke();
  }
  line(cpuHist,'#5b8cff');
  line(memHist,'#2ecc71');
}
async function pull(){
  try{
    const r=await fetch('/api/stats');const d=await r.json();
    $('kCpu').textContent=d.cpu.toFixed(1)+'%';
    $('kMem').textContent=d.mem_pct.toFixed(1)+'%';
    $('kMemSub').textContent=fmtB(d.mem_used)+' / '+fmtB(d.mem_total);
    $('kNet').textContent=fmtR(d.net_in+ d.net_out);
    $('kNetSub').textContent='↓ '+fmtR(d.net_in)+' · ↑ '+fmtR(d.net_out);
    cpuHist.push(d.cpu);if(cpuHist.length>N)cpuHist.shift();
    memHist.push(d.mem_pct);if(memHist.length>N)memHist.shift();
    draw();
    const dt=new Date(d.ts*1000);
    $('meta').textContent='更新于 '+dt.toLocaleTimeString()+(d.has_psutil?' · psutil':' · 原生');
  }catch(e){$('meta').textContent='采样失败：'+e;}
}
async function topPull(){
  try{
    const r=await fetch('/api/top');const d=await r.json();
    $('topBody').innerHTML=(d.procs||[]).map(p=>{
      const memStr=p.mem>1024*1024*1024?(p.mem/1024/1024/1024).toFixed(1)+' GB'
        :p.mem>1024*1024?(p.mem/1024/1024).toFixed(0)+' MB'
        :fmtB(p.mem);
      return `<tr><td>${p.pid}</td><td>${p.name}</td><td class="num">${p.cpu.toFixed(1)}</td><td class="num">${memStr}</td></tr>`;
    }).join('');
    $('topMeta').textContent=d.procs?d.procs.length+' 条':'';
  }catch(e){$('topBody').innerHTML='<tr><td colspan=4>top 拉取失败：'+e+'</td></tr>';}
}
pull();topPull();
setInterval(pull,2000);
setInterval(topPull,3000);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    print(f"[system-monitor] listening on http://127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
