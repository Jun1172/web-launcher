"""calculator —— 现代双模式计算器 (极简/安全/全键盘支持)"""
import os
import json, os
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

def get_port():
    """
    获取端口的优先级：
    1. 环境变量 LAUNCHER_APP_PORT (支持 Launcher 动态分配，防冲突)
    2. 同目录下的 app.json 中的 port 字段 (支持静态配置)
    3. 兜底返回 0 (让操作系统随机分配空闲端口)
    """
    # 1. 尝试从环境变量获取
    env_port = os.environ.get("LAUNCHER_APP_PORT")
    if env_port:
        try: return int(env_port)
        except ValueError: pass
    
    # 2. 尝试从 app.json 获取
    app_json_path = Path(__file__).parent / "app.json"
    if app_json_path.exists():
        try:
            config = json.loads(app_json_path.read_text(encoding="utf-8"))
            port = config.get("port")
            if port: return int(port)
        except Exception: pass
        
    # 3. 兜底
    return 0

PORT = get_port()

# --- 下方为完整的 HTML/CSS/JS 代码 (与上一版相同，保证功能可用) ---
HTML = r"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body { margin: 0; display: flex; justify-content: center; align-items: center; height: 100vh; background: #f6f8ff; font-family: system-ui, sans-serif; }
.calc { width: 340px; background: #fff; border-radius: 20px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); overflow: hidden; }
.tabs { display: flex; background: #f0f2f5; }
.tab { flex: 1; padding: 12px; border: none; background: none; font-size: 14px; cursor: pointer; color: #666; }
.tab.active { background: #fff; color: #222; font-weight: bold; box-shadow: 0 -2px 0 #5b8cff inset; }
.display { padding: 20px; text-align: right; min-height: 100px; display: flex; flex-direction: column; justify-content: flex-end; }
.history { font-size: 12px; color: #999; min-height: 20px; display: flex; justify-content: space-between; }
.current { font-size: 36px; font-weight: 300; color: #222; word-break: break-all; }
.modes { display: flex; padding: 0 10px 10px; gap: 5px; }
.mode-btn { flex: 1; padding: 6px; border: 1px solid #ddd; background: #fff; border-radius: 8px; font-size: 12px; cursor: pointer; }
.mode-btn.active { background: #5b8cff; color: #fff; border-color: #5b8cff; }
.buttons { padding: 10px; display: flex; flex-direction: column; gap: 8px; }
.row { display: flex; gap: 8px; }
.btn { flex: 1; padding: 15px 0; border: none; border-radius: 12px; font-size: 18px; cursor: pointer; background: #f0f2f5; color: #222; transition: all 0.1s; }
.btn:active { transform: scale(0.95); }
.btn.op { background: #5b8cff; color: #fff; }
.btn.fn { background: #e2e8f0; color: #475569; }
.btn.bit { background: #e0e7ff; color: #4338ca; font-size: 14px; }
.btn.hex { background: #fce7f3; color: #be185d; font-size: 16px; }
.btn:disabled { opacity: 0.3; cursor: not-allowed; }
</style>
</head>
<body>
<div class="calc">
  <div class="tabs">
    <button class="tab active" data-mode="standard" onclick="switchMode('standard')">标准</button>
    <button class="tab" data-mode="programmer" onclick="switchMode('programmer')">程序员</button>
  </div>
  <div class="display">
    <div class="history" id="history"></div>
    <div class="current" id="current">0</div>
  </div>
  <div class="modes" id="modes" style="display:none;">
    <button class="mode-btn active" data-base="10" onclick="switchBase(10)">DEC</button>
    <button class="mode-btn" data-base="16" onclick="switchBase(16)">HEX</button>
    <button class="mode-btn" data-base="8" onclick="switchBase(8)">OCT</button>
    <button class="mode-btn" data-base="2" onclick="switchBase(2)">BIN</button>
  </div>
  <div class="buttons" id="buttons"></div>
</div>
<script>
let mode = 'standard';
let currentBase = 10;
let displayValue = '0';
let previousValue = null;
let operator = null;
let isTyping = false;

const standardKeys = [
  ['AC', '±', '%', '÷'],
  ['7', '8', '9', '×'],
  ['4', '5', '6', '-'],
  ['1', '2', '3', '+'],
  ['0', '.', '=']
];

const programmerKeys = [
  ['A', 'B', 'C', 'D', 'E', 'F'],
  ['<<', '>>', 'AND', 'OR'],
  ['XOR', 'NOT', 'MOD', '÷'],
  ['7', '8', '9', '×'],
  ['4', '5', '6', '-'],
  ['1', '2', '3', '+'],
  ['0', '=', '±']
];

function updateDisplay() {
  document.getElementById('current').textContent = displayValue;
  const hist = document.getElementById('history');
  if (mode === 'programmer') {
    const val = parseInt(displayValue, currentBase);
    if (!isNaN(val) && displayValue !== 'Error') {
      hist.innerHTML = `
        <span>HEX: ${val.toString(16).toUpperCase()}</span>
        <span>DEC: ${val.toString(10)}</span>
        <span>OCT: ${val.toString(8)}</span>
        <span>BIN: ${val.toString(2)}</span>
      `;
    } else { hist.innerHTML = ''; }
  } else { hist.innerHTML = ''; }
}

function inputChar(ch) {
  if (!isTyping) { displayValue = ''; isTyping = true; }
  if (mode === 'programmer') {
    const valid = '0123456789ABCDEF'.substring(0, currentBase === 10 ? 10 : currentBase === 16 ? 16 : currentBase === 8 ? 8 : 2);
    if (!valid.includes(ch.toUpperCase())) return;
    ch = ch.toUpperCase();
  } else {
    if (ch === '.') { if (displayValue.includes('.')) return; }
    else if (!'0123456789'.includes(ch)) return;
  }
  displayValue = (displayValue === '0' && ch !== '.') ? ch : displayValue + ch;
  updateDisplay();
}

function setOperator(op) {
  if (operator && isTyping) calculate();
  previousValue = parseInt(displayValue, currentBase);
  operator = op;
  isTyping = false;
  document.getElementById('history').textContent = `${previousValue} ${op}`;
}

function calculate() {
  if (operator === null || previousValue === null) return;
  const curr = parseInt(displayValue, currentBase);
  let result = 0;
  switch(operator) {
    case '+': result = previousValue + curr; break;
    case '-': result = previousValue - curr; break;
    case '×': result = previousValue * curr; break;
    case '÷': result = curr === 0 ? 'Error' : previousValue / curr; break;
    case 'AND': result = previousValue & curr; break;
    case 'OR': result = previousValue | curr; break;
    case 'XOR': result = previousValue ^ curr; break;
    case '<<': result = previousValue << curr; break;
    case '>>': result = previousValue >> curr; break;
    case 'MOD': case '%': result = previousValue % curr; break;
  }
  if (result === 'Error') displayValue = 'Error';
  else {
    if (mode === 'standard' && !Number.isInteger(result)) displayValue = result.toString();
    else displayValue = Math.trunc(result).toString(currentBase).toUpperCase();
  }
  previousValue = null; operator = null; isTyping = false;
  document.getElementById('history').textContent = '';
  updateDisplay();
}

function clearAll() {
  displayValue = '0'; previousValue = null; operator = null; isTyping = false;
  document.getElementById('history').textContent = '';
  updateDisplay();
}

function switchMode(m) {
  mode = m;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.mode === m));
  document.getElementById('modes').style.display = m === 'programmer' ? 'flex' : 'none';
  renderButtons(); clearAll();
}

function switchBase(b) {
  if (b === currentBase) return;
  if (displayValue !== 'Error' && displayValue !== '0' && displayValue !== '') {
    const val = parseInt(displayValue, currentBase);
    if (!isNaN(val)) displayValue = val.toString(b).toUpperCase();
  }
  currentBase = b;
  document.querySelectorAll('.mode-btn').forEach(btn => btn.classList.toggle('active', parseInt(btn.dataset.base) === b));
  renderButtons(); updateDisplay();
}

function handleKey(key) {
  if (key === 'AC') return clearAll();
  if (key === '±') {
    if (displayValue !== '0' && displayValue !== 'Error') {
      displayValue = displayValue.startsWith('-') ? displayValue.slice(1) : '-' + displayValue;
      updateDisplay();
    }
    return;
  }
  if (key === '=') return calculate();
  if (key === 'NOT') {
    const val = parseInt(displayValue, currentBase);
    if (!isNaN(val)) { displayValue = (~val).toString(currentBase).toUpperCase(); updateDisplay(); }
    return;
  }
  if (['+', '-', '×', '÷', 'AND', 'OR', 'XOR', '<<', '>>', 'MOD', '%'].includes(key)) return setOperator(key);
  inputChar(key);
}

function renderButtons() {
  const container = document.getElementById('buttons');
  container.innerHTML = '';
  const keys = mode === 'standard' ? standardKeys : programmerKeys;
  keys.forEach(row => {
    const rowDiv = document.createElement('div');
    rowDiv.className = 'row';
    row.forEach(key => {
      const btn = document.createElement('button');
      btn.textContent = key;
      btn.className = 'btn';
      if (['÷', '×', '-', '+', '='].includes(key)) btn.classList.add('op');
      if (['AC', '±', '%', 'NOT', 'MOD'].includes(key)) btn.classList.add('fn');
      if (['AND', 'OR', 'XOR', '<<', '>>'].includes(key)) btn.classList.add('bit');
      if ('ABCDEF'.includes(key)) btn.classList.add('hex');
      if (mode === 'programmer') {
        if ('ABCDEF'.includes(key) && currentBase < 16) btn.disabled = true;
        if ('89'.includes(key) && currentBase < 10) btn.disabled = true;
        if ('234567'.includes(key) && currentBase < 8) btn.disabled = true;
        if (key === '.') btn.disabled = true;
      }
      btn.onclick = () => handleKey(key);
      rowDiv.appendChild(btn);
    });
    container.appendChild(rowDiv);
  });
}

renderButtons();
</script>
</body>
</html>"""

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML.encode("utf-8"))
    def log_message(self, *a): pass

if __name__ == "__main__":
    print(f"[Calculator] 启动成功，监听端口: {PORT}")
    ThreadingHTTPServer((os.environ.get("APP_HOST", "127.0.0.1"), PORT), H).serve_forever()