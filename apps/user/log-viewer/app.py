"""log-viewer —— 实时日志查看器
- 端口 8151（默认，可被环境变量 LAUNCHER_APP_PORT 覆盖）
- SSE 实时推流 GET /api/logs?file=<path>：增量读取（tail -f 效果），跨平台纯 Python
- GET /api/files：扫描常见日志路径（launcher.log / 系统日志 / 当前目录 *.log）
- GET /api/tail?file=<path>&lines=N：从文件末尾 seek 倒读最后 N 行（不依赖系统 tail）
- 前端：深色终端风格，级别着色、关键字过滤、搜索跳转、暂停/清屏、断线自动重连
"""
import json
import os
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path


def get_port():
    """端口读取：优先 LAUNCHER_APP_PORT，缺失回退 app.json 的 port，均无效返回 0。"""
    env_port = os.environ.get("LAUNCHER_APP_PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            pass
    j = Path(__file__).resolve().parent / "app.json"
    if j.exists():
        try:
            return int(json.loads(j.read_text(encoding="utf-8")).get("port", 0))
        except Exception:
            pass
    return 0


PORT = get_port()

# 脚本所在目录与 launcher 根目录（web-launcher/）
HERE = Path(__file__).resolve().parent
BASE = HERE.parent.parent.parent  # web-launcher 根


# ── 日志文件收集 ──────────────────────────────────────────
def collect_log_files():
    """扫描常见日志文件路径，返回 [{path, name, size, mtime}]"""
    candidates = []

    # 1) launcher.log / launcher-stdout.log：从脚本目录向上逐级查找（同目录或上级）
    for d in (HERE, HERE.parent, HERE.parent.parent, BASE):
        for name in ("launcher.log", "launcher-stdout.log"):
            candidates.append(d / name)

    # 2) 当前脚本目录与 BASE 目录下的 *.log
    for d in (HERE, BASE):
        try:
            candidates.extend(d.glob("*.log"))
        except Exception:
            pass

    # 3) Linux / macOS 系统日志
    for syslog in ("/var/log/syslog", "/var/log/messages", "/var/log/system.log"):
        candidates.append(Path(syslog))

    # 去重 + 过滤存在的文件
    seen = set()
    result = []
    for p in candidates:
        try:
            rp = p.resolve()
        except Exception:
            continue
        key = str(rp).lower()  # Windows 路径不区分大小写
        if key in seen:
            continue
        seen.add(key)
        try:
            st = rp.stat()
        except OSError:
            continue
        result.append({
            "path": str(rp),
            "name": rp.name,
            "size": st.st_size,
            "mtime": int(st.st_mtime),
        })
    return result


def _allowed_set():
    """当前允许访问的日志文件绝对路径集合（小写规范化，用于防路径穿越）"""
    return {str(Path(f["path"]).resolve()).lower() for f in collect_log_files()}


def _resolve(file_param):
    """把请求参数 file 解析为允许访问的绝对路径；不在白名单返回 None"""
    if not file_param:
        return None
    try:
        rp = Path(file_param).resolve()
    except Exception:
        return None
    if str(rp).lower() in _allowed_set():
        return str(rp)
    return None


# ── 文件末尾倒读（跨平台，不依赖系统 tail）──
def tail_file(path, n=100):
    """从文件末尾 seek 倒读最后 n 行，纯 Python 实现"""
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    if size == 0 or n <= 0:
        return []

    chunk = 8192
    pos = size
    buf = b""
    with open(path, "rb") as f:
        # 一直往前读，直到攒够 n 个换行或读到文件头
        while pos > 0 and buf.count(b"\n") < n:
            read = min(chunk, pos)
            pos -= read
            f.seek(pos)
            buf = f.read(read) + buf

    parts = buf.split(b"\n")
    # 文件以 \n 结尾时末尾会多一个空串，去掉
    if parts and parts[-1] == b"":
        parts = parts[:-1]
    # 如果未读到文件头（pos>0），buf 开头是一行被截断的半行，丢弃
    if pos > 0 and parts:
        parts = parts[1:]
    last_n = parts[-n:] if len(parts) > n else parts
    # 与 SSE 生成器保持一致：去掉行尾 \r（Windows 换行符）
    return [p.decode("utf-8", errors="replace").rstrip("\r") for p in last_n]


# ── SSE 生成器（增量读取，tail -f 效果）──
def _sse(event, data):
    """构造一条 SSE 消息；用 JSON 编码 data 以安全承载任意文本"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def sse_generator(file_path):
    """持续推送 file_path 的新增行；记录 seek 位置只推送新增内容"""
    pos = 0
    inode = None
    try:
        st = os.stat(file_path)
        inode = st.st_ino
        pos = st.st_size  # 从当前末尾开始，只推新内容
    except OSError as e:
        yield _sse("status", {"type": "error", "msg": f"无法访问文件: {e}"})
        return

    yield _sse("status", {"type": "info", "msg": "已连接，监听新增日志…"})

    leftover = b""  # 缓冲上次未读完的半行
    while True:
        try:
            st = os.stat(file_path)
        except OSError:
            yield _sse("status", {"type": "error", "msg": "文件暂时不可访问，重试中…"})
            time.sleep(2)
            continue

        # 检测日志轮转/截断：inode 变化 或 文件变小
        if st.st_ino != inode or st.st_size < pos:
            inode = st.st_ino
            pos = 0
            leftover = b""
            yield _sse("status", {"type": "rotate", "msg": "检测到文件轮转，从头追踪"})

        new_data = b""
        if st.st_size > pos:
            try:
                with open(file_path, "rb") as f:
                    f.seek(pos)
                    new_data = f.read()
                    pos = f.tell()
            except OSError as e:
                yield _sse("status", {"type": "error", "msg": f"读取失败: {e}"})
                time.sleep(1)
                continue

        if new_data:
            data = leftover + new_data
            parts = data.split(b"\n")
            leftover = parts[-1]  # 末尾可能是不完整行，留到下次
            for raw in parts[:-1]:
                text = raw.decode("utf-8", errors="replace")
                if text.endswith("\r"):
                    text = text[:-1]
                yield _sse("log", text)
        else:
            # 无新内容，发 SSE 注释心跳，保活防代理超时
            yield ": heartbeat\n\n"

        time.sleep(0.4)


# ── HTTP Handler ──────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    # 用 HTTP/1.1 以支持 SSE 长连接流式响应
    protocol_version = "HTTP/1.1"

    def log_message(self, *a, **k):
        pass  # 静默访问日志

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _write_sse(self, text):
        """写入一段 SSE 文本并立即 flush"""
        self.wfile.write(text.encode("utf-8"))
        self.wfile.flush()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)
        file_param = qs.get("file", [""])[0]

        if path == "/":
            # 返回内嵌 HTML 首页
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        elif path == "/api/files":
            self._json({"files": collect_log_files()})

        elif path == "/api/tail":
            abs_path = _resolve(file_param)
            if abs_path is None:
                self._json({"error": "文件不在允许列表内", "lines": []}, status=403)
                return
            try:
                n = int(qs.get("lines", ["100"])[0])
            except ValueError:
                n = 100
            n = max(1, min(n, 5000))  # 限制单次读取行数
            lines = tail_file(abs_path, n)
            self._json({"file": abs_path, "count": len(lines), "lines": lines})

        elif path == "/api/logs":
            abs_path = _resolve(file_param)
            # SSE 流式响应：不设 Content-Length，连接保持打开持续推送
            self.send_response(200 if abs_path else 403)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.close_connection = True  # 推流结束后关闭，便于线程退出
            if abs_path is None:
                self._write_sse(_sse("status", {"type": "error", "msg": "文件不在允许列表内"}))
                return
            try:
                for chunk in sse_generator(abs_path):
                    self._write_sse(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass  # 客户端断开连接，正常退出
        else:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", "12")
            self.end_headers()
            self.wfile.write(b"404 Not Found")


# ── 前端 HTML（内嵌，单文件无需外部资源）──
HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>📜 实时日志查看器</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0a0d0a; --panel:#0f130f; --border:#1f2a1f;
  --green:#33ff66; --green-dim:#1aaa44;
  --red:#ff5555; --orange:#ffb347; --blue:#5aa9ff; --gray:#888;
  --highlight:#3a2a00; --newflash:#143b14;
}
html,body{height:100%}
body{
  font-family:Consolas,"Cascadia Mono","Courier New",monospace;
  background:var(--bg); color:var(--green);
  display:flex; flex-direction:column; height:100vh; overflow:hidden;
}
/* 工具栏 */
.toolbar{
  display:flex; flex-wrap:wrap; align-items:center; gap:6px;
  padding:8px 10px; background:var(--panel); border-bottom:1px solid var(--border);
}
.toolbar label{font-size:12px; color:var(--green-dim); margin-right:2px}
.toolbar select,.toolbar input{
  background:#070a07; color:var(--green); border:1px solid var(--border);
  border-radius:3px; padding:5px 8px; font-family:inherit; font-size:13px; outline:none;
  min-width:0;
}
.toolbar select:focus,.toolbar input:focus{border-color:var(--green-dim)}
.toolbar input.flex{flex:1 1 140px}
.btn{
  background:#070a07; color:var(--green); border:1px solid var(--border);
  border-radius:3px; padding:5px 10px; font-family:inherit; font-size:13px; cursor:pointer;
  transition:background .12s,border-color .12s;
}
.btn:hover{background:#142214; border-color:var(--green-dim)}
.btn.active{background:#2a5a2a; border-color:var(--green); color:#fff}
.btn.warn:hover{background:#3a1a1a; border-color:var(--red); color:var(--red)}
.match-info{font-size:12px; color:var(--green-dim); min-width:46px; text-align:center}
/* 状态栏 */
.statusbar{
  display:flex; gap:14px; align-items:center; flex-wrap:wrap;
  padding:4px 10px; background:var(--panel); border-bottom:1px solid var(--border);
  font-size:12px; color:var(--green-dim);
}
.statusbar .spacer{flex:1}
.dot{display:inline-block; width:8px; height:8px; border-radius:50%; background:#555; margin-right:4px; vertical-align:middle}
.dot.on{background:var(--green); box-shadow:0 0 6px var(--green)}
.dot.connecting{background:var(--orange); box-shadow:0 0 6px var(--orange)}
.dot.off{background:var(--red)}
/* 日志区 */
.log-area{
  flex:1; overflow-y:auto; padding:6px 8px; font-size:13px; line-height:1.45;
}
.log-line{
  white-space:pre-wrap; word-break:break-all; padding:1px 6px; border-radius:2px;
  border-left:2px solid transparent;
}
.log-line.new{animation:flash .6s ease-out}
@keyframes flash{0%{background:var(--newflash)}100%{background:transparent}}
.log-line.search-match{background:var(--highlight); border-left-color:var(--orange)}
.log-line.search-current{outline:1px solid var(--orange); outline-offset:-1px}
.lvl-ERROR,.lvl-FATAL,.lvl-CRITICAL{color:var(--red); font-weight:bold}
.lvl-WARN{color:var(--orange)}
.lvl-INFO{color:var(--blue)}
.lvl-DEBUG,.lvl-TRACE{color:var(--gray)}
.status-line{color:var(--green-dim); font-style:italic; border-left-color:var(--green-dim)}
.status-line.err{color:var(--red)}
.empty{color:var(--gray); text-align:center; padding:40px 10px}
/* 滚动条 */
.log-area::-webkit-scrollbar{width:10px; height:10px}
.log-area::-webkit-scrollbar-track{background:#070a07}
.log-area::-webkit-scrollbar-thumb{background:#1f2a1f; border-radius:5px}
.log-area::-webkit-scrollbar-thumb:hover{background:#2a3a2a}
@media(max-width:640px){
  .toolbar label.hide-sm,.statusbar .hide-sm{display:none}
  .toolbar select{max-width:100%}
}
</style>
</head>
<body>

<div class="toolbar">
  <label>📜 文件</label>
  <select id="fileSel" style="max-width:300px"></select>
  <label class="hide-sm">过滤</label>
  <input id="filterInp" class="flex" type="text" placeholder="关键字过滤（仅显示含此词的行）">
  <input id="searchInp" class="flex" type="search" placeholder="搜索高亮…">
  <button class="btn" id="prevBtn" title="上一个匹配 (Shift+Enter)">↑</button>
  <span id="matchInfo" class="match-info">0/0</span>
  <button class="btn" id="nextBtn" title="下一个匹配 (Enter)">↓</button>
  <button class="btn" id="pauseBtn" title="暂停/继续 (空格)">⏸ 暂停</button>
  <button class="btn warn" id="clearBtn" title="清屏">🗑 清屏</button>
</div>

<div class="statusbar">
  <span><span class="dot" id="connDot"></span><span id="connTxt">未连接</span></span>
  <span>📄 <span id="curFile">—</span></span>
  <span>📊 <span id="lineCount">0</span> 行</span>
  <span class="spacer"></span>
  <span class="hide-sm" style="opacity:.6">Enter 搜索 · ↑↓ 跳转 · 空格暂停</span>
</div>

<div class="log-area" id="logArea">
  <div class="empty">请在上方选择一个日志文件开始查看…</div>
</div>

<script>
// ── 全局状态 ──
const MAX_LINES = 3000;          // 内存中保留的最大行数（超出丢最旧）
const state = {
  lines: [],        // 全部接收到的行文本（capped）
  filter: "",       // 关键字过滤（仅显示含此词的行）
  search: "",       // 搜索词（高亮匹配行）
  paused: false,
  autoScroll: true,
  es: null,         // EventSource
  matchEls: [],     // 当前搜索匹配的 DOM 节点
  matchIdx: -1,
};

const $ = id => document.getElementById(id);
const logArea = $('logArea');

// ── 工具函数 ──
function escapeHtml(s){
  return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
// 按日志级别关键字着色（在已转义的文本上操作）
function colorizeLevels(s){
  return s.replace(/\b(FATAL|CRITICAL|ERROR|WARNING|WARN|INFO|DEBUG|TRACE)\b/g, m => {
    let cls = 'lvl-INFO';
    if(/^(FATAL|CRITICAL|ERROR)$/.test(m)) cls = 'lvl-ERROR';
    else if(/^WARN/i.test(m)) cls = 'lvl-WARN';
    else if(/^(DEBUG|TRACE)$/.test(m)) cls = 'lvl-DEBUG';
    else cls = 'lvl-INFO';
    return '<span class="'+cls+'">'+m+'</span>';
  });
}
function passesFilter(text){
  if(!state.filter) return true;
  return text.toLowerCase().indexOf(state.filter.toLowerCase()) >= 0;
}
function matchesSearch(text){
  if(!state.search) return false;
  return text.toLowerCase().indexOf(state.search.toLowerCase()) >= 0;
}

// ── 渲染单行 ──
function makeLineNode(text, isStatus, statusType){
  const div = document.createElement('div');
  div.className = 'log-line' + (isStatus ? ' status-line' : '') + (statusType === 'error' ? ' err' : '');
  if(isStatus){
    div.textContent = '› ' + text;
  } else {
    div.innerHTML = colorizeLevels(escapeHtml(text));
    div._raw = text;
    div.classList.add('new');
    setTimeout(() => div.classList.remove('new'), 600);
  }
  return div;
}

// 添加一条日志行（来自 SSE）
function addLogLine(text){
  state.lines.push(text);
  if(state.lines.length > MAX_LINES){
    state.lines.shift();
    if(!state.paused){
      // 移除最旧的日志 DOM 节点
      const first = logArea.querySelector('.log-line:not(.status-line)');
      if(first) first.remove();
    }
  }
  if(state.paused) return;          // 暂停时只缓冲不渲染
  if(!passesFilter(text)) return;   // 不符合过滤则不显示
  const node = makeLineNode(text, false);
  logArea.appendChild(node);
  if(matchesSearch(text)){
    node.classList.add('search-match');
    state.matchEls.push(node);
    updateMatchInfo();
  }
  if(state.autoScroll) scrollToBottom();
}

// 添加一条状态行（连接信息/错误/轮转）
function addStatusLine(msg, type){
  if(!msg) return;
  const node = makeLineNode(msg, true, type);
  logArea.appendChild(node);
  if(state.autoScroll) scrollToBottom();
}

function scrollToBottom(){ logArea.scrollTop = logArea.scrollHeight; }

// ── 全量重建可见 DOM（过滤/搜索变化或恢复暂停时调用）──
function rebuild(){
  logArea.innerHTML = '';
  state.matchEls = [];
  state.matchIdx = -1;
  const frag = document.createDocumentFragment();
  for(const text of state.lines){
    if(!passesFilter(text)) continue;
    const node = makeLineNode(text, false);
    if(matchesSearch(text)){
      node.classList.add('search-match');
      state.matchEls.push(node);
    }
    frag.appendChild(node);
  }
  logArea.appendChild(frag);
  updateMatchInfo();
  updateLineCount();
  if(state.autoScroll) scrollToBottom();
}

function updateLineCount(){ $('lineCount').textContent = state.lines.length; }

function updateMatchInfo(){
  const total = state.matchEls.length;
  if(total === 0){
    state.matchIdx = -1;
    $('matchInfo').textContent = '0/0';
    return;
  }
  if(state.matchIdx < 0 || state.matchIdx >= total) state.matchIdx = 0;
  state.matchEls.forEach((el, i) => el.classList.toggle('search-current', i === state.matchIdx));
  const cur = state.matchEls[state.matchIdx];
  if(cur) cur.scrollIntoView({block:'center'});
  $('matchInfo').textContent = (state.matchIdx + 1) + '/' + total;
}
function jumpMatch(dir){
  const total = state.matchEls.length;
  if(total === 0) return;
  state.matchIdx = (state.matchIdx + dir + total) % total;
  updateMatchInfo();
}

// ── SSE 连接 ──
function connectSSE(file){
  disconnectSSE();
  if(!file) return;
  const es = new EventSource('/api/logs?file=' + encodeURIComponent(file));
  state.es = es;
  setConn('connecting');
  es.addEventListener('open', () => setConn('on'));
  es.addEventListener('log', e => {
    let text = e.data;
    try{ text = JSON.parse(e.data); }catch(_){}
    addLogLine(text);
    updateLineCount();
  });
  es.addEventListener('status', e => {
    try{
      const d = JSON.parse(e.data);
      addStatusLine(d.msg || '', d.type);
    }catch(_){}
  });
  es.onerror = () => {
    // EventSource 会自动重连，这里只更新状态
    setConn('off');
  };
}
function disconnectSSE(){
  if(state.es){ state.es.close(); state.es = null; }
  setConn('off');
}
function setConn(s){
  const dot = $('connDot'), txt = $('connTxt');
  dot.className = 'dot';
  if(s === 'on'){ dot.classList.add('on'); txt.textContent = '已连接 · 实时推流'; }
  else if(s === 'connecting'){ dot.classList.add('connecting'); txt.textContent = '连接中…'; }
  else { txt.textContent = '已断开，自动重连中…'; }
}

// ── 加载历史尾部 ──
async function loadTail(file){
  try{
    const r = await fetch('/api/tail?file=' + encodeURIComponent(file) + '&lines=200');
    const d = await r.json();
    if(d.error){ addStatusLine(d.error, 'error'); return; }
    state.lines = (d.lines || []).slice();
    logArea.innerHTML = '';
    state.matchEls = []; state.matchIdx = -1;
    const frag = document.createDocumentFragment();
    for(const text of state.lines){
      if(!passesFilter(text)) continue;
      const node = makeLineNode(text, false);
      if(matchesSearch(text)){ node.classList.add('search-match'); state.matchEls.push(node); }
      frag.appendChild(node);
    }
    logArea.appendChild(frag);
    updateMatchInfo(); updateLineCount();
    scrollToBottom();
  }catch(e){
    addStatusLine('加载历史失败: ' + e, 'error');
  }
}

// ── 选择文件 ──
async function selectFile(file){
  $('curFile').textContent = file ? file.split(/[\\/]/).pop() : '—';
  state.lines = [];
  state.matchEls = []; state.matchIdx = -1;
  logArea.innerHTML = '<div class="empty">加载中…</div>';
  updateLineCount();
  if(!file){ disconnectSSE(); return; }
  await loadTail(file);
  const empty = logArea.querySelector('.empty'); if(empty) empty.remove();
  connectSSE(file);
}

// ── 加载文件列表 ──
async function loadFiles(){
  const sel = $('fileSel');
  sel.innerHTML = '<option value="">— 选择日志文件 —</option>';
  try{
    const r = await fetch('/api/files');
    const d = await r.json();
    const files = d.files || [];
    if(!files.length){
      sel.innerHTML = '<option value="">（未发现日志文件）</option>';
      addStatusLine('未发现可用日志文件，请检查路径', 'error');
      return;
    }
    let defaultPicked = false;
    for(const f of files){
      const opt = document.createElement('option');
      opt.value = f.path;
      opt.textContent = f.name + '  [' + formatSize(f.size) + ', ' + fmtDate(new Date(f.mtime*1000)) + ']';
      // 默认优先选 launcher.log（主日志）
      if(!defaultPicked && /launcher\.log$/i.test(f.name)){ opt.selected = true; defaultPicked = true; }
      sel.appendChild(opt);
    }
    if(!defaultPicked) sel.selectedIndex = 1; // 回退到第一个实际文件
    selectFile(sel.value);
  }catch(e){
    addStatusLine('获取文件列表失败: ' + e, 'error');
  }
}
function formatSize(b){
  if(!b) return '0B';
  const u = ['B','KB','MB','GB'];
  const i = Math.floor(Math.log(b)/Math.log(1024));
  return (b/Math.pow(1024,i)).toFixed(i===0?0:1) + u[i];
}
function fmtDate(d){
  const p = x => String(x).padStart(2,'0');
  return p(d.getMonth()+1)+'-'+p(d.getDate())+' '+p(d.getHours())+':'+p(d.getMinutes());
}

// ── 事件绑定 ──
$('fileSel').addEventListener('change', e => selectFile(e.target.value));
$('filterInp').addEventListener('input', e => {
  state.filter = e.target.value.trim();
  clearTimeout(state._filterT);
  state._filterT = setTimeout(rebuild, 250);
});
$('searchInp').addEventListener('input', e => {
  state.search = e.target.value.trim();
  clearTimeout(state._searchT);
  state._searchT = setTimeout(rebuild, 250);
});
$('searchInp').addEventListener('keydown', e => {
  if(e.key === 'Enter'){ e.preventDefault(); jumpMatch(e.shiftKey ? -1 : 1); }
});
$('prevBtn').addEventListener('click', () => jumpMatch(-1));
$('nextBtn').addEventListener('click', () => jumpMatch(1));
$('pauseBtn').addEventListener('click', () => {
  state.paused = !state.paused;
  const b = $('pauseBtn');
  b.textContent = state.paused ? '▶ 继续' : '⏸ 暂停';
  b.classList.toggle('active', state.paused);
  if(!state.paused) rebuild(); // 恢复时把缓冲内容同步到视图
});
$('clearBtn').addEventListener('click', () => {
  state.lines = [];
  state.matchEls = []; state.matchIdx = -1;
  logArea.innerHTML = '';
  updateLineCount(); updateMatchInfo();
});

// 滚动检测：贴底则自动滚，向上滚即停
logArea.addEventListener('scroll', () => {
  state.autoScroll = (logArea.scrollTop + logArea.clientHeight >= logArea.scrollHeight - 6);
});

// 全局快捷键
document.addEventListener('keydown', e => {
  const tag = e.target.tagName;
  if(tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
  if(e.code === 'Space'){ e.preventDefault(); $('pauseBtn').click(); }
  else if(e.key === 'ArrowDown' && state.search){ e.preventDefault(); jumpMatch(1); }
  else if(e.key === 'ArrowUp' && state.search){ e.preventDefault(); jumpMatch(-1); }
});

// 初始化
loadFiles();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    print(f"[log-viewer] 启动于 http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
