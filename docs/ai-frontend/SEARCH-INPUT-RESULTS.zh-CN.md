# 搜索输入框修复：2026-10-04

两处搜索输入（侧栏历史搜索、会话内查找）已取消全局绿色焦点 outline，保留原搜索容器边框。没有修改其他输入框或按钮的焦点样式。

输入法部分优先搬运 Pi-Desktop `0d47d26769ecbeca1c3ab56fa83b58a91de8190e` 的现成代码：

- `SearchDialog.tsx`：原生文本输入属性，以及 `event.nativeEvent.isComposing || event.keyCode === 229` 时放行的键盘处理。
- `useAppShellRuntime.tsx`：全局快捷键在 `isComposing`／229 时直接返回。
- `styles/overlays.css`：搜索输入的 `outline: none`，按本项目选择器接入，覆盖全局绿色焦点 outline。

接入点是 `SearchBar.tsx`、`Chat.tsx`、已有 Pi 侧栏及搜索样式。组合输入的确认／取消不再触发查找导航、关闭搜索或全局快捷键。会话内输入使用中性 `type="text"`，保留 `role="searchbox"` 和搜索名称；没有设置系统输入语言、强制 IME 模式或重建搜索服务。

公开 Codex 仓库已核对，未提供可直接接入本项目的桌面 React 搜索输入组件。本轮实际搬运 Pi 的上述输入／事件／样式片段，继续连接既有 host store；现有搜索匹配和高亮算法保留。三份完整原文件按固定 Git blob／SHA-256 核验，原件和许可随生产资源分发，见 [Pi 来源说明](../../ai/third_party/pi-desktop/NOTICE.md)及[来源验收](verification/search-input-source-result.json)。用户要求的“先找现成代码、优先搬运与拼接”已记录在 [来源约束](FRONTEND-SOURCES.md)。

验证：修复前检查复现绿色 outline 和组合输入快捷键被拦截；修复后 9 项相关 Edge 浏览器检查、24 项搜索／宿主状态单元检查、TypeScript 和生产构建通过。原有查找匹配、高亮、上／下一个结果、清空搜索、侧栏预览、多选和滑条检查通过。

真实生产 pywebview／WebView2 的两种搜索输入均通过组合输入、中文／日文提交和焦点保持检查；组合中的 Enter／Escape 未被取消默认行为，搜索保持打开。使用 WebView2 DevTools 输入协议生成组合输入，检查真实 `compositionstart/update/end`；不宣称逐一人工操作了系统安装的每一种输入法切换快捷键。宿主 `ImeMode` 为 `NoControl`，没有禁止输入法或模型／Praat 调用。见 [原生验收](verification/search-input-desktop-result.json)，可运行 [verify_search_input_desktop.py](../../ai/tests/verify_search_input_desktop.py)复核。

`ai/frontend/dist` 已更新；重开 AI 前端加载新资源。
