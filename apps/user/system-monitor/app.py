"""system-monitor —— 系统监控（专业版）
- 端口 8130
- 实时采集：CPU/内存/磁盘/网络 详细信息
- TOP 10 进程列表
- 参考 Windows 任务管理器设计
"""
import json
import os
import platform
import subprocess
import sys
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

PORT = 8130
IS_WIN = platform.system() == "Windows"

# ── 优先用 psutil ──────────────────────────────────────────────
try:
    import psutil
    HAVE_PSUTIL = True
except ImportError:
    HAVE_PSUTIL = False

# ── CPU 信息 ───────────────────────────────────────────────
def get_cpu_info():
    """获取CPU详细信息"""
    info = {
        "name": platform.processor() or "Unknown",
        "cores": os.cpu_count() or 1,
        "logical_cores": psutil.cpu_count(logical=True) if HAVE_PSUTIL else os.cpu_count(),
        "usage": 0.0,
        "freq_current": 0.0,
        "freq_base": 0.0,
        "processes": 0,
        "threads": 0,
        "context_switches": 0,
        "uptime": 0,
    }
    
    if HAVE_PSUTIL:
        # CPU频率
        freq = psutil.cpu_freq()
        if freq:
            info["freq_current"] = round(freq.current, 2)
            info["freq_base"] = round(freq.max, 2)
        
        # CPU使用率
        info["usage"] = psutil.cpu_percent(interval=None)
        
        # 进程和线程数
        info["processes"] = len(psutil.pids())
        
        # 系统启动时间
        try:
            boot = psutil.boot_time()
            info["uptime"] = int(time.time() - boot)
        except:
            pass
        
        # 上下文切换
        try:
            ctx = psutil.cpu_stats()
            info["context_switches"] = ctx.ctx_switches
        except:
            pass
    elif IS_WIN:
        # Windows 原生方式
        try:
            import ctypes
            # 获取CPU使用率
            info["usage"] = _win_cpu_usage()
            
            # 获取进程数
            info["processes"] = subprocess.check_output(
                "wmic process get ProcessId | find /c \"\"", 
                shell=True, text=True, encoding='gbk'
            ).strip()
            info["processes"] = int(info["processes"]) if info["processes"].isdigit() else 0
        except:
            pass
    else:
        # Linux
        try:
            with open("/proc/stat") as f:
                line = f.readline()
            parts = line.split()[1:]
            vals = [int(x) for x in parts[:4]]
            idle = vals[3]
            total = sum(vals)
            if hasattr(get_cpu_info, '_prev'):
                idle_delta = idle - get_cpu_info._prev_idle
                total_delta = total - get_cpu_info._prev_total
                if total_delta > 0:
                    info["usage"] = round((1 - idle_delta / total_delta) * 100, 1)
            get_cpu_info._prev_idle = idle
            get_cpu_info._prev_total = total
            
            # 进程数
            info["processes"] = len(os.listdir("/proc")) // 2  # 近似值
        except:
            pass
    
    return info

def _win_cpu_usage():
    """Windows CPU使用率"""
    try:
        import ctypes
        class FILETIME(ctypes.Structure):
            _fields_ = [("low", ctypes.c_uint), ("high", ctypes.c_uint)]
        
        idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
        ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
        
        idle_t = (idle.high << 32) | idle.low
        total_t = ((kernel.high << 32) | kernel.low) + ((user.high << 32) | user.low)
        
        if hasattr(_win_cpu_usage, '_prev'):
            idle_delta = idle_t - _win_cpu_usage._prev_idle
            total_delta = total_t - _win_cpu_usage._prev_total
            if total_delta > 0:
                return round((1 - idle_delta / total_delta) * 100, 1)
        
        _win_cpu_usage._prev_idle = idle_t
        _win_cpu_usage._prev_total = total_t
        return 0.0
    except:
        return 0.0

