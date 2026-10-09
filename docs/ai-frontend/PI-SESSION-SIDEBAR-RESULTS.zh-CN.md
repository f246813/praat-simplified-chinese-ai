# 会话侧栏

`src/pi/sidebar/Sidebar.tsx` 适配 Pi 侧栏的紧凑会话列表、独立置顶、自定义分区、时间分组、折叠、四种排序、悬停预览、多选、菜单和键盘操作。会话来源按项目／连接／列表组织，详见 [工具栏菜单](SIDEBAR-OPTIONS-RESULTS.zh-CN.md)。

会话点击由 ChatStore 加载；草稿与阅读位置按会话保存。Ctrl／Cmd 与 Shift 多选、侧栏快捷键和宽度调整连接现有宿主。预览通过读取会话生成，不依赖独立 Agent 运行时。旧库正文只读；归档、分区和隐藏入口的侧旁元数据例外见 [归档页面](ARCHIVED-SETTINGS-COMPLETION.zh-CN.md)。

当前滑条通道为 14px，细滑块和尺寸限制见 [滚动条](HISTORY-SCROLLBAR-RESULTS.zh-CN.md)。来源固定为 Pi `0d47d26769ecbeca1c3ab56fa83b58a91de8190e`，原件、许可及适配范围见 [来源说明](FRONTEND-SOURCES.md)。检查入口包括 `ai/tests/verify_history_organization_desktop.py` 和前端 `tests/browser` 中的侧栏用例。
