# WebView2 Runtime 安装

launcher.exe 的桌面窗口依赖 WebView2 Runtime。Win11 自带；Win10 LTSC/精简版/久未更新的机器可能缺失，表现为窗口打开后全白。

> 缺失时 launcher 会自动回退纯 HTTP 模式（不开窗口，日志里给出 `http://127.0.0.1:8000/` 访问地址），不影响使用，但推荐装上以恢复原生窗口体验。

## 安装方式（任选其一）

1. **官方在线安装包（推荐）**：到 <https://developer.microsoft.com/microsoft-edge/webview2/> 下载 **Evergreen Standalone Installer**（x64），双击运行，几秒装完，不用重启。
2. **离线安装包**：同一页面的 Fixed Version / 离线版（约 100+ MB），适合不能上网的工控机/内网机器。
3. **winget 命令行**：`winget install Microsoft.EdgeWebView2Runtime`

## 判断是否已装

装过新版 Edge 浏览器的机器通常已有 WebView2，无需重复安装。验证方法：运行 launcher.exe，若正常弹出桌面窗口即已安装；若日志显示回退 HTTP 模式则未装。