# ── 内存信息 ───────────────────────────────────────────────
def get_memory_info():
    """获取内存详细信息"""
    info = {
        "total": 0,
        "available": 0,
        "used": 0,
        "percent": 0.0,
        "committed_total": 0,
        "committed_used": 0,
        "cached": 0,
        "buffers": 0,
        "page_file_total": 0,
        "page_file_used": 0,
    }
    
    if HAVE_PSUTIL:
        mem = psutil.virtual_memory()
        info["total"] = mem.total
        info["available"] = mem.available
        info["used"] = mem.used
        info["percent"] = mem.percent
        
        # 提交内存
        try:
            committed = psutil.virtual_memory()  # Windows特有
            info["committed_total"] = getattr(committed, 'total', 0)
        except:
            pass
        
        # 缓存和缓冲区
        info["cached"] = getattr(mem, 'cached', 0)
        info["buffers"] = getattr(mem, 'buffers', 0)
        
        # 交换分区
        try:
            swap = psutil.swap_memory()
            info["page_file_total"] = swap.total
            info["page_file_used"] = swap.used
        except:
            pass
    elif IS_WIN:
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
                ]
            
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            
            info["total"] = stat.ullTotalPhys
            info["available"] = stat.ullAvailPhys
            info["used"] = stat.ullTotalPhys - stat.ullAvailPhys
            info["percent"] = stat.dwMemoryLoad
            info["page_file_total"] = stat.ullTotalPageFile
            info["page_file_used"] = stat.ullTotalPageFile - stat.ullAvailPageFile
        except:
            pass
    else:
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        key = parts[0].strip()
                        val = int(parts[1].strip().split()[0]) * 1024
                        if key == "MemTotal":
                            info["total"] = val
                        elif key == "MemAvailable":
                            info["available"] = val
                        elif key == "Buffers":
                            info["buffers"] = val
                        elif key == "Cached":
                            info["cached"] = val
            
            info["used"] = info["total"] - info["available"]
            info["percent"] = round((info["used"] / info["total"]) * 100, 1) if info["total"] else 0
        except:
            pass
    
    return info

# ── 磁盘信息 ───────────────────────────────────────────────
def get_disk_info():
    """获取磁盘详细信息"""
    disks = []
    
    if HAVE_PSUTIL:
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                disk_info = {
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": usage.percent,
                    "read_bytes": 0,
                    "write_bytes": 0,
                    "read_speed": 0,
                    "write_speed": 0,
                }
                
                # IO统计
                try:
                    io = psutil.disk_io_counters(perdisk=True)
                    if part.device in io:
                        disk_io = io[part.device]
                        disk_info["read_bytes"] = disk_io.read_bytes
                        disk_info["write_bytes"] = disk_io.write_bytes
                        
                        # 计算速度（需要保存上次值）
                        if not hasattr(get_disk_info, '_prev_disk_io'):
                            get_disk_info._prev_disk_io = {}
                        
                        if part.device in get_disk_info._prev_disk_io:
                            prev = get_disk_info._prev_disk_io[part.device]
                            dt = time.time() - getattr(get_disk_info, '_last_disk_time', time.time())
                            if dt > 0:
                                disk_info["read_speed"] = max(0, (disk_io.read_bytes - prev["read_bytes"]) / dt)
                                disk_info["write_speed"] = max(0, (disk_io.write_bytes - prev["write_bytes"]) / dt)
                        
                        get_disk_info._prev_disk_io[part.device] = {
                            "read_bytes": disk_io.read_bytes,
                            "write_bytes": disk_io.write_bytes,
                        }
                        get_disk_info._last_disk_time = time.time()
                except:
                    pass
                
                disks.append(disk_info)
            except:
                continue
    elif IS_WIN:
        try:
            import string
            drives = []
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1:
                    drives.append(f"{letter}:\\")
                bitmask >>= 1
            
            for drive in drives:
                try:
                    free_bytes = ctypes.c_ulonglong(0)
                    total_bytes = ctypes.c_ulonglong(0)
                    ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                        drive, ctypes.byref(ctypes.c_ulonglong(0)),
                        ctypes.byref(total_bytes), ctypes.byref(free_bytes)
                    )
                    
                    disks.append({
                        "device": drive,
                        "mountpoint": drive,
                        "total": total_bytes.value,
                        "used": total_bytes.value - free_bytes.value,
                        "free": free_bytes.value,
                        "percent": round(((total_bytes.value - free_bytes.value) / total_bytes.value) * 100, 1) if total_bytes.value else 0,
                    })
                except:
                    continue
        except:
            pass
    else:
        # Linux
        try:
            with open("/proc/mounts") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 3 and parts[2] not in ["proc", "sysfs", "devtmpfs"]:
                        try:
                            usage = shutil.disk_usage(parts[1])
                            disks.append({
                                "device": parts[0],
                                "mountpoint": parts[1],
                                "fstype": parts[2],
                                "total": usage.total,
                                "used": usage.used,
                                "free": usage.free,
                                "percent": round((usage.used / usage.total) * 100, 1) if usage.total else 0,
                            })
                        except:
                            continue
        except:
            pass
    
    return disks

