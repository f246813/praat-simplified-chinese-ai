# 现代 AI 前端：PI-Desktop 已批准交互缺口审计

> 状态：**审计完成；本轮补齐“窗口内分区尺寸调节”。** 其余缺口按优先级列在第 4 节，尚未实施。
> 上游比对基线：PI-Desktop 固定研究提交 `0d47d26769ecbeca1c3ab56fa83b58a91de8190e`（桌面包 0.16.0，LGPL-3.0）。
> 交互级规格（含全部实测常量与源码位置）：[PI-DESKTOP-INTERACTION-SPEC.zh-CN.md](PI-DESKTOP-INTERACTION-SPEC.zh-CN.md)。
> 本文不改变已确认架构；[CHAT-UI-ARCHITECTURE.zh-CN.md](CHAT-UI-ARCHITECTURE.zh-CN.md) 仍是权威设计。

> 2026-10-04 后续授权：用户已明确要求迁入会话侧栏全部交互。第 4.1 项现已实现，批量删除也使用就地两段确认；侧栏滚动通道扩大为 14px。当前状态见 [会话侧栏移植验收](PI-SESSION-SIDEBAR-RESULTS.zh-CN.md)，本文早期“未授权”描述仅记录当时范围。

## 1. 结论

1. **架构文档第 3 节（聊天功能六组）已基本落地**，逐项核对见第 3 节。**架构文档第 3 节的全部批准项现已落地**（展开锚定、长历史挂载窗口与阅读锚点、对话缩略图、转写内搜索与命中高亮均已补齐）；已批准范围内**没有已知未落地项**。
2. **架构文档第 4、5 节（会话侧栏、设置仪表盘）逐条落地**，包括默认折叠、齿轮固定底部、六分类页面。
3. **本轮已补齐全部六项选定交互**：窗口内分区尺寸调节、展开锚定、转写右键菜单、输入补全、长历史挂载窗口与阅读锚点、对话缩略图、转写内搜索与命中高亮（第 6 节）。
4. **用户选定的六项已全部落地。** 第 4 节列出的 4 项剩余缺口都是**表外的 P2 交互**（侧栏分组与悬停预览、Toast 与通知、设置搜索与快捷键页、就地两段式删除确认），不在本轮授权范围内。
5. **两个会“静默毁掉”移植的宿主事实**（第 5 节）已核实：WebView2 以 private mode 运行且关闭时删除整个用户数据目录，因此任何照搬 PI-Desktop `localStorage` 的持久化都不会生效。
6. **一个新发现的既有缺陷**：assistant-ui 的自动跟随会在内容尺寸变化时把视口拉回底部，即使读者已上翻。展开锚定顺带修复了这一点（第 6.2 节有反证数据）。

## 2. 核对方法

- **本地实现**：逐文件阅读 `ai/frontend/src` 全部 17 个源文件与 `styles.css`；对“不存在的能力”用 `grep` 反证（`resize|pointerdown|minimap|content-visibility|anchor|slash|autocomplete|completion`），而不是只看文档声明。
- **上游比对**：按固定提交拉取 `apps/desktop/src` 与 `packages/shared/src` 的完整文件树，再逐个取正文；`raw.githubusercontent.com` 在本会话不稳定，改用同 revision 的 jsDelivr 镜像取正文、`api.github.com` 的 git trees/contents 做路径发现与兜底。**所有引用内容都出自该 SHA，没有降级到其他版本。**
- **判定标准**：架构文档第 3 节表格是“批准范围”，第 4、5 节是布局要求；表格之外的交互按“是否属于主流 AI 客户端基础交互”分级，不擅自升级为已批准项。
- **诚实边界**：PI-Desktop 的 `ComposerStatus.tsx` 与本项目同名的 `ComposerStatus.tsx` 不是同一个东西——上游该文件渲染队列提示与 toast，上下文用量检查器由 `features/chat/composer/ComposerToolbar.tsx` 挂载。命名相同不代表已搬入。

## 3. 架构文档第 3 节逐项核对

