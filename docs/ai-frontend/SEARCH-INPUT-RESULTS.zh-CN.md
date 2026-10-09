# 搜索输入与 IME

侧栏搜索与会话内查找使用普通文本输入、保留搜索语义和中性焦点样式。`isComposing` 或 keyCode 229 时放行组合输入键盘事件，避免确认／取消输入法被识别为查找导航、关闭或全局快捷键。

组合事件处理与 no-outline 样式片段来自 Pi 固定提交 `0d47d26769ecbeca1c3ab56fa83b58a91de8190e` 的 `SearchDialog.tsx`、`useAppShellRuntime.tsx` 与 `styles/overlays.css`；固定原件保存在 `ai/third_party/pi-desktop/upstream/search/`。匹配服务另见 [搜索数据流](SEARCH-PERFORMANCE-RESULTS.zh-CN.md)。

检查入口为 `ai/tests/verify_search_input_desktop.py`。事件层检查不证明操作系统所有输入法切换快捷键或实体输入法均已人工验证。
