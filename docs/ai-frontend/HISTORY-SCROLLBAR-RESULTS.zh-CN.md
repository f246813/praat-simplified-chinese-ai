# 左侧历史栏贴边滚动条验收（2026-10-04）

按用户提供的 Codex 截图调整左侧会话历史栏。继续使用项目已提取的 PI-Desktop 滚动条规则与显示逻辑，不添加依赖或另一套会话运行时。

后续用户反馈滑块仍难选中，已扩大为 14px 命中通道并迁入整套会话侧栏交互；当前实现和验收见 [会话侧栏移植](PI-SESSION-SIDEBAR-RESULTS.zh-CN.md)。下面保留首轮 6px 版本的历史记录。

## 来源与修改

- 固定来源：PI-Desktop `0d47d26769ecbeca1c3ab56fa83b58a91de8190e` 的 `apps/desktop/src/styles/base.css` 和 `apps/desktop/src/lib/scrollbar-reveal.ts`。原始代码在 `ai/third_party/pi-desktop/upstream/`，实际使用的移植代码在 `ai/frontend/src/pi/`；许可和来源见 [NOTICE](../../ai/third_party/pi-desktop/NOTICE.md)。这些移植文件本次保持原实现。
- 本次产品源码修改仅在 `ai/frontend/src/styles.css`：历史滚动区域向侧栏框线延伸，条目保留原有内边距；适配常规及 900px 以下窗口的内边距，阻止横向滚动，预留稳定的 6px 原生通道。
- 原滚动区域距外边缘 16px，修改后紧邻边框内侧（默认缩放下距外边缘 1px，即边框本身）。侧栏宽度调节区移到边框外侧，避免覆盖原生滑块。
- 滑块由浏览器按可见高度／内容总高度自动计算；增加历史会缩短，删除或筛选会增长，内容不足一屏时无需滚动。沿用 Pi 的圆角、透明轨道以及悬停／焦点／滚动显示、滚动后保持 300ms 的行为。

## 验证结果

- 前端 Vitest：12 个文件，79 项通过。
- 相关 Playwright：8 项通过，覆盖会话菜单、CRUD、输入法、阅读位置、后台流式隔离、侧栏／对话区拖动和键盘调节。
- 独立原生滚动检查：3、35、70 条记录，以及搜索到 1 条记录；1280px、820px、390px 窗口均贴边且没有横向溢出。实际指针拖动原生滑块可以滚动列表，侧栏宽度不变；筛选前后条目宽度稳定。[浏览器读数](verification/history-scrollbar-browser-result.json)
- 真实 pywebview＋WebView2：使用最新生产资源、隔离数据库／配置和 70 条宿主历史，筛选到 35 条及 1 条均通过。实际 DPI=1.25，贴边距离与经缩放的边框宽度一致；调节区与滚动区域无重叠。原生滚动及显示计时正常，真实用户数据未用于验收。[桌面验收](verification/history-scrollbar-desktop-result.json)
- 离线资产、408 项依赖通知、TypeScript 与 Vite 生产构建成功，`ai/frontend/dist` 及随包可重建源码已更新。保留既有大 chunk 提示。首次构建遇到本机 esbuild 在系统临时目录的权限错误，依照已有构建记录使用独立工具副本与进程内 TEMP／TMP 后成功，未改变系统权限或工具源文件。

截图来自明确的浏览器演示夹具，鼠标位于原生滑块处；35 条历史的可见滑块约 94px，70 条约 46px：

| 35 条历史 | 70 条历史 |
|---|---|
| ![35 条历史](screenshots/history-scrollbar-35.png) | ![70 条历史](screenshots/history-scrollbar-70.png) |

## 使用

关闭当前 AI 聊天窗口，再从 Praat 的“前端／启动前端”打开，即可加载最新生产资源。

源码备份和本轮检查脚本位于 `.aipraat-backups/history-scrollbar-20261004-112846/`。本次未重制安装器或发布版本。