# ── 网络信息 ───────────────────────────────────────────────
def get_network_info():
    """获取网络详细信息"""
    interfaces = []
    
    if HAVE_PSUTIL:
        io = psutil.net_io_counters(pernic=True)
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        
        for nic, io_stats in io.items():
            nic_info = {
                "name": nic,
                "bytes_sent": io_stats.bytes_sent,
                "bytes_recv": io_stats.bytes_recv,
                "packets_sent": io_stats.packets_sent,
                "packets_recv": io_stats.packets_recv,
                "errin": io_stats.errin,
                "errout": io_stats.errout,
                "speed": 0,
                "is_up": False,
                "addresses": [],
            }
            
            # 获取IP地址
            if nic in addrs:
                for addr in addrs[nic]:
                    if addr.family == psutil.AF_LINK:
                        nic_info["mac"] = addr.address
                    elif addr.family == 2:  # AF_INET
                        nic_info["addresses"].append({
                            "type": "IPv4",
                            "address": addr.address,
                            "netmask": addr.netmask,
                        })
                    elif addr.family == 23:  # AF_INET6
                        nic_info["addresses"].append({
                            "type": "IPv6",
                            "address": addr.address,
                        })
            
            # 获取状态和速度
            if nic in stats:
                nic_info["is_up"] = stats[nic].isup
                nic_info["speed"] = stats[nic].speed if stats[nic].speed else 0
            
            # 计算速度
            if not hasattr(get_network_info, '_prev_net'):
                get_network_info._prev_net = {}
            
            if nic in get_network_info._prev_net:
                prev = get_network_info._prev_net[nic]
                dt = time.time() - getattr(get_network_info, '_last_net_time', time.time())
                if dt > 0:
                    nic_info["send_speed"] = max(0, (io_stats.bytes_sent - prev["bytes_sent"]) / dt)
                    nic_info["recv_speed"] = max(0, (io_stats.bytes_recv - prev["bytes_recv"]) / dt)
            else:
                nic_info["send_speed"] = 0
                nic_info["recv_speed"] = 0
            
            get_network_info._prev_net[nic] = {
                "bytes_sent": io_stats.bytes_sent,
                "bytes_recv": io_stats.bytes_recv,
            }
            get_network_info._last_net_time = time.time()
            
            interfaces.append(nic_info)
    elif IS_WIN:
        # Windows 简化版
        try:
            out = subprocess.check_output(
                "wmic nic where PhysicalAdapter=True get Name,Speed | more",
                shell=True, text=True, encoding='gbk', errors='ignore'
            )
            # 解析输出...
        except:
            pass
    else:
        # Linux
        try:
            with open("/proc/net/dev") as f:
                for line in f:
                    if ":" in line:
                        parts = line.split(":")
                        nic = parts[0].strip()
                        if nic not in ["lo"]:
                            stats = parts[1].split()
                            interfaces.append({
                                "name": nic,
                                "bytes_recv": int(stats[0]),
                                "packets_recv": int(stats[1]),
                                "bytes_sent": int(stats[8]),
                                "packets_sent": int(stats[9]),
                            })
        except:
            pass
    
    return interfaces

