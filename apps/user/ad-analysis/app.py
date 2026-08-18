"""ad-analysis —— ADC/IQ 曲线数据分析工具
- 端口 8115
- 严格遵循原始业务逻辑：64字节文件头解析、组件切换、ADC/IQ 复杂通道映射、ECharts 渲染
"""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PORT = 8115

# 使用 r"""...""" 原始字符串，防止 Python 误解析 JS 中的 \n 或 \uFEFF
HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ADC/IQ 曲线数据分析工具 (Web版)</title>
    <!-- 引入 Bootstrap 和 ECharts -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <style>
        body { background-color: #f4f6f9; font-family: 'Segoe UI', system-ui, sans-serif; }
        .card { box-shadow: 0 4px 12px rgba(0,0,0,0.08); margin-bottom: 20px; border: none; border-radius: 12px; }
        .card-header { background-color: #fff; border-bottom: 1px solid #eee; font-weight: 600; border-radius: 12px 12px 0 0 !important; }
        #chart-container { width: 100%; height: 650px; }
        .channel-list { max-height: 600px; overflow-y: auto; }
        .btn-action { height: 45px; font-weight: 500; letter-spacing: 0.5px; }
        .hint-text { font-size: 13px; color: #6c757d; margin-top: 8px; }
        .badge-zoom { background-color: #e9ecef; color: #495057; font-weight: normal; }
    </style>
</head>
<body>

<div class="container-fluid py-4">
    <h2 class="text-center mb-4 fw-bold text-primary">📊 ADC/IQ 曲线数据分析工具</h2>
    
    <!-- 控制面板 -->
    <div class="card">
        <div class="card-body">
            <div class="row g-3 align-items-end">
                <div class="col-md-3">
                    <label class="form-label fw-bold">1. 导入 BIN 文件</label>
                    <input type="file" class="form-control" id="fileInput" accept=".bin">
                </div>
                <div class="col-md-2">
                    <label class="form-label fw-bold">2. 数据类型</label>
                    <select class="form-select" id="dataTypeSelect">
                        <option value="ADC" selected>ADC (16bit)</option>
                        <option value="IQ">IQ (32bit)</option>
                    </select>
                </div>
                <div class="col-md-2">
                    <label class="form-label fw-bold">3. 选择组件</label>
                    <select class="form-select" id="compSelect" disabled>
                        <option>请先导入文件</option>
                    </select>
                </div>
                <div class="col-md-2">
                    <label class="form-label fw-bold">4. 通道控制</label>
                    <button class="btn btn-outline-secondary w-100" onclick="toggleSelectAll()">全选 / 取消全选</button>
                </div>
                <div class="col-md-3 d-grid gap-2">
                    <div class="row g-2">
                        <div class="col-6"><button class="btn btn-primary w-100 btn-action" onclick="plotCurves()">📈 绘制曲线</button></div>
                        <div class="col-6"><button class="btn btn-success w-100 btn-action" onclick="exportCSV()">📥 导出 CSV</button></div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- 绘图与通道列表 -->
    <div class="row">
        <div class="col-md-3">
            <div class="card h-100">
                <div class="card-header">通道列表 (按住Ctrl多选)</div>
                <div class="card-body channel-list p-0">
                    <select class="form-select border-0 h-100" id="channelSelect" multiple size="25" style="border-radius: 0;"></select>
                </div>
            </div>
        </div>
        <div class="col-md-9">
            <div class="card h-100">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <span>波形预览</span>
                    <div class="hint-text mb-0">
                        <span class="badge badge-zoom">🖱️ 滚轮: X轴缩放</span>
                        <span class="badge badge-zoom">⌨️ Ctrl+滚轮: Y轴缩放</span>
                        <span class="badge badge-zoom">🖼️ 右上角: 区域框选放大</span>
                    </div>
                </div>
                <div class="card-body">
                    <div id="chart-container"></div>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
    let currentFile = null;
    let dataLenArray = [];
    let parsedData = {};
    let chart = echarts.init(document.getElementById('chart-container'));

    document.getElementById('fileInput').addEventListener('change', handleFile);
    document.getElementById('compSelect').addEventListener('change', parseData);
    document.getElementById('dataTypeSelect').addEventListener('change', parseData);

    // 窗口自适应
    window.addEventListener('resize', () => chart.resize());

    async function handleFile(e) {
        currentFile = e.target.files[0];
        if (!currentFile) return;

        const buffer = await currentFile.arrayBuffer();
        const view = new DataView(buffer);

        dataLenArray = [];
        for (let i = 0; i < 16; i++) {
            dataLenArray.push(view.getUint32(i * 4, true));
        }

        const compSelect = document.getElementById('compSelect');
        compSelect.innerHTML = '';
        let hasData = false;
        for (let i = 0; i < 16; i++) {
            if (dataLenArray[i] > 0) {
                compSelect.add(new Option(`组件 ${i + 1}`, i));
                hasData = true;
            }
        }
        
        if (hasData) {
            compSelect.disabled = false;
            parseData();
        } else {
            alert("未找到有效数据组件");
        }
    }

    async function parseData() {
        if (!currentFile) return;
        
        const compId = parseInt(document.getElementById('compSelect').value);
        const dataType = document.getElementById('dataTypeSelect').value;
        const buffer = await currentFile.arrayBuffer();
        const view = new DataView(buffer);

        let offset = 64;
        for (let i = 0; i < compId; i++) offset += dataLenArray[i];
        const compLen = dataLenArray[compId];

        if (dataType === 'ADC') {
            parsedData = parseADC(view, offset, compLen, compId);
        } else {
            parsedData = parseIQ(view, offset, compLen, compId);
        }

        updateChannelList();
    }

    function parseADC(view, offset, length, compId) {
        const validLen = Math.floor(length / 32) * 32;
        const channels = {};
        const evenTable = [4,5,6,7,12,13,14,15, 0,1,2,3,8,9,10,11];
        const oddTable = [15,14,13,12,7,6,5,4, 11,10,9,8,3,2,1,0];
        const table = compId % 2 === 0 ? evenTable : oddTable;

        for (let i = 0; i < 16; i++) {
            const readAddr = table[i];
            const name = i < 8 ? `通道${compId*8+i+1} H极化` : `通道${compId*8+(i-8)+1} V极化`;
            const data = [];
            for (let j = 0; j < validLen / 32; j++) {
                const byteOffset = offset + j * 32 + readAddr * 2;
                data.push(view.getInt16(byteOffset, true));
            }
            channels[name] = data;
        }
        return channels;
    }

    function parseIQ(view, offset, length, compId) {
        const validLen = Math.floor(length / 16) * 16;
        const channels = {};
        
        let startIdx = 0;
        for(let i=0; i<validLen/16; i++) {
            const hq = view.getUint32(offset + i*16 + 12, true);
            const td = (hq >>> 27) & 0x7;
            const freq = (hq >>> 30) & 0x3;
            if(td === 1 && freq === 0) {
                startIdx = i;
                break;
            }
        }

        const alignedLen = Math.floor((validLen/16 - startIdx) / 512) * 512;
        
        for(let f=0; f<4; f++) {
            for(let t=0; t<8; t++) {
                channels[`H_F${f}_TD${t}_Real`] = []; channels[`H_F${f}_TD${t}_Imag`] = [];
                channels[`V_F${f}_TD${t}_Real`] = []; channels[`V_F${f}_TD${t}_Imag`] = [];
            }
        }

        for(let i=0; i<alignedLen; i++) {
            const idx = offset + (startIdx + i)*16;
            const vi = view.getUint32(idx, true);
            const vq = view.getUint32(idx + 4, true);
            const hi = view.getUint32(idx + 8, true);
            const hq = view.getUint32(idx + 12, true);

            const extract24 = (val) => {
                let v = val & 0xFFFFFF;
                return v >= 0x800000 ? v - 0x1000000 : v;
            };

            const tdH = (hq >>> 27) & 0x7, freqH = (hq >>> 30) & 0x3;
            const tdV = (vq >>> 27) & 0x7, freqV = (vq >>> 30) & 0x3;

            channels[`H_F${freqH}_TD${tdH}_Real`].push(extract24(hi));
            channels[`H_F${freqH}_TD${tdH}_Imag`].push(extract24(hq));
            channels[`V_F${freqV}_TD${tdV}_Real`].push(extract24(vi));
            channels[`V_F${freqV}_TD${tdV}_Imag`].push(extract24(vq));
        }
        return channels;
    }

    function updateChannelList() {
        const select = document.getElementById('channelSelect');
        select.innerHTML = '';
        Object.keys(parsedData).forEach(name => {
            select.add(new Option(name, name));
        });
        toggleSelectAll(true);
    }

    function toggleSelectAll(forceSelect = false) {
        const select = document.getElementById('channelSelect');
        const shouldSelect = forceSelect || Array.from(select.selectedOptions).length === 0;
        for (let i = 0; i < select.options.length; i++) {
            select.options[i].selected = shouldSelect;
        }
    }

    function getSelectedChannels() {
        const select = document.getElementById('channelSelect');
        return Array.from(select.selectedOptions).map(o => o.value);
    }

    function plotCurves() {
        const selected = getSelectedChannels();
        if (selected.length === 0) {
            alert("请至少选择一个通道进行绘制！");
            return;
        }

        const series = selected.map(name => ({
            name: name,
            type: 'line',
            showSymbol: false,
            data: parsedData[name],
            sampling: 'lttb', // 降采样算法，保留波形特征
            large: true,
            largeThreshold: 2000
        }));

        chart.setOption({
            tooltip: { 
                trigger: 'axis',
                axisPointer: { type: 'cross' } // 十字准星
            },
            legend: { type: 'scroll', bottom: 0, data: selected },
            toolbox: {
                feature: {
                    dataZoom: { yAxisIndex: 'none', title: { zoom: '区域放大', back: '还原' } },
                    restore: { title: '重置视图' },
                    saveAsImage: { title: '保存图片', pixelRatio: 2 } // 高清保存
                },
                right: 20
            },
            // 核心修复：X轴和Y轴完全独立缩放
            dataZoom: [
                { 
                    type: 'inside', 
                    xAxisIndex: 0, 
                    filterMode: 'none' // 关键：X轴缩放时，Y轴保持固定
                },
                { 
                    type: 'inside', 
                    yAxisIndex: 0, 
                    filterMode: 'none' // 允许Y轴独立缩放 (配合Ctrl+滚轮)
                },
                { 
                    type: 'slider', 
                    xAxisIndex: 0, 
                    filterMode: 'none',
                    bottom: 30 
                },
                { 
                    type: 'slider', 
                    yAxisIndex: 0, 
                    filterMode: 'none',
                    right: 10,
                    width: 20,
                    handleSize: '80%'
                }
            ],
            grid: {
                left: 60,
                right: 60, // 给右侧Y轴滑动条留出空间
                top: 40,
                bottom: 80
            },
            xAxis: { type: 'category', name: '采样点', boundaryGap: false },
            yAxis: { 
                type: 'value', 
                name: '幅值', 
                scale: true, // 关键：Y轴不从0开始，自适应数据波动
                splitLine: { lineStyle: { type: 'dashed' } }
            },
            series: series
        }, true);
    }

    function exportCSV() {
        const channels = getSelectedChannels();
        if (channels.length === 0) {
            alert("请至少选择一个通道进行导出！");
            return;
        }

        const maxLen = Math.max(...channels.map(c => parsedData[c].length));
        let csvRows = ["Sample_Index," + channels.join(",")];
        
        for (let i = 0; i < maxLen; i++) {
            let row = [i];
            channels.forEach(ch => row.push(parsedData[ch][i] !== undefined ? parsedData[ch][i] : ""));
            csvRows.push(row.join(","));
        }

        // 添加 BOM 头防止 Excel 打开中文乱码
        const BOM = "\uFEFF"; 
        const blob = new Blob([BOM + csvRows.join("\n")], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.setAttribute("href", url);
        
        const compId = parseInt(document.getElementById('compSelect').value) + 1;
        const dataType = document.getElementById('dataTypeSelect').value;
        link.setAttribute("download", `组件${compId}_${dataType}_曲线数据_${new Date().getTime()}.csv`);
        
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    }
</script>
</body>
</html>"""


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
    print(f"ad-analysis → http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()