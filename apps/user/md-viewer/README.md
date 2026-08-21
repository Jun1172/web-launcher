# 📖 离线设备手册（md-viewer）

Markdown 文档浏览器，用于离线浏览设备手册 / 技术文档。

## 功能
- 左侧目录树递归展示 `docs/` 下的 Markdown 文档，文件夹可折叠
- 右侧阅读区渲染 Markdown（标题 / 列表 / 代码块 / 表格 / 链接 / 图片 / 加粗斜体）
- 本地图片通过 `/api/image` 加载，相对路径按当前文件目录解析
- 深色 GitBook 风格主题，面包屑导航，移动端侧栏可折叠
- 离线运行，所有资源内嵌，不依赖外部 CDN

## 目录约定
- `docs/` —— 文档根目录（缺失时自动创建示例 `README.md`）
- `docs/images/` —— 文档引用的本地图片
- 仅 `.md` / `.markdown` 文件出现在目录树；图片在 Markdown 中引用即可

## 接口
| 路由 | 说明 |
| --- | --- |
| `GET /` | 首页（内嵌 HTML） |
| `GET /api/tree` | docs 目录树（JSON 嵌套结构） |
| `GET /api/file?path=xxx` | 读取 Markdown 文本内容 |
| `GET /api/image?path=xxx` | 读取图片（按扩展名设置 Content-Type） |

## 安全
- 路径遍历防护：禁止 `..`，resolve 后校验仍在 `docs/` 目录内

## 文件
- `app.json` —— 应用清单（端口 8154）
- `app.py` —— 单文件 HTTP 服务（HTML/CSS/JS 内嵌，含极简 Markdown 渲染器）
