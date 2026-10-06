# 空会话首屏滚动修复

## 原因与修改

修复前，欢迎区在消息滚动容器内同时使用 `height:100%` 和 `min-height:400px`（窄窗口为 300px），后面还有空消息区的上下内边距。Edge 复现：1280×850 时消息区 clientHeight=551、scrollHeight=610；800×600 时为 308、448。侧栏展开与折叠均可复现。

参考 [Codex startup_draft_layout.rs](https://github.com/openai/codex/blob/main/codex-rs/tui/src/startup_draft_layout.rs)：首屏装饰只在标题与底部输入区之间的剩余区域绘制，不进入 scrollback。公开仓库提供 Rust 终端首屏布局，没有可直接复制的桌面 React/CSS 源码。本次在现有 React 窗口中移植这套布局方式，没有把 Rust 源码作为前端执行代码。

- `ai/frontend/src/Chat.tsx`：欢迎内容成为消息 viewport 的兄弟元素，由剩余空间容器承载；右键事件由该容器处理，保持欢迎页与消息区菜单。
- `ai/frontend/src/styles.css`：欢迎区限制在剩余空间内；空消息区不添加内边距；根据剩余高度收紧欢迎区，低高度时隐藏装饰或次要文字；历史消息继续使用原有滚动容器。
- 已重建 `ai/frontend/dist`。关闭并重新打开 AI 对话窗口后生效。
- 源码及旧前端资源备份：`backups/chat-empty-layout-20261006/`；修改差异：[chat-empty-layout.diff](chat-empty-layout.diff)。

## 验证

- 新增 Playwright 空布局回归：7 种 viewport 尺寸（360×320 至 1600×1000）× 侧栏展开/折叠，检查 scrollHeight=clientHeight、设置 scrollTop 后仍为 0、输入区在窗口内；另验证欢迎快捷按钮与历史切换后的滚动行为。
- 首轮修复前的两个回归用例因真实溢出而失败；修复后均通过。
- [相关浏览器回归](chat-empty-layout-browser.log)：10 项通过，覆盖首屏、历史滚动、阅读锚点、区域宽度、查找与右键菜单；此前 UI 回归包含输入法、草稿、附件、设置与流式历史，也通过。
- [实际 WebView2](chat-empty-layout-webview.json)：生产资源、临时配置与临时数据库；4 种请求窗口尺寸 × 侧栏展开/折叠，共 8 组实际 viewport 测量均无滚动空间，欢迎快捷按钮可填写输入区。未执行模型请求或 Praat 操作。
- [生产构建](chat-empty-layout-build-retry.log)：TypeScript 与 Vite 通过。第一次构建遇到 esbuild 系统临时目录访问错误，换用任务专用临时目录后成功。
- [全量前端单元测试](chat-empty-layout-vitest.log)：112 项通过、1 项失败。失败项为 `tests/speech-dictionaries.test.tsx > switches the sidebar to acoustic models and uses their picker and current selection`，期待旧标题“管理语音词典与模型”，与当前词典页面不符；本次未修改该页面或其测试。

生产 CSS：`assets/index-Bj127IaB.css`，SHA-256 `38ADB1F92F6ED7A3E5E19D737244BD65D6AEA9F1BC496A8598FD85ADBCD86D11`。
