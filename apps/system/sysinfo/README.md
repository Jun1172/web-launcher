# 📊 系统信息（sysinfo，系统应用）

![界面预览](images/screenshot.png)

实时显示 CPU / 内存 / 磁盘使用情况和版本信息。

## 功能
- **CPU 使用率**：采样 GetSystemTimes（Windows）/ /proc/stat（Linux）
- **内存使用率**：GlobalMemoryStatusEx（Windows）/ /proc/meminfo（Linux）
- **磁盘占用**：项目所在盘符的使用情况
- **版本信息**：Launcher 版本、Python 版本、OS、主机名、CPU 核心数
- **已安装应用列表**：扫描 `apps/system/` 和 `apps/user/` 显示全部应用及版本
- 每 3 秒自动刷新动态信息

## 系统应用属性
- ✅ 默认安装（在 `apps/system/sysinfo/`）
- ✅ 可通过应用商店升级
- ❌ 不可卸载

## 跨平台支持
- **Windows**：用 `ctypes` 调 `kernel32` API（GetSystemTimes / GlobalMemoryStatusEx）
- **Linux**：读 `/proc/stat` 和 `/proc/meminfo`
- **macOS**：暂不支持动态采集（静态信息仍可显示）

## 文件
- `app.json` —— 应用清单
- `app.py` —— 单文件 HTTP 服务（HTML + JSON API）

## API
- `GET /` —— 系统信息页面
- `GET /api/info` —— 返回 JSON 格式的静态 + 动态信息
