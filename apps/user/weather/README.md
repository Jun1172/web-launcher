# 🌤️ 天气（weather）

![界面预览](images/screenshot.png)

天气 demo，验证多视图切换与 mock 数据驱动 UI 场景。

## 功能
- 5 个城市切换（北京、上海、广州、成都、哈尔滨）
- 当前天气（温度、描述、风力、湿度、AQI）
- 未来 3 天预报
- 内置简单 JSON API（`/api/cities`、`/api/forecast?id=xxx`）方便外部调试

## 验证什么
1. 多视图切换（顶部 tab 切换城市）
2. mock 数据驱动 UI 渲染
3. 单页面内提供 HTML + JSON 两种响应
4. base64 注入数据，避免模板转义问题

## 注意
- 数据是写死的（仅用于功能演示），不联网
- 想接真实数据，把 `CITIES` / `FORECAST` 换成真实 API 拉取即可

## 文件
- `app.json` —— 应用清单
- `app.py` —— 单文件 HTTP 服务（HTML + JSON API）