| 功能组 | 批准要求 | 本地实现证据 | 判定 |
| --- | --- | --- | --- |
| 输入编辑器 | 富文本输入 | `Composer.tsx` + Tiptap starter-kit | 已落地 |
| | 中文输入法防误发送 | `Composer.tsx` composition 守卫 + `editor.ts::shouldSend` | 已落地 |
| | 换行、快捷键 | Shift+Enter 换行；Ctrl/⌘+B、I、Alt+↑/↓ 输入历史；`send_key` 可配 | 已落地 |
| | 输入历史 | `editor.ts::InputHistory`（`navigate` 带原始草稿回退） | 已落地 |
| | 会话草稿 | `store.view({draft})` + `sessions.view` RPC，按会话隔离 | 已落地 |
| | 附件标记及删除 | `ComposerPrimitive.Attachments` + `NativeAttachment`（含移除按钮） | 已落地 |
| 思考与执行过程 | 思考折叠／展开 | `Chat.tsx::ActivityCard` 用原生 `<details>`；空思考不渲染 | 已落地 |
| | 执行过程展示 | `activities`（progress/thinking/tool/compression）按消息归属 | 已落地 |
| | 真实运行状态 | `statusLabel`、`.actual-running`、无内容时明确“等待后端内容…”，不伪造思考 | 已落地 |
| 工具卡片 | 参数／结果／状态／展开详情 | `ActivityCard` tool 分支：参数 JSON、结果／结构化证据、投递事实 | 已落地 |
| 流式正文 | 流式 Markdown | assistant-ui 流式 + `Markdown.tsx` | 已落地 |
| | 代码高亮、公式／图表 | rehype-highlight、KaTeX、离线 Mermaid（host origin 加载） | 已落地 |
| | 文字释放效果 | `Markdown.tsx` 平滑显示（项目本地适配，非 Pi 模块） | 已落地 |
| 滚动与历史 | 自动跟随、上翻停止跟随、回到底部 | `ThreadPrimitive.Viewport autoScroll` + `.jump-wrap` 回到底部 | 已落地 |
| | **展开锚定** | `scroll.ts` + `Anchoring.tsx`：以行的“相对滚动容器顶边偏移”为锚，内容尺寸变化时补偿；见第 6.2 节 | 已落地 |
| | **长历史显示** | 挂载窗口（首帧 15 / 稳态 60 / 每次 +40）＋「显示更早的 N 条消息」入口＋对话缩略图导航；见第 6.5、6.6 节 | 已落地 |
| | 阅读位置保留 | `session.scroll` + `useLayoutEffect` 双帧恢复 | 已落地 |
| 附件交互 | 标记、粘贴、拖入、文件选择、预览、反馈 | `Composer.tsx` `handlePaste`/`handleDrop`/`attachments.choose`/`attachments.preview`；导入中／失败状态 | 已落地 |

架构文档第 4 节（侧栏默认折叠、展开入口、新建／搜索／切换／重命名／删除、草稿与阅读位置、齿轮固定底部、折叠仍保留齿轮、完整设置仪表盘）与第 5 节（六分类、左导航右卡片）**逐条已落地**，见 `App.tsx`、`SessionRow.tsx`、`Settings.tsx`。

## 4. 仍未搬入的 PI-Desktop 交互（均属表外，不在本轮授权范围）

**已批准范围内没有已知未落地项。** 下面这些是架构文档表格之外、本轮未被选中的成熟交互，列在这里只为留档，不代表已获授权。

**4.1 会话侧栏分组与悬停预览（后续已实施）。** 固定来源的时间分组为今天／昨天／近 7 天／近 14 天／更早，结合置顶、折叠、排序、多选、500ms 悬停预览和键盘导航，已在用户后续明确授权下接入。实现与实测见 [会话侧栏移植验收](PI-SESSION-SIDEBAR-RESULTS.zh-CN.md)。

**4.2 Toast 与通知。** 本地用顶部错误横幅 + 后台任务弹窗。PI 有 `Toast.tsx` 与 `NotificationCenter`。

**4.3 设置搜索与键盘快捷键页。** 本地 `Settings.tsx` 无搜索框、无快捷键自定义页；PI 有 `settings-search.ts` 与 `KeyboardShortcutsSection.tsx`（含 `Mod+K`、`Mod+B`、`Mod+,` 等默认绑定与显式解绑语义）。

**4.4 双击确认删除（armed delete，批量场景已实施）。** 单个会话保留原模态确认；多选删除使用迁入的 `use-armed-delete.ts`，3200ms 内再次点击确认，且确认绑定所选 ID 集合。

### 明确不搬（架构已排除，不是缺口）

PI-Desktop 的 `ChatSurface`、完整 `Composer`、全局 `app-store`、Electron／Rust 宿主、preload／IPC、插件系统、子 Agent、工作面板、计划审批与权限卡片一律不搬。**因此工作面板的宽度调节（`work-panel-resize.ts`）也不搬**——它依附于被排除的工作面板本身。

