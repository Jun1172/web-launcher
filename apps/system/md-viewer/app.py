"""md-viewer —— Web Launcher 项目说明书
Markdown 文档浏览器：左侧目录树导航 + 右侧渲染阅读 + 本地图片离线加载。
单文件 HTTP 服务（ThreadingHTTPServer），前端 HTML/CSS/JS 全部内嵌，离线可用。

说明：marked.js 完整库体积较大且无法离线可靠内嵌，前端内置一个极简
Markdown 渲染器，支持标题 / 列表 / 任务列表 / 代码块 / 表格 / 引用 /
链接 / 图片 / 加粗 / 斜体 / 删除线 / 行内代码 / 水平线。
"""
import json
import os
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# 端口：优先读取 launcher 注入的环境变量，默认 8154
PORT = int(os.environ.get("LAUNCHER_APP_PORT", 8154))

# 应用根目录 & 文档根目录
BASE_DIR = Path(__file__).resolve().parent
DOCS_DIR = BASE_DIR / "docs"

# 目录树中允许展示的文档扩展名（图片在 Markdown 中引用即可，不入树）
ALLOWED_EXT = {".md", ".markdown"}

# 图片扩展名 -> Content-Type 映射
IMAGE_CT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".ico": "image/x-icon",
}

# docs/ 缺失时自动生成的示例 README（运行时兜底，存在则不覆盖）
SAMPLE_README = """# Web Launcher 项目说明书

这是自动生成的示例文档。把项目说明、应用文档或部署手册放进 `docs/` 目录即可在左侧目录树浏览。

## 快速开始

- 在 `docs/` 放入 Markdown 文档（`.md`）
- 在 `docs/images/` 放入图片，用相对路径 `![说明](images/xxx.png)` 引用
- 点击左侧目录树中的文件即可阅读

> 提示：支持子目录分类组织文档。
"""


def ensure_docs():
    """确保 docs 目录存在；若缺失则创建并放入示例 README.md。"""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    sample = DOCS_DIR / "README.md"
    if not sample.exists():
        sample.write_text(SAMPLE_README, encoding="utf-8")


def safe_join(rel_path):
    """把相对路径安全拼接到 docs/ 下，防止路径遍历。

    返回 (绝对 Path, 错误信息)；成功时错误为 None。
    """
    if not rel_path:
        return None, "缺少 path 参数"
    # 统一正斜杠并去掉前导斜杠
    rel = rel_path.replace("\\", "/").lstrip("/")
    # 禁止任何 .. 段
    if ".." in rel.split("/"):
        return None, "禁止访问上级目录"
    target = (DOCS_DIR / rel).resolve()
    # 关键安全校验：resolve 后必须仍在 docs 目录内
    try:
        target.relative_to(DOCS_DIR.resolve())
    except ValueError:
        return None, "路径越界"
    return target, None


def build_tree(rel_path=""):
    """递归构建 docs 目录树，返回嵌套结构。

    {
      "name": "docs",
      "path": "",
      "type": "dir",
      "children": [ {name,path,type,children}, ... ]
    }
    路径以 docs 根为基准，统一用正斜杠。目录在前、文件名按字母排序。
    """
    full = DOCS_DIR / rel_path if rel_path else DOCS_DIR
    node = {
        "name": rel_path.split("/")[-1] if rel_path else "docs",
        "path": rel_path,
        "type": "dir",
        "children": [],
    }
    try:
        entries = sorted(
            full.iterdir(),
            key=lambda p: (not p.is_dir(), p.name.lower()),
        )
    except OSError:
        entries = []
    for entry in entries:
        child_rel = f"{rel_path}/{entry.name}" if rel_path else entry.name
        if entry.is_dir():
            node["children"].append(build_tree(child_rel))
        elif entry.suffix.lower() in ALLOWED_EXT:
            node["children"].append({
                "name": entry.name,
                "path": child_rel,
                "type": "file",
                "children": [],
            })
    return node


