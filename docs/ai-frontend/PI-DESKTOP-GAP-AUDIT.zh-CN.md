# 前端交互实现与限制

本文描述 `ai/frontend/src` 的当前实现。固定上游来源见 [来源说明](FRONTEND-SOURCES.md)，交互参考见 [Pi 交互来源](PI-DESKTOP-INTERACTION-SPEC.zh-CN.md)。下列数值是当前实现参数，不能据此推断批准的业务规则。

| 模块 | 当前行为与限制 |
| --- | --- |
| `layout.ts`、`Panes.tsx` | 侧栏宽度 240–520、默认 272，低于拖动阈值 160 时折叠；主栏预算下限 450。对话带默认 850、配置范围 560–4000，受实际窗口宽度约束；宿主保存宽度 |
| `scroll.ts`、`Anchoring.tsx` | 展开保持行相对视口偏移，内容 ResizeObserver 处理高度变化；用户滚动解除锚定 |
| `transcript-menu.ts`、`TranscriptMenu.tsx` | 复制／选择消息、会话复制与选择、工具证据复制、顶部／最新跳转；没有消息改写、单消息删除或重新生成接口 |
| `completions.ts`、`Composer.tsx` | `/新建`、`/设置`、`/取消`、`/附件`；取消只在本会话任务活动时出现；没有插件命令或工作区 `@` 文件 RPC |
| `transcript-window.ts` | 首帧 15、稳态至少 60、展开步长 40；120px 触顶阈值。阅读锚点可扩展挂载窗口；全部已加载历史仍在内存 |
| `minimap.ts`、`MinimapRail.tsx` | 缩略图导航已挂载行，更早入口展开下一段窗口 |
| `search.ts`、`SearchBar.tsx` | 当前渲染正文中的字面量匹配、最多 500 处；CSS 高亮不可用时仅定位。未挂载行需要先展开 |
| `codex/useSessionSearch.ts` | 宿主跨会话正文搜索，100ms 防抖和代次检查；草稿、阅读位置、排序和预览不改变搜索修订 |
| `pi/sidebar/styles.css` | 原生 14px 滚动通道、静止 6px 可见滑块、CSS 最短高度 68px；实际尺寸受浏览器滚动规则约束 |

这些适配使用同一 ChatStore 和受限 RPC。远程连接管理、插件系统、工作面板与 Pi Agent 运行时没有接入。可复现检查入口见 [构建说明](BUILD-RESULTS.zh-CN.md)，浏览器与模拟宿主覆盖范围需与真实桌面／模型能力区分。