## 5. 两个会静默毁掉移植的宿主事实

### 5.1 WebView2 private mode 会删掉 localStorage

`ai/praat_ai/modern_host.py` 以 `private_mode=True` + `storage_path=.../webview-profile` 启动。安装的 pywebview 中：

- `webview/platforms/edgechromium.py`：`props.set_IsInPrivateModeEnabled(_state['private_mode'])`（第 81 行）——InPrivate 下 DOM storage 不落盘；
- 同一文件 `clear_user_data()`（第 122 行）在私有模式下 `shutil.rmtree(self.user_data_folder)`（第 132 行）；
- `webview/platforms/winforms.py` 第 378 行在窗口关闭时调用 `self.browser.clear_user_data()`。

**结论：localStorage／IndexedDB 的写入在关闭前端窗口后一律消失。** PI-Desktop 的侧栏宽度正是存在 `localStorage`（键 `pi.desktop.sidebarWidth`，`{min:240, default:275, max:520}`），照搬会得到一个“每次重开都回到默认”的假象功能。本项目的布局值改为走宿主 `settings.preferences` 白名单（第 6.3 节）。同理，第 3 节任何需要持久化的新交互都必须先接到这条链路上。

### 5.2 分区预算常量

PI 的三栏预算以 `MAIN_PANE_MIN_WIDTH = 450` 为硬地板（由 composer 工具栏展开行推导），侧栏让它先行。本项目没有工作面板，预算退化为“侧栏 vs 主列”两栏，常量沿用 450。上限保留 PI 的 `SIDEBAR_WIDTH_MAX = 520`、下限 `SIDEBAR_WIDTH_MIN = 240`；默认值取本项目既有的 272（≈ PI 的 275），以免既有用户界面在升级后突变。对话区列宽沿用 PI 的 `MIN 560` 与 `GUTTER 24`，默认取本项目既有的 850（PI 为 760）。

## 6. 本轮已实施

### 6.1 窗口内分区尺寸调节

![默认布局：侧栏 272px，对话区与输入框共用 850px 居中带](screenshots/pane-resize-default.png)

![抓手柄收窄后的对话区：命中 560px 下限，输入框同步收窄](screenshots/pane-resize-narrow-band.png)

交互移植自 PI-Desktop（`lib/sidebar-resize.ts`、`lib/sidebar-preferences.ts`、`packages/shared/src/chat-content-width.ts`、`components/ConversationWidthHandles.tsx`），**实现为项目本地代码**（`ai/frontend/src/layout.ts` + `ai/frontend/src/Panes.tsx`），未复制上游源码——持久化机制必须替换，改写后已不构成可替换源码的对应物。

常量与算法：

| 项 | 值 | 来源 |
| --- | --- | --- |
| 侧栏宽度 | min 240 / default 272 / max 520 | PI 的 240／275／520，默认取本项目原值 |
| 侧栏拖动折叠阈值 | 160 | PI `SIDEBAR_COLLAPSE_THRESHOLD` |
| 侧栏键盘步长 | 16（Shift 32） | PI `SIDEBAR_RESIZE_STEP` |
| 主列硬地板 | 450 | PI `MAIN_PANE_MIN_WIDTH` |
| 对话区列宽 | min 560 / default 850 / 上限 = 面板宽 − 48 | PI `MIN_CHAT_CONTENT_MAX_WIDTH` |
| 对话区两侧留白 | 24 | PI `CHAT_CONTENT_WIDTH_GUTTER` |
| 拖动换算 | 1px 指针 = 2px 列宽（两侧手柄移动同一条居中带） | PI `chatContentWidthFromDrag` |

交互：

- **侧栏分隔条**：展开时出现在侧栏右缘（含 5px 骑缝抓取区），光标 `col-resize`；拖动实时改宽，松手落盘；**拖到 160px 以下直接折叠成 68px 轨道**，且不改写已保存的展开宽度（再次展开回到原值）；双击还原 272；键盘 ←/→ 步进 16（Shift 32）、Home 还原、End 到当前预算上限；拖动中按 Escape 取消并回退。
- **对话区双边缘手柄**：分居居中带左右，拖动改变同一个“首选列宽”，实时列宽为 `min(100%, 首选值)`，所以窄窗口会压缩绘制宽度但**不改写偏好**；双击还原 850；键盘 ←/→ 步进 16（Shift 32）、Home 还原、End 撑满可用宽度。
- **共同细节**：指针捕获 + `requestAnimationFrame` 合并高频移动；手势期间给 `document.documentElement` 打 `data-pane-resizing`，用于 `cursor:col-resize`、`user-select:none` 和**关闭侧栏的 180ms 宽度过渡**（否则拖动会滞后于指针）；组件在手势中被卸载时清理该标记；`role="separator"` + `aria-orientation` + `aria-valuemin/max/now`，可 Tab 聚焦并有 `:focus-visible` 描边。

