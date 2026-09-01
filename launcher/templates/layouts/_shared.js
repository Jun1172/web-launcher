/* _shared.js - 跨布局通用逻辑
 * 约定：每个布局 HTML 须实现 buildHome()；可选 updateDots() / onDragH(dx) / onDragHReset() / onSwipeH(dx)
 *   buildHome()    - 根据 APPS 渲染桌面图标（必须）
 *   updateDots()   - 更新运行状态指示器（可选）
 *   onDragH(dx)    - 横向拖动跟手（可选，分页布局用）
 *   onDragHReset() - 拖动结束重置过渡（可选）
 *   onSwipeH(dx)   - 横向滑动结束（可选，dx>0 右滑翻上页，dx<0 左滑翻下页）
 */
const THEMES = __THEMES__;
const LAYOUTS = __LAYOUTS__;
let currentTheme='tech-dark';
let currentLayout='grid';
let APPS=[], current=null, recentsOpen=false, suppress=false;
const pages={}, openedOrder=[];
const $=id=>document.getElementById(id);

/* ── 工具 ─ */
function showToast(msg,dur){const d=document.createElement('div');d.className='__toast';
  d.textContent=msg;document.body.appendChild(d);
  setTimeout(()=>{d.style.transition='opacity 0.2s';d.style.opacity='0';
    setTimeout(()=>d.remove(),220);},(dur||1600));}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function clUL(text){if(!text)return'<li style="opacity:.4">暂无</li>';
  return String(text).split('\n').map(s=>s.trim().replace(/^[-•*]\s*/,'')).filter(Boolean)
    .map(s=>'<li>'+esc(s)+'</li>').join('')||'<li style="opacity:.4">暂无</li>';}

/* ── 时钟 / 网络 / 电量 / 问候语 ── */
function updateGreeting() {
  const h = new Date().getHours();
  let greet = '晚上好';
  if (h >= 5 && h < 12) greet = '早上好';
  else if (h >= 12 && h < 18) greet = '下午好';
  const g=$('cwGreeting'); if(g) g.textContent = greet + '，欢迎使用';
}

function tick(){
  const d=new Date(), p=n=>String(n).padStart(2,'0');
  const t=p(d.getHours())+':'+p(d.getMinutes());
  $('sbTime').textContent=t;
  const cwT=$('cwTime'); if(cwT) cwT.textContent=t;
  const cwD=$('cwDate'); if(cwD) cwD.textContent=`${d.getFullYear()}年${d.getMonth()+1}月${d.getDate()}日 周${'日一二三四五六'[d.getDay()]}`;
  updateGreeting();
}
tick(); setInterval(tick, 1000);

const setNet=()=>$('netIcon').classList.toggle('off',!navigator.onLine);
addEventListener('online',setNet);addEventListener('offline',setNet);setNet();
if(navigator.getBattery)navigator.getBattery().then(b=>{
  const up=()=>{$('battFill').style.width=(b.level*100)+'%';
    $('battFill').style.background=b.charging?'#fbbf24':'var(--success)';
    $('battPct').textContent=Math.round(b.level*100)+'%'+(b.charging?' ⚡':'');};
  up();b.addEventListener('levelchange',up);b.addEventListener('chargingchange',up);});

/* ── 应用打开/关闭 ── */
async function openApp(a){
  let pg=pages[a.id];if(!pg){
    pg=document.createElement('div');pg.className='page';
    const isBg=!a.cmd||(a.cmd&&a.port==null);
    if(isBg){
      pg.innerHTML=`<div class="bar"><span>${esc(a.icon)} ${esc(a.name)}</span>
        <span><button onclick="goHome()"> 回桌面</button>
        <button onclick="killApp('${a.id}')">✕ 退出</button></span></div>
        <div class="loading">正在启动 ${esc(a.name)}…</div>
        <div style="text-align:center;margin-top:40px;color:var(--text-secondary)">${esc(a.name)} 后台运行中</div>`;
    }else{
      pg.innerHTML=`<div class="bar"><span>${esc(a.icon)} ${esc(a.name)}</span>
        <span><button onclick="goHome()">🏠 回桌面</button>
        <button onclick="killApp('${a.id}')">✕ 退出</button></span></div>
        <div class="loading">正在拉起进程，等待端口就绪…</div>
        <iframe allow="modals" style="display:none"></iframe><div class="gz"></div>`;
    }
    document.body.appendChild(pg);pages[a.id]=pg;openedOrder.push(a.id);}
  pg.classList.add('show');$('home').classList.add('dim');current=a.id;
  const wasRunning=a.running;
  const j=await (await fetch('/api/open?id='+a.id)).json();
  const iframe=pg.querySelector('iframe'),ld=pg.querySelector('.loading');
  if(j.url){
    if(j.ok&&(!wasRunning||!iframe.src)){
      iframe.src=j.url+(j.url.includes('?')?'&':'?')+'t='+Date.now();
      iframe.onload=()=>{ld.style.display='none';iframe.style.display='block';};
    }else{ld.style.display='none';iframe.style.display='block';}
  }else{ ld.style.display='none'; }
  poll();}

