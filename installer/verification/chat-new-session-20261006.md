# AI 对话窗口默认进入新会话

窗口首次连接宿主时创建并选中空白“新会话”，不自动加载第一条历史记录。历史会话保留在侧栏，可继续查看和使用；刷新宿主记录、重连及事件游标重置保持当前选择。关闭后重新打开窗口会创建另一条独立的新会话。

## 实现与交付

- `ai/frontend/src/App.tsx` 在首次启动调用 `initialize({newSession: true})`。
- `ai/frontend/src/store.ts` 的初始化复用现有会话创建、持久化和选择流程；默认初始化继续用于刷新和同步。
- 已通过 TypeScript 检查并重建 `ai/frontend/dist`，该目录即当前 Praat 使用的前端资源。关闭并重新打开 AI 对话窗口后生效。
- 旧源代码与前端资源备份在 `backups/chat-new-session-20261006-001106/`。

## 验证

- [前端全量测试](chat-new-session-vitest.log)：20 个文件、113 项通过。新增 3 项覆盖置顶/旧历史保留、空工作空间、新会话创建、重复刷新、事件重置及重新打开。
- [真实 WebView2](chat-new-session-webview.json)：12 项通过。使用临时数据库和配置，验证首次打开与重新打开均显示空白新会话、刷新不额外创建会话、历史查看和任务归属正常；模型执行使用测试夹具，未调用真实模型或修改用户历史。
- [浏览器菜单与归档回归](chat-new-session-browser.log)：10 项通过。新测试的首次失败来自测试误用多选样式判断当前会话，已改为核对 `aria-current` 并在后续运行通过。
- [浏览器启动、侧栏和对话回归](chat-new-session-browser-followup.log)：11 项通过；滚动条用例运行时仍使用旧会话数量，调整为包含启动新会话后，[单独复验 1 项通过](chat-new-session-browser-scrollbar.log)。三次运行合计覆盖 22 项不同的浏览器检查，均已通过。
- [生产构建](chat-new-session-build.log)：成功，运行时主资源为 `assets/index-CZSAVVC4.js`，SHA-256 为 `47EF70A104D968FB845F003B8B45E60C20831E6E11E27E5C168B905B00F8984E`。

本次仅改变打开窗口时的会话选择，用户原有会话、草稿及设置保留。
