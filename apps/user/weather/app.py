"""weather —— 天气 demo
- 端口 8113
- 验证：mock 数据驱动 UI + 多视图切换（城市列表 ↔ 详情）
- 注意：数据是写死的，仅用于功能演示，不联网
"""
import json
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

PORT = 8113

# ── mock 数据 ───────────────────────────────────────────
CITIES = [
    {"id": "beijing",   "name": "北京",   "icon": "☀️", "temp": 28, "desc": "晴朗",   "wind": "东南 3 级", "hum": 42, "aqi": 78,  "aqiLabel": "良"},
    {"id": "shanghai",  "name": "上海",   "icon": "⛅", "temp": 26, "desc": "多云",   "wind": "东风 4 级", "hum": 68, "aqi": 55,  "aqiLabel": "良"},
    {"id": "guangzhou", "name": "广州",   "icon": "🌧️", "temp": 30, "desc": "小雨",   "wind": "南风 2 级", "hum": 88, "aqi": 42,  "aqiLabel": "优"},
    {"id": "chengdu",   "name": "成都",   "icon": "🌫️", "temp": 24, "desc": "雾霾",   "wind": "微风",     "hum": 72, "aqi": 138, "aqiLabel": "轻度"},
    {"id": "harbin",    "name": "哈尔滨", "icon": "❄️", "temp": 12, "desc": "小雪",   "wind": "北风 5 级", "hum": 56, "aqi": 35,  "aqiLabel": "优"},
]
FORECAST = {  # 未来 3 天
    "beijing":  [{"d":"明天","i":"⛅","t":27},{"d":"后天","i":"🌧️","t":23},{"d":"大后天","i":"☀️","t":29}],
    "shanghai": [{"d":"明天","i":"🌧️","t":24},{"d":"后天","i":"⛅","t":25},{"d":"大后天","i":"☀️","t":28}],
    "guangzhou":[{"d":"明天","i":"🌧️","t":29},{"d":"后天","i":"⛅","t":31},{"d":"大后天","i":"☀️","t":33}],
    "chengdu":  [{"d":"明天","i":"🌫️","t":23},{"d":"后天","i":"⛅","t":25},{"d":"大后天","i":"☀️","t":27}],
    "harbin":   [{"d":"明天","i":"❄️","t":10},{"d":"后天","i":"🌨️","t":8}, {"d":"大后天","i":"⛅","t":14}],
}

HTML = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🌤️ 天气</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,"PingFang SC",sans-serif;
background:linear-gradient(160deg,#3498db22,#fff);color:#222;min-height:100vh}
.head{background:linear-gradient(135deg,#3498db,#2c5aa0);color:#fff;
padding:24px 20px 30px;text-align:center}
.head h1{font-size:18px;font-weight:500;margin-bottom:4px;opacity:.85}
.head .sub{font-size:11px;opacity:.55}
.city{font-size:24px;margin:18px 0 6px;font-weight:600}
.icon{font-size:72px;line-height:1;margin:8px 0}
.temp{font-size:56px;font-weight:200;font-variant-numeric:tabular-nums}
.desc{font-size:15px;margin-top:4px;opacity:.9}
.tabs{display:flex;overflow-x:auto;background:#fff;border-bottom:1px solid #eee;
padding:8px 6px;gap:4px}
.tab{padding:8px 14px;border-radius:10px;font-size:13px;cursor:pointer;
white-space:nowrap;transition:background .15s;color:#666}
.tab.active{background:#3498db;color:#fff;font-weight:500}
.body{padding:18px 20px}
.row{display:flex;justify-content:space-between;padding:12px 0;
border-bottom:1px solid #f0f0f0;font-size:14px}
.row:last-child{border:0}
.row .k{color:#888}
.row .v{font-weight:500}
.aqi{display:inline-block;padding:2px 10px;border-radius:8px;font-size:12px;color:#fff}
.forecast{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:16px}
.fc{background:#f7faff;border-radius:12px;padding:14px 8px;text-align:center}
.fc .d{font-size:12px;color:#888;margin-bottom:6px}
.fc .i{font-size:28px;margin:6px 0}
.fc .t{font-size:16px;font-weight:600}
</style></head><body>
<div class="head">
  <h1>🌤️ 天气 <span class="sub">mock 数据 · :8113</span></h1>
  <div class="city" id="city"></div>
  <div class="icon" id="icon"></div>
  <div class="temp" id="temp"></div>
  <div class="desc" id="desc"></div>
</div>
<div class="tabs" id="tabs"></div>
<div class="body">
  <div class="row"><span class="k">💨 风力</span><span class="v" id="wind"></span></div>
  <div class="row"><span class="k">💧 湿度</span><span class="v" id="hum"></span></div>
  <div class="row"><span class="k">🌫️ 空气质量</span><span class="v" id="aqi"></span></div>
  <div class="forecast" id="forecast"></div>
</div>
<script>
const CITIES=window.CITIES;
const FORE=window.FORECAST;
let cur=CITIES[0].id;
function aqiColor(l){
  if(l==='优')return '#27ae60';
  if(l==='良')return '#2ecc71';
  if(l.includes('轻度'))return '#f39c12';
  if(l.includes('中度'))return '#e67e22';
  return '#e74c3c';
}
function render(){
  const c=CITIES.find(x=>x.id===cur);
  document.getElementById('city').textContent=c.name;
  document.getElementById('icon').textContent=c.icon;
  document.getElementById('temp').textContent=c.temp+'°';
  document.getElementById('desc').textContent=c.desc;
  document.getElementById('wind').textContent=c.wind;
  document.getElementById('hum').textContent=c.hum+'%';
  const a=document.getElementById('aqi');
  a.innerHTML=c.aqi+' <span class="aqi" style="background:'+aqiColor(c.aqiLabel)+'">'+c.aqiLabel+'</span>';
  const f=FORE[cur]||[];
  document.getElementById('forecast').innerHTML=f.map(x=>
    `<div class="fc"><div class="d">${x.d}</div><div class="i">${x.i}</div><div class="t">${x.t}°</div></div>`
  ).join('');
  document.querySelectorAll('.tab').forEach(t=>
    t.classList.toggle('active',t.dataset.id===cur));
}
const tb=document.getElementById('tabs');
CITIES.forEach(c=>{
  const t=document.createElement('div');t.className='tab';t.dataset.id=c.id;
  t.textContent=c.name;t.onclick=()=>{cur=c.id;render();};
  tb.appendChild(t);
});
render();
</script></body></html>"""


def render_page():
    """把 CITIES / FORECAST 直接作为 JS 对象注入（避免 atob 处理 UTF-8 乱码）"""
    cities_js = json.dumps(CITIES, ensure_ascii=False)
    fore_js = json.dumps(FORECAST, ensure_ascii=False)
    inject = f"<script>window.CITIES={cities_js};window.FORECAST={fore_js};</script>"
    return HTML.replace("</head>", inject + "</head>", 1)


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        # 简单 API：返回 JSON 数据（方便外部调试）
        if u.path == "/api/cities":
            b = json.dumps(CITIES, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json;charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b)
            return
        if u.path == "/api/forecast":
            cid = parse_qs(u.query).get("id", [None])[0]
            data = FORECAST.get(cid, [])
            b = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json;charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html;charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(render_page().encode("utf-8"))

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"weather demo → http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