function goHome(){if(recentsOpen)return closeRecents();
  if(!current)return;pages[current].classList.remove('show');
  $('home').classList.remove('dim');current=null;}

async function killApp(id){
  const card=document.querySelector(`#rCards .card[data-id="${id}"]`);
  if(card){card.classList.add('fadeOut');}
  try{await fetch('/api/close?id='+id);}catch(e){}
  if(pages[id]){
    const iframe=pages[id].querySelector('iframe');
    if(iframe){
      const done=new Promise(res=>{
        iframe.onload=()=>{iframe.remove();res();};
        iframe.src='about:blank';
        setTimeout(res,300);
      });
      await done;
    }
    pages[id].style.display='none';
    setTimeout(()=>{
      if(pages[id]&&!pages[id].parentElement)return;
      if(pages[id]){pages[id].remove();delete pages[id];}
      const idx=openedOrder.indexOf(id);if(idx>=0)openedOrder.splice(idx,1);
      if(current===id){current=null;$('home').classList.remove('dim');}
      if(recentsOpen)renderRecents();poll();},50);
  }else{
    const idx=openedOrder.indexOf(id);if(idx>=0)openedOrder.splice(idx,1);
    if(current===id){current=null;$('home').classList.remove('dim');}
    if(recentsOpen)renderRecents();poll();}}

/* ── 最近任务 ── */
function openRecents(){recentsOpen=true;renderRecents();$('recents').classList.add('show');}
function closeRecents(){recentsOpen=false;$('recents').classList.remove('show');}
function renderRecents(){
  const box=$('rCards');box.innerHTML='';
  if(!openedOrder.length){box.innerHTML='<div class="rEmpty">没有运行中的应用</div>';return;}
  openedOrder.slice().reverse().forEach(id=>{
    const a=APPS.find(x=>x.id===id);if(!a)return;
    const c=document.createElement('div');c.className='card';c.dataset.id=id;
    c.innerHTML=`<button class="x">✕</button>
      <div class="tile" style="--c:${a.color}">${a.icon}</div>
      <div class="name">${esc(a.name)}</div><div class="st">${a.running?'进程运行中':'页面保活中'}</div>`;
    let sy=null,mvY=0;
    c.addEventListener('pointerdown',e=>{sy=e.clientY;c.setPointerCapture(e.pointerId);c.style.transition='none';});
    c.addEventListener('pointermove',e=>{if(sy==null)return;mvY=e.clientY-sy;if(mvY<0)c.style.transform=`translateY(${mvY}px)`;});
    c.addEventListener('pointerup',e=>{
      if(sy==null)return;const dy=mvY;mvY=0;sy=null;c.style.transition='';c.style.transform='';
      if(dy<-60){killApp(id);return;}
      if(Math.abs(dy)<6)c.click();});
    c.onclick=()=>{if(suppress)return;closeRecents();openApp(a);};
    c.querySelector('.x').onclick=e=>{e.stopPropagation();killApp(id);};
    box.appendChild(c);});}