持久化：`preferences` 白名单新增两个键，与既有 `theme`／`font_size`／`send_key`／`smooth_stream` 同一条链路。

- `ai/praat_ai/modern_settings.py`：`PREFERENCES` 增加 `sidebar_width=272`、`conversation_width=850`；新增 `PREFERENCE_RANGES`，在 `save()` 内对 `font_size`／`sidebar_width`／`conversation_width` 统一钳位；非数值回退默认值，不写入 NaN、不抛错中断保存。
- 前端拖动结束（含键盘与双击）后 **350ms 防抖**发一次 `settings.save {preferences:{...}}` 局部补丁；宿主按键合并、保留其余偏好与未知字段。写失败时保留屏幕上的宽度并报错，下一次手势重试。
- 前端另有防御性归一化（`clampSidebarWidth` / `resolveConversationWidth`），因此手工改坏的配置文件不会产生不可用的界面。

与 PI-Desktop 的有意差异：

| 差异 | 原因 |
| --- | --- |
| 侧栏宽度存宿主 `preferences`，不用 `localStorage` | 第 5.1 节：WebView2 私有模式会清空 |
| 对话区列宽存宿主 `preferences`（PI 也是存设置，但走 app-store + IPC） | 本项目只有单一受限 RPC，不引入全局 store |
| 无工作面板预算分支 | 工作面板明确不搬 |
| 默认值 272／850 而非 275／760 | 保持既有界面观感，避免升级即变 |
| 对话区与输入框共用一条居中带 | PI 同源设计；本项目原为 850／800 两条不一致的宽度 |

### 6.2 展开锚定

架构文档第 3 节“滚动与历史”里此前唯一未落地的批准项。

**算法**（移植 PI-Desktop 的 `lib/disclosure-anchor.ts`，项目本地实现见 `ai/frontend/src/scroll.ts`）：

- 锚是**被点开那一行相对滚动容器顶边的偏移**，不是 `scrollTop`。内容空间位置 `elementOffset + scrollTop` 在滚动下不变，所以**行上方**的高度变化（折叠、前插历史页）也被补偿。
- `target = clamp(elementOffset + scrollTop − anchor.offset)`；与当前 `scrollTop` 相差小于 `DISCLOSURE_ANCHOR_TOLERANCE_PX = 0.5` 时返回 `null`，**不写滚动容器**（每次写入都会发一次 scroll 事件）。
- 每次纠正后按行**实际落点**重新采纳锚（边界钳位是浏览器的答案，不与之对抗）。

**交互与接线**：

- 在 `<summary>` 的 `onClick` 里取锚——此时 `<details>` 尚未翻转，量到的是展开前的布局。
- 由 `.transcript-content` 的 `ResizeObserver` 恢复；观察**内容**而不是滚动容器，因为展开一行改变的是 `scrollHeight`，视口盒子本身不变。
- 真实手势（`wheel`、`touchstart`，以及阅读键以外的 `keydown`）解除 hold，因此流式增长不会把视图从刚打开的位置拖走。阅读键（`↑ ↓ PageUp PageDown Home End Space`）**不**解除，否则读者一按键就丢掉位置。
- 每张工具／思考卡片带 `data-activity-id`，供测试与后续缩略图定位。

**反证**：把 `<summary>` 的锚定回调停掉，同一用例的读数位置偏移 **16 570 px**（不是几十像素的抖动，而是被拉回底部）；恢复后偏移 ≤ 2 px。用例同时包含“锚定不得压制自然撑高”的对照断言，避免把“什么都不做”当成通过。

这同时暴露了一个**既有缺陷**：assistant-ui 的 `useThreadViewportAutoScroll` 在内容尺寸变化时，只要 `followBottomRef` 仍为真就会 `scrollToBottom("instant")`，而该标志只在它识别出“用户上滚”后才转假。因此读者上翻后若发生内容变化（卡片展开、工具状态更新），视口会被拉回底部。展开锚定在 ResizeObserver 回调里先行纠正，实际效果是保住了读数位置；这是本项带来的副作用收益，但**没有**改 assistant-ui 的跟随策略本身。