# ── 进程信息 ───────────────────────────────────────────────
def get_top_processes(limit=10):
    """获取TOP进程"""
    procs = []
    
    if HAVE_PSUTIL:
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "memory_info"]):
            try:
                mem = p.info["memory_info"]
                procs.append({
                    "pid": p.info["pid"],
                    "name": p.info["name"] or "Unknown",
                    "cpu": p.info["cpu_percent"] or 0.0,
                    "memory_percent": p.info["memory_percent"] or 0.0,
                    "memory_bytes": mem.rss if mem else 0,
                    "threads": p.num_threads() if hasattr(p, 'num_threads') else 0,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        
        procs.sort(key=lambda x: x["cpu"], reverse=True)
        return procs[:limit]
    elif IS_WIN:
        try:
            out = subprocess.check_output(
                "wmic process get ProcessId,Name,WorkingSetSize /format:csv",
                text=True, shell=True, encoding='gbk', errors='ignore'
            )
            rows = [r for r in out.splitlines() if r.strip() and "," in r][1:]
            for r in rows[:limit]:
                parts = r.split(",")
                if len(parts) >= 4:
                    try:
                        procs.append({
                            "pid": int(parts[3]),
                            "name": parts[1],
                            "cpu": 0.0,
                            "memory_percent": 0.0,
                            "memory_bytes": int(parts[2]),
                        })
                    except:
                        continue
        except:
            pass
    
    return procs

# ── HTTP Handler ───────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a, **k):
        pass

    def _json(self, obj):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        path = urlparse(self.path).path
        
        if path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML.encode("utf-8"))
        elif path == "/api/system":
            data = {
                "cpu": get_cpu_info(),
                "memory": get_memory_info(),
                "disks": get_disk_info(),
                "network": get_network_info(),
                "timestamp": int(time.time()),
                "has_psutil": HAVE_PSUTIL,
            }
            self._json(data)
        elif path == "/api/processes":
            self._json({"processes": get_top_processes(10)})
        else:
            self.send_response(404)
            self.end_headers()

# ── HTML 前端 ─────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>📊 系统监控专业版</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{
    font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
    background:#f0f2f5;color:#1a1a1a;
    min-height:100vh;padding:20px;
}
.container{max-width:1400px;margin:0 auto}
h1{font-size:24px;margin-bottom:20px;color:#1a1a1a}

.tabs{display:flex;gap:8px;margin-bottom:20px;border-bottom:2px solid #e0e0e0}
.tab{
    padding:10px 20px;background:none;border:none;
    cursor:pointer;font-size:14px;font-weight:500;
    color:#666;border-bottom:2px solid transparent;margin-bottom:-2px;
    transition:all 0.2s;
}
.tab:hover{color:#0078d4}
.tab.active{color:#0078d4;border-bottom-color:#0078d4}

.content{display:none}
.content.active{display:block}

.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}

.card{
    background:#fff;border-radius:8px;padding:20px;
    box-shadow:0 2px 8px rgba(0,0,0,0.08);
}
.card h2{font-size:16px;margin-bottom:16px;color:#1a1a1a;border-bottom:1px solid #e0e0e0;padding-bottom:8px}

.metric{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #f0f0f0}
.metric:last-child{border-bottom:none}
.metric-label{color:#666;font-size:13px}
.metric-value{font-weight:600;font-family:Consolas,monospace;font-size:13px}
.metric-value.highlight{color:#0078d4}
.metric-value.warning{color:#d83b01}

.progress{
    height:8px;background:#e0e0e0;border-radius:4px;
    overflow:hidden;margin-top:8px;
}
.progress-bar{
    height:100%;background:#0078d4;transition:width 0.3s;
}

table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:10px;color:#666;font-weight:500;border-bottom:2px solid #e0e0e0}
td{padding:10px;border-bottom:1px solid #f0f0f0;font-family:Consolas,monospace}
tr:hover{background:#f8f9fa}

.chart{height:200px;background:#f8f9fa;border-radius:4px;margin-top:16px;position:relative}
</style>
</head>
<body>
<div class="container">
    <h1> 系统监控专业版</h1>
    
    <div class="tabs">
        <button class="tab active" onclick="switchTab('overview')">概览</button>
        <button class="tab" onclick="switchTab('cpu')">CPU</button>
        <button class="tab" onclick="switchTab('memory')">内存</button>
        <button class="tab" onclick="switchTab('disk')">磁盘</button>
        <button class="tab" onclick="switchTab('network')">网络</button>
        <button class="tab" onclick="switchTab('processes')">进程</button>
    </div>
    
    <div id="overview" class="content active"></div>
    <div id="cpu" class="content"></div>
    <div id="memory" class="content"></div>
    <div id="disk" class="content"></div>
    <div id="network" class="content"></div>
    <div id="processes" class="content"></div>
</div>

<script>
let sysData = {};

function switchTab(tab) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.content').forEach(c => c.classList.remove('active'));
    event.target.classList.add('active');
    document.getElementById(tab).classList.add('active');
    render(tab);
}

function fmtBytes(b) {
    if (!b) return '0 B';
    const u = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(b) / Math.log(1024));
    return (b / Math.pow(1024, i)).toFixed(1) + ' ' + u[i];
}

function fmtTime(sec) {
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    return `${h.toString().padStart(2,'0')}:${m.toString().padStart(2,'0')}:${s.toString().padStart(2,'0')}`;
}

async function fetchSystem() {
    try {
        const r = await fetch('/api/system');
        sysData = await r.json();
        render(document.querySelector('.tab.active').textContent.toLowerCase());
    } catch (e) {
        console.error(e);
    }
}

async function fetchProcesses() {
    try {
        const r = await fetch('/api/processes');
        const d = await r.json();
        renderProcesses(d.processes);
    } catch (e) {
        console.error(e);
    }
}

function render(tab) {
    if (tab === 'overview') renderOverview();
    else if (tab === 'cpu') renderCPU();
    else if (tab === 'memory') renderMemory();
    else if (tab === 'disk') renderDisk();
    else if (tab === 'network') renderNetwork();
}

function renderOverview() {
    const d = sysData;
    document.getElementById('overview').innerHTML = `
        <div class="grid">
            <div class="card">
                <h2>⚡ CPU</h2>
                <div class="metric">
                    <span class="metric-label">使用率</span>
                    <span class="metric-value ${(d.cpu?.usage||0) > 80 ? 'warning' : 'highlight'}">${(d.cpu?.usage||0).toFixed(1)}%</span>
                </div>
                <div class="progress"><div class="progress-bar" style="width:${d.cpu?.usage||0}%"></div></div>
                <div class="metric" style="margin-top:12px">
                    <span class="metric-label">速度</span>
                    <span class="metric-value">${(d.cpu?.freq_current||0).toFixed(2)} GHz</span>
                </div>
                <div class="metric">
                    <span class="metric-label">核心数</span>
                    <span class="metric-value">${d.cpu?.cores||0} 核 / ${d.cpu?.logical_cores||0} 线程</span>
                </div>
            </div>
            
            <div class="card">
                <h2>💾 内存</h2>
                <div class="metric">
                    <span class="metric-label">使用率</span>
                    <span class="metric-value ${(d.memory?.percent||0) > 80 ? 'warning' : 'highlight'}">${(d.memory?.percent||0).toFixed(1)}%</span>
                </div>
                <div class="progress"><div class="progress-bar" style="width:${d.memory?.percent||0}%"></div></div>
                <div class="metric" style="margin-top:12px">
                    <span class="metric-label">已用 / 总计</span>
                    <span class="metric-value">${fmtBytes(d.memory?.used||0)} / ${fmtBytes(d.memory?.total||0)}</span>
                </div>
            </div>
            
            <div class="card">
                <h2>💿 磁盘</h2>
                ${(d.disks||[]).slice(0,2).map(disk => `
                    <div class="metric">
                        <span class="metric-label">${disk.mountpoint}</span>
                        <span class="metric-value">${disk.percent?.toFixed(1)||0}%</span>
                    </div>
                `).join('')}
            </div>
            
            <div class="card">
                <h2>🌐 网络</h2>
                ${(d.network||[]).slice(0,2).map(nic => `
                    <div class="metric">
                        <span class="metric-label">${nic.name}</span>
                        <span class="metric-value">↓ ${fmtBytes(nic.recv_speed||0)}/s ↑ ${fmtBytes(nic.send_speed||0)}/s</span>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
}

function renderCPU() {
    const d = sysData.cpu || {};
    document.getElementById('cpu').innerHTML = `
        <div class="card">
            <h2> CPU 详细信息</h2>
            <div class="metric"><span class="metric-label">名称</span><span class="metric-value">${d.name||'Unknown'}</span></div>
            <div class="metric"><span class="metric-label">使用率</span><span class="metric-value highlight">${d.usage?.toFixed(1)||0}%</span></div>
            <div class="metric"><span class="metric-label">当前速度</span><span class="metric-value">${(d.freq_current||0).toFixed(2)} GHz</span></div>
            <div class="metric"><span class="metric-label">基准速度</span><span class="metric-value">${(d.freq_base||0).toFixed(2)} GHz</span></div>
            <div class="metric"><span class="metric-label">物理核心</span><span class="metric-value">${d.cores||0}</span></div>
            <div class="metric"><span class="metric-label">逻辑处理器</span><span class="metric-value">${d.logical_cores||0}</span></div>
            <div class="metric"><span class="metric-label">进程数</span><span class="metric-value">${d.processes||0}</span></div>
            <div class="metric"><span class="metric-label">系统运行时间</span><span class="metric-value">${fmtTime(d.uptime||0)}</span></div>
        </div>
    `;
}

function renderMemory() {
    const d = sysData.memory || {};
    document.getElementById('memory').innerHTML = `
        <div class="card">
            <h2>💾 内存详细信息</h2>
            <div class="metric"><span class="metric-label">总计</span><span class="metric-value">${fmtBytes(d.total)}</span></div>
            <div class="metric"><span class="metric-label">已使用</span><span class="metric-value highlight">${fmtBytes(d.used)}</span></div>
            <div class="metric"><span class="metric-label">可用</span><span class="metric-value">${fmtBytes(d.available)}</span></div>
            <div class="metric"><span class="metric-label">使用率</span><span class="metric-value ${(d.percent||0) > 80 ? 'warning' : ''}">${d.percent?.toFixed(1)||0}%</span></div>
            <div class="metric"><span class="metric-label">缓存</span><span class="metric-value">${fmtBytes(d.cached||0)}</span></div>
            <div class="metric"><span class="metric-label">缓冲区</span><span class="metric-value">${fmtBytes(d.buffers||0)}</span></div>
            <div class="metric"><span class="metric-label">分页文件总计</span><span class="metric-value">${fmtBytes(d.page_file_total||0)}</span></div>
            <div class="metric"><span class="metric-label">分页文件已用</span><span class="metric-value">${fmtBytes(d.page_file_used||0)}</span></div>
        </div>
    `;
}

function renderDisk() {
    const disks = sysData.disks || [];
    let html = '<div class="grid">';
    disks.forEach(disk => {
        html += `
            <div class="card">
                <h2>💿 ${disk.mountpoint || disk.device}</h2>
                <div class="metric"><span class="metric-label">设备</span><span class="metric-value">${disk.device||'N/A'}</span></div>
                <div class="metric"><span class="metric-label">文件系统</span><span class="metric-value">${disk.fstype||'N/A'}</span></div>
                <div class="metric"><span class="metric-label">总计</span><span class="metric-value">${fmtBytes(disk.total)}</span></div>
                <div class="metric"><span class="metric-label">已使用</span><span class="metric-value highlight">${fmtBytes(disk.used)}</span></div>
                <div class="metric"><span class="metric-label">可用</span><span class="metric-value">${fmtBytes(disk.free)}</span></div>
                <div class="metric"><span class="metric-label">使用率</span><span class="metric-value ${(disk.percent||0) > 80 ? 'warning' : ''}">${disk.percent?.toFixed(1)||0}%</span></div>
                <div class="metric"><span class="metric-label">读取速度</span><span class="metric-value">${fmtBytes(disk.read_speed||0)}/s</span></div>
                <div class="metric"><span class="metric-label">写入速度</span><span class="metric-value">${fmtBytes(disk.write_speed||0)}/s</span></div>
            </div>
        `;
    });
    html += '</div>';
    document.getElementById('disk').innerHTML = html;
}

function renderNetwork() {
    const interfaces = sysData.network || [];
    let html = '<div class="grid">';
    interfaces.forEach(nic => {
        html += `
            <div class="card">
                <h2>🌐 ${nic.name}</h2>
                <div class="metric"><span class="metric-label">状态</span><span class="metric-value">${nic.is_up ? '🟢 已连接' : '🔴 断开'}</span></div>
                <div class="metric"><span class="metric-label">发送速度</span><span class="metric-value">${fmtBytes(nic.send_speed||0)}/s</span></div>
                <div class="metric"><span class="metric-label">接收速度</span><span class="metric-value">${fmtBytes(nic.recv_speed||0)}/s</span></div>
                <div class="metric"><span class="metric-label">总发送</span><span class="metric-value">${fmtBytes(nic.bytes_sent||0)}</span></div>
                <div class="metric"><span class="metric-label">总接收</span><span class="metric-value">${fmtBytes(nic.bytes_recv||0)}</span></div>
                <div class="metric"><span class="metric-label">速度</span><span class="metric-value">${nic.speed ? fmtBytes(nic.speed) + '/s' : 'N/A'}</span></div>
                ${(nic.addresses||[]).map(addr => `
                    <div class="metric"><span class="metric-label">${addr.type}</span><span class="metric-value">${addr.address}</span></div>
                `).join('')}
            </div>
        `;
    });
    html += '</div>';
    document.getElementById('network').innerHTML = html;
}

function renderProcesses(procs) {
    document.getElementById('processes').innerHTML = `
        <div class="card">
            <h2>🚀 TOP 进程 (按CPU排序)</h2>
            <table>
                <thead>
                    <tr><th>PID</th><th>名称</th><th>CPU %</th><th>内存</th><th>内存 %</th><th>线程</th></tr>
                </thead>
                <tbody>
                    ${(procs||[]).map(p => `
                        <tr>
                            <td>${p.pid}</td>
                            <td>${p.name}</td>
                            <td>${p.cpu?.toFixed(1)||0}</td>
                            <td>${fmtBytes(p.memory_bytes||0)}</td>
                            <td>${p.memory_percent?.toFixed(1)||0}%</td>
                            <td>${p.threads||0}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        </div>
    `;
}

// 初始化
fetchSystem();
fetchProcesses();
setInterval(fetchSystem, 2000);
setInterval(fetchProcesses, 3000);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    print(f"[System Monitor] 启动于 http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()