$('clearAll').onclick=async ()=>{
  const n=openedOrder.length;if(!n)return;
  if(!confirm(`确定关闭所有 ${n} 个运行中的应用？（进程将被回收）`))return;
  const all=[...openedOrder];
  for(const id of all){
    if(pages[id]){
      const iframe=pages[id].querySelector('iframe');
      if(iframe){iframe.src='about:blank';}
      pages[id].style.display='none';
    }
  }
  await new Promise(r=>setTimeout(r,250));
  for(const id of all){ try{await fetch('/api/close?id='+id);}catch(e){} }
  setTimeout(()=>{
    for(const id of all){ if(pages[id]){pages[id].remove();delete pages[id];} }
    openedOrder.length=0;
    if(current){current=null;$('home').classList.remove('dim');}
    if(recentsOpen)renderRecents();
    poll();
    showToast(`已关闭 ${all.length} 个后台进程`);},100);};
$('closeR').onclick=closeRecents;

/* ── 主题切换 ── */
function applyTheme(theme){
  if(!THEMES.some(t=>t.id===theme)) theme='tech-dark';
  currentTheme=theme;
  document.documentElement.dataset.theme=theme;
  document.querySelectorAll('.themeBtn').forEach(b=>b.classList.toggle('active',b.dataset.theme===theme));
}
async function initTheme(){
  try{
    const ly=await fetch('/api/layout').then(r=>r.json());
    currentLayout=ly.layout||'grid';
    applyTheme(ly.theme||'tech-dark');
  }catch(e){applyTheme('tech-dark');}
}
async function setTheme(theme){
  applyTheme(theme);
  try{
    await fetch('/api/layout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({theme})});
    const t=THEMES.find(x=>x.id===theme);
    showToast('风格已切换：'+(t?t.name:theme));
  }catch(e){showToast('保存失败');}
}
function renderThemeList(){
  const box=$('themeList');if(!box)return;
  box.innerHTML='';
  THEMES.forEach(t=>{
    const b=document.createElement('button');
    b.className='themeBtn'+(t.id===currentTheme?' active':'');
    b.dataset.theme=t.id;
    b.innerHTML=`<span class="sw" style="background:${t.swatch}"></span>${esc(t.name)}`;
    b.onclick=()=>setTheme(t.id);
    box.appendChild(b);
  });
}

/* ── 布局风格切换 ── */
async function setLayout(layout){
  if(!LAYOUTS.some(l=>l.id===layout))return;
  try{
    await fetch('/api/layout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({layout})});
    showToast('布局切换中…');
    setTimeout(()=>location.reload(),300);
  }catch(e){showToast('保存失败');}
}
function renderLayoutPicker(){
  const box=$('layoutPicker');if(!box)return;
  box.innerHTML='';
  LAYOUTS.forEach(l=>{
    const b=document.createElement('button');
    b.className='layoutBtn'+(l.id===currentLayout?' active':'');
    b.dataset.layout=l.id;
    b.innerHTML=`<span>${l.icon||''}</span>${esc(l.name)}`;
    b.onclick=()=>setLayout(l.id);
    box.appendChild(b);
  });
}

/* ── 布局编辑模态 ── */
function openLayout(){
  $('layoutMask').classList.add('show');
  renderThemeList();
  renderLayoutPicker();
  renderLayoutList();
}
function closeLayout(){$('layoutMask').classList.remove('show');}
$('layoutBtn').onclick=openLayout;
$('layoutMask').addEventListener('click',e=>{if(e.target.id==='layoutMask')closeLayout();});

async function renderLayoutList(){
  const box=$('layList');
  box.innerHTML='<div style="padding:14px;color:var(--text-secondary)">加载中…</div>';
  let apps, ly;
  try{
    [apps, ly] = await Promise.all([
      fetch('/api/apps').then(r=>r.json()),
      fetch('/api/layout').then(r=>r.json())
    ]);
  }catch(e){ box.innerHTML='<div style="padding:14px;color:var(--danger)">加载失败：'+esc(e.message)+'</div>'; return; }

  if(!apps.length){ box.innerHTML='<div style="padding:14px;color:var(--text-secondary)">暂无应用</div>'; return; }

  // layout.json 未保存过时 ly.dock 为 null → 用 app.json 的 dock 默认值显示
  // 一旦用户保存过（哪怕清空），ly.dock 是数组 → 按用户选择判定
  const useLayoutDock = Array.isArray(ly.dock);
  const dockSet = new Set(ly.dock || []);
  const hiddenSet = new Set(ly.hidden || []);

  box.innerHTML='';
  apps.forEach(a=>{
    const inDock = useLayoutDock ? dockSet.has(a.id) : !!a.dock;
    const isHidden = hiddenSet.has(a.id);
    const row=document.createElement('div'); row.className='layRow';
    row.innerHTML=
      '<span class="ic" style="color:'+(a.color||'#888')+'">'+(a.icon||'📦')+'</span>'+
      '<span class="nm">'+esc(a.name)+(a.system?'<small>系统</small>':'')+'</span>'+
      '<label class="cb"><input type="checkbox" data-id="'+a.id+'" data-field="dock" '+(inDock?'checked':'')+'> Dock</label>'+
      '<label class="cb hideLbl"><input type="checkbox" data-id="'+a.id+'" data-field="hidden" '+(isHidden?'checked':'')+'> <span>隐藏</span></label>';
    box.appendChild(row);
  });
}

async function saveLayout(){
  const dock=[], hidden=[];
  document.querySelectorAll('#layList input[type=checkbox]').forEach(cb=>{
    const id=cb.dataset.id, f=cb.dataset.field;
    if(cb.checked){
      if(f==='dock') dock.push(id);
      if(f==='hidden') hidden.push(id);
    }
  });
  try{
    const r=await fetch('/api/layout',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({dock, hidden})
    });
    const j=await r.json();
    if(j.ok){
      showToast('布局已保存');
      closeLayout();
      await poll();
      if(typeof buildHome==='function')buildHome();
    } else { alert('保存失败：'+j.msg); }
  }catch(e){ alert('请求失败：'+e.message); }
}

/* ── 轮询 ── */
async function poll(){
  const prev=APPS.map(a=>a.id).join(',');
  APPS=await (await fetch('/api/apps')).json();
  const cur=APPS.map(a=>a.id).join(',');
  if(prev!==cur&&prev.length&&typeof buildHome==='function')buildHome();
  if(typeof updateDots==='function')updateDots();
  if(recentsOpen)renderRecents();}

/* ── 全局手势 ── */
let drag=null;
addEventListener('pointerdown',e=>{
  if(e.target.closest('#homeBar,button,.bar,#statusbar,.card,.modalMask input,.modalMask button'))return;
  drag={x:e.clientX,y:e.clientY,dx:0,dy:0,axis:null};
  if(!recentsOpen&&e.target.setPointerCapture)e.target.setPointerCapture(e.pointerId);});
addEventListener('pointermove',e=>{
  if(!drag)return;drag.dx=e.clientX-drag.x;drag.dy=e.clientY-drag.y;
  if(!drag.axis&&(Math.abs(drag.dx)>8||Math.abs(drag.dy)>8))
    drag.axis=Math.abs(drag.dx)>Math.abs(drag.dy)?'h':'v';
  if(typeof onDragH==='function'&&!recentsOpen&&!current&&drag.axis==='h'){
    onDragH(drag.dx);}});
addEventListener('pointerup',e=>{
  if(!drag)return;const{dx,dy,axis}=drag;drag=null;
  suppress=!!axis&&(Math.abs(dx)>8||Math.abs(dy)>8);
  if(typeof onDragHReset==='function')onDragHReset();
  if(recentsOpen){if(axis==='v'&&dy>70)closeRecents();return;}
  if(!current){
    if(axis==='v'&&dy<-60){openRecents();return;}
    if(axis==='h'&&typeof onSwipeH==='function')onSwipeH(dx);
  } else { if(axis==='v'&&dy<-50)openRecents(); }});
document.addEventListener('click',e=>{
  if(suppress){suppress=false;return;}
  const ic=e.target.closest('.icon');if(!ic)return;
  const a=APPS.find(x=>x.id===ic.dataset.id);if(a)openApp(a);});
$('homeBar').onclick=()=>{if(recentsOpen)closeRecents();else openRecents();};
addEventListener('keydown',e=>{if(e.key==='Escape'){
  if($('layoutMask').classList.contains('show'))closeLayout();
  else goHome();}});

/* ── 初始化 ── */
initTheme();
poll().then(()=>{
  if(typeof buildHome==='function')buildHome();
  setInterval(poll,2000);});

/* ── pywebview 窗口控制（自注入，reload 后不丢） ──
   仅在 pywebview 环境创建：状态栏拖拽 + 8 边缘缩放热区 + 右上角 —▢✕ 按钮。
   非桌面窗口模式（纯 HTTP）下 window.pywebview 不存在 → 静默跳过。
   /api/ui/config 的 show_window_buttons=false 时跳过 —▢✕ 按钮组（嵌入式/kiosk 场景）。 */
var __uiCfg = {show_window_buttons: true, fx_enabled: true, fx_particle_count: 38,
               fx_pointer_glow: true, fx_meteor: true, fx_ripple: true, __loaded: false};
fetch('/api/ui/config').then(r=>r.json()).then(function(c){
  Object.assign(__uiCfg, c);
  __uiCfg.__loaded = true;
  /* 如果窗口壳已经初始化过但当时没拿到配置，这里补一次按钮注入 */
  if(c.show_window_buttons === false){
    document.documentElement.classList.add('no-win-buttons');
  }
}).catch(function(){ __uiCfg.__loaded = true; });

function setupWinChrome(){
  try{
    if(!window.pywebview||!window.pywebview.api)return;
    var api=window.pywebview.api;
    if(typeof api.start_drag!=='function')return;
  }catch(e){return;}
  if(window.__winChromeReady)return;
  window.__winChromeReady=true;

  var sb=document.getElementById('statusbar');
  if(!sb)return;
  var sbR=sb.querySelector('.sbR');
  if(!sbR)return;

  /* 状态栏 = 标题栏：按下拖拽，双击最大化；按钮除外 */
  var lastDown=0;
  sb.addEventListener('pointerdown',function(e){
    if(e.target.closest('button'))return;
    if(e.button!==0)return;
    var now=Date.now();
    if(now-lastDown<350){lastDown=0;api.toggle_maximize();return;}
    lastDown=now;
    api.start_drag();
  });

  /* 边缘缩放热区（页面内不可见 div 触发原生缩放循环） */
  function mkZone(cur,code,css){
    var d=document.createElement('div');
    d.style.cssText='position:fixed;z-index:9998;background:transparent;cursor:'+cur+';'+css;
    d.addEventListener('pointerdown',function(e){
      e.stopPropagation();e.preventDefault();
      try{api.start_resize(code);}catch(_){}
    });
    document.body.appendChild(d);
  }
  mkZone('ew-resize','l','left:0;top:0;width:6px;height:100%;');
  mkZone('ew-resize','r','right:0;top:0;width:6px;height:100%;');
  mkZone('ns-resize','t','left:0;top:0;width:100%;height:6px;');
  mkZone('ns-resize','b','left:0;bottom:0;width:100%;height:6px;');
  mkZone('nwse-resize','tl','left:0;top:0;width:12px;height:12px;');
  mkZone('nesw-resize','tr','right:0;top:0;width:12px;height:12px;');
  mkZone('nesw-resize','bl','left:0;bottom:0;width:12px;height:12px;');
  mkZone('nwse-resize','br','right:0;bottom:0;width:12px;height:12px;');

  /* 右上角窗口控制按钮组 —— 嵌入式/kiosk 场景通过 config.json
     ui.show_window_buttons=false 关闭，前端读 __uiCfg 决定是否注入 */
  if(__uiCfg.show_window_buttons===false)return;

  var grp=document.createElement('span');
  grp.style.cssText='display:flex;align-items:center;gap:2px;margin-left:12px;background:rgba(255,255,255,0.05);border-radius:8px;padding:2px;';
  function mkBtn(svg,title,fn,hoverIn,hoverOut){
    var b=document.createElement('button');
    b.title=title;
    b.style.cssText='background:transparent;border:0;cursor:pointer;padding:6px 8px;border-radius:6px;transition:all 0.15s;display:flex;align-items:center;color:var(--text-secondary);';
    b.innerHTML=svg;
    b.onmouseover=function(){b.style.background='rgba(255,255,255,0.1)';b.style.color='var(--text-primary)';if(hoverIn)hoverIn(b);};
    b.onmouseout=function(){b.style.background='transparent';b.style.color='var(--text-secondary)';if(hoverOut)hoverOut(b);};
    b.onclick=fn;
    return b;
  }
  var minSvg='<svg width="12" height="12" viewBox="0 0 12 12"><rect x="2" y="5.5" width="8" height="1.2" rx="0.6" fill="currentColor"/></svg>';
  var maxSvg='<svg width="12" height="12" viewBox="0 0 12 12"><rect x="2.5" y="2.5" width="7" height="7" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>';
  var closeSvg='<svg width="12" height="12" viewBox="0 0 12 12"><path d="M3.5 3.5L8.5 8.5M8.5 3.5L3.5 8.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/></svg>';
  grp.appendChild(mkBtn(minSvg,'最小化',function(){api.minimize_window();}));
  grp.appendChild(mkBtn(maxSvg,'最大化/还原',function(){api.toggle_maximize();}));
  var cb=mkBtn(closeSvg,'关闭',function(){api.close_window();},
    function(b){b.style.background='rgba(248,113,113,0.2)';b.style.color='#f87171';},
    function(b){b.style.background='transparent';b.style.color='var(--text-secondary)';});
  grp.appendChild(cb);
  sbR.appendChild(grp);
}
/* pywebview 注入 window.pywebview 通常在 DOMContentLoaded 之后；
   立即尝试一次，再延时兜底一次（覆盖 reload 时序差异） */
setupWinChrome();
setTimeout(setupWinChrome,300);
setTimeout(setupWinChrome,1500);

/* ══════════════ 氛围动态层 ══════════════
   1) 星尘粒子：30 颗小星 + 8 颗大萤火，CSS 动画上浮（GPU 合成）
   2) 鼠标跟随光晕：rAF 平滑插值跟随指针
   3) 时钟呼吸 + 分钟翻转：光晕脉动 + 数字翻入
   4) 流星：7~16s 随机一颗划过
   5) 点击涟漪：磁贴/图标按下扩散光环
   6) 资源守护：窗口最小化/隐藏时 CSS 动画暂停 + rAF 停表
   全部 respect prefers-reduced-motion（CSS 侧已关动画，这里直接不建 DOM）
   config.json 的 ui.fx_enabled=false 时整体跳过（嵌入式低端设备节能模式） */
function setupAmbientFX(){
  var reduce = false;
  try { reduce = matchMedia('(prefers-reduced-motion: reduce)').matches; } catch(e){}
  if (reduce) return;
  if (__uiCfg.fx_enabled === false) return;  /* config.json 关闭动效 */

  /* ── 粒子层 ── */
  var layer = document.createElement('div');
  layer.id = 'fx-layer';
  var frag = document.createDocumentFragment();
  /* 注意：不能用 `|| 38` 兜底 —— 0 是合法值（关闭粒子），会被当成 falsy 变回 38 */
  var _pc = __uiCfg.fx_particle_count;
  var count = (typeof _pc === 'number' && isFinite(_pc) && _pc >= 0)
    ? Math.min(Math.floor(_pc), 300)   /* 上限 300，防止手滑写个大值拖垮页面 */
    : 38;
  for (var i = 0; i < count; i++) {
    var s = document.createElement('i');
    var big = i % 5 === 0; /* 每 5 颗出 1 颗大萤火 */
    var size = big ? 3 + Math.random() * 3 : 1.2 + Math.random() * 1.8;
    s.className = 'fx-star' + (big ? ' big' : '');
    s.style.left = (Math.random() * 100).toFixed(2) + '%';
    s.style.width = size.toFixed(1) + 'px';
    s.style.height = size.toFixed(1) + 'px';
    s.style.setProperty('--dur', (big ? 22 + Math.random() * 14 : 13 + Math.random() * 10).toFixed(1) + 's');
    s.style.setProperty('--delay', (-Math.random() * 26).toFixed(1) + 's'); /* 负延迟：一开场就满天星 */
    s.style.setProperty('--peak', (big ? 0.55 + Math.random() * 0.3 : 0.35 + Math.random() * 0.4).toFixed(2));
    s.style.setProperty('--drift', ((Math.random() - 0.5) * 70).toFixed(0) + 'px');
    if (big) s.style.setProperty('--sway-t', (4.5 + Math.random() * 4).toFixed(1) + 's');
    frag.appendChild(s);
  }
  layer.appendChild(frag);
  document.body.appendChild(layer);

  /* ── 资源守护：窗口不可见 → 暂停全部 CSS 动画 + 停 rAF ── */
  function setFrozen(frozen){
    document.documentElement.style.setProperty('--fx-play', frozen ? 'paused' : 'running');
    layer.style.animationPlayState = frozen ? 'paused' : 'running';
  }
  document.addEventListener('visibilitychange', function(){
    setFrozen(document.hidden);
  });

  /* ── 鼠标跟随光晕（窗口隐藏时 rAF 自动降到 ~0 次/秒，无需额外处理） ──
     ui.fx_pointer_glow=false 时整块跳过：不建 DOM、不挂监听、不跑 rAF（省电） */
  if (__uiCfg.fx_pointer_glow !== false) {
  var glow = document.createElement('div');
  glow.id = 'fx-glow';
  document.body.appendChild(glow);
  var tx = innerWidth / 2, ty = innerHeight / 2, gx = tx, gy = ty, seen = false;
  addEventListener('pointermove', function (e) {
    tx = e.clientX; ty = e.clientY;
    if (!seen) { seen = true; document.body.classList.add('fx-ready'); gx = tx; gy = ty; }
  }, { passive: true });
  addEventListener('pointerleave', function () { document.body.classList.remove('fx-ready'); seen = false; });
  (function follow() {
    if (!document.hidden) {
      gx += (tx - gx) * 0.07; /* 慢半拍跟随，产生"拖尾"手感 */
      gy += (ty - gy) * 0.07;
      glow.style.transform = 'translate3d(' + gx.toFixed(1) + 'px,' + gy.toFixed(1) + 'px,0)';
    }
    requestAnimationFrame(follow);
  })();
  }

  /* ── 时钟呼吸 ── */
  var clockEl = document.getElementById('cwTime');
  if (clockEl) clockEl.classList.add('fx-clock-breathe');

  /* ── 分钟翻转：整分时数字翻入（改 tick 之外的独立钩子） ── */
  if (clockEl) {
    var lastMin = new Date().getMinutes();
    var origText = '';
    var flipObs = setInterval(function(){
      if (document.hidden) return;
      var m = new Date().getMinutes();
      if (m !== lastMin) {
        lastMin = m;
        clockEl.classList.remove('fx-flip');
        void clockEl.offsetWidth; /* 强制 reflow 重启动画 */
        clockEl.classList.add('fx-flip');
      }
    }, 1000);
  }

  /* ── 流星：随机间隔生成，划过即自删 ── */
  function spawnMeteor(){
    if (document.hidden) { scheduleMeteor(); return; }
    var m = document.createElement('i');
    m.className = 'fx-meteor';
    m.style.left = (55 + Math.random() * 45) + '%';   /* 右上半区出发 */
    m.style.setProperty('--dur', (0.9 + Math.random() * 0.7).toFixed(2) + 's');
    layer.appendChild(m);
    setTimeout(function(){ m.remove(); }, 2200);
    scheduleMeteor();
  }
  function scheduleMeteor(){
    setTimeout(spawnMeteor, 7000 + Math.random() * 9000);
  }
  /* 注意：ui.fx_meteor=false 时不启动定时器链，也就不再有 setTimeout 唤醒 */
  if (__uiCfg.fx_meteor !== false) scheduleMeteor();

  /* ── 点击涟漪：任何 .icon/.tile 按下时从指针位置扩散 ── */
  if (__uiCfg.fx_ripple !== false) document.addEventListener('pointerdown', function(e){
    var host = e.target.closest ? e.target.closest('.icon, .tile, .card, .themeBtn, .layoutBtn') : null;
    if (!host) return;
    var r = host.getBoundingClientRect();
    if (r.width > 300) return; /* 超大容器不扩散，避免怪异 */
    var rp = document.createElement('i');
    rp.className = 'fx-ripple';
    rp.style.left = (e.clientX - r.left) + 'px';
    rp.style.top = (e.clientY - r.top) + 'px';
    host.appendChild(rp);
    setTimeout(function(){ rp.remove(); }, 600);
  });
}

/* setupAmbientFX 依赖 __uiCfg（/api/ui/config 异步加载），等它就绪后跑一次。
   顶部的 fetch 已设置 __uiCfg，这里轮询等到 __loaded=true 即触发。 */
(function waitUiThenFx(){
  if (__uiCfg.__loaded) { setupAmbientFX(); return; }
  setTimeout(waitUiThenFx, 80);
})();