### 6.3 转写右键菜单

移植 PI-Desktop 的 `features/chat/transcript/menu-items.tsx` + `TranscriptMenu.tsx`：一个会话只有一个浮动层（行不能拥有一个比自己寿命长的菜单），行只通过 context 发布它自己掌握的数据，菜单词汇是纯函数（`ai/frontend/src/transcript-menu.ts`），组件只做接线。

**只保留宿主能诚实执行的项，被删掉的都写明理由**：

| PI 的项 | 本项目的处置 |
| --- | --- |
| `copy` / `select-text` | 已搬：复制消息／选择消息文本 |
| `copy-conversation` / `select-conversation` / `scroll-top` / `scroll-bottom` | 已搬（会话背景右键） |
| `edit` / `delete` / 版本切换 | **不搬**：契约没有消息改写 RPC，而改写历史会与已持久化的证据记录冲突 |
| `regenerate` / `branch` | **不搬**：`tasks.submit` 是从新目标起一个新任务，无法重跑已结算的一轮 |
| — | **新增** `copy-evidence`：本项目的核心对象是结构化工具结果，它已在行内 |

细节：

- 菜单项集合由 `messageMenuEntries` / `conversationMenuEntries` 纯函数决定，`separatorBefore` 只在确有其事时绘制，空集合不打开菜单。
- 复制采用 PI 的“选区内优先”规则：行内有实时选区就复制选区，否则复制整条消息。
- `copy-evidence` 只收 `type === 'tool'` 且**已有 result** 的活动（进度与思考不是测量），输出 JSON。
- 空菜单不弹；`Esc`／外部点击／滚动／失焦关闭；键盘 ↑↓ Home End 导航由已提取的 `pi/ContextMenu.tsx` 提供。
- 「回到最新」复用应用自己的「回到最新」控件，从而**重新进入** assistant-ui 的跟随模式，而不是只滚一次。
- 「跳到顶部」用瞬时滚动：PI 自己的会话菜单也是瞬时的；平滑动画会在菜单同一 tick 卸载时被取消而静默失效（本轮实测）。

### 6.4 输入补全

移植 PI-Desktop 的 `features/chat/composer/slash-dispatch.ts` 与 `ComposerAutocomplete.tsx` 的**交互**（输入 `/` → 过滤列表 → 键盘选择 → 接受后执行），实现见 `ai/frontend/src/completions.ts` 与 `Composer.tsx`。

**只保留宿主能诚实执行的命令**：PI 的补全列表由宿主命令（template/control）与插件组构成，本项目没有插件注册表、没有工作区文件 RPC（`@` 引用因此不搬），也没有压缩／清空上下文这类控制命令的 RPC——架构文档明确禁止显示虚假的压缩能力，所以这些一律不做。留下的四条都对应界面上**已经存在**的控件：

| 命令 | 动作 |
| --- | --- |
| `/新建`（`/new`） | 新建并切换会话 |
| `/设置`（`/settings`） | 打开设置仪表盘 |
| `/取消`（`/stop`） | 取消本会话任务；**仅在本会话有运行中任务时出现** |
| `/附件`（`/attach`） | 打开系统文件选择器 |

细节：

- 触发只在词首：`/` 必须紧跟在行首或空白之后，因此 `2026/10`、`a/b`、`https://…`、以及已经带空格的 `/设置 其余` 都不会打开列表。
- 打开时列表**接管导航键**：↑↓ 移动高亮，Enter/Tab 接受，Escape 关闭；因此按 Enter 是执行命令而不是发送消息，命令 token 也不会变成用户消息。
- 接受后 token 从草稿中删除，命令只执行动作、不留文本。
- 输入法组合期间不做补全（与发送守卫同一套 IME 判定）。
- 只读旧记录没有补全列表（无可执行动作）。

### 6.5 长历史挂载窗口与阅读锚点

架构文档第 3 节“长历史显示”的落地。移植 PI-Desktop 的 `lib/transcript-window.ts` 与 `lib/transcript-reading.ts`（项目本地实现见 `ai/frontend/src/transcript-window.ts`）。

**为什么是挂载窗口而不是像素虚拟化**：PI 的 ADR 0120 明确 —— `content-visibility` 只跳过布局与绘制、把每一行都留在内存里，对低内存机型是错误取舍。所以本项目也只挂载窗口内的行，其余的行根本不进 DOM。