# ============================== 内嵌前端 ==============================
# 使用原始字符串避免 JS 正则的反斜杠被 Python 转义；注意内部不能出现 """
HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>📚 Web Launcher 项目说明书</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0d1117;--panel:#161b22;--panel2:#1f2428;--border:#30363d;
  --text:#c9d1d9;--mute:#8b949e;--heading:#f0f6fc;--link:#58a6ff;
  --accent:#ec4899;--code:#f0883e;--ok:#3fb950;
}
html,body{height:100%}
body{font-family:system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  background:var(--bg);color:var(--text);line-height:1.6;-webkit-font-smoothing:antialiased}
.app{display:flex;height:100vh;overflow:hidden}

/* 侧栏 */
.sidebar{width:300px;flex-shrink:0;background:var(--panel);border-right:1px solid var(--border);
  overflow-y:auto;transition:transform .25s ease;z-index:30}
.sidebar-head{position:sticky;top:0;background:var(--panel);padding:16px 18px 12px;
  border-bottom:1px solid var(--border);font-weight:700;color:var(--heading);font-size:15px}
.sidebar-head .sub{display:block;font-weight:400;color:var(--mute);font-size:11px;margin-top:3px}
#tree{padding:8px 8px 24px}
details>summary{list-style:none;cursor:pointer;padding:6px 10px;border-radius:6px;
  display:flex;align-items:center;gap:6px;color:var(--text);font-size:13.5px;user-select:none}
