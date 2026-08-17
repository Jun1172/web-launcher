"""game2048 —— 经典 2048 小游戏
- 端口 8114
- 验证：复杂游戏逻辑 + 键盘/触摸滑动 + localStorage 存最高分
"""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PORT = 8114

HTML = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>🎮 2048</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{height:100%;overflow:hidden;touch-action:none}
body{font-family:system-ui,-apple-system,"PingFang SC",sans-serif;
background:#faf8ef;color:#776e65;user-select:none;
display:flex;flex-direction:column;align-items:center;justify-content:center;padding:16px}
.wrap{width:100%;max-width:380px}
.head{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}
.head h1{font-size:34px;font-weight:700;color:#776e65}
.scores{display:flex;gap:8px}
.sc{background:#bbada0;color:#fff;border-radius:8px;padding:8px 14px;text-align:center;min-width:64px}
.sc .label{font-size:10px;text-transform:uppercase;opacity:.7;letter-spacing:1px}
.sc .val{font-size:20px;font-weight:700;font-variant-numeric:tabular-nums}
.bar{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;font-size:13px;color:#8f8780}
.bar button{background:#8f7a66;color:#fff;border:0;border-radius:6px;padding:8px 14px;
font-size:13px;font-weight:600;cursor:pointer}
.bar button:active{transform:scale(.95)}
.board{position:relative;background:#bbada0;border-radius:8px;padding:10px;aspect-ratio:1}
.grid{display:grid;grid-template-columns:repeat(4,1fr);grid-template-rows:repeat(4,1fr);
gap:10px;height:100%}
.cell{background:rgba(238,228,218,.35);border-radius:6px}
.tiles{position:absolute;inset:10px;pointer-events:none}
.tile{position:absolute;display:flex;align-items:center;justify-content:center;
border-radius:6px;font-weight:700;transition:transform .12s cubic-bezier(.2,.8,.2,1);
width:calc((100% - 30px)/4);height:calc((100% - 30px)/4)}
.t2{background:#eee4da;color:#776e65}
.t4{background:#ede0c8;color:#776e65}
.t8{background:#f2b179;color:#fff}
.t16{background:#f59563;color:#fff}
.t32{background:#f67c5f;color:#fff}
.t64{background:#f65e3b;color:#fff}
.t128{background:#edcf72;color:#fff;font-size:90%}
.t256{background:#edcc61;color:#fff;font-size:90%}
.t512{background:#edc850;color:#fff;font-size:90%}
.t1024{background:#edc53f;color:#fff;font-size:75%}
.t2048{background:#edc22e;color:#fff;font-size:75%}
.t-big{background:#3c3a32;color:#fff;font-size:60%}
.tip{margin-top:12px;font-size:12px;color:#8f8780;text-align:center;line-height:1.6}
.overlay{position:absolute;inset:0;background:rgba(238,228,218,.85);border-radius:8px;
display:none;flex-direction:column;align-items:center;justify-content:center;z-index:10}
.overlay.show{display:flex}
.overlay h2{font-size:32px;color:#776e65;margin-bottom:6px}
.overlay p{font-size:13px;color:#8f8780;margin-bottom:14px}
.overlay button{background:#8f7a66;color:#fff;border:0;border-radius:6px;padding:10px 22px;
font-size:14px;font-weight:600;cursor:pointer}
</style></head><body>
<div class="wrap">
  <div class="head">
    <h1>2048</h1>
    <div class="scores">
      <div class="sc"><div class="label">分数</div><div class="val" id="score">0</div></div>
      <div class="sc"><div class="label">最高</div><div class="val" id="best">0</div></div>
    </div>
  </div>
  <div class="bar">
    <span>方向键 / 滑动操作</span>
    <button onclick="newGame()">新游戏</button>
  </div>
  <div class="board" id="board">
    <div class="grid" id="grid"></div>
    <div class="tiles" id="tiles"></div>
    <div class="overlay" id="overlay">
      <h2 id="ovTitle">游戏结束</h2>
      <p id="ovText">没有可行的移动了</p>
      <button onclick="newGame()">再来一局</button>
    </div>
  </div>
  <div class="tip">合并相同数字达到 2048 获胜 · 最高分自动保存</div>
</div>
<script>
const SIZE=4;
let grid,score,best=+localStorage.getItem('g2048_best')||0,won=false;
const $=id=>document.getElementById(id);

function newGame(){
  grid=Array(SIZE).fill(0).map(()=>Array(SIZE).fill(0));
  score=0;won=false;
  addRandom();addRandom();
  $('overlay').classList.remove('show');
  render();
}

function addRandom(){
  const empty=[];
  for(let r=0;r<SIZE;r++)for(let c=0;c<SIZE;c++)if(!grid[r][c])empty.push([r,c]);
  if(!empty.length)return false;
  const[r,c]=empty[Math.floor(Math.random()*empty.length)];
  grid[r][c]=Math.random()<.9?2:4;
  return true;
}

function render(){
  $('score').textContent=score;
  if(score>best){best=score;localStorage.setItem('g2048_best',best);}
  $('best').textContent=best;
  const t=$('tiles');t.innerHTML='';
  for(let r=0;r<SIZE;r++)for(let c=0;c<SIZE;c++){
    const v=grid[r][c];if(!v)continue;
    const el=document.createElement('div');
    el.className='tile t'+(v>2048?'-big':v);
    el.textContent=v;
    // 4x4 网格，gap=10px：每格 (100%-30px)/4，位置 = c*(cell+10px)
    el.style.left=`calc(${c}*((100% - 30px)/4 + 10px))`;
    el.style.top=`calc(${r}*((100% - 30px)/4 + 10px))`;
    t.appendChild(el);
  }
}

function move(dir){
  // dir: 0=LEFT 1=DOWN 2=RIGHT 3=UP
  // 实现：把网格顺时针旋转 dir*90 度，向左合并，再逆旋转回去
  let moved=false,g=grid.map(r=>r.slice());
  // 统一把方向旋转成"向左"，处理完再转回来
  const rotate=(g,n)=>{for(let i=0;i<n;i++)g=g[0].map((_,c)=>g.map(r=>r[c]).reverse());return g;};
  const unrotate=(g,n)=>rotate(g,(4-n)%4);
  g=rotate(g,dir);
  for(let r=0;r<SIZE;r++){
    let row=g[r].filter(x=>x);
    for(let i=0;i<row.length-1;i++){
      if(row[i]===row[i+1]){row[i]*=2;score+=row[i];row.splice(i+1,1);
        if(row[i]===2048&&!won){won=true;showWin();}}
    }
    while(row.length<SIZE)row.push(0);
    if(JSON.stringify(g[r])!==JSON.stringify(row))moved=true;
    g[r]=row;
  }
  g=unrotate(g,dir);
  if(moved){grid=g;addRandom();render();checkOver();}
}

function showWin(){
  $('ovTitle').textContent='🎉 你赢了！';
  $('ovText').textContent='达到了 2048！可以继续合并更大的数字。';
  $('overlay').classList.add('show');
  setTimeout(()=>$('overlay').classList.remove('show'),2500);
}

function checkOver(){
  for(let r=0;r<SIZE;r++)for(let c=0;c<SIZE;c++){
    if(!grid[r][c])return;
    if(c<SIZE-1&&grid[r][c]===grid[r][c+1])return;
    if(r<SIZE-1&&grid[r][c]===grid[r+1][c])return;
  }
  $('ovTitle').textContent='游戏结束';
  $('ovText').textContent='没有可行的移动了';
  $('overlay').classList.add('show');
}

// 方向常量（语义化，避免数字搞混）
// move(dir) 内部把网格顺时针旋转 dir*90 度后向左合并，再逆旋转。
// 对应关系：0=向左 1=向下 2=向右 3=向上
const LEFT=0,DOWN=1,RIGHT=2,UP=3;

// 键盘
addEventListener('keydown',e=>{
  const m={ArrowUp:UP,ArrowRight:RIGHT,ArrowDown:DOWN,ArrowLeft:LEFT,
           'w':UP,'d':RIGHT,'s':DOWN,'a':LEFT,
           'W':UP,'D':RIGHT,'S':DOWN,'A':LEFT};
  if(m[e.key]!==undefined){e.preventDefault();move(m[e.key]);}
});

// 滑动（鼠标 + 触摸都支持）
let swipe=null;
const board=$('board');
board.addEventListener('pointerdown',e=>{
  swipe={x:e.clientX,y:e.clientY};
});
board.addEventListener('pointerup',e=>{
  if(!swipe)return;
  const dx=e.clientX-swipe.x,dy=e.clientY-swipe.y;
  swipe=null;
  if(Math.abs(dx)<20&&Math.abs(dy)<20)return;  // 距离太短，当作点击
  if(Math.abs(dx)>Math.abs(dy))move(dx>0?RIGHT:LEFT);
  else move(dy>0?DOWN:UP);
});
// 阻止鼠标拖动时的文本选中
board.addEventListener('dragstart',e=>e.preventDefault());

// 初始化网格背景
const gridEl=$('grid');
for(let i=0;i<SIZE*SIZE;i++){const c=document.createElement('div');c.className='cell';gridEl.appendChild(c);}
newGame();
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html;charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(HTML.encode("utf-8"))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"game2048 demo → http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