| 项 | 值 |
| --- | --- |
| 首帧挂载（会话切换后的第一次提交） | 15 |
| 稳态窗口 | 60 |
| 每次「显示更早」新增 | 40 |
| 触顶自动展开阈值 | 距顶 120px |

**本项目特有的契约改动**：原来的阅读位置是 `session.scroll`，一个像素偏移；只在“已挂载内容”这一坐标系里有意义。一旦只挂载尾部窗口，同一个 `scrollTop` 会指向完全不同的消息，于是“阅读位置保留”会**静默变成错误的位置**。所以 `sessions.view` 增加了 `anchor = {messageId, offset}`：

- 前端在滚动时按行取锚（二分查找最后一行其内容坐标顶边不高于视口顶边），offset = 该行顶边相对视口顶边的偏移（可为负，与展开锚定同一套约定）。
- 恢复时用锚反解 `scrollTop`；锚所在行不在窗口里就先把窗口撑到包含它。
- Python 侧 `sessions` 表增加 `anchor` 列（`ALTER TABLE ... ADD COLUMN`，对既有库增量迁移），并在存储层校验（非空有界 id、有限 offset），**拒绝**写入无法解析的位置而不是存下一个会指错的位置。
- 只写草稿的部分更新不会清掉锚。

**两个必须一起做的配套**，否则窗口化会破坏阅读：

1. **前插补偿**：扩窗口会在阅读位置**上方**插入行，滚动位置按新增的 `scrollHeight` 差额同步下移。
2. **只记真实滚动**：恢复、前插补偿、菜单「跳到顶部」都会写 `scrollTop`，这些布局/程序化滚动不能在 600ms 内反过来覆盖锚。没有这道闸门，一次会话切换就会把锚改写成“窗口被钳到底部”的垃圾位置（调试时实测到过）。

**窗口与锚的优先级**：锚的要求**优先于**首帧只挂 15 行的省渲染策略。调试时踩到的真实缺陷是——首帧 15 行时按锚反解只能得到 `null`，恢复退化成像素回退；而且 `restored` 置位后锚要求被撤下，窗口又缩回 60，把刚恢复到的行丢掉。现在锚要求会被提交进 `windowSize`，不会随恢复完成而失效。

**既有验收用例的更新**：`ui.spec.ts` 原本断言长历史渲染 121 条 `.message`，并断言切回后 `scrollTop` 与切走前相差不超过 10px。窗口化后这两条都不再成立（挂载 60 条；窗口重建后同样的视觉位置对应不同的 `scrollTop`）。用例改为：先断言稳态窗口 60 条与「显示更早的 61 条」入口，再用**顶部可见消息 id**断言阅读位置被保留——这才是这项功能真正的契约。

### 6.6 对话缩略图

![缩略图导轨：左侧 dash 序列、当前阅读位置高亮，悬停显示该轮预览](screenshots/minimap-rail.png)

交互移植自 PI-Desktop 的 `components/ConversationMinimap.tsx` 与 `lib/conversation-minimap.ts`（项目本地实现见 `ai/frontend/src/minimap.ts` 与 `MinimapRail.tsx`）。

| 项 | 值 | 来源 |
| --- | --- | --- |
| 预览上限 | 280 字符 | PI `CONVERSATION_MINIMAP_PREVIEW_MAX_CHARS` |
| 溢出判定 | `scrollHeight − clientHeight > 1px` | PI `OVERFLOW_EPSILON_PX` |
| 显示条件 | 有更早历史，或（≥2 个 dash 且溢出） | PI `shouldRenderConversationMinimap` |
| 放大半径 / 强度 | 46px / 1.3×（余弦衰减） | PI `MAGNIFY_RADIUS` / `MAGNIFY_BOOST` |
| 悬停吸附 | 24px 内才出预览；气泡高 132px 并夹在导轨内 | PI `POPOVER_SNAP` / `POPOVER_HEIGHT` |
| dash 宽度 | user 13px，assistant 8px | PI `--dash-w` |
| 阅读线 | 视口高 30% 处 | PI `MINIMAP_ANCHOR_RATIO` |
| 跳转落点 | 该行上方 24px | PI 的 `offset − 24` |

**两处因本项目而必须不同**：

1. 导轨**只描述已挂载的行**——挂载窗口之外的行没有 DOM，给它们画 dash 会“跳到不存在的位置”（PI 在 D261 里也是这个结论）。
2. 「更早历史」那条虚线在本项目是**展开下一页窗口**，不是取更早的分页（契约没有分页读取）。