details>summary::-webkit-details-marker{display:none}
details>summary:hover{background:#1f2428}
.arrow{display:inline-block;width:12px;color:var(--mute);transition:transform .15s;font-size:10px}
details[open]>summary .arrow{transform:rotate(90deg)}
.tree-folder .fname{font-weight:600}
.tree-children{margin-left:14px;border-left:1px solid #21262d;padding-left:2px}
.tree-file{padding:6px 10px 6px 22px;border-radius:6px;cursor:pointer;font-size:13.5px;
  color:#b1bac4;display:flex;align-items:center;gap:7px;word-break:break-all}
.tree-file:hover{background:#1f2428;color:var(--text)}
.tree-file.active{background:#2d333b;color:var(--accent);box-shadow:inset 2px 0 0 var(--accent)}
.tree-file .ic{opacity:.7;font-size:13px}

/* 主区 */
.main{flex:1;display:flex;flex-direction:column;min-width:0}
.topbar{display:flex;align-items:center;gap:10px;padding:12px 22px;border-bottom:1px solid var(--border);
  background:var(--panel);min-height:50px}
.menu-btn{display:none;background:none;border:1px solid var(--border);color:var(--text);
  width:36px;height:34px;border-radius:8px;font-size:17px;cursor:pointer}
.breadcrumb{font-size:13px;color:var(--mute);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.breadcrumb .bc-root{color:var(--accent);font-weight:600}
.breadcrumb .bc-sep{margin:0 7px;color:#484f58}
.breadcrumb .bc-item{color:var(--text)}
.content{flex:1;overflow-y:auto;padding:32px 24px 80px}
.md{max-width:860px;margin:0 auto}

/* Markdown 排版 */
.md h1,.md h2,.md h3,.md h4,.md h5,.md h6{color:var(--heading);line-height:1.3;margin:30px 0 14px;font-weight:700}
.md h1{font-size:30px;padding-bottom:.3em;border-bottom:1px solid var(--border)}
.md h2{font-size:24px;padding-bottom:.3em;border-bottom:1px solid var(--border)}
.md h3{font-size:20px}
.md h4{font-size:17px}
.md p{margin:14px 0}
.md a{color:var(--link);text-decoration:none}
.md a:hover{text-decoration:underline}
.md strong{color:var(--heading);font-weight:700}
.md ul,.md ol{margin:14px 0;padding-left:26px}
.md li{margin:6px 0}
.md li input[type=checkbox]{margin-right:6px;vertical-align:middle}
.md blockquote{margin:16px 0;padding:6px 16px;border-left:3px solid var(--accent);
  background:#161b22;color:var(--mute);border-radius:0 6px 6px 0}
.md blockquote p{margin:8px 0}
.md code{font-family:"SFMono-Regular",Consolas,"Liberation Mono",Menlo,monospace;font-size:88%;
  background:var(--panel2);padding:2px 6px;border-radius:5px;color:var(--code)}
.md pre{background:var(--panel2);border:1px solid var(--border);border-radius:8px;padding:14px 16px;
  overflow-x:auto;margin:16px 0}
.md pre code{background:none;padding:0;color:#c9d1d9;font-size:87%;line-height:1.55}
.md table{border-collapse:collapse;width:100%;margin:16px 0;display:block;overflow-x:auto}
.md th,.md td{border:1px solid var(--border);padding:8px 13px;text-align:left}
.md th{background:var(--panel2);color:var(--heading);font-weight:600}
.md tr:nth-child(2n){background:rgba(255,255,255,.018)}
.md img{max-width:100%;border-radius:8px;border:1px solid var(--border);margin:10px 0}
.md hr{border:0;border-top:1px solid var(--border);margin:26px 0}
.md del{color:var(--mute)}

/* 状态 */
.loading,.empty,.error{padding:60px 20px;text-align:center;color:var(--mute)}
.error{color:#f85149}

/* 移动端遮罩 */
.backdrop{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:25}

@media (max-width:820px){
  .sidebar{position:fixed;top:0;left:0;height:100vh;transform:translateX(-100%);box-shadow:2px 0 20px rgba(0,0,0,.4)}
  .sidebar.open{transform:translateX(0)}
  .menu-btn{display:inline-flex;align-items:center;justify-content:center}
  .backdrop.show{display:block}
  .content{padding:22px 16px 60px}
}
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar" id="sidebar">
    <div class="sidebar-head">📚 Web Launcher 项目说明书
      <span class="sub">md-viewer · :__PORT__</span>
    </div>
    <div id="tree"></div>
  </aside>
  <div class="backdrop" id="backdrop" onclick="toggleSidebar(false)"></div>
  <main class="main">
    <div class="topbar">
      <button class="menu-btn" onclick="toggleSidebar()">☰</button>
      <div class="breadcrumb" id="breadcrumb"></div>
    </div>
    <div class="content"><div class="md" id="content"><div class="loading">加载中…</div></div></div>
  </main>
</div>

<script>
// ===================== 极简 Markdown 渲染器 =====================
// 说明：marked.js 完整库无法离线可靠内嵌，此处自行实现极简渲染器。
// 当前阅读的文件路径（相对 docs 根），用于解析图片 / 内部链接的相对路径
var currentFile = '';

function escapeHtml(s){
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
// 属性专用转义：输入已经过 escapeHtml，这里只额外处理双引号
function q(s){ return String(s).replace(/"/g,'&quot;'); }

function fileDir(path){
  var p = String(path||'').replace(/\\/g,'/');
  var i = p.lastIndexOf('/');
  return i < 0 ? '' : p.slice(0, i);
}
// 图片相对路径 -> /api/image?path=
function resolveImg(src){
  if(/^(https?:|data:|\/\/)/i.test(src)) return src;
  var n = src.replace(/\\/g,'/');
  var resolved = n.charAt(0)==='/' ? n.slice(1) : (function(){
    var d = fileDir(currentFile);
    return d ? d + '/' + n : n;
  })();
  return '/api/image?path=' + encodeURIComponent(resolved);
}
// 内部 markdown 链接相对路径 -> 相对 docs 根
function resolveMd(src){
  var n = src.replace(/\\/g,'/');
  if(n.charAt(0)==='/') return n.slice(1);
  var d = fileDir(currentFile);
  return d ? d + '/' + n : n;
}

// 行内渲染：抽出行内代码 -> 转义 -> 强调 -> 图片 -> 链接 -> 还原代码
function renderInline(text){
  var codes = [];
  text = text.replace(/`([^`]+)`/g, function(m,c){ codes.push(c); return '\u0000C'+(codes.length-1)+'\u0000'; });
  text = escapeHtml(text);
  text = text.replace(/\*\*([^\s*][^*]*?)\*\*/g, '<strong>$1</strong>');
  text = text.replace(/__([^\s_][^_]*?)__/g, '<strong>$1</strong>');
  text = text.replace(/(^|[^\w*])\*([^\s*][^*]*?)\*(?=[^\w*]|$)/g, '$1<em>$2</em>');
  text = text.replace(/~~([^\s~][^~]*?)~~/g, '<del>$1</del>');
  // 图片（必须在链接之前处理，避免 [alt](url) 被当链接）
  text = text.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)/g, function(m,alt,url,title){
    return '<img src="'+resolveImg(url)+'" alt="'+q(alt)+'"'+(title?' title="'+q(title)+'"':'')+' loading="lazy">';
  });
  // 链接
  text = text.replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)/g, function(m,t,url,title){
    if(/^(https?:|data:|\/\/|mailto:|tel:|#)/i.test(url)){
      return '<a href="'+q(url)+'"'+(title?' title="'+q(title)+'"':'')+' target="_blank" rel="noopener">'+t+'</a>';
    }
    if(/\.md$|\.markdown$/i.test(url)){
      return '<a href="javascript:void(0)" data-md="'+q(resolveMd(url))+'"'+(title?' title="'+q(title)+'"':'')+' onclick="loadFile(this.dataset.md)">'+t+'</a>';
    }
    return '<a href="'+q(url)+'"'+(title?' title="'+q(title)+'"':'')+' target="_blank" rel="noopener">'+t+'</a>';
  });
  // 还原行内代码
  text = text.replace(/\u0000C(\d+)\u0000/g, function(m,i){ return '<code>'+escapeHtml(codes[+i])+'</code>'; });
  return text;
}

// 块级渲染
function renderMarkdown(src){
  src = String(src||'').replace(/\r\n/g,'\n').replace(/\r/g,'\n');
  var lines = src.split('\n');
  var out = [];
  var i = 0;
  var listType = null;   // 'ul' | 'ol' | null
  var para = [];

  function flushPara(){
    if(para.length){ out.push('<p>'+renderInline(para.join(' '))+'</p>'); para = []; }
  }
  function closeList(){
    if(listType){ out.push('</'+listType+'>'); listType = null; }
  }

  while(i < lines.length){
    var line = lines[i];

    // 代码围栏
    var fence = line.match(/^(\s*)(```|~~~)(.*)$/);
    if(fence){
      flushPara(); closeList();
      var lang = fence[3].trim();
      var code = [];
      i++;
      while(i < lines.length && !/^\s*(```|~~~)/.test(lines[i])){ code.push(lines[i]); i++; }
      if(i < lines.length) i++; // 跳过结束围栏
      out.push('<pre><code class="language-'+q(lang)+'">'+escapeHtml(code.join('\n'))+'</code></pre>');
      continue;
    }

    // 标题
    var h = line.match(/^(#{1,6})\s+(.*)$/);
    if(h){
      flushPara(); closeList();
      var lvl = h[1].length;
      var txt = renderInline(h[2].replace(/\s+#+\s*$/,''));
      out.push('<h'+lvl+'>'+txt+'</h'+lvl+'>');
      i++; continue;
    }

    // 水平分割线
    if(/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)){
      flushPara(); closeList(); out.push('<hr>'); i++; continue;
    }

    // 表格：当前行含 | 且下一行是分隔行（仅由 : | - 空格组成且含 -）
    var next = i+1 < lines.length ? lines[i+1] : '';
    if(line.indexOf('|')!==-1 && /^[ \t]*\|?[ \t:|\-]+$/.test(next) && next.indexOf('-')!==-1){
      flushPara(); closeList();
      var parseRow = function(l){
        return l.trim().replace(/^\|/,'').replace(/\|\s*$/,'').split('|').map(function(s){return s.trim();});
      };
      var headers = parseRow(line);
      var sep = parseRow(next);
      var aligns = sep.map(function(s){
        if(/^-+:$/.test(s)) return 'right';
        if(/^:-+$/.test(s)) return 'left';
        if(/^:-+:$/.test(s)) return 'center';
        return null;
      });
      i += 2;
      var rows = [];
      while(i < lines.length && lines[i].trim()!=='' && lines[i].indexOf('|')!==-1){
        rows.push(parseRow(lines[i])); i++;
      }
      var t = '<table><thead><tr>';
      headers.forEach(function(hh,idx){
        var a = aligns[idx];
        t += '<th'+(a?' style="text-align:'+a+'"':'')+'>'+renderInline(hh)+'</th>';
      });
      t += '</tr></thead><tbody>';
      rows.forEach(function(r){
        t += '<tr>';
        headers.forEach(function(_,idx){
          var a = aligns[idx];
          t += '<td'+(a?' style="text-align:'+a+'"':'')+'>'+renderInline(r[idx]||'')+'</td>';
        });
        t += '</tr>';
      });
      t += '</tbody></table>';
      out.push(t);
      continue;
    }

    // 引用块
    if(/^\s*>/.test(line)){
      flushPara(); closeList();
      var quote = [];
      while(i < lines.length && /^\s*>/.test(lines[i])){
        quote.push(lines[i].replace(/^\s*>\s?/,''));
        i++;
      }
      out.push('<blockquote>'+renderMarkdown(quote.join('\n'))+'</blockquote>');
      continue;
    }

    // 列表
    var li = line.match(/^(\s*)([-*+]|\d+\.)\s+(.*)$/);
    if(li){
      flushPara();
      var wantType = /\d+\./.test(li[2]) ? 'ol' : 'ul';
      if(listType !== wantType){ closeList(); listType = wantType; out.push('<'+listType+'>'); }
      var item = li[3];
      var task = item.match(/^\[([ xX])\]\s+(.*)$/);
      if(task){
        var checked = task[1].toLowerCase()==='x';
        out.push('<li><input type="checkbox" disabled'+(checked?' checked':'')+'> '+renderInline(task[2])+'</li>');
      } else {
        out.push('<li>'+renderInline(item)+'</li>');
      }
      i++; continue;
    }

    // 空行
    if(line.trim()===''){ flushPara(); closeList(); i++; continue; }

    // 段落
    para.push(line.trim());
    i++;
  }
  flushPara(); closeList();
  return out.join('\n');
}

// ===================== 目录树 =====================
function renderTreeNodes(nodes, container){
  container.innerHTML = '';
  nodes.forEach(function(node){
    if(node.type === 'dir'){
      var det = document.createElement('details');
      det.open = true;
      var sum = document.createElement('summary');
      sum.className = 'tree-folder';
      sum.innerHTML = '<span class="arrow">▶</span><span>📁</span> <span class="fname">'+escapeHtml(node.name)+'</span>';
      det.appendChild(sum);
      var child = document.createElement('div');
      child.className = 'tree-children';
      det.appendChild(child);
      renderTreeNodes(node.children, child);
      container.appendChild(det);
    } else {
      var f = document.createElement('div');
      f.className = 'tree-file';
      f.dataset.path = node.path;
      f.innerHTML = '<span class="ic">📄</span>'+escapeHtml(node.name);
      f.onclick = function(){ loadFile(node.path); };
      container.appendChild(f);
    }
  });
}

function findFirstFile(node){
  for(var k=0;k<node.children.length;k++){
    var c = node.children[k];
    if(c.type === 'file') return c.path;
    if(c.type === 'dir'){ var f = findFirstFile(c); if(f) return f; }
  }
  return null;
}

// ===================== 加载与渲染 =====================
function renderBreadcrumb(path){
  var bc = document.getElementById('breadcrumb');
  if(!path){ bc.innerHTML = ''; return; }
  var html = '<span class="bc-root">📖 docs</span>';
  path.split('/').forEach(function(seg){
    html += '<span class="bc-sep">/</span><span class="bc-item">'+escapeHtml(seg)+'</span>';
  });
  bc.innerHTML = html;
}

function loadFile(path){
  currentFile = path || '';
  renderBreadcrumb(path);
  document.querySelectorAll('.tree-file').forEach(function(el){
    el.classList.toggle('active', el.dataset.path === path);
  });
  if(window.innerWidth <= 820) toggleSidebar(false);
  var content = document.getElementById('content');
  content.className = 'md';
  content.innerHTML = '<div class="loading">加载中…</div>';
  fetch('/api/file?path=' + encodeURIComponent(path))
    .then(function(r){ return r.json(); })
    .then(function(data){
      if(data.error){ content.innerHTML = '<div class="error">⚠️ '+escapeHtml(data.error)+'</div>'; return; }
      content.innerHTML = renderMarkdown(data.content);
      content.scrollTop = 0;
    })
    .catch(function(e){
      content.innerHTML = '<div class="error">⚠️ 加载失败：'+escapeHtml(e.message)+'</div>';
    });
}

function toggleSidebar(force){
  var sb = document.getElementById('sidebar');
  var bd = document.getElementById('backdrop');
  var open = (typeof force === 'boolean') ? force : !sb.classList.contains('open');
  sb.classList.toggle('open', open);
  bd.classList.toggle('show', open);
}

function init(){
  fetch('/api/tree')
    .then(function(r){ return r.json(); })
    .then(function(tree){
      renderTreeNodes(tree.children || [], document.getElementById('tree'));
      var first = findFirstFile(tree);
      if(first) loadFile(first);
      else document.getElementById('content').innerHTML = '<div class="empty">docs 目录为空，放入 .md 文档试试</div>';
    })
    .catch(function(e){
      document.getElementById('content').innerHTML = '<div class="error">⚠️ 目录加载失败：'+escapeHtml(e.message)+'</div>';
    });
}
init();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    # 静态响应工具方法
    def _send(self, body, ctype, code=200, cache="no-store"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8", code)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            self._send(HTML.replace("__PORT__", str(PORT)), "text/html; charset=utf-8")
        elif path == "/api/tree":
            self._json(build_tree())
        elif path == "/api/file":
            rel = qs.get("path", [None])[0]
            target, err = safe_join(rel)
            if err:
                self._json({"error": err}, 400)
                return
            if not target.is_file():
                self._json({"error": "文件不存在"}, 404)
                return
            try:
                content = target.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = target.read_bytes().decode("utf-8", errors="replace")
            self._json({"path": rel, "content": content})
        elif path == "/api/image":
            rel = qs.get("path", [None])[0]
            target, err = safe_join(rel)
            if err:
                self._send(err, "text/plain; charset=utf-8", 400)
                return
            if not target.is_file():
                self._send("图片不存在", "text/plain; charset=utf-8", 404)
                return
            ctype = IMAGE_CT.get(target.suffix.lower(), "application/octet-stream")
            self._send(target.read_bytes(), ctype, 200, "no-cache")
        else:
            self._send("Not Found", "text/plain; charset=utf-8", 404)

    def log_message(self, *a):
        pass  # 静默访问日志


if __name__ == "__main__":
    ensure_docs()
    print(f"📖 md-viewer → http://127.0.0.1:{PORT}")
    print(f"   文档目录: {DOCS_DIR}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
