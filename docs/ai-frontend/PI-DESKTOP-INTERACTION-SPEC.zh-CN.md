# Pi 交互参考与适配边界

固定来源为 [PI-Desktop `0d47d26769ecbeca1c3ab56fa83b58a91de8190e`](https://github.com/vastsa/PI-Desktop/tree/0d47d26769ecbeca1c3ab56fa83b58a91de8190e)，LGPL-3.0。原样文件、局部提取物和交互参考需区分，清单见 [来源说明](FRONTEND-SOURCES.md)及 `ai/third_party/pi-desktop/NOTICE.md`。

| 交互参考 | 本项目适配 |
| --- | --- |
| `SearchDialog.tsx`、转写搜索高亮 | IME 事件放行、普通文本输入与 CSS Custom Highlight API；会话内查找由渲染文本提供，跨会话正文由 Codex／SQLite 适配提供 |
| `ConversationMinimap.tsx`、`conversation-minimap.ts` | 当前挂载行导航与预览，更早入口扩展挂载窗口 |
| `transcript-window.ts`、`transcript-reading.ts` | 消息挂载窗口和宿主 `{messageId,offset}` 阅读锚点 |
| composer slash dispatch | 当前四个界面动作，没有 Pi 插件命令注册表 |
| sidebar resize、chat content width | 项目本地布局计算，宽度通过宿主偏好保存 |
| `ContextMenu.tsx`、侧栏源文件 | 局部提取／适配，连接 ChatStore 和白名单 RPC |

Pi 的搜索 IPC、Electron／Rust 宿主、全局 app-store 与 Agent 运行时没有作为本项目运行时导入。本项目上下文状态栏是局部实现；不能从文件同名推断复制了 Pi `ComposerStatus.tsx`。当前参数与未接入能力见 [交互实现](PI-DESKTOP-GAP-AUDIT.zh-CN.md)。
