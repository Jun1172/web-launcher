"""cron-ui —— 可视化定时任务
- 端口 8152（可通过 LAUNCHER_APP_PORT 环境变量覆盖）
- 5 段 Cron 表达式可视化生成 + 内存调度器
- 任务存储：tasks.json（与 app.py 同目录）
- 手动触发、执行日志、下次执行时间计算
- Windows 用 CREATE_NO_WINDOW 隐藏子进程窗口
"""
import json
import os
import re
import sys
import threading
import time
import uuid
import subprocess
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# ── 配置 ───────────────────────────────────────────────
PORT = int(os.environ.get("LAUNCHER_APP_PORT", 8152))
APP_DIR = os.path.dirname(os.path.abspath(__file__))
TASKS_FILE = os.path.join(APP_DIR, "tasks.json")
IS_WIN = sys.platform == "win32"
SCHEDULER_INTERVAL = 1.0   # 调度器轮询间隔（秒）
MAX_LOGS = 50              # 每个任务保留日志条数

# ── 全局状态 ────────────────────────────────────────────
TASKS = {}                 # id -> task dict
TASKS_LOCK = threading.RLock()
RUNNING_TASKS = set()      # 正在执行的 task id 集合

# ── 任务存储 ────────────────────────────────────────────
def load_tasks():
    """从 tasks.json 加载任务到内存"""
    global TASKS
    try:
        if os.path.exists(TASKS_FILE):
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                # 兼容旧格式：列表转字典
                TASKS = {t["id"]: t for t in data if isinstance(t, dict) and "id" in t}
            elif isinstance(data, dict):
                TASKS = data
    except Exception as e:
        print(f"[cron-ui] 加载任务失败: {e}", flush=True)
        TASKS = {}


