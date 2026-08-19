import json
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

BASE = Path(__file__).parent.parent.parent
CONFIG_JSON = BASE / "config.json"

def load_config():
    if CONFIG_JSON.exists():
        try:
            return json.loads(CONFIG_JSON.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}

CONFIG = load_config()
LAUNCHER_HOST = CONFIG.get("launcher", {}).get("host", "127.0.0.1")
LAUNCHER_PORT = CONFIG.get("launcher", {}).get("port", 8000)
PORT = CONFIG.get("ports", {}).get("store", 8100)
LAUNCHER_URL = f"http://{LAUNCHER_HOST}:{LAUNCHER_PORT}"

# ── 旗舰级毛玻璃 UI 模板 ──
HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>🛒 应用商店</title>
<style>
:root {
    --glass-bg: rgba(255, 255, 255, 0.05);
    --glass-bg-hover: rgba(255, 255, 255, 0.1);
    --glass-border: rgba(255, 255, 255, 0.08);
    --glass-border-hover: rgba(255, 255, 255, 0.2);
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
        radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.2) 0px, transparent 50%),
        radial-gradient(at 100% 0%, rgba(168, 85, 247, 0.15) 0px, transparent 50%),
        radial-gradient(at 100% 100%, rgba(236, 72, 153, 0.15) 0px, transparent 50%);
    background-attachment: fixed;
    min-height: 100vh;
    padding: 24px;
}
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }

/* ── 头部与搜索 ── */
.header { display:flex; flex-direction:column; gap:16px; margin-bottom:24px; }
.header-top { display:flex; justify-content:space-between; align-items:center; padding:0 4px; }
.header h1 { font-size:22px; font-weight:700; letter-spacing:-0.5px; display:flex; align-items:center; gap:10px; }
.header .sub { font-size:13px; color:var(--text-secondary); margin-top:4px; }

.refresh-btn {
    background: var(--glass-bg); border: 1px solid var(--glass-border); color: var(--text-primary);
    border-radius: 10px; padding: 8px 14px; font-size: 13px; font-weight: 500; cursor: pointer;
    display: flex; align-items: center; gap: 6px; transition: all 0.2s ease;
}
.refresh-btn:hover { background: var(--glass-bg-hover); border-color: var(--glass-border-hover); transform: translateY(-1px); }

.search-box { position: relative; }
.search-box::before {
    content: '🔍'; position: absolute; left: 14px; top: 50%; transform: translateY(-50%);
    font-size: 14px; opacity: 0.5; pointer-events: none;
}
.search {
    width: 100%; padding: 12px 16px 12px 40px;
    background: var(--glass-bg); border: 1px solid var(--glass-border);
    border-radius: 14px; color: var(--text-primary); font-size: 14px;
    outline: none; transition: all 0.2s ease;
}
.search::placeholder { color: var(--text-secondary); }
.search:focus { background: rgba(255,255,255,0.08); border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-glow); }

/* ── Tabs 分段控制器 ── */
.tabs {
    display: flex; gap: 4px; background: rgba(0,0,0,0.2); border: 1px solid var(--glass-border);
    border-radius: 14px; padding: 4px; margin-bottom: 20px; width: fit-content;
}
.tab {
    padding: 8px 16px; border-radius: 10px; font-size: 13px; font-weight: 500;
    color: var(--text-secondary); cursor: pointer; transition: all 0.25s ease;
    display: flex; align-items: center; gap: 6px;
}
.tab:hover { color: var(--text-primary); background: rgba(255,255,255,0.05); }
.tab.active { background: var(--glass-bg-hover); color: var(--text-primary); font-weight: 600; box-shadow: 0 2px 8px rgba(0,0,0,0.2); }
.tab .count {
    background: rgba(255,255,255,0.1); padding: 1px 7px; border-radius: 8px; font-size: 11px; font-weight: 600;
}
.tab.active .count { background: var(--accent); color: #fff; }

/* ── 应用列表与卡片 ── */
.app-list { display:flex; flex-direction:column; gap:12px; }
.app-card {
    display: flex; align-items: center; gap: 16px; padding: 16px;
    background: var(--glass-bg); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
    border: 1px solid var(--glass-border); border-radius: 18px;
    transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
    position: relative; overflow: hidden;
}
.app-card::before {
    content: ''; position: absolute; top: 0; left: -100%; width: 50%; height: 100%;
    background: linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent);
    transform: skewX(-25deg); transition: left 0.5s;
}
.app-card:hover::before { left: 150%; }
.app-card:hover { background: var(--glass-bg-hover); border-color: var(--glass-border-hover); transform: translateY(-3px); box-shadow: 0 12px 24px rgba(0,0,0,0.2); }

