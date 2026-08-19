import json, os, sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

BASE = Path(__file__).parent.parent.parent
CONFIG_JSON = BASE / "config.json"

def load_config():
    if CONFIG_JSON.exists():
        try: return json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
        except: return {}
    return {}

CONFIG = load_config()
PORT = int(os.environ.get("LAUNCHER_APP_PORT", 0))

# ─ 极光毛玻璃风格 HTML ─
HTML = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>️ 秒表与日历</title>
<style>
:root {
    --glass-bg: rgba(255, 255, 255, 0.07);
    --glass-border: rgba(255, 255, 255, 0.12);
    --text-primary: #f8fafc;
    --text-secondary: #94a3b8;
    --accent: #818cf8;
    --success: #34d399;
    --danger: #f87171;
    --warning: #fbbf24;
}
* { margin:0; padding:0; box-sizing:border-box; }
body {
    font-family: system-ui, -apple-system, "PingFang SC", sans-serif;
    color: var(--text-primary);
    min-height: 100vh;
    background-color: #0b1120;
    background-image: 
        radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.25) 0px, transparent 50%),
        radial-gradient(at 100% 0%, rgba(168, 85, 247, 0.25) 0px, transparent 50%),
        radial-gradient(at 100% 100%, rgba(236, 72, 153, 0.2) 0px, transparent 50%),
        radial-gradient(at 0% 100%, rgba(34, 211, 238, 0.2) 0px, transparent 50%);
    background-size: 200% 200%;
    animation: aurora 25s ease infinite;
    display: flex; justify-content: center; align-items: center; padding: 24px;
}
@keyframes aurora {
    0% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } 100% { background-position: 0% 50%; }
}

.app-container {
    display: grid; grid-template-columns: 1fr 1fr; gap: 24px;
    width: 100%; max-width: 1000px;
}
@media (max-width: 768px) { .app-container { grid-template-columns: 1fr; } }

.card {
    background: var(--glass-bg);
    backdrop-filter: blur(24px); -webkit-backdrop-filter: blur(24px);
    border: 1px solid var(--glass-border);
    border-radius: 24px;
    padding: 32px;
    box-shadow: 0 20px 40px rgba(0,0,0,0.2), inset 0 1px 0 rgba(255,255,255,0.1);
    display: flex; flex-direction: column;
}

/* ── 秒表区域 ── */
.stopwatch-header { text-align: center; margin-bottom: 24px; }
.stopwatch-header h2 { font-size: 20px; font-weight: 600; margin-bottom: 4px; }
.stopwatch-header p { font-size: 12px; color: var(--text-secondary); }

