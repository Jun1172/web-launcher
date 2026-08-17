# 🗒️ 便签（notes）

便签 demo，验证 `localStorage` 持久化场景。

## 功能
- 添加便签（输入框 + 回车 / 按钮）
- 双击便签进入编辑，失焦保存
- 删除便签（带确认）
- 全部数据存于浏览器 `localStorage`，关闭重开仍在

## 验证什么
1. iframe 内 `localStorage` 是否可正常读写
2. 列表的增删改交互
3. 时间格式化（今天 / 跨天）

## 文件
- `app.json` —— 应用清单
- `app.py` —— 单文件 HTTP 服务（HTML/CSS/JS 内联）
