# 🛒 应用商店（store，系统应用）

![界面预览](images/screenshot.png)

Launcher 的内置应用商店，浏览远端仓库并安装 / 升级 / 卸载应用。

## 功能
- 三个 tab：全部 / 已安装 / 可更新
- 搜索框按名称过滤
- 系统应用显示"系统"标签 + "✓ 系统应用"按钮（不可卸载）
- 用户应用支持"安装 / 升级 / 卸载"
- 通过 launcher 的 `LAUNCHER_URL` 调用 `/api/repo`、`/api/install`、`/api/uninstall`

## 系统应用属性
- ✅ 默认安装
- ✅ 自身可被升级（新版本覆盖 `apps/system/store/`）
- ❌ 不可卸载

## 文件
- `app.json` —— 应用清单
- `app.py` —— 单文件 HTTP 服务（HTML/CSS/JS 全部内联）

## 依赖
- 启动时从 `config.json` 读取 `launcher.host` / `launcher.port`，
  拼出 `LAUNCHER_URL` 注入到前端 JS 中。
- 远端仓库地址在 `config.json` 的 `repo.url` 里配置。