.app-icon {
    width: 56px; height: 56px; border-radius: 16px; display: flex; align-items: center; justify-content: center;
    font-size: 28px; flex-shrink: 0;
    border: 1px solid rgba(255,255,255,0.1);
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.1);
}
.app-info { flex: 1; min-width: 0; }
.app-name { font-size: 15px; font-weight: 600; display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.app-tag {
    font-size: 10px; padding: 2px 8px; border-radius: 6px; font-weight: 600;
    background: rgba(52, 211, 153, 0.15); color: var(--success); border: 1px solid rgba(52, 211, 153, 0.2);
}
.app-desc {
    font-size: 12.5px; color: var(--text-secondary); line-height: 1.5;
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.app-meta { font-size: 11.5px; color: var(--text-secondary); margin-top: 6px; opacity: 0.7; font-variant-numeric: tabular-nums; }
.app-meta .ver-up { color: var(--warning); font-weight: 600; }

.app-actions { flex-shrink: 0; display: flex; gap: 8px; align-items: center; }
.btn {
    padding: 8px 16px; border: 0; border-radius: 10px; font-size: 12.5px; font-weight: 600;
    cursor: pointer; transition: all 0.2s ease; display: flex; align-items: center; gap: 4px;
}
.btn:active { transform: scale(0.95); }
.btn-install { background: var(--accent); color: #fff; box-shadow: 0 4px 12px var(--accent-glow); }
.btn-install:hover { background: #6366f1; transform: translateY(-1px); }
.btn-upgrade { background: var(--warning); color: #0f172a; }
.btn-upgrade:hover { background: #f59e0b; transform: translateY(-1px); }
.btn-uninstall { background: rgba(248, 113, 113, 0.15); color: var(--danger); border: 1px solid rgba(248, 113, 113, 0.2); }
.btn-uninstall:hover { background: rgba(248, 113, 113, 0.25); }
.btn-disabled { background: rgba(255,255,255,0.05); color: var(--text-secondary); cursor: not-allowed; border: 1px solid var(--glass-border); }
.btn-system { background: rgba(52, 211, 153, 0.1); color: var(--success); border: 1px solid rgba(52, 211, 153, 0.2); cursor: default; }
.btn-info {
    background: rgba(255,255,255,0.05); color: var(--text-primary); border: 1px solid var(--glass-border);
    border-radius: 10px; padding: 8px 12px; font-size: 13px;
}
.btn-info:hover { background: var(--glass-bg-hover); border-color: var(--glass-border-hover); }
.btn:disabled { pointer-events: none; opacity: 0.6; }

/* ── 空状态与错误 ── */
.empty, .error { text-align: center; padding: 60px 20px; border-radius: 18px; margin-top: 20px; }
.empty { background: var(--glass-bg); border: 1px dashed var(--glass-border); color: var(--text-secondary); }
.empty-icon { font-size: 48px; margin-bottom: 12px; opacity: 0.4; }
.error { background: rgba(248, 113, 113, 0.1); border: 1px solid rgba(248, 113, 113, 0.2); color: var(--danger); }

/* ── 弹窗 (Modal) ── */
.modalMask {
    position: fixed; inset: 0; z-index: 999; background: rgba(0,0,0,0.6);
    backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
    display: none; align-items: center; justify-content: center; padding: 24px;
    animation: fade .2s ease;
}
.modalMask.show { display: flex; }
@keyframes fade { from { opacity: 0; } }

.modal {
    width: min(600px, 92vw); max-height: 85vh;
    background: rgba(20, 25, 45, 0.85); backdrop-filter: blur(30px); -webkit-backdrop-filter: blur(30px);
    border: 1px solid var(--glass-border); border-radius: 22px;
    padding: 24px; display: flex; flex-direction: column; gap: 18px;
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255,255,255,0.08);
    animation: pop .3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
@keyframes pop { from { transform: scale(0.95) translateY(10px); opacity: 0; } }

.modalHead { display: flex; align-items: flex-start; gap: 16px; }
.modalHead .bigIcon {
    width: 64px; height: 64px; border-radius: 18px; font-size: 32px;
    display: flex; align-items: center; justify-content: center; flex-shrink: 0;
    border: 1px solid rgba(255,255,255,0.1); box-shadow: inset 0 1px 0 rgba(255,255,255,0.1);
}
.modalHead .titleRow { flex: 1; min-width: 0; }
.modalHead h2 { font-size: 18px; font-weight: 600; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.modalHead .metaTop { font-size: 12.5px; color: var(--text-secondary); margin-top: 4px; }
.modalHead .x {
    background: transparent; border: 0; color: var(--text-secondary); font-size: 24px; cursor: pointer;
    padding: 4px; border-radius: 8px; line-height: 1; transition: all 0.2s;
}
.modalHead .x:hover { background: rgba(255,255,255,0.1); color: var(--text-primary); }

.verGrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; }
.verCell {
    background: rgba(0,0,0,0.2); border: 1px solid var(--glass-border); border-radius: 12px; padding: 12px;
}
.verCell .lb { font-size: 10px; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px; font-weight: 600; }
.verCell .vl { font-size: 15px; font-weight: 600; font-variant-numeric: tabular-nums; }
.verCell .sub { font-size: 11px; color: var(--text-secondary); margin-top: 4px; }

.sectionBox {
    background: rgba(0,0,0,0.2); border: 1px solid var(--glass-border); border-radius: 12px; padding: 14px;
}
.sectionBox h4 { font-size: 12px; font-weight: 600; color: var(--text-secondary); margin-bottom: 10px; text-transform: uppercase; letter-spacing: 0.5px; }
.clArea { max-height: 180px; overflow-y: auto; font-size: 12.5px; line-height: 1.8; color: var(--text-secondary); }
.clArea ul { padding-left: 18px; }

.modalFoot { display: flex; justify-content: flex-end; gap: 10px; margin-top: auto; padding-top: 10px; }
.btnGhost {
    background: rgba(255,255,255,0.08); color: var(--text-primary); border: 1px solid var(--glass-border);
    padding: 9px 18px; border-radius: 10px; font-size: 13px; cursor: pointer; font-weight: 600; transition: all 0.2s;
}
.btnGhost:hover { background: var(--glass-bg-hover); border-color: var(--glass-border-hover); }

/* ── 确认对话框特化 ── */
.confirm-modal { width: min(400px, 90vw); }
.confirm-modal h2 { font-size: 17px; }
.confirm-modal .msg { font-size: 13.5px; line-height: 1.7; color: var(--text-secondary); white-space: pre-line; margin: 8px 0; }
.btnPri {
    background: var(--danger); color: #fff; border: 0; padding: 9px 20px; border-radius: 10px;
    font-size: 13px; cursor: pointer; font-weight: 600; transition: all 0.2s;
}
.btnPri:hover { background: #ef4444; transform: translateY(-1px); box-shadow: 0 4px 12px rgba(248, 113, 113, 0.3); }

/* ── 全局 Loading ── */
.__busy {
    position: fixed; left: 50%; top: 24px; transform: translateX(-50%);
    padding: 10px 20px; background: var(--accent); color: #fff; border-radius: 12px;
    font-size: 13px; font-weight: 600; z-index: 9999;
    box-shadow: 0 8px 24px var(--accent-glow); animation: pop .3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
</style>
</head>
<body>

<div class="header">
  <div class="header-top">
    <div>
      <h1>🛒 应用商店</h1>
      <div class="sub" id="sub">正在加载…</div>
    </div>
    <button class="refresh-btn" onclick="loadData()">⟳ 刷新</button>
  </div>
  
  <div class="tabs">
    <div class="tab active" data-tab="all" onclick="switchTab('all')">全部 <span class="count" id="cntAll">0</span></div>
    <div class="tab" data-tab="installed" onclick="switchTab('installed')">已安装 <span class="count" id="cntInstalled">0</span></div>
    <div class="tab" data-tab="updates" onclick="switchTab('updates')">可更新 <span class="count" id="cntUpdates">0</span></div>
  </div>

  <div class="search-box">
    <input class="search" id="search" placeholder="搜索应用名称或描述…" oninput="filterApps()">
  </div>
</div>

<div class="app-list" id="list"></div>

<!-- 确认弹窗 -->
<div class="modalMask" id="confirmMask" role="dialog">
  <div class="modal confirm-modal">
    <div class="modalHead" style="margin-bottom: 8px;">
      <h2 id="confirmTitle" style="margin:0;">确认操作</h2>
    </div>
    <div class="msg" id="confirmMsg"></div>
    <div class="modalFoot">
      <button class="btnGhost" id="confirmCancel">取消</button>
      <button class="btnPri" id="confirmOk">确认执行</button>
    </div>
  </div>
</div>

<!-- 详情弹窗 -->
<div class="modalMask" id="detailMask" role="dialog">
  <div class="modal" id="detailBox">
    <div class="modalHead">
      <div class="bigIcon" id="dIcon">📦</div>
      <div class="titleRow">
        <h2 id="dName">应用名称</h2>
        <div class="metaTop" id="dMeta">版本信息…</div>
      </div>
      <button class="x" onclick="closeDetail()" aria-label="关闭">×</button>
    </div>
    <div class="verGrid" id="dVerGrid"></div>
    <div class="sectionBox">
      <h4>📋 更新说明 (Changelog)</h4>
      <div class="clArea"><ul id="dChangelog"></ul></div>
    </div>
    <div class="modalFoot">
      <button class="btnGhost" onclick="closeDetail()">关闭</button>
    </div>
  </div>
</div>

<script>
const LAUNCHER_URL = window.LAUNCHER_URL || '';
let repoApps=[], installedApps=[], currentTab='all', searchQuery='';

async function api(path){
  const r = await fetch(LAUNCHER_URL + path);
  return r.json();
}

/* ── 工具函数 ── */
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function clUL(text){
  if(!text) return '<li style="opacity:.4">暂无更新说明</li>';
  return String(text).split('\n').map(s=>s.trim().replace(/^[-•*]\s*/,'')).filter(Boolean)
    .map(s=>'<li>'+esc(s)+'</li>').join('') || '<li style="opacity:.4">暂无更新说明</li>';
}
function fmtTime(s){if(!s) return '—'; return s.replace('T',' ').slice(0,16);}
function fmtSize(n){if(!n) return ''; return n<1024?(n+' B'):(n/1024).toFixed(1)+' KB';}

function setBusy(msg){
  document.querySelectorAll('button').forEach(b => b.disabled = true);
  if(document.getElementById('__busy')) return;
  const label = document.createElement('div'); label.id = '__busy'; label.textContent = msg;
  document.body.appendChild(label);
}
function clearBusy(){
  document.querySelectorAll('button').forEach(b => b.disabled = false);
  document.getElementById('__busy')?.remove();
}

function showConfirm(title, msg){
  return new Promise(resolve => {
    document.getElementById('confirmTitle').textContent = title;
    document.getElementById('confirmMsg').textContent = msg;
    const mask = document.getElementById('confirmMask');
    mask.classList.add('show');
    const ok = document.getElementById('confirmOk');
    const cancel = document.getElementById('confirmCancel');
    const cleanup = (result) => {
      mask.classList.remove('show');
      ok.onclick = null; cancel.onclick = null;
      resolve(result);
    };
    ok.onclick = () => cleanup(true);
    cancel.onclick = () => cleanup(false);
  });
}

/* ── 主数据加载 ── */
async function loadData(){
  document.getElementById('sub').textContent = '正在连接 Launcher 获取数据…';
  try{
    const [repo, apps] = await Promise.all([api('/api/repo'), api('/api/apps')]);
    if(repo.error){ showError('连不上仓库：' + repo.error); return; }
    
    installedApps = apps;
    repoApps = repo.apps.map(m => {
      const local = apps.find(a => a.id === m.id);
      const system = !!(local && local.system);
      return {
        ...m,
        installed: !!local,
        system,
        upgradable: !!local && compareVer(m.version, local.version) > 0,
        localVersion: local ? local.version : null,
        localReleased: local ? local.released : null,
      };
    });
    
    const installedCount = installedApps.filter(a => !a.system).length;
    document.getElementById('sub').textContent = `共 ${repoApps.length} 个应用 · 已安装 ${installedCount} 个`;
    updateCounts();
    render();
  } catch(e) {
    showError('加载失败：' + e.message + '<br>请确认 Launcher 正在运行');
  }
}

function compareVer(a, b){
  const pa = (a||'0').split('.').map(n => parseInt(n)||0);
  const pb = (b||'0').split('.').map(n => parseInt(n)||0);
  for(let i=0; i<3; i++){
    if((pa[i]||0) > (pb[i]||0)) return 1;
    if((pa[i]||0) < (pb[i]||0)) return -1;
  }
  return 0;
}

function updateCounts(){
  document.getElementById('cntAll').textContent = repoApps.length;
  document.getElementById('cntInstalled').textContent = repoApps.filter(a => a.installed).length;
  document.getElementById('cntUpdates').textContent = repoApps.filter(a => a.upgradable).length;
}

function switchTab(t){
  currentTab = t;
  document.querySelectorAll('.tab').forEach(el => el.classList.toggle('active', el.dataset.tab === t));
  render();
}

function filterApps(){
  searchQuery = document.getElementById('search').value.toLowerCase();
  render();
}

function render(){
  let list = repoApps;
  if(currentTab === 'installed') list = list.filter(a => a.installed);
  else if(currentTab === 'updates') list = list.filter(a => a.upgradable);
  
  if(searchQuery) {
    list = list.filter(a => a.name.toLowerCase().includes(searchQuery) || (a.changelog && a.changelog.toLowerCase().includes(searchQuery)));
  }
  
  const box = document.getElementById('list');
  if(!list.length){
    const messages = {
      all: '还没有应用，去发布第一个吧 🚀',
      installed: '没有安装任何应用',
      updates: '所有应用都是最新的 ✨'
    };
    box.innerHTML = `<div class="empty"><div class="empty-icon">📦</div><div class="empty-text">${messages[currentTab] || '未找到匹配的应用'}</div></div>`;
    return;
  }
  
  box.innerHTML = '';
  list.forEach(app => box.appendChild(renderCard(app)));
}

/* ── 应用卡片渲染 ── */
function renderCard(app){
  const d = document.createElement('div'); d.className = 'app-card';
  const tag = app.system ? '<span class="app-tag">系统</span>' : '';
  
  let verHtml = '';
  if(app.installed) {
    if(app.upgradable) {
      verHtml = `<span class="ver-up">v${app.localVersion||'?'} → v${app.version}</span>`;
    } else {
      verHtml = `<span style="opacity:.6">v${app.version}</span>`;
    }
  } else {
    verHtml = `<span style="opacity:.6">v${app.version}</span>`;
  }
  
  const desc = esc(app.changelog || '暂无详细描述');
  let action = '';
  
  if(app.system && app.installed){
    action = app.upgradable
      ? `<button class="btn btn-upgrade" data-action="upgrade" data-id="${app.id}">⬆ 升级</button>`
      : `<button class="btn btn-system" disabled>✓ 系统应用</button>`;
  } else if(!app.installed){
    action = `<button class="btn btn-install" data-action="install" data-id="${app.id}">⬇ 安装</button>`;
  } else if(app.upgradable){
    action = `
      <button class="btn btn-upgrade" data-action="upgrade" data-id="${app.id}">⬆ 升级</button>
      <button class="btn btn-uninstall" data-action="uninstall" data-id="${app.id}">✕ 卸载</button>`;
  } else {
    action = `
      <button class="btn btn-disabled" disabled>✓ 已安装</button>
      <button class="btn btn-uninstall" data-action="uninstall" data-id="${app.id}">✕ 卸载</button>`;
  }
  
  d.innerHTML = `
    <div class="app-icon" style="background:linear-gradient(135deg, ${app.color}40, ${app.color}15)">${app.icon || '📦'}</div>
    <div class="app-info">
      <div class="app-name">${esc(app.name)} ${tag}</div>
      <div class="app-desc" title="${esc(app.changelog || '')}">${desc}</div>
      <div class="app-meta">${verHtml} · ${fmtSize(app.size)}</div>
    </div>
    <div class="app-actions">
      <button class="btn-info" data-action="detail" data-id="${app.id}" title="查看详情 / 历史版本">ⓘ</button>
      ${action}
    </div>`;
  return d;
}

/* ── 详情弹窗 ── */
let DETAIL_APP = null;
function openDetail(id){
  const app = repoApps.find(a => a.id === id); if(!app) return;
  DETAIL_APP = app;
  
  document.getElementById('dIcon').textContent = app.icon || '📦';
  document.getElementById('dIcon').style.background = `linear-gradient(135deg, ${app.color}40, ${app.color}15)`;
  
  const tag = document.getElementById('dTag');
  tag.style.display = app.system ? 'inline-block' : 'none';
  
  const nameEl = document.getElementById('dName');
  nameEl.innerHTML = esc(app.name) + ' ';
  nameEl.appendChild(tag);
  
  const curV = app.localVersion || '未安装';
  const latestV = app.version;
  
  const cells = [
    {lb: '当前版本', vl: curV, sub: app.localReleased ? fmtTime(app.localReleased) : (app.installed ? '已安装' : '—')},
    {lb: '最新版本', vl: 'v' + latestV, sub: app.released ? fmtTime(app.released) : '—'},
    {lb: '应用类型', vl: app.system ? '🛡️ 系统' : '📦 用户', sub: app.installed ? '已在设备中' : '尚未安装'},
    {lb: '包体大小', vl: fmtSize(app.size), sub: app.id},
  ];
  
  document.getElementById('dVerGrid').innerHTML = cells.map(c => `
    <div class="verCell">
      <div class="lb">${c.lb}</div>
      <div class="vl">${esc(String(c.vl))}</div>
      <div class="sub">${esc(String(c.sub))}</div>
    </div>`).join('');
    
  document.getElementById('dChangelog').innerHTML = clUL(app.changelog);
  document.getElementById('detailMask').classList.add('show');
}

function closeDetail(){
  document.getElementById('detailMask').classList.remove('show');
  DETAIL_APP = null;
}
document.getElementById('detailMask').addEventListener('click', e => { if(e.target.id === 'detailMask') closeDetail(); });
window.addEventListener('keydown', e => { if(e.key === 'Escape') { closeDetail(); document.getElementById('confirmMask').classList.remove('show'); } });

/* ── 事件委托 ── */
document.addEventListener('click', async (e) => {
  const btn = e.target.closest('button[data-action]');
  if(!btn) return;
  const id = btn.dataset.id, action = btn.dataset.action;

  if(action === 'detail'){ openDetail(id); return; }

  if(action === 'install' || action === 'upgrade'){
    setBusy(action === 'upgrade' ? '升级中：下载 + 校验 + 重启…' : '安装中：下载 + 校验 + 部署…');
    try{
      const r = await api('/api/install?id=' + encodeURIComponent(id));
      clearBusy();
      if(r.ok){
        if(id === 'store' && action === 'upgrade'){
          alert('✅ 应用商店升级完成，页面将刷新以载入新版本');
          setTimeout(() => location.reload(), 600); return;
        }
        loadData();
      } else {
        alert('操作失败：' + r.msg);
      }
    } catch(ex){
      clearBusy();
      if(action === 'upgrade' && id === 'store'){ setTimeout(() => location.reload(), 600); return; }
      alert('请求失败：' + ex.message);
    }
    return;
  }

  if(action === 'uninstall'){
    if(!(await showConfirm('确认卸载', `确认卸载「${DETAIL_APP ? DETAIL_APP.name : id}」吗？\n\n• 运行中的进程将被关闭\n• 应用目录及数据将被永久删除`))) return;
    
    setBusy('卸载中…');
    try{
      const r = await api('/api/uninstall?id=' + encodeURIComponent(id));
      clearBusy();
      if(r.ok){ loadData(); }
      else { alert('卸载失败：' + r.msg); }
    } catch(ex){
      clearBusy(); alert('请求失败：' + ex.message);
    }
    return;
  }
});

function showError(msg){
  document.getElementById('list').innerHTML = `<div class="error">⚠️ ${msg}</div>`;
}

// 初始化
loadData();
</script>
</body>
</html>"""

def render_page():
    """把 LAUNCHER_URL 注入到前端 JS 全局变量"""
    inject = f"<script>window.LAUNCHER_URL='{LAUNCHER_URL}';</script>"
    return HTML.replace("</head>", inject + "</head>", 1)


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html;charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(render_page().encode("utf-8"))

    def log_message(self, *a):
        pass

if __name__ == "__main__":
    print(f"Store → http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()