.time-display {
    font-size: 72px; font-weight: 200; text-align: center;
    font-variant-numeric: tabular-nums; letter-spacing: -2px;
    background: linear-gradient(to bottom, #fff 0%, #cbd5e1 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    margin: 20px 0 32px;
    text-shadow: 0 4px 12px rgba(0,0,0,0.1);
}
.time-display .ms { font-size: 48px; opacity: 0.8; }

.controls { display: flex; justify-content: center; gap: 16px; margin-bottom: 24px; }
.btn {
    padding: 12px 28px; border: 1px solid var(--glass-border); border-radius: 14px;
    background: rgba(255,255,255,0.05); color: var(--text-primary);
    font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.2s;
    min-width: 100px;
}
.btn:hover { background: rgba(255,255,255,0.12); border-color: rgba(255,255,255,0.25); transform: translateY(-2px); }
.btn:active { transform: translateY(0); }
.btn-primary { background: var(--accent); border-color: var(--accent); color: #fff; box-shadow: 0 4px 12px rgba(129,140,248,0.3); }
.btn-primary:hover { background: #6366f1; }
.btn-danger { color: var(--danger); }

.laps-container {
    flex: 1; overflow-y: auto; max-height: 200px;
    border-top: 1px solid var(--glass-border); padding-top: 16px;
}
.laps-container::-webkit-scrollbar { width: 4px; }
.laps-container::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.2); border-radius: 2px; }
.lap-item {
    display: flex; justify-content: space-between; padding: 8px 12px;
    font-size: 13px; border-radius: 8px; margin-bottom: 4px;
    font-variant-numeric: tabular-nums;
}
.lap-item:nth-child(odd) { background: rgba(255,255,255,0.03); }
.lap-item .lap-name { color: var(--text-secondary); }
.lap-item .lap-time { font-weight: 500; }

/* ── 日历区域 ─ */
.calendar-header {
    display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;
}
.calendar-header h2 { font-size: 20px; font-weight: 600; }
.calendar-nav { display: flex; gap: 8px; }
.nav-btn {
    width: 32px; height: 32px; border-radius: 8px; border: 1px solid var(--glass-border);
    background: rgba(255,255,255,0.05); color: var(--text-primary);
    display: flex; align-items: center; justify-content: center; cursor: pointer; transition: 0.2s;
}
.nav-btn:hover { background: rgba(255,255,255,0.12); }

.weekdays {
    display: grid; grid-template-columns: repeat(7, 1fr); text-align: center;
    font-size: 12px; color: var(--text-secondary); margin-bottom: 12px; font-weight: 500;
}
.days-grid {
    display: grid; grid-template-columns: repeat(7, 1fr); gap: 6px; flex: 1;
}
.day-cell {
    aspect-ratio: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
    border-radius: 10px; font-size: 14px; position: relative; cursor: default; transition: 0.2s;
}
.day-cell:hover { background: rgba(255,255,255,0.05); }
.day-cell.other-month { opacity: 0.3; }
.day-cell.today { background: rgba(129, 140, 248, 0.2); border: 1px solid var(--accent); font-weight: 600; }
.day-cell.today .day-num { color: var(--accent); }

.holiday-tag {
    font-size: 9px; padding: 1px 4px; border-radius: 4px; margin-top: 2px; font-weight: 600;
}
.tag-holiday { background: rgba(248, 113, 113, 0.2); color: var(--danger); }
.tag-work { background: rgba(251, 191, 36, 0.2); color: var(--warning); }

.legend {
    display: flex; justify-content: center; gap: 16px; margin-top: 16px; font-size: 11px; color: var(--text-secondary);
}
.legend-item { display: flex; align-items: center; gap: 6px; }
.legend-dot { width: 8px; height: 8px; border-radius: 2px; }
</style></head><body>

<div class="app-container">
    <!-- 秒表卡片 -->
    <div class="card">
        <div class="stopwatch-header">
            <h2>⏱️ 精准秒表</h2>
            <p>精确到 0.01 秒 · 支持计次</p>
        </div>
        <div class="time-display">
            <span id="mainTime">00:00</span><span class="ms" id="msTime">.00</span>
        </div>
        <div class="controls">
            <button class="btn btn-primary" id="btnStart">开始</button>
            <button class="btn" id="btnLap" disabled>计次</button>
            <button class="btn btn-danger" id="btnReset" disabled>重置</button>
        </div>
        <div class="laps-container" id="lapsList"></div>
    </div>

    <!-- 日历卡片 -->
    <div class="card">
        <div class="calendar-header">
            <h2 id="calTitle">2026年 8月</h2>
            <div class="calendar-nav">
                <button class="nav-btn" id="prevMonth">‹</button>
                <button class="nav-btn" id="nextMonth">›</button>
            </div>
        </div>
        <div class="weekdays">
            <div>日</div><div>一</div><div>二</div><div>三</div><div>四</div><div>五</div><div>六</div>
        </div>
        <div class="days-grid" id="daysGrid"></div>
        <div class="legend">
            <div class="legend-item"><div class="legend-dot" style="background:var(--danger)"></div>节假日</div>
            <div class="legend-item"><div class="legend-dot" style="background:var(--warning)"></div>调休上班</div>
        </div>
    </div>
</div>

<script>
/* ═══════════════════════════════════════════
   1. 毫秒级秒表逻辑 (基于 Date.now 差值)
   ═══════════════════════════════════════════ */
const $ = id => document.getElementById(id);
let isRunning = false, startTime = 0, elapsedTime = 0, timerId = null, lapCount = 0;

function formatTime(ms) {
    const totalSec = Math.floor(ms / 1000);
    const m = Math.floor(totalSec / 60).toString().padStart(2, '0');
    const s = (totalSec % 60).toString().padStart(2, '0');
    const centisec = Math.floor((ms % 1000) / 10).toString().padStart(2, '0');
    return { main: `${m}:${s}`, ms: `.${centisec}` };
}

function updateDisplay() {
    const now = Date.now();
    const currentMs = elapsedTime + (isRunning ? now - startTime : 0);
    const t = formatTime(currentMs);
    $('mainTime').textContent = t.main;
    $('msTime').textContent = t.ms;
    if (isRunning) timerId = requestAnimationFrame(updateDisplay);
}

$('btnStart').onclick = () => {
    if (!isRunning) {
        isRunning = true; startTime = Date.now();
        $('btnStart').textContent = '暂停'; $('btnStart').classList.remove('btn-primary');
        $('btnLap').disabled = false; $('btnReset').disabled = false;
        updateDisplay();
    } else {
        isRunning = false; elapsedTime += Date.now() - startTime;
        $('btnStart').textContent = '继续'; $('btnStart').classList.add('btn-primary');
        $('btnLap').disabled = true; cancelAnimationFrame(timerId);
    }
};

$('btnReset').onclick = () => {
    isRunning = false; elapsedTime = 0; lapCount = 0;
    $('btnStart').textContent = '开始'; $('btnStart').classList.add('btn-primary');
    $('btnLap').disabled = true; $('btnReset').disabled = true;
    $('lapsList').innerHTML = '';
    cancelAnimationFrame(timerId);
    const t = formatTime(0); $('mainTime').textContent = t.main; $('msTime').textContent = t.ms;
};

$('btnLap').onclick = () => {
    if (!isRunning) return;
    lapCount++;
    const currentMs = elapsedTime + Date.now() - startTime;
    const t = formatTime(currentMs);
    const lapHtml = `<div class="lap-item"><span class="lap-name">计次 ${lapCount}</span><span class="lap-time">${t.main}${t.ms}</span></div>`;
    $('lapsList').insertAdjacentHTML('afterbegin', lapHtml);
};

/* ═══════════════════════════════════════════
   2. 日历与节假日逻辑 (内嵌 2024-2026 数据)
   ═══════════════════════════════════════════ */
// 简化版节假日数据：key 为 "YYYY-MM-DD"，value 为 {name, type} (holiday=休, work=班)
const HOLIDAYS = {
    // 2024
    "2024-01-01": {n:"元旦",t:"h"}, "2024-02-10": {n:"春节",t:"h"}, "2024-02-11": {n:"春节",t:"h"},
    "2024-02-12": {n:"春节",t:"h"}, "2024-02-13": {n:"春节",t:"h"}, "2024-02-14": {n:"春节",t:"h"},
    "2024-02-15": {n:"春节",t:"h"}, "2024-02-16": {n:"春节",t:"h"}, "2024-02-17": {n:"春节",t:"h"},
    "2024-04-04": {n:"清明",t:"h"}, "2024-04-05": {n:"清明",t:"h"}, "2024-04-06": {n:"清明",t:"h"},
    "2024-05-01": {n:"劳动",t:"h"}, "2024-05-02": {n:"劳动",t:"h"}, "2024-05-03": {n:"劳动",t:"h"},
    "2024-05-04": {n:"劳动",t:"h"}, "2024-05-05": {n:"劳动",t:"h"},
    "2024-06-08": {n:"端午",t:"h"}, "2024-06-09": {n:"端午",t:"h"}, "2024-06-10": {n:"端午",t:"h"},
    "2024-09-15": {n:"中秋",t:"h"}, "2024-09-16": {n:"中秋",t:"h"}, "2024-09-17": {n:"中秋",t:"h"},
    "2024-10-01": {n:"国庆",t:"h"}, "2024-10-02": {n:"国庆",t:"h"}, "2024-10-03": {n:"国庆",t:"h"},
    "2024-10-04": {n:"国庆",t:"h"}, "2024-10-05": {n:"国庆",t:"h"}, "2024-10-06": {n:"国庆",t:"h"},
    "2024-10-07": {n:"国庆",t:"h"},
    // 2025
    "2025-01-01": {n:"元旦",t:"h"}, "2025-01-28": {n:"春节",t:"h"}, "2025-01-29": {n:"春节",t:"h"},
    "2025-01-30": {n:"春节",t:"h"}, "2025-01-31": {n:"春节",t:"h"}, "2025-02-01": {n:"春节",t:"h"},
    "2025-02-02": {n:"春节",t:"h"}, "2025-02-03": {n:"春节",t:"h"}, "2025-02-04": {n:"春节",t:"h"},
    "2025-04-04": {n:"清明",t:"h"}, "2025-04-05": {n:"清明",t:"h"}, "2025-04-06": {n:"清明",t:"h"},
    "2025-05-01": {n:"劳动",t:"h"}, "2025-05-02": {n:"劳动",t:"h"}, "2025-05-03": {n:"劳动",t:"h"},
    "2025-05-04": {n:"劳动",t:"h"}, "2025-05-05": {n:"劳动",t:"h"},
    "2025-05-31": {n:"端午",t:"h"}, "2025-06-01": {n:"端午",t:"h"}, "2025-06-02": {n:"端午",t:"h"},
    "2025-10-01": {n:"国庆",t:"h"}, "2025-10-02": {n:"国庆",t:"h"}, "2025-10-03": {n:"国庆",t:"h"},
    "2025-10-04": {n:"国庆",t:"h"}, "2025-10-05": {n:"国庆",t:"h"}, "2025-10-06": {n:"国庆",t:"h"},
    "2025-10-07": {n:"国庆",t:"h"}, "2025-10-08": {n:"国庆",t:"h"},
    // 2026
    "2026-01-01": {n:"元旦",t:"h"}, "2026-01-02": {n:"元旦",t:"h"}, "2026-01-03": {n:"元旦",t:"h"},
    "2026-02-17": {n:"春节",t:"h"}, "2026-02-18": {n:"春节",t:"h"}, "2026-02-19": {n:"春节",t:"h"},
    "2026-02-20": {n:"春节",t:"h"}, "2026-02-21": {n:"春节",t:"h"}, "2026-02-22": {n:"春节",t:"h"},
    "2026-02-23": {n:"春节",t:"h"},
    "2026-04-05": {n:"清明",t:"h"}, "2026-04-06": {n:"清明",t:"h"}, "2026-04-07": {n:"清明",t:"h"},
    "2026-05-01": {n:"劳动",t:"h"}, "2026-05-02": {n:"劳动",t:"h"}, "2026-05-03": {n:"劳动",t:"h"},
    "2026-05-04": {n:"劳动",t:"h"}, "2026-05-05": {n:"劳动",t:"h"},
    "2026-06-19": {n:"端午",t:"h"}, "2026-06-20": {n:"端午",t:"h"}, "2026-06-21": {n:"端午",t:"h"},
    "2026-09-25": {n:"中秋",t:"h"}, "2026-09-26": {n:"中秋",t:"h"}, "2026-09-27": {n:"中秋",t:"h"},
    "2026-10-01": {n:"国庆",t:"h"}, "2026-10-02": {n:"国庆",t:"h"}, "2026-10-03": {n:"国庆",t:"h"},
    "2026-10-04": {n:"国庆",t:"h"}, "2026-10-05": {n:"国庆",t:"h"}, "2026-10-06": {n:"国庆",t:"h"},
    "2026-10-07": {n:"国庆",t:"h"},
    // 调休上班日 (示例)
    "2024-02-04": {n:"调休",t:"w"}, "2024-02-18": {n:"调休",t:"w"},
    "2025-01-26": {n:"调休",t:"w"}, "2025-02-08": {n:"调休",t:"w"},
    "2026-02-14": {n:"调休",t:"w"}, "2026-02-28": {n:"调休",t:"w"}
};

let currentYear = new Date().getFullYear();
let currentMonth = new Date().getMonth(); // 0-11

function renderCalendar() {
    const year = currentYear, month = currentMonth;
    $('calTitle').textContent = `${year}年 ${month + 1}月`;
    const grid = $('daysGrid'); grid.innerHTML = '';
    
    const firstDay = new Date(year, month, 1).getDay();
    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const daysInPrevMonth = new Date(year, month, 0).getDate();
    const today = new Date();
    
    // 上月补位
    for (let i = firstDay - 1; i >= 0; i--) {
        const d = daysInPrevMonth - i;
        grid.innerHTML += `<div class="day-cell other-month"><span class="day-num">${d}</span></div>`;
    }
    // 当月
    for (let d = 1; d <= daysInMonth; d++) {
        const dateStr = `${year}-${String(month+1).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
        const isToday = (d === today.getDate() && month === today.getMonth() && year === today.getFullYear());
        const holiday = HOLIDAYS[dateStr];
        
        let tagHtml = '';
        if (holiday) {
            const cls = holiday.t === 'h' ? 'tag-holiday' : 'tag-work';
            const text = holiday.t === 'h' ? '休' : '班';
            tagHtml = `<span class="holiday-tag ${cls}">${text}</span>`;
        }
        
        grid.innerHTML += `
            <div class="day-cell ${isToday ? 'today' : ''}" title="${holiday ? holiday.n : ''}">
                <span class="day-num">${d}</span>
                ${tagHtml}
            </div>`;
    }
    // 下月补位
    const totalCells = firstDay + daysInMonth;
    const nextDays = 42 - totalCells; // 保持 6 行
    for (let d = 1; d <= nextDays; d++) {
        grid.innerHTML += `<div class="day-cell other-month"><span class="day-num">${d}</span></div>`;
    }
}

$('prevMonth').onclick = () => { currentMonth--; if(currentMonth<0){currentMonth=11;currentYear--;} renderCalendar(); };
$('nextMonth').onclick = () => { currentMonth++; if(currentMonth>11){currentMonth=0;currentYear++;} renderCalendar(); };

renderCalendar();
</script></body></html>"""

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html;charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML.encode("utf-8"))
    def log_message(self, *a): pass

if __name__ == "__main__":
    print(f"️ 秒表与日历 → http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()