def save_tasks():
    """保存内存中的任务到 tasks.json（不保存以 _ 开头的内部字段）"""
    try:
        with TASKS_LOCK:
            cleaned = {
                tid: {k: v for k, v in t.items() if not k.startswith("_")}
                for tid, t in TASKS.items()
            }
            with open(TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(cleaned, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[cron-ui] 保存任务失败: {e}", flush=True)


# ── Cron 解析 ───────────────────────────────────────────
# 5 段：minute hour day month weekday
CRON_RANGES = {
    "minute":   (0, 59),
    "hour":     (0, 23),
    "day":      (1, 31),
    "month":    (1, 12),
    "weekday":  (0, 6),   # 0=周日, 6=周六
}


def parse_field(expr, min_val, max_val):
    """解析单段 cron 表达式，返回匹配值集合
    支持: * / N / */N / A-B / A,B,C / A-B/N
    解析失败返回空集合
    """
    if expr == "*":
        return set(range(min_val, max_val + 1))
    result = set()
    for part in expr.split(","):
        part = part.strip()
        if not part:
            continue
        # 处理步长 N/M
        step = 1
        base = part
        if "/" in part:
            base, step_str = part.split("/", 1)
            try:
                step = int(step_str)
                if step <= 0:
                    return set()
            except ValueError:
                return set()
        # 处理区间 A-B 或单值
        if base == "*":
            start, end = min_val, max_val
        elif "-" in base:
            try:
                a, b = base.split("-", 1)
                start, end = int(a), int(b)
            except ValueError:
                return set()
        else:
            try:
                start = int(base)
                end = start
            except ValueError:
                return set()
        # 范围校验
        if start < min_val or end > max_val or start > end:
            return set()
        for v in range(start, end + 1, step):
            result.add(v)
    return result


def parse_cron(expr):
    """解析 5 段 cron 表达式，返回 dict 或 None（失败）"""
    parts = expr.strip().split()
    if len(parts) != 5:
        return None
    keys = ("minute", "hour", "day", "month", "weekday")
    out = {}
    for i, key in enumerate(keys):
        lo, hi = CRON_RANGES[key]
        vals = parse_field(parts[i], lo, hi)
        if not vals:
            return None
        out[key] = vals
    return out


def cron_match(parsed, dt):
    """判断 datetime dt 是否匹配 cron"""
    if dt.minute not in parsed["minute"]:
        return False
    if dt.hour not in parsed["hour"]:
        return False
    if dt.month not in parsed["month"]:
        return False
    day_match = dt.day in parsed["day"]
    # Python weekday(): 0=周一..6=周日；cron: 0=周日..6=周六
    cron_wd = (dt.weekday() + 1) % 7
    wd_match = cron_wd in parsed["weekday"]
    day_is_star = parsed["day"] == set(range(1, 32))
    wd_is_star = parsed["weekday"] == set(range(0, 7))
    if day_is_star and wd_is_star:
        return True
    if day_is_star:
        return wd_match
    if wd_is_star:
        return day_match
    # 标准 cron 语义：day 和 weekday 都被限制时取 OR
    return day_match or wd_match


def next_run_time(parsed, after=None):
    """计算 after 之后下一次匹配时间（最多扫描 366 天）"""
    if after is None:
        after = datetime.now()
    cur = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = 366 * 24 * 60
    for _ in range(limit + 1):
        if cron_match(parsed, cur):
            return cur
        cur += timedelta(minutes=1)
    return None


# ── 任务执行 ────────────────────────────────────────────
def _decode(out):
    """解码子进程输出 bytes（utf-8 失败则尝试 gbk，再兜底 latin-1）"""
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return out.decode("gbk", errors="ignore")
        except Exception:
            return out.decode("latin-1", errors="ignore")


def execute_task(task):
    """执行一次任务命令，返回 (exit_code, output)
    - Windows 用 CREATE_NO_WINDOW 隐藏窗口
    - 30 秒超时
    - 输出截断前 2000 字符
    """
    cmd = (task.get("command") or "").strip()
    if not cmd:
        return -1, "命令为空"
    try:
        kwargs = {}
        if IS_WIN:
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.Popen(
            cmd, shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            **kwargs,
        )
        try:
            out, _ = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
            return -1, "执行超时（30s）"
        text = _decode(out).strip()
        return proc.returncode, text[:2000]
    except Exception as e:
        return -2, f"执行异常: {e}"


def append_log(task, exit_code, output):
    """追加执行日志，保留最近 MAX_LOGS 条"""
    log = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "exit_code": exit_code,
        "output": output,
    }
    task.setdefault("logs", []).append(log)
    if len(task["logs"]) > MAX_LOGS:
        task["logs"] = task["logs"][-MAX_LOGS:]
    task["last_run"] = log["time"]


# ── 调度器 ──────────────────────────────────────────────
def run_scheduled(tid):
    """调度线程中执行任务"""
    with TASKS_LOCK:
        if tid in RUNNING_TASKS:
            return
        RUNNING_TASKS.add(tid)
        task = TASKS.get(tid)
        snapshot = dict(task) if task else None
    if not snapshot:
        with TASKS_LOCK:
            RUNNING_TASKS.discard(tid)
        return
    try:
        exit_code, output = execute_task(snapshot)
        with TASKS_LOCK:
            t = TASKS.get(tid)
            if t:
                append_log(t, exit_code, output)
                save_tasks()
    finally:
        with TASKS_LOCK:
            RUNNING_TASKS.discard(tid)


def scheduler_loop():
    """后台调度器：每秒检查是否进入新分钟，匹配则触发任务"""
    last_minute = datetime.now().replace(second=0, microsecond=0)
    while True:
        try:
            now = datetime.now().replace(second=0, microsecond=0)
            if now != last_minute:
                triggered = []
                with TASKS_LOCK:
                    for tid, task in TASKS.items():
                        if not task.get("enabled", True):
                            continue
                        if tid in RUNNING_TASKS:
                            continue
                        parsed = parse_cron(task.get("cron", ""))
                        if parsed and cron_match(parsed, now):
                            triggered.append(tid)
                for tid in triggered:
                    threading.Thread(
                        target=run_scheduled, args=(tid,), daemon=True
                    ).start()
                last_minute = now
        except Exception as e:
            print(f"[cron-ui] 调度器异常: {e}", flush=True)
        time.sleep(SCHEDULER_INTERVAL)


# ── HTTP Handler ────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        """读取并解析 JSON 请求体，失败返回 None"""
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return None
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    def do_GET(self):
        path = urlparse(self.path).path
        # 首页
        if path == "/":
            self._html(HTML_PAGE)
            return
        # 任务列表
        if path == "/api/tasks":
            with TASKS_LOCK:
                tasks = [
                    {k: v for k, v in t.items() if not k.startswith("_")}
                    for t in TASKS.values()
                ]
            self._json({"ok": True, "tasks": tasks})
            return
        # 任务日志 /api/tasks/{id}/logs
        m = re.match(r"^/api/tasks/([^/]+)/logs$", path)
        if m:
            tid = m.group(1)
            with TASKS_LOCK:
                t = TASKS.get(tid)
                if not t:
                    self._json({"ok": False, "error": "任务不存在"}, 404)
                    return
                logs = list(t.get("logs", []))
            self._json({"ok": True, "logs": logs})
            return
        self._json({"ok": False, "error": "Not Found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        # 创建任务 POST /api/tasks
        if path == "/api/tasks":
            body = self._read_body()
            if not isinstance(body, dict):
                self._json({"ok": False, "error": "请求体无效"}, 400)
                return
            name = str(body.get("name", "")).strip()
            cron = str(body.get("cron", "")).strip()
            command = str(body.get("command", "")).strip()
            enabled = bool(body.get("enabled", True))
            if not name or not cron or not command:
                self._json({"ok": False, "error": "name/cron/command 不能为空"}, 400)
                return
            if not parse_cron(cron):
                self._json({"ok": False, "error": "Cron 表达式无效"}, 400)
                return
            tid = uuid.uuid4().hex[:12]
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            task = {
                "id": tid, "name": name, "cron": cron,
                "command": command, "enabled": enabled,
                "created": now, "last_run": "", "logs": [],
            }
            with TASKS_LOCK:
                TASKS[tid] = task
                save_tasks()
            self._json({"ok": True, "task": dict(task)})
            return
        # 更新任务 POST /api/tasks/{id}/update
        m = re.match(r"^/api/tasks/([^/]+)/update$", path)
        if m:
            tid = m.group(1)
            body = self._read_body()
            if not isinstance(body, dict):
                self._json({"ok": False, "error": "请求体无效"}, 400)
                return
            with TASKS_LOCK:
                t = TASKS.get(tid)
                if not t:
                    self._json({"ok": False, "error": "任务不存在"}, 404)
                    return
                if "name" in body:
                    t["name"] = str(body["name"]).strip()
                if "cron" in body:
                    cron = str(body["cron"]).strip()
                    if not parse_cron(cron):
                        self._json({"ok": False, "error": "Cron 表达式无效"}, 400)
                        return
                    t["cron"] = cron
                if "command" in body:
                    t["command"] = str(body["command"]).strip()
                if "enabled" in body:
                    t["enabled"] = bool(body["enabled"])
                save_tasks()
                cleaned = {k: v for k, v in t.items() if not k.startswith("_")}
            self._json({"ok": True, "task": cleaned})
            return
        # 删除任务 POST /api/tasks/{id}/delete
        m = re.match(r"^/api/tasks/([^/]+)/delete$", path)
        if m:
            tid = m.group(1)
            with TASKS_LOCK:
                if tid not in TASKS:
                    self._json({"ok": False, "error": "任务不存在"}, 404)
                    return
                del TASKS[tid]
                save_tasks()
            self._json({"ok": True})
            return
        # 手动触发执行 POST /api/tasks/{id}/run
        m = re.match(r"^/api/tasks/([^/]+)/run$", path)
        if m:
            tid = m.group(1)
            with TASKS_LOCK:
                t = TASKS.get(tid)
                if not t:
                    self._json({"ok": False, "error": "任务不存在"}, 404)
                    return
                if tid in RUNNING_TASKS:
                    self._json({"ok": False, "error": "任务正在执行中"}, 409)
                    return
                RUNNING_TASKS.add(tid)
                snapshot = {k: v for k, v in t.items() if not k.startswith("_")}
            try:
                exit_code, output = execute_task(snapshot)
                with TASKS_LOCK:
                    t = TASKS.get(tid)
                    if t:
                        append_log(t, exit_code, output)
                        save_tasks()
                        cleaned = {k: v for k, v in t.items() if not k.startswith("_")}
                    else:
                        cleaned = None
                self._json({
                    "ok": True, "exit_code": exit_code,
                    "output": output, "task": cleaned,
                })
            finally:
                with TASKS_LOCK:
                    RUNNING_TASKS.discard(tid)
            return
        self._json({"ok": False, "error": "Not Found"}, 404)


# ── HTML 前端（内嵌） ────────────────────────────────────
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>⏱️ 可视化定时任务</title>
<style>
:root{
  --bg:#0a0e1a; --panel:#131826; --card:#1a2030; --border:#2a3245;
  --accent:#8b5cf6; --accent2:#6366f1;
  --text:#e2e8f0; --muted:#64748b;
  --success:#10b981; --danger:#ef4444; --warning:#f59e0b;
}
*{margin:0;padding:0;box-sizing:border-box}
body{
  font-family:system-ui,-apple-system,"Segoe UI","PingFang SC",sans-serif;
  background:var(--bg);
  background-image:
    radial-gradient(circle at 20% 0%,rgba(139,92,246,.10),transparent 40%),
    radial-gradient(circle at 80% 100%,rgba(99,102,241,.10),transparent 40%);
  background-attachment:fixed;
  color:var(--text);min-height:100vh;padding:20px;
}
.container{max-width:1200px;margin:0 auto}
header{
  display:flex;justify-content:space-between;align-items:center;
  margin-bottom:24px;padding:16px 20px;
  background:linear-gradient(135deg,rgba(139,92,246,.18),rgba(99,102,241,.08));
  border:1px solid var(--border);border-radius:14px;
  backdrop-filter:blur(8px);
}
header h1{font-size:20px;font-weight:600;display:flex;align-items:center;gap:8px}
header .ic{font-size:24px}
header .meta{font-size:12px;color:var(--muted);display:flex;align-items:center;gap:12px}
header .dot{color:var(--success);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.btn{
  padding:8px 16px;border:1px solid var(--border);background:var(--card);
  color:var(--text);border-radius:8px;cursor:pointer;font-size:13px;
  transition:all .15s;display:inline-flex;align-items:center;gap:6px;
}
.btn:hover{border-color:var(--accent);background:rgba(139,92,246,.15)}
.btn.primary{background:linear-gradient(135deg,var(--accent),var(--accent2));border-color:transparent;color:#fff}
.btn.primary:hover{opacity:.9}
.btn.danger:hover{border-color:var(--danger);background:rgba(239,68,68,.15);color:var(--danger)}
.btn.small{padding:4px 10px;font-size:12px}
.btn:disabled{opacity:.5;cursor:not-allowed}
.tasks{display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:16px}
.task{
  background:var(--card);border:1px solid var(--border);border-radius:12px;
  padding:16px;position:relative;transition:all .15s;
}
.task:hover{border-color:var(--accent);box-shadow:0 4px 20px rgba(139,92,246,.12)}
.task.disabled{opacity:.6}
.task.running{border-color:var(--warning);animation:pulse 1s infinite}
.task-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;gap:8px}
.task-name{font-size:15px;font-weight:600;word-break:break-all;flex:1}
.task-actions{display:flex;gap:6px;flex-shrink:0}
.task-cron{
  display:inline-block;padding:2px 8px;background:rgba(139,92,246,.18);
  color:#c4b5fd;border-radius:6px;font-family:"Consolas","SF Mono",monospace;
  font-size:12px;margin-bottom:4px;
}
.task-desc{font-size:12px;color:var(--muted);margin-bottom:10px}
.task-cmd{
  font-family:"Consolas","SF Mono",monospace;font-size:12px;
  background:rgba(0,0,0,.3);padding:8px 10px;border-radius:6px;
  color:#a5b4fc;margin-bottom:10px;word-break:break-all;
  border-left:3px solid var(--accent2);max-height:80px;overflow-y:auto;
}
.task-meta{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-bottom:10px;gap:8px;flex-wrap:wrap}
.task-meta .k{color:#94a3b8}
.task-meta .v{color:var(--text)}
.task-meta .next{color:var(--success)}
.task-meta .last{color:var(--warning)}
.task-footer{display:flex;justify-content:space-between;align-items:center;padding-top:10px;border-top:1px solid var(--border)}
.switch{position:relative;width:36px;height:20px;display:inline-block;flex-shrink:0}
.switch input{display:none}
.switch .slider{
  position:absolute;inset:0;background:#475569;border-radius:20px;
  cursor:pointer;transition:.2s;
}
.switch .slider:before{
  content:"";position:absolute;width:16px;height:16px;left:2px;top:2px;
  background:#fff;border-radius:50%;transition:.2s;
}
.switch input:checked + .slider{background:var(--success)}
.switch input:checked + .slider:before{transform:translateX(16px)}
.logs{margin-top:10px;border-top:1px dashed var(--border);padding-top:10px;display:none}
.logs.show{display:block}
.log-item{
  padding:8px 10px;background:rgba(0,0,0,.25);border-radius:6px;
  margin-bottom:6px;font-size:11px;font-family:"Consolas",monospace;
}
.log-item .log-head{display:flex;justify-content:space-between;margin-bottom:4px}
.log-item .log-time{color:var(--muted)}
.log-item .log-code{font-weight:600}
.log-item .log-code.ok{color:var(--success)}
.log-item .log-code.err{color:var(--danger)}
.log-item .log-out{
  color:#94a3b8;word-break:break-all;white-space:pre-wrap;
  max-height:80px;overflow-y:auto;
}
.modal-mask{
  position:fixed;inset:0;background:rgba(0,0,0,.65);display:none;
  align-items:center;justify-content:center;z-index:100;backdrop-filter:blur(4px);
}
.modal-mask.show{display:flex}
.modal{
  background:var(--panel);border:1px solid var(--border);border-radius:14px;
  padding:24px;width:92%;max-width:580px;max-height:90vh;overflow-y:auto;
}
.modal h2{font-size:16px;margin-bottom:16px;display:flex;justify-content:space-between;align-items:center}
.modal h2 .close{cursor:pointer;color:var(--muted);font-size:22px;line-height:1}
.modal h2 .close:hover{color:var(--text)}
.field{margin-bottom:14px}
.field label{display:block;font-size:12px;color:var(--muted);margin-bottom:6px}
.field input[type=text],.field textarea{
  width:100%;padding:10px 12px;background:var(--card);
  border:1px solid var(--border);border-radius:8px;
  color:var(--text);font-size:13px;font-family:inherit;
}
.field input:focus,.field textarea:focus{outline:none;border-color:var(--accent)}
.field textarea{font-family:"Consolas",monospace;resize:vertical;min-height:60px}
.cron-builder{
  background:var(--card);border:1px solid var(--border);
  border-radius:8px;padding:12px;
}
.cron-fields{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}
.cron-field label{font-size:11px;color:var(--muted);margin-bottom:4px;display:block}
.cron-field select{
  width:100%;padding:6px 8px;background:var(--bg);
  border:1px solid var(--border);border-radius:6px;
  color:var(--text);font-size:12px;
}
.cron-field select:focus{outline:none;border-color:var(--accent)}
.cron-custom{margin-top:4px}
.cron-custom input{width:100%;padding:4px 8px;font-size:11px}
.cron-preview{
  margin-top:12px;padding:10px 12px;background:rgba(139,92,246,.10);
  border:1px solid rgba(139,92,246,.30);border-radius:8px;
}
.cron-preview .expr{
  font-family:"Consolas",monospace;font-size:15px;color:#c4b5fd;
  font-weight:600;letter-spacing:1px;
}
.cron-preview .desc{font-size:12px;color:var(--muted);margin-top:4px}
.toggle-row{display:flex;align-items:center;gap:10px}
.toggle-row span{font-size:13px}
.modal-footer{display:flex;justify-content:flex-end;gap:8px;margin-top:20px}
.toast{
  position:fixed;right:20px;bottom:20px;background:var(--panel);
  border:1px solid var(--border);border-radius:10px;padding:12px 16px;
  max-width:400px;box-shadow:0 8px 24px rgba(0,0,0,.5);z-index:200;
  transform:translateX(440px);transition:transform .25s;
}
.toast.show{transform:translateX(0)}
.toast.ok{border-left:3px solid var(--success)}
.toast.err{border-left:3px solid var(--danger)}
.toast .t-title{font-size:13px;font-weight:600;margin-bottom:4px}
.toast .t-body{
  font-size:12px;color:var(--muted);font-family:"Consolas",monospace;
  max-height:200px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;
}
.empty{text-align:center;padding:60px 20px;color:var(--muted)}
.empty .ic{font-size:48px;display:block;margin-bottom:8px;opacity:.5}
.empty .hint{font-size:13px}
@media(max-width:640px){
  .cron-fields{grid-template-columns:repeat(2,1fr)}
  .tasks{grid-template-columns:1fr}
  header{flex-direction:column;align-items:flex-start;gap:12px}
}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1><span class="ic">⏱️</span>可视化定时任务</h1>
    <div class="meta">
      <span><span class="dot">●</span> 运行中 · :__PORT__ · <span id="taskCount">0</span> 个任务</span>
      <button class="btn primary" onclick="openAddModal()">+ 新建任务</button>
    </div>
  </header>
  <div class="tasks" id="taskList"></div>
  <div class="empty" id="empty" style="display:none">
    <span class="ic">⏱️</span>
    <div class="hint">还没有定时任务，点击右上角"新建任务"创建第一个</div>
  </div>
</div>

<!-- 新建/编辑任务弹窗 -->
<div class="modal-mask" id="modalMask">
  <div class="modal">
    <h2>
      <span id="modalTitle">新建任务</span>
      <span class="close" onclick="closeModal()">×</span>
    </h2>
    <div class="field">
      <label>任务名称</label>
      <input type="text" id="fName" placeholder="例如：每日备份">
    </div>
    <div class="field">
      <label>Cron 表达式生成器（5 段：分 时 日 月 周）</label>
      <div class="cron-builder">
        <div class="cron-fields">
          <div class="cron-field">
            <label>分 (0-59)</label>
            <select id="fMin" onchange="onCronSelectChange()"></select>
            <div class="cron-custom" id="cMin" style="display:none">
              <input type="text" placeholder="如 0,30 或 */15 或 10-20" oninput="onCronCustomChange()">
            </div>
          </div>
          <div class="cron-field">
            <label>时 (0-23)</label>
            <select id="fHour" onchange="onCronSelectChange()"></select>
            <div class="cron-custom" id="cHour" style="display:none">
              <input type="text" placeholder="如 0,12 或 */2" oninput="onCronCustomChange()">
            </div>
          </div>
          <div class="cron-field">
            <label>日 (1-31)</label>
            <select id="fDay" onchange="onCronSelectChange()"></select>
            <div class="cron-custom" id="cDay" style="display:none">
              <input type="text" placeholder="如 1,15 或 */2" oninput="onCronCustomChange()">
            </div>
          </div>
          <div class="cron-field">
            <label>月 (1-12)</label>
            <select id="fMonth" onchange="onCronSelectChange()"></select>
            <div class="cron-custom" id="cMonth" style="display:none">
              <input type="text" placeholder="如 1,4 或 */3" oninput="onCronCustomChange()">
            </div>
          </div>
          <div class="cron-field">
            <label>周 (0-6, 0=周日)</label>
            <select id="fWeek" onchange="onCronSelectChange()"></select>
            <div class="cron-custom" id="cWeek" style="display:none">
              <input type="text" placeholder="如 1-5 或 0,6" oninput="onCronCustomChange()">
            </div>
          </div>
        </div>
        <div class="cron-preview">
          <div class="expr" id="cronExpr">* * * * *</div>
          <div class="desc" id="cronDesc">每分钟</div>
        </div>
      </div>
    </div>
    <div class="field">
      <label>执行命令（shell 命令）</label>
      <textarea id="fCmd" placeholder='例如：echo hello 或 python backup.py'></textarea>
    </div>
    <div class="field">
      <label>启用状态</label>
      <div class="toggle-row">
        <label class="switch">
          <input type="checkbox" id="fEnabled" checked onchange="updateEnabledLabel()">
          <span class="slider"></span>
        </label>
        <span id="fEnabledLabel">启用</span>
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn" onclick="closeModal()">取消</button>
      <button class="btn primary" id="saveBtn" onclick="saveTask()">保存</button>
    </div>
  </div>
</div>

<!-- Toast 提示 -->
<div class="toast" id="toast">
  <div class="t-title" id="toastTitle"></div>
  <div class="t-body" id="toastBody"></div>
</div>

<script>
// ── Cron 下拉选项 ──────────────────────────────────
const OPTIONS = {
  min: [
    ['*','每分钟'],['*/2','每2分钟'],['*/5','每5分钟'],['*/10','每10分钟'],
    ['*/15','每15分钟'],['*/20','每20分钟'],['*/30','每30分钟'],
    ['0','0分'],['15','15分'],['30','30分'],['45','45分'],
    ['0,30','0,30分'],['0,15,30,45','每刻钟'],['__custom__','自定义…']
  ],
  hour: [
    ['*','每小时'],['*/2','每2小时'],['*/4','每4小时'],['*/6','每6小时'],
    ['*/8','每8小时'],['*/12','每12小时'],
    ['0','0点'],['2','2点'],['6','6点'],['8','8点'],['12','12点'],
    ['18','18点'],['22','22点'],['0,12','0,12点'],['__custom__','自定义…']
  ],
  day: [
    ['*','每天'],['1','1号'],['15','15号'],['1,15','1,15号'],
    ['*/2','每隔一天'],['*/5','每5天'],['1-7','前7天'],['__custom__','自定义…']
  ],
  month: [
    ['*','每月'],['1','1月'],['*/3','每季度'],['*/6','每半年'],
    ['6,12','6,12月'],['__custom__','自定义…']
  ],
  week: [
    ['*','每天'],['0','周日'],['1','周一'],['6','周六'],
    ['1-5','工作日'],['0,6','周末'],['1,3,5','一三五'],['__custom__','自定义…']
  ]
};

let editingId = null;   // 当前编辑的任务 id（null=新建）
let tasks = [];          // 前端任务缓存

function cap(s){return s.charAt(0).toUpperCase()+s.slice(1)}

// ── 初始化下拉框 ──────────────────────────────────
function initSelects(){
  ['min','hour','day','month','week'].forEach(k=>{
    const sel=document.getElementById('f'+cap(k));
    OPTIONS[k].forEach(([v,label])=>{
      const o=document.createElement('option');
      o.value=v;o.textContent=label;sel.appendChild(o);
    });
  });
}

// ── Cron 解析（JS 端，用于下次执行时间计算与描述） ──────────
function parseCronField(expr,mn,mx){
  if(expr==='*'){
    const r=[];for(let i=mn;i<=mx;i++)r.push(i);return r;
  }
  const result=new Set();
  for(const part of expr.split(',')){
    const p=part.trim();if(!p)continue;
    let base=p,step=1;
    if(p.includes('/')){
      const idx=p.indexOf('/');
      base=p.slice(0,idx);
      step=parseInt(p.slice(idx+1));
      if(!step||step<=0)return null;
    }
    let start,end;
    if(base==='*'){start=mn;end=mx}
    else if(base.includes('-')){
      const [a,b]=base.split('-');
      start=parseInt(a);end=parseInt(b);
    }else{
      start=parseInt(base);
      if(isNaN(start))return null;
      end=start;
    }
    if(isNaN(start)||isNaN(end)||start<mn||end>mx||start>end)return null;
    for(let v=start;v<=end;v+=step)result.add(v);
  }
  return Array.from(result);
}

function parseCron(expr){
  const parts=expr.trim().split(/\s+/);
  if(parts.length!==5)return null;
  const minute=parseCronField(parts[0],0,59);
  const hour=parseCronField(parts[1],0,23);
  const day=parseCronField(parts[2],1,31);
  const month=parseCronField(parts[3],1,12);
  const weekday=parseCronField(parts[4],0,6);
  if(!minute||!hour||!day||!month||!weekday)return null;
  return {minute,hour,day,month,weekday,raw:parts};
}

function cronMatch(parsed,dt){
  if(!parsed.minute.includes(dt.getMinutes()))return false;
  if(!parsed.hour.includes(dt.getHours()))return false;
  if(!parsed.month.includes(dt.getMonth()+1))return false;
  // JS getDay(): 0=周日..6=周六，与 cron weekday 一致
  const dayMatch=parsed.day.includes(dt.getDate());
  const wdMatch=parsed.weekday.includes(dt.getDay());
  const dayStar=parsed.day.length===31;
  const wdStar=parsed.weekday.length===7;
  if(dayStar&&wdStar)return true;
  if(dayStar)return wdMatch;
  if(wdStar)return dayMatch;
  return dayMatch||wdMatch;
}

function nextRun(parsed,after){
  after=after||new Date();
  const cur=new Date(after);
  cur.setSeconds(0,0);
  cur.setMinutes(cur.getMinutes()+1);
  const limit=366*24*60;
  for(let i=0;i<=limit;i++){
    if(cronMatch(parsed,cur))return cur;
    cur.setMinutes(cur.getMinutes()+1);
  }
  return null;
}

// ── Cron 人类可读描述 ──────────────────────────────────
function describeCron(expr){
  const parsed=parseCron(expr);
  if(!parsed)return '表达式无效';
  const [min,hour,day,mon,wd]=parsed.raw;
  const isNum=s=>/^\d+$/.test(s);
  const isList=s=>/^\d+(,\d+)*$/.test(s);
  // 时间描述
  let timeDesc='';
  if(min==='*'&&hour==='*')timeDesc='每分钟';
  else if(min.startsWith('*/'))timeDesc='每'+min.slice(2)+'分钟';
  else if(hour==='*'){
    if(min==='0'||min==='00')timeDesc='每小时整点';
    else if(isNum(min))timeDesc='每小时第'+parseInt(min)+'分';
    else if(isList(min))timeDesc='每小时 '+min+' 分';
    else timeDesc='每小时 分'+min;
  }else if(hour.startsWith('*/')){
    if(min==='0'||min==='00')timeDesc='每'+hour.slice(2)+'小时整点';
    else timeDesc='每'+hour.slice(2)+'小时 分'+min;
  }else if(isNum(hour)){
    const h=parseInt(hour);
    let hLabel;
    if(h===0)hLabel='凌晨0点';
    else if(h<6)hLabel='凌晨'+h+'点';
    else if(h<12)hLabel='早上'+h+'点';
    else if(h===12)hLabel='中午12点';
    else if(h<18)hLabel='下午'+h+'点';
    else hLabel='晚上'+h+'点';
    if(min==='0'||min==='00')timeDesc=hLabel;
    else if(isNum(min))timeDesc=hour.padStart(2,'0')+':'+min.padStart(2,'0');
    else timeDesc=hour+':'+min;
  }else{
    timeDesc='时'+hour+' 分'+min;
  }
  // 日期描述
  let dateDesc='';
  const dayStar=day==='*';
  const monStar=mon==='*';
  const wdStar=wd==='*';
  if(dayStar&&monStar&&wdStar)dateDesc='';
  else if(!dayStar){
    if(monStar&&wdStar)dateDesc='每月'+day+'号';
    else if(!monStar&&wdStar)dateDesc=mon+'月'+day+'号';
    else dateDesc=(monStar?'':mon+'月 ')+'每月'+day+'号';
  }else if(!wdStar){
    const wdMap={0:'日',1:'一',2:'二',3:'三',4:'四',5:'五',6:'六'};
    const parts=wd.split(',').map(w=>{
      if(w.includes('-')){
        const [a,b]=w.split('-');
        return '周'+(wdMap[a]||a)+'到周'+(wdMap[b]||b);
      }
      return '周'+(wdMap[w]||w);
    });
    dateDesc='每'+parts.join('、');
    if(!monStar)dateDesc=mon+'月 '+dateDesc;
  }else if(!monStar){
    dateDesc=mon+'月每天';
  }
  // 合并
  if(!dateDesc){
    if(timeDesc.startsWith('每'))return timeDesc;
    if(/^\d/.test(timeDesc))return '每天 '+timeDesc;
    return '每天'+timeDesc;
  }
  let td=timeDesc;
  if(td.startsWith('每天'))td=td.slice(2);
  if(/^\d/.test(td))return dateDesc+' '+td;
  return dateDesc+' '+td;
}

// ── Cron 生成器交互 ──────────────────────────────────
function onCronSelectChange(){
  ['min','hour','day','month','week'].forEach(k=>{
    const sel=document.getElementById('f'+cap(k));
    const cust=document.getElementById('c'+cap(k));
    if(sel.value!=='__custom__'){
      cust.style.display='none';
      const inp=cust.querySelector('input');
      if(inp)inp.value='';
    }else{
      cust.style.display='block';
    }
  });
  updateCronPreview();
}

function onCronCustomChange(){updateCronPreview()}

function getFieldVal(k){
  const sel=document.getElementById('f'+cap(k));
  if(sel.value==='__custom__'){
    const inp=document.getElementById('c'+cap(k)).querySelector('input');
    return (inp.value||'').trim()||'*';
  }
  return sel.value;
}

function setFieldVal(k,val){
  const sel=document.getElementById('f'+cap(k));
  const cust=document.getElementById('c'+cap(k));
  const inp=cust.querySelector('input');
  let found=false;
  for(const o of sel.options){
    if(o.value===val){found=true;break}
  }
  if(found){
    sel.value=val;
    cust.style.display='none';
    if(inp)inp.value='';
  }else{
    sel.value='__custom__';
    cust.style.display='block';
    if(inp)inp.value=val;
  }
}

function buildCronExpr(){
  return ['min','hour','day','month','week'].map(getFieldVal).join(' ');
}

function updateCronPreview(){
  const expr=buildCronExpr();
  document.getElementById('cronExpr').textContent=expr;
  document.getElementById('cronDesc').textContent=describeCron(expr);
}

function updateEnabledLabel(){
  document.getElementById('fEnabledLabel').textContent=
    document.getElementById('fEnabled').checked?'启用':'停用';
}

// ── 任务列表加载与渲染 ──────────────────────────────────
async function loadTasks(){
  try{
    const r=await fetch('/api/tasks');
    const d=await r.json();
    const expanded={};
    tasks.forEach(t=>{if(t._expanded)expanded[t.id]=true});
    tasks=(d.tasks||[]).map(t=>{t._expanded=!!expanded[t.id];return t});
    render();
  }catch(e){
    showToast('加载失败',String(e),'err');
  }
}

function fmtNext(expr){
  const parsed=parseCron(expr);
  if(!parsed)return '表达式无效';
  const next=nextRun(parsed);
  if(!next)return '无匹配';
  return next.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
}

function escapeHtml(s){
  return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function renderLogs(logs){
  if(!logs.length)return '<div style="font-size:12px;color:var(--muted);padding:8px">暂无执行记录</div>';
  return logs.slice().reverse().map(l=>`
    <div class="log-item">
      <div class="log-head">
        <span class="log-time">${escapeHtml(l.time)}</span>
        <span class="log-code ${l.exit_code===0?'ok':'err'}">退出码: ${l.exit_code}</span>
      </div>
      <div class="log-out">${escapeHtml(l.output||'(无输出)')}</div>
    </div>`).join('');
}

function render(){
  const list=document.getElementById('taskList');
  const empty=document.getElementById('empty');
  document.getElementById('taskCount').textContent=tasks.length;
  if(!tasks.length){
    list.innerHTML='';
    empty.style.display='block';
    return;
  }
  empty.style.display='none';
  list.innerHTML=tasks.map(t=>{
    const enabled=t.enabled!==false;
    const cls=(enabled?'':'disabled')+(t._running?' running':'');
    const nextT=enabled?fmtNext(t.cron):'已停用';
    return `
      <div class="task ${cls}" data-id="${escapeHtml(t.id)}">
        <div class="task-head">
          <div class="task-name">${escapeHtml(t.name)}</div>
          <div class="task-actions">
            <button class="btn small" onclick="runTask('${escapeHtml(t.id)}',event)">▶ 运行</button>
            <button class="btn small" onclick="editTask('${escapeHtml(t.id)}',event)">编辑</button>
            <button class="btn small danger" onclick="deleteTask('${escapeHtml(t.id)}',event)">删除</button>
          </div>
        </div>
        <div class="task-cron">${escapeHtml(t.cron)}</div>
        <div class="task-desc">${escapeHtml(describeCron(t.cron))}</div>
        <div class="task-cmd">${escapeHtml(t.command)}</div>
        <div class="task-meta">
          <span><span class="k">上次:</span> <span class="last">${escapeHtml(t.last_run||'未执行')}</span></span>
          <span><span class="k">下次:</span> <span class="next">${escapeHtml(nextT)}</span></span>
        </div>
        <div class="task-footer">
          <label class="switch">
            <input type="checkbox" ${enabled?'checked':''} onchange="toggleTask('${escapeHtml(t.id)}',this.checked)">
            <span class="slider"></span>
          </label>
          <button class="btn small" onclick="toggleLogs('${escapeHtml(t.id)}',event)">${t._expanded?'收起日志':'查看日志'}</button>
        </div>
        <div class="logs ${t._expanded?'show':''}" id="logs-${escapeHtml(t.id)}">
          ${renderLogs(t.logs||[])}
        </div>
      </div>`;
  }).join('');
}

// ── 任务操作 ──────────────────────────────────
async function toggleTask(id,enabled){
  try{
    await fetch('/api/tasks/'+id+'/update',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({enabled})
    });
    const t=tasks.find(x=>x.id===id);
    if(t)t.enabled=enabled;
    render();
  }catch(e){
    showToast('更新失败',String(e),'err');
  }
}

async function runTask(id,ev){
  ev&&ev.stopPropagation();
  const card=document.querySelector('.task[data-id="'+CSS.escape(id)+'"]');
  if(card)card.classList.add('running');
  try{
    const r=await fetch('/api/tasks/'+id+'/run',{method:'POST'});
    const d=await r.json();
    if(d.ok){
      showToast('执行完成 退出码 '+d.exit_code,d.output||'(无输出)',d.exit_code===0?'ok':'err');
      const t=tasks.find(x=>x.id===id);
      if(t&&d.task)Object.assign(t,d.task);
      render();
    }else{
      showToast('执行失败',d.error||'未知错误','err');
    }
  }catch(e){
    showToast('执行失败',String(e),'err');
  }finally{
    const c=document.querySelector('.task[data-id="'+CSS.escape(id)+'"]');
    if(c)c.classList.remove('running');
  }
}

async function deleteTask(id,ev){
  ev&&ev.stopPropagation();
  if(!confirm('确定删除此任务？'))return;
  try{
    await fetch('/api/tasks/'+id+'/delete',{method:'POST'});
    tasks=tasks.filter(x=>x.id!==id);
    render();
  }catch(e){
    showToast('删除失败',String(e),'err');
  }
}

async function toggleLogs(id,ev){
  ev&&ev.stopPropagation();
  const t=tasks.find(x=>x.id===id);
  if(!t)return;
  try{
    const r=await fetch('/api/tasks/'+id+'/logs');
    const d=await r.json();
    if(d.ok)t.logs=d.logs||[];
  }catch(e){}
  t._expanded=!t._expanded;
  render();
}

// ── 弹窗 ──────────────────────────────────
function openAddModal(){
  editingId=null;
  document.getElementById('modalTitle').textContent='新建任务';
  document.getElementById('fName').value='';
  document.getElementById('fCmd').value='';
  document.getElementById('fEnabled').checked=true;
  ['min','hour','day','month','week'].forEach(k=>{
    const sel=document.getElementById('f'+cap(k));
    sel.value='*';
    const cust=document.getElementById('c'+cap(k));
    cust.style.display='none';
    const inp=cust.querySelector('input');
    if(inp)inp.value='';
  });
  updateCronPreview();
  updateEnabledLabel();
  document.getElementById('modalMask').classList.add('show');
}

function editTask(id,ev){
  ev&&ev.stopPropagation();
  const t=tasks.find(x=>x.id===id);
  if(!t)return;
  editingId=id;
  document.getElementById('modalTitle').textContent='编辑任务';
  document.getElementById('fName').value=t.name;
  document.getElementById('fCmd').value=t.command;
  document.getElementById('fEnabled').checked=t.enabled!==false;
  const parts=t.cron.trim().split(/\s+/);
  ['min','hour','day','month','week'].forEach((k,i)=>{
    setFieldVal(k,parts[i]||'*');
  });
  updateCronPreview();
  updateEnabledLabel();
  document.getElementById('modalMask').classList.add('show');
}

function closeModal(){
  document.getElementById('modalMask').classList.remove('show');
}

async function saveTask(){
  const name=document.getElementById('fName').value.trim();
  const cron=buildCronExpr();
  const command=document.getElementById('fCmd').value.trim();
  const enabled=document.getElementById('fEnabled').checked;
  if(!name){showToast('提示','请填写任务名称','err');return}
  if(!command){showToast('提示','请填写执行命令','err');return}
  if(!parseCron(cron)){showToast('提示','Cron 表达式无效','err');return}
  const btn=document.getElementById('saveBtn');
  btn.disabled=true;
  try{
    const body={name,cron,command,enabled};
    const url=editingId?('/api/tasks/'+editingId+'/update'):'/api/tasks';
    const r=await fetch(url,{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body)
    });
    const d=await r.json();
    if(d.ok){
      closeModal();
      await loadTasks();
      showToast('成功',editingId?'任务已更新':'任务已创建','ok');
    }else{
      showToast('保存失败',d.error||'未知错误','err');
    }
  }catch(e){
    showToast('保存失败',String(e),'err');
  }finally{
    btn.disabled=false;
  }
}

// ── Toast ──────────────────────────────────
let toastTimer=null;
function showToast(title,body,type){
  const t=document.getElementById('toast');
  t.className='toast '+(type||'');
  document.getElementById('toastTitle').textContent=title;
  document.getElementById('toastBody').textContent=body||'';
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer=setTimeout(()=>t.classList.remove('show'),6000);
}

// ── 初始化 ──────────────────────────────────
initSelects();
loadTasks();
// 每 30 秒重渲染，刷新下次执行时间
setInterval(()=>render(),30000);
// 点击遮罩关闭弹窗
document.getElementById('modalMask').addEventListener('click',e=>{
  if(e.target.id==='modalMask')closeModal();
});
// Esc 关闭弹窗
document.addEventListener('keydown',e=>{
  if(e.key==='Escape')closeModal();
});
</script>
</body>
</html>"""

# 把端口注入 HTML
HTML_PAGE = HTML_TEMPLATE.replace("__PORT__", str(PORT))


# ── 启动入口 ────────────────────────────────────────────
if __name__ == "__main__":
    load_tasks()
    # 启动后台调度器线程（daemon，随主进程退出）
    threading.Thread(target=scheduler_loop, daemon=True).start()
    print(f"[cron-ui] 启动于 http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