**实现要点**：当前 dash 由 rAF 合并的滚动回调**命令式**更新（`classList` + `aria-current`），放大直接写 `--magnify`，两者都不触发逐帧 React 渲染；dash 的 marker 下标与按钮下标分开记录，因为导轨里多了一条「更早历史」——第一版把两者当成同一个下标，悬停预览会指到相邻的一轮（已修，并被用例覆盖）。

**调试中发现的既有缺陷（已修）**：前插补偿原本写在按 `window.mounted` 触发的 layout effect 里。加入缩略图后这条路径开始失效——实测补偿时读到的 `scrollHeight` 仍是旧值，delta 为 0，补偿被静默跳过（用例表现为「显示更早」后视图跳走 40 行）。根因是 **assistant-ui 会在本次提交之后才把新的消息行同步进 DOM**，在提交期测量读到的是旧高度；之前之所以“看起来能用”，是因为消息数组每次渲染都是新引用、运行时被更频繁地重新同步，属于时序巧合。现在补偿挂在**内容 ResizeObserver** 上（谁引起的高度变化都会触发），并允许一页分多次到达：每次投递按新增高度补一次，记录在 400ms 空闲后失效，避免把后续流式增长也算成前插。

### 6.7 转写内搜索与命中高亮

![会话内查找：计数、上/下一处，命中由 CSS Custom Highlight API 绘制，正文未被改写](screenshots/transcript-search.png)

移植 PI-Desktop 的转写内搜索交互（`components/SearchDialog.tsx`、`lib/transcript-search-highlight.ts`、`hooks/use-transcript-search-focus.ts`），项目本地实现见 `ai/frontend/src/search.ts` 与 `SearchBar.tsx`。

**一处有意的方法差异**：PI 在**宿主侧**（SQLite，一行一个命中）搜索，再到 DOM 里重新匹配以绘制那一条消息。本契约没有搜索 RPC，而整段已加载历史本来就在渲染进程里，所以这里的可搜索集合是**已渲染的转写**：**凡是被计入的命中，都是能被高亮、也能被对齐到的命中**。只存在于 Markdown 源码、或被挂载窗口扣住的行里的匹配**不计入数字**——界面改为提供「显示更早的 N 条消息」这个动作，而不是报一个自己指不出来的计数。

| 项 | 值 | 来源 |
| --- | --- | --- |
| 命中上限 | 500（防病态查询） | 本项目自行设定 |
| 对齐落点 | 视口高 1/3 处，单次最多移动 160px | PI 的 `min(160, clientHeight / 3)` |
| 快捷键 | `Ctrl / ⌘ + K` 打开，`Esc` 关闭，`Enter` 下一处、`Shift + Enter` 上一处 | PI 的 `openSearch` 默认绑定就是 `Mod+K`（`Ctrl+F` 留给宿主自带的查找栏） |

**实现要点**：

- 高亮用 **CSS Custom Highlight API**（`CSS.highlights.set(...)` ＋ `::highlight()`），与 PI 同一机制——它**不改写 React 拥有的 DOM**，用例专门断言转写里没有插入任何 `<mark>`。不支持的宿主会明确显示「仅能定位到消息」，而不是静默不画。
- 匹配在拼接后的可见文本上做，能跨行内元素命中，再用节点偏移映射回 `Range`；只有当小写折叠保持长度一致时才走这条路，否则退化为逐文本节点匹配——否则 `İ` 这类字符会让下标悄悄指到错误的字符上。
- 非正文的 chrome（按钮、mermaid／代码复制按钮、`aria-hidden` 装饰、缩略图导轨、显示更早入口）被排除在可搜索文本之外。
- 流式正文与挂载窗口变化都会改动可搜索文本，因此用 `MutationObserver`（rAF 合并）重新扫描；命中集合与计数一起更新。

**调试中发现的真实冲突（已修）**：「滚到顶部就展开下一页」这条既有规则会和搜索对齐打架——跳到靠近顶部的一处命中时，对齐本身把 `scrollTop` 写到了接近 0，于是被判定为「读者到达顶部」，窗口展开、前插补偿再把视图推到一万多像素之外，那处命中直接飞出屏幕（实测计数从 `1/32` 变成 `1/54`、`scrollTop` 从 480 跳到 10746）。修法是让对齐**声明这次滚动是我们写的**（与展开补偿、恢复共用同一套 `own` 记录）：既不再触发自动展开，也不会把这次跳转写进阅读锚点——这正是 PI 在跳转前 `releaseFollow()` 想达到的效果。

### 6.8 合并验证

| 层级 | 结果 | 边界 |
| --- | --- | --- |
| TypeScript | `npx tsc -b` 通过 | — |
| 前端单元 | `vitest run` **79 项**通过（12 个文件；layout 7 ＋ scroll 5 ＋ transcript-menu 5 ＋ completions 4 ＋ transcript-window 6 ＋ minimap 6 ＋ search 7 为新增） | jsdom，非真实宿主 |
| 浏览器交互 | `playwright test` **29 项**通过（10 个 spec 文件：原 8 项无回归 ＋ 分区调节 2 ＋ 展开锚定 2 ＋ 右键菜单 2 ＋ 输入补全 3 ＋ 挂载窗口 4 ＋ 缩略图 4 ＋ 会话内查找 4；`ui.spec.ts` 的长历史用例按新契约改写） | Edge 154 无头浏览器，**不是** pywebview 窗口 |
| Python 模块 | `python tests/test_modern_app.py` **29 项**通过（新增：偏好钳位与保留、阅读锚点持久化与校验、既有库增量迁移） | 离线，未联网 |
| 生产构建 | `npm run build` 通过；CSS 53.99→59.30 kB，主 JS 3,526→3,552.17 kB | 需按 BUILD-RESULTS 记录的 esbuild 临时副本绕过本机 Temp 权限问题 |

**涉及文件**

新增：`ai/frontend/src/layout.ts`、`Panes.tsx`、`scroll.ts`、`Anchoring.tsx`、`transcript-menu.ts`、`TranscriptMenu.tsx`、`completions.ts`、`transcript-window.ts`、`minimap.ts`、`MinimapRail.tsx`、`search.ts`、`SearchBar.tsx`，以及 `tests/layout.test.ts`、`tests/scroll.test.ts`、`tests/transcript-menu.test.ts`、`tests/completions.test.ts`、`tests/transcript-window.test.ts`、`tests/minimap.test.ts`、`tests/search.test.ts`、`tests/browser/pane-resize.spec.ts`、`tests/browser/disclosure-anchor.spec.ts`、`tests/browser/transcript-menu.spec.ts`、`tests/browser/completions.spec.ts`、`tests/browser/transcript-window.spec.ts`、`tests/browser/minimap.spec.ts`、`tests/browser/search.spec.ts`、`tests/browser/reveal.ts`。
修改：`ai/frontend/src/App.tsx`、`Chat.tsx`、`store.ts`、`types.ts`、`styles.css`、`demo.ts`、`tests/browser/ui.spec.ts`、`playwright.config.ts`、`ai/praat_ai/modern_settings.py`、`modern_store.py`、`modern_app.py`、`ai/tests/test_modern_app.py`、`docs/ai-frontend/HOST-CONTRACT.md`、`FRONTEND-SOURCES.md`、`CHAT-UI-ARCHITECTURE.zh-CN.md`。

`playwright.config.ts` 只增加一个可选环境开关：默认仍用打包 Chromium，`PI_PLAYWRIGHT_CHANNEL=msedge` 时改用已安装的 Edge（与 WebView2 同引擎）。默认行为未变。

**未做**：真实 pywebview＋WebView2 窗口内的人工拖拽／展开／右键／补全验收；安装包合并；全量 Python 回归（按既定测试分级，只跑了受影响模块）。因此**不能**声称这些交互已在真实桌面宿主中验收。

## 7. 复跑命令

```powershell
Set-Location ai\frontend
npx tsc -b
npx vitest run
$env:PI_PLAYWRIGHT_CHANNEL = 'msedge'      # 可选；缺省用打包 Chromium
npx playwright test
npm run build

Set-Location ..                              # ai\
$env:PYTHONPATH = (Get-Location).Path
python tests/test_modern_app.py
```

## 8. 来源与许可

PI-Desktop（LGPL-3.0）在本轮仅作为**交互与常量参考**，未复制源码进本项目，因此不新增 LGPL 覆盖文件；`ai/third_party/pi-desktop/` 与 `dist/pi-desktop-source/` 中既有的 ContextMenu／滚动条提取物不受影响，转写右键菜单直接复用该提取物而不是再抄一份。命名相同不代表同源：本项目 `ComposerStatus.tsx` 是项目本地适配。详见 [FRONTEND-SOURCES.md](FRONTEND-SOURCES.md) 与 [PI-DESKTOP-INTERACTION-SPEC.zh-CN.md](PI-DESKTOP-INTERACTION-SPEC.zh-CN.md)。
