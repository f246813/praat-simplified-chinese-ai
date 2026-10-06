# PI-Desktop 三簇交互实现级规格（pin `0d47d26769ecbeca1c3ab56fa83b58a91de8190e`）

审计对象：`vastsa/PI-Desktop`，LGPL-3.0，精确修订 `0d47d26769ecbeca1c3ab56fa83b58a91de8190e`。
取源方式：`raw.githubusercontent.com` 在本会话中不稳定（间歇 `TypeError: fetch failed`），改用同 revision 的
`https://cdn.jsdelivr.net/gh/vastsa/PI-Desktop@0d47d26769ecbeca1c3ab56fa83b58a91de8190e/<path>` 镜像取正文，
用 `api.github.com` 的 git trees / contents 做路径发现。以下所有标识符与数字均引自上述 revision 的原文。

## 先说明三处与任务预设不符的地方（不虚构）

1. **不存在 `MAX_RESULTS` 这个标识符。** 全簇搜索的上限是字面量：宿主侧 `crates/host-core/src/session_search.rs`
   里 `LIMIT 31 OFFSET ?3` + `hits.truncate(30)` + `let next_offset = (hits.len() > 30).then(|| offset.saturating_add(30));`
   （每页 30 个会话），每会话片段 `LIMIT 2`、片段预算 `180` 字符。渲染侧另有 `candidates.slice(0, 30)`（空查询时）。
2. **`apps/desktop/src/features/chat/composer/ComposerStatus.tsx` 与本簇无关。** 该 revision 下它渲染的是队列提示
   (`queuedPrompts`)、拖入文件夹提示和 enhancement 失败 toast；**上下文用量检查器由
   `apps/desktop/src/features/chat/composer/ComposerToolbar.tsx` 挂载**（`{contextUsage ? <ContextUsageInspector {...contextUsage} /> : null}`）。
3. **`apps/desktop/electron/main/session-search.ts` 返回 404**（不存在）。宿主实现是 Rust：
   `crates/host-core/src/session_search.rs`（29134 字节），暴露给前端的 IPC 名是 `IPC.invoke.sessionSearch` /
   `IPC.invoke.sessionSearchContext`（`apps/desktop/src/lib/api.ts`）。

另外：`SearchDialog` 里**没有**「上一处/下一处匹配」按钮；`ConversationMinimap` **没有**拖拽/擦洗（只有 click）。
这两点在后文重复强调，避免移植时凭空发明。

---

## 簇 1 — 会话内 / 转写内搜索

### 1.1 入口与快捷键

- 快捷键表在 `packages/shared/src/keyboard-shortcuts.ts`：
  `{ id: "openSearch", group: "navigation", defaultBinding: "Mod+K" }`，
  以及 `{ id: "openCommandPalette", group: "navigation", defaultBinding: "Mod+Shift+P" }`。
  同表里还有 `toggleSidebar = Mod+B`、`openWorkPanel = Mod+J`、`abort = Mod+Period`、`navigateBack = Mod+BracketLeft` 等。
  `Mod` 在 darwin 上是 Cmd、否则是 Ctrl（`keybindingFromEvent`）。`resolveKeybinding(shortcut, overrides, platform)`
  允许用户在 `settings.keybindings` 里覆盖；值为 `null` 表示显式解绑（返回 `null`，不再匹配）。
- 注册点在 `apps/desktop/src/features/app/useAppShellRuntime.tsx` 的全局 `window.addEventListener("keydown", onKey)`：
  - 先跳过纯修饰键 `MODIFIER_ONLY_KEYS = {Alt, AltGraph, Control, Meta, Shift}`、`e.isComposing`、`e.keyCode === 229`（IME 保护）；
  - `KEYBOARD_SHORTCUTS.find(candidate => keybindingMatchesEvent(resolveKeybinding(candidate, settings?.keybindings, platform), e, platform))`；
  - 找不到就退到插件快捷键：`setting.type === "shortcut" && keybindingMatchesEvent(String(setting.value ?? setting.default ?? ""), e, platform)` → `api.executeCommand(...)`；
  - 命中后 `e.preventDefault()`，`runShortcut(id)` 中 `case "openSearch": case "openCommandPalette": setSearchOpen(true);`。
    （两者今天打开同一个 surface。）`e.repeat` 只对 `navigateBack/navigateForward/voiceToggle/voiceCancel` 做忽略。
- 其他入口：原生菜单命令 `openSearch` / `openCommandPalette` 也走 `runMenuCommand` → `setSearchOpen(true)`；
  `ConversationTopbar` 的 `onOpenSearch={() => setSearchOpen(true)}`；侧栏搜索按钮。
- `SearchDialog` 由 `features/app/AppShell.tsx` 挂载一次：`<SearchDialog open={searchOpen} onClose={() => setSearchOpen(false)} />`，
  并把它作为「面板阻塞」信号：`<WorkPanel panelBlocked={searchOpen} … />`。
- `searchOpen` 是 `useState(false)`（`useAppShellRuntime` 内部），**不持久化**。

### 1.2 对话框结构（DOM / ARIA 契约）

`components/SearchDialog.tsx` + `components/SearchSessionResults.tsx`：

```
.search-overlay                 (onClick={onClose})
└─ .search-dialog               role="dialog" aria-modal="true" aria-label={t("nav.search")}
   │                            onClick={stopPropagation}; 自己的 onKeyDown 里处理 Escape
   ├─ .search-input-row → <input class="search-input">
   │     role="combobox" aria-expanded="true"
   │     aria-controls="global-search-results"
   │     aria-activedescendant={`global-search-option-${active}`}
   │     aria-label={t("nav.search")} placeholder={t("search.placeholder")}
   │     maxLength={500} autoFocus spellCheck={false} autoCorrect="off" autoCapitalize="off"
   └─ .search-results#global-search-results   role="listbox" aria-label={t("nav.search")}
      ├─ option 0                role="option"  id="global-search-option-0"   ← t("nav.newTask")
      ├─ <SearchSessionResults/> 分组 (.search-group-label) + 会话行 + 逐条命中行
      ├─ loading 行 (.search-empty role="status")
      ├─ error 行 (.search-empty role="alert") + retry 按钮
      ├─ 「加载更多」行            id=`global-search-option-${moreIndex}`
      ├─ Pages 分组 (PAGE_ENTRIES)
      ├─ Settings 分组
      ├─ Commands 分组
      └─ 空结果行 (.search-empty)
```

- 分组标签来自 `GROUP_KEYS = ["today","yesterday","previous7Days","previous30Days","earlier"]`，
  对应 `t("search.today")` 等；分桶用 `groupKeyFor(updatedAt, startOfToday)`，
  `DAY_MS = 86_400_000`，边界为 `startOfToday`、`-1*DAY_MS`、`-7*DAY_MS`、`-30*DAY_MS`，无法解析的时间戳归 `"earlier"`。
- `PAGE_ENTRIES = [{page:"scheduled", labelKey:"scheduled.title", icon:IconClock}, {page:"plugins", labelKey:"nav.plugins", icon:IconAt}]`，
  仅在 `query.trim()` 非空且翻译后的标签 `includes(q)` 时出现。
- 设置结果来自 `searchSettings(query, t, { developerMode, includeDevelopmentOnly: import.meta.env.DEV })`
  —— 开发者模式关闭时，只对开发者开放的目的地不进列表。
- 「最近会话」列表（空查询）：`isDefaultSessionTitle` 的无标题草稿被跳过；归档会话在无查询时隐藏；
  `listableSessions(...)` 过滤掉自动化/计划任务会话（issue #1291），落库字段是 `SessionSummary.scheduledRun`。
- 结果行内容：标题 + 项目标签 + 徽章 `search.metadataMatch` / `search.messageMatches`(count) / `search.archived`，
  右侧 `.search-item-running`（6px 圆点，`--ds-success`）当 `runningSessions[session.id]`。
- 命中行：`search.user | search.assistant` + `new Date(match.createdAt).toLocaleString()` + 片段。

### 1.3 状态模型与查询防抖

- 查询是**瞬态** zustand store（`hooks/use-session-search.ts`）：
  `export const useSessionSearchState = create<{query:string; setQuery:(q:string)=>void}>(…)`，初值 `""`；
  注释明确「Transient search state survives closing the palette, never goes to disk」——关掉对话框查询仍在。
- `useSessionSearch(open, query)`：
  - `const controller = useMemo(() => new SessionSearchController(api.searchSessions), [])`；
  - `const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot)`；
  - 防抖：`const normalized = query.trim();` 然后
    `if (!open) return; controller.reset(normalized); const timer = window.setTimeout(() => void controller.load(), 150);`
    cleanup 是 `clearTimeout(timer); controller.cancel();` → **150 ms**。
  - 快照去脏：`hits: state.query === normalized ? state.hits.filter(h => !isAutomationSession(h.session)) : []`，
    `nextOffset` 同理（不匹配时 `null`），`error` 同理 `undefined`，
    `loading: Boolean(normalized) && (state.query !== normalized || state.loading)`。
- `SessionSearchController`（`lib/session-search.ts`）：`generation` 计数器实现「异步归属查询」；
  `reset()` 自增 generation 并清空；`load(offset = 0)` 记录 generation，响应回来若 `generation !== this.generation` 直接丢弃；
  追加页时用 `Set` 去重 `session.id`（`previous` 仅在 `offset` 非 0 时保留）；
  `loadMore()` 需要 `!loading && nextOffset !== null`；`retry()` 需要 `!loading`，从 `hits.length ? (nextOffset ?? 0) : 0` 重试。
- 命令搜索是**另一个** 80 ms 防抖（`SearchDialog`）：
  `const handle = window.setTimeout(() => { void api.searchCommands(query).then(res => setCommandResult({query, hits: res.commands})) }, 80);`
  `commandHits = commandResult.query === query ? commandResult.hits : []`（同样按 query 归属）。
- 打开时的副作用：`setActive(0)`、清空命令命中、`void refreshSessions().catch(()=>undefined)`（捕捉打开后被重命名/新建的会话）。
- 选项索引（扁平 listbox 的关键算术）：`optionIndex` 从 **1** 起（0 = 新建任务）；每个会话行占用
  `1 + row.hit?.matches.length`。然后
  `moreIndex = sessionOptionCount + 1`；
  `pageBase = moreIndex + (query.trim() && search.nextOffset !== null ? 1 : 0)`；
  `settingsBase = pageBase + pageHits.length`；
  `commandsBase = settingsBase + settingsHits.length`；
  `optionCount = commandsBase + commandHits.length`。
- `active` 的变化：query 变 → `setActive(0)`；`optionCount` 变 → `setActive(v => Math.min(v, optionCount - 1))`；
  `active` 变 → `document.getElementById(\`global-search-option-${active}\`)?.scrollIntoView({ block: "nearest" })`。

### 1.4 结果排序与上限（含真实数字）

宿主侧 `crates/host-core/src/session_search.rs`：

- 空查询直接返回 `hits: vec![], next_offset: None`。
- `register_contains` 注册标量函数 `pi_search_contains(text, query)` =
  `text.to_lowercase().contains(&query.to_lowercase())`，带 `SQLITE_UTF8 | SQLITE_DETERMINISTIC | SQLITE_INNOCUOUS`；
  注释说明「Unicode lowercase is shared with the renderer」——渲染侧对应 `foldSearchText = text.toLowerCase()`。
- FTS 只是**预筛**，条件：
  `query.chars().count() >= 3 && !query.contains('\u{0307}') && query.chars().all(|ch| ch.is_ascii() || (!ch.is_lowercase() && !ch.is_uppercase()))`
  → `AND m.mid IN (SELECT rowid FROM messages_fts WHERE messages_fts MATCH ?2)`，
  否则退化为 `AND ?2 IS NOT NULL` 的全量字面扫描（CJK、短词、含 U+0307 的查询走这条）。
- 主查询（要点）：
  - CTE `matched` 以 `m.role IN ('user','assistant')` 聚合 `COUNT(*)`；
  - 结果 `WHERE s.deleted_at IS NULL AND (matched.count > 0 OR metadata_match)`；
  - `metadata_match` = `pi_search_contains(s.title, ?1) OR pi_search_contains(p.name, ?1) OR pi_search_contains(p.path, ?1)`；
  - `scheduled_run` = `EXISTS (SELECT 1 FROM task_runs r WHERE r.session_id = s.id)`；
  - **`ORDER BY s.updated_at DESC, s.id ASC LIMIT 31 OFFSET ?3`**；
  - `let next_offset = (hits.len() > 30).then(|| offset.saturating_add(30)); hits.truncate(30);`
  - 每会话片段：`SELECT id, role, created_at, text FROM messages WHERE session_id = ?1 AND role IN ('user','assistant') AND pi_search_contains(text, ?2) ORDER BY created_at DESC, seq DESC, id ASC LIMIT 2`。
- **没有相关性打分**：排序纯时间倒序 + id 升序。片段文本用 `sentence_excerpt(text, query, 180)`：
  在 `。！？!?` 或「`.` 后接空白/收尾引号」或换行（`\n \r U+2028 U+2029`）处切句，吞掉连续收尾标点；句子超预算则退到
  `excerpt(text, query, budget)`，它以 `budget / 3` 左偏居中（`start = position.saturating_sub(budget/3)`），
  两端超界时加 `…`。
- 渲染侧上限：空查询时 `candidates.slice(0, 30)`；`<input maxLength={500}>`。

### 1.5 高亮（两套机制，务必区分）

**(a) 对话框内 —— React `<mark>` 注入。**
`components/SearchHighlight.tsx`：`const ranges = searchMatchRanges(text, query);` 然后按 range 切开文本，
命中段包成 `<mark className="search-hit">`。用于标题、项目名、设置行、命令名、以及**消息片段**。
`lib/session-search.ts` 的 `searchMatchRanges(text, query)`：
- `const needle = foldSearchText(query.trim())`，空串返回 `[]`；
- 小写可能**扩张字符数**（`İ` → `i` + combining dot），因此仅当 `folded.length !== text.length` 时才构建
  `starts[]/ends[]` 映射表，把折叠后的下标映回原文偏移（普通 ASCII/CJK 路径零分配）；
- 逐个 `folded.indexOf(needle, from)` 推进，`from = index + needle.length`；
- **重叠/相邻命中会合并**：`if (previous && start < previous[1]) previous[1] = end; else ranges.push([start,end]);`
样式：`overlays.css` 的 `.search-hit { background: transparent; color: var(--ds-text-primary); font-weight: var(--font-weight-semibold) }`
（行表面继承，无高亮底色）；`session-search.css` 只为**消息片段**加底色：
`.search-message-snippet .search-hit { border-radius: var(--radius-sm); background: color-mix(in oklab, var(--ds-accent) 28%, var(--ds-bg-primary)); }`
（`session-search.css` 全文 640 字节，其余规则是 `.search-message-hit`、`.search-message-meta`、`.search-session-details`、
`.search-session-meta` 的排版。）

**(b) 渲染出的转写内 —— CSS Custom Highlight API + DOM Range（无 `<mark>` 注入）。**
`hooks/use-transcript-search-focus.ts` 的 `installTranscriptSearchFocus(...)`：
- 定位消息节点：`content.querySelector<HTMLElement>(\`[data-message-id="${CSS.escape(target.messageId)}"]\`)`，
  再 `const row = message.closest<HTMLElement>(".message-row") ?? message`，给 row 加 `.transcript-search-target`
  （CSS：`.message-row.transcript-search-target { content-visibility: visible; }`，见 `messages.css`）。
- `locateTranscriptSearch(message, target.query, source)`（`lib/transcript-search-highlight.ts`）：
  - 先 `searchMatchRanges(source, query)[0]` 拿到**源码**首个命中；
  - 在 `root.querySelectorAll("[data-source-start][data-source-end]")` 里找**最小**的包住它的元素作为 `owner`；
  - 再对 `owner ?? root` 调 `transcriptSearchRanges(root, query)`，它用
    `document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {acceptNode})` 收集可见文本节点，
    排除 `NON_CONTENT = "button:not(.chat-text-link):not(.chat-file-chip):not(.chat-code-link), textarea, [aria-hidden='true']"`，
    按拼接后的整串文本做匹配，再把每段 `[start,end)` 反查成 `document.createRange()`（可跨 Markdown 内联元素，
    但**不重写 React 拥有的 DOM**）；
  - 若渲染文本里没有命中但源码有（链接 URL、强调分隔符、图片目标），返回 `{ranges: [], sourceElement: owner}`。
- 上色：
  ```
  paint(): match.sourceElement?.classList.add("transcript-search-source-match");
           if (typeof Highlight !== "undefined" && CSS.highlights && match.ranges.length) {
             highlight = new Highlight(...match.ranges);
             CSS.highlights.set("transcript-search", highlight);
           }
  ```
  `messages.css` 对应：
  `::highlight(transcript-search) { color: var(--ds-text-primary); background-color: color-mix(in srgb, var(--ds-accent) 35%, transparent); }`
  `.transcript-search-source-match { background-color: color-mix(in srgb, var(--ds-accent) 25%, transparent); outline: 2px solid color-mix(in srgb, var(--ds-accent) 65%, transparent); outline-offset: 2px; }`
  `unpaint()` 会 `CSS.highlights.delete("transcript-search")`（且只在仍是自己那个 Highlight 时删）。
- 双节点契约：`features/chat/transcript/MessageRow.tsx` 在同一个 `.message-row` 上同时输出
  `data-minimap-id={message.id}` 与 `data-message-id={message.id}`（`role="article"`，
  `aria-label` 为 `chat.userMessage` / `chat.assistantMessage`）。
- `lib/transcript-search-context.ts` 全文仅 3 行：`TranscriptSearchContext = createContext<TranscriptSearchTarget|null>(null)`。
  `TranscriptSearchTarget = { sessionId, messageId, query, requestId }`（`lib/transcript-reading.ts`）。

### 1.6 「下一处/上一处」与滚动位置

对话框**没有**上/下一处控件。流程是「选结果 → 跳转 → 在转写里对齐并高亮」：

1. `run(row, messageId?)`（SearchDialog）：自增 `selectionRequest.current`；
   若当前已是该会话且不在切换中 → `setPage("chat")`，否则 `await selectSession(row.session.id)`；
   然后校验 `request === selectionRequest.current && selected.activeSessionId === row.session.id && selected.page === "chat"`，
   否则放弃；`const targetId = messageId ?? row.hit?.matches[0]?.messageId;`
   有则 `void selected.navigateTranscript({ sessionId, messageId: targetId, query: query.trim() })`。
   随后 `onClose()`，并在 `requestAnimationFrame` 里 `document.querySelector<HTMLTextAreaElement>(".composer-input")?.focus({preventScroll:true})`。
2. 转写侧 `useTranscriptSearchFocus` 在 `useLayoutEffect` 里安装（依赖含 `contentVersion`，
   由 `useTranscriptScroll` 传入 `historyEntries`，所以挂载窗口变化会重装）。
   - `fresh = position.current.requestId !== target.requestId`。新鲜则
     `position.current = { requestId, alignUntil: performance.now() + 1500 }` → **对齐窗口 1500 ms**。
   - `onNavigate(fresh)` 落到 `releaseSearchFollow(fresh)`（`useTranscriptScroll`）：
     `if (fresh) prependHeightRef.current = null; releaseDisclosureAnchor(); cancelFollowScroll(); pinnedRef.current = false; setShowJump(true);`
     —— **先脱离 follow 模式**，否则下一步的无手势滚动会被当成布局 clamp 而被 follow 拽回底部。
   - `align()`：
     ```
     if (performance.now() >= position.current.alignUntil) return;
     const rect = match.ranges[0]?.getBoundingClientRect() ?? (match.sourceElement ?? message).getBoundingClientRect();
     const viewport = scroller.getBoundingClientRect();
     scroller.scrollTop += rect.top - viewport.top - Math.min(160, scroller.clientHeight / 3);
     onPosition?.(scroller.scrollTop);
     ```
     即把命中放到视口约 **1/3** 处、但上移量**封顶 160 px**；直接写 `scrollTop`（不是 `scrollTo({behavior:"smooth"})`）。
   - 对齐的持续时间由 `ResizeObserver(align)` 观察 `content` 驱动（内容高度持续变化时反复纠偏）；
     `timer = setTimeout(stopAlignment, max(0, alignUntil - performance.now()))` 兜底；
     任一用户手势（`GESTURES = ["wheel","touchstart","touchmove","pointerdown","keydown"]`，passive）立即停止对齐，
     但 keydown 若是阅读键 `READING_KEYS = {ArrowUp, ArrowDown, PageUp, PageDown, Home, End, " "}` 则不停止。
     `onPosition(scroller.scrollTop)` 把本次写入登记为「自己的滚动工作」，避免随后的原生 scroll 事件被读成用户上滚。
   - `MutationObserver(message, {childList:true, subtree:true, characterData:true})` 在文本变更时
     unpaint → 重新 `locateTranscriptSearch` → paint → align（几何变化则复用同一 match）。
   - cleanup（StrictMode 重放也安全）：清 timer、`resize.disconnect()`、移除 GESTURES、`mutation.disconnect()`、
     去掉 row 的 `.transcript-search-target`、`unpaint()`。
3. 会话内的「上/下一处」由宿主提供，不在对话框里：`api.getSearchContext({sessionId, messageId, query, direction})`
   → `crates/host-core/src/session_search.rs::context()`：
   - `direction` 窗口：`around` = `(position-10, position+11)`（≤21 条）；`before` = `(position-20, position)`；
     `after` = `(position+1, position+21)`；
   - 返回 `hasMoreBefore/hasMoreAfter` 与 `previous_match_id` / `next_match_id`，
     用 `seq < / > (SELECT seq FROM messages WHERE id = ?3)` + `ORDER BY seq DESC/ASC LIMIT 1`；
     查询为空则两者为 `None`；
   - 每条消息正文用 `excerpt(text, query, 64 * 1024)` 截断（仅 `around` 且是该 message 时才以 query 居中）。
   - 该函数按**物理 JSONL 位置**解析稳定消息 ID（`find_message_position`），不依赖 SQLite 去重后的 seq。
   `lib/transcript-reading.ts` 里还有 `TRANSCRIPT_PAGE_SIZE = 100`、`TRANSCRIPT_SEARCH_PAGE_SIZE = 60`、
   `TRANSCRIPT_CONTENT_LIMIT = 64 * 1024`。

### 1.7 键盘处理与空/加载/错误状态

- 输入框 `onKeyDown`：IME 保护（`isComposing || keyCode === 229`）后，
  `Escape` → preventDefault + `onClose()`；
  `ArrowDown` → `setActive(v => Math.min(v + 1, optionCount - 1))`；
  `ArrowUp` → `setActive(v => Math.max(v - 1, 0))`；
  `Enter` → preventDefault + `runActive()`。
- 对话框自身也有 `onKeyDown` 处理 `Escape`（注释：即使焦点已离开输入框也能关闭）。
- `runActive()` 按扁平索引分派：`active === 0` → 新建任务；命中会话行 → 打开会话；
  命中消息行（`active - row.optionIndex - 1`）→ 打开该 messageId；
  `active === moreIndex && nextOffset !== null` → `search.loadMore()`；
  再依次落 Pages / Settings / Commands。
- 遮罩点击关闭；**没有焦点陷阱，也没有 Tab 处理**（Tab 会离开对话框）。
- 状态行：`query.trim() && search.loading` → `<div class="search-empty" role="status">{t("search.loading")}</div>`；
  `query.trim() && search.error` → `<div class="search-empty" role="alert">{t("search.failed")}<button class="btn btn-secondary">{t("search.retry")}</button></div>`；
  `query.trim() && search.nextOffset !== null` → 「加载更多」`role="option"`、`aria-disabled={search.loading}`；
  四个列表全空且 query 非空且非 loading/error → `<div class="search-empty">{t("search.empty")}</div>`（**无 role**）。
- 视觉（`styles/overlays.css`，注释自称 "Global search (Codex-style ⌘K spotlight)"）：
  `.search-overlay { position: fixed; inset: 0; z-index: 40; align-items: flex-start; justify-content: center;
  background: color-mix(in oklab, #000 45%, transparent); padding: clamp(48px, 16vh, 140px) 24px 48px;
  animation: overlay-in … }`；
  `.search-dialog { width: min(100%, 620px); max-height: min(460px, 100%); border-radius: var(--radius-lg-plus);
  background: var(--ds-bg-elevated-opaque); box-shadow: var(--ds-shadow-dialog); animation: surface-in-top … }`；
  `.search-input-row { padding: 14px 16px 8px; gap: 10px }`；`.search-results { overflow-y: auto; padding: 6px }`；
  行 `.search-item { gap: 10px; padding: 8px 10px; border-radius: var(--radius-md-plus) }`，`.search-item.active` 用 `--ds-bg-hover`。
  `chrome.css` 覆盖层级：`.app-shell > .search-overlay { z-index: 1200 }`（高于 `.window-controls` 的 1100 与 splash 1300 之下）。

---

## 簇 2 — 会话缩略图（长历史导航）

### 2.1 每条目渲染什么（角色标记？工具点？）

`lib/conversation-minimap.ts`：

```ts
export type ConversationMinimapMarker = { id: string; role: "user" | "assistant"; preview: string };
export const CONVERSATION_MINIMAP_PREVIEW_MAX_CHARS = 280;
export function buildConversationMinimapMarkers(messages: UiMessage[]): ConversationMinimapMarker[]
```

- 一条 user 消息 = 一个 marker（`preview = messageContentFacts(message).trimmedContent.slice(0, 280)`），
  同时把 `assistantMarkerIndex = null`（开启新的助手轮）。
- 助手侧是**按轮**而非按消息：首个有内容的助手分片建 marker 并记住下标；
  后续分片用 `appendPreview(current, next)` 追加（以 `"\n\n"` 连接，整体 `.slice(0, 280)`）；
  一旦 `preview.length >= 280` 就 `continue`（后续分片不可能再改变饱和的 preview 或其首个锚点）。
- `role !== "user" && role !== "assistant"` 一律跳过；助手分片 `trimmedContent` 为空则跳过。
- **没有 tool 点**。角色差异只体现在 CSS 与 `aria-label`：
  `roleLabel = role === "user" ? t("chat.userMessage") : t("chat.assistantMessage")`。
- 另外有一个特殊条目 `EARLIER_HISTORY_MARKER_ID = "__earlier-history__"`（虚线、可点击加载更早历史），见 2.7。

### 2.2 何时显示（最小条目数？）

```ts
export function shouldRenderConversationMinimap({markerCount, overflows, hasEarlier}) {
  return hasEarlier || (markerCount >= 2 && overflows);
}
```

- `overflows` 在 `updateOverflow()` 里算：`el.scrollHeight - el.clientHeight > OVERFLOW_EPSILON_PX`，
  `const OVERFLOW_EPSILON_PX = 1;`（注释 "Hide the rail until content actually overflows one viewport"）。
- 即：**至少 2 个 marker 且内容溢出**，或者有更早历史（`hasEarlier`）时无条件显示。
- `ChatTranscript` 还额外要求 `paneVisible && !veilCovering` 才挂载（隐藏的保留窗格不测量；
  也不在 settle veil 未升起时对仍在移动的行缓存偏移）。
- `hasEarlier` 来自 `useTranscriptScroll`：`transcriptWindow.hiddenAbove > 0 || hasMoreBefore`。

### 2.3 与转写滚动的同步（观察者）

没有任何 IntersectionObserver 出现在 minimap 中（IntersectionObserver 用在 `useTranscriptScroll` 里观察历史边界）。
minimap 用三类监听：

1. **滚动**：`el.addEventListener("scroll", scheduleScroll, { passive: true })`，
   `scheduleScroll` 用 `requestAnimationFrame` 合并 → `updateActive(); updateOverflow();`。
2. **内容尺寸**：`new ResizeObserver(scheduleResize)` 观察 `el.firstElementChild`（内容盒），
   外加 `window.addEventListener("resize", scheduleResize)`；
   `scheduleResize` → rAF → `recomputeOffsets(); updateActive(); updateOverflow(); measureMagnifyCenters();`。
3. **导轨自身尺寸**：`new ResizeObserver(() => { cancelAnimationFrame(frame); frame = requestAnimationFrame(measureMagnifyCenters); })` 观察 `railRef`。
   理由写在注释里：导轨高度由 `--composer-dock-height` 派生，而 composer 会随草稿增高重新发布该变量，
   所以 dash 中心会移动而 marker 集合不变。

活跃项跟踪：
- `cachedOffsetsRef` 缓存 `[{id, offset}]`，offset = `node.getBoundingClientRect().top - baseTop + el.scrollTop`，
  节点来自 `el.querySelectorAll<HTMLElement>("[data-minimap-id]")` 并按 `markerIds` 过滤（只在 resize / marker 变化时重算）。
- `updateActive()`：`const anchor = el.scrollTop + el.clientHeight * 0.3;` 二分查找最后一个 `offset <= anchor` 的 marker，
  命中则加 `.active` 与 `aria-current="true"`。**O(log n)**，避免每帧 O(n) DOM 查询。
- `activeIdRef` / `overflowsRef` 做值比较，未变则跳过 setState。

### 2.4 放大（macOS Dock 式余弦衰减，命令式写 CSS 变量）

```
const MAGNIFY_RADIUS = 46;   // 衰减半径
const MAGNIFY_BOOST  = 1.3;  // 峰值增长系数
scale = cursorY == null || dist >= MAGNIFY_RADIUS
      ? 1
      : 1 + MAGNIFY_BOOST * Math.cos((dist / MAGNIFY_RADIUS) * (Math.PI / 2));
btn.style.setProperty("--magnify", scale.toFixed(3));
```
- mousemove → `cancelAnimationFrame(moveRaf.current); moveRaf.current = requestAnimationFrame(() => applyMagnify(y))`，
  `y = event.clientY - rail.getBoundingClientRect().top`；`mouseleave` → `applyMagnify(null)`；卸载时取消 rAF。
- 中心点 `magnifyCentersRef = [{id, center: btn.offsetTop + btn.offsetHeight / 2}]`，`measureMagnifyCenters()` 只读一轮再排序；
  注释解释：若在写 `--magnify` 的同一循环里读 `offsetTop`，每条 dash 每帧都会强制一次同步布局（O(markers) layout/frame）。
- dash 只**横向**放大：`width: calc(var(--dash-w) * var(--magnify, 1))` + `transition: width 90ms …`，
  高度恒为 8px，所以放大永不改变堆叠布局。
- 未渲染时（`markers.length === 0` 的边界）会回退调用一次 `measureMagnifyCenters()`。

### 2.5 悬停预览气泡

```
const POPOVER_SNAP = 24;      // 光标需离 dash 多近才吸附
const POPOVER_HEIGHT = 132;   // 气泡估计高度
top = min(max(nearest.center - 36, 0), max(rail.clientHeight - POPOVER_HEIGHT, 0));
```
- 只有 `dist <= POPOVER_SNAP` 且是最近的 dash 才显示；渲染
  `<div class="minimap-popover" role="tooltip" style={{top: `${hovered.top}px`}}>`，内含
  `.minimap-popover-role`（角色名）与 `.minimap-popover-text`（preview）。
- `setHovered` 有相等性守卫（同一 marker.id 且同一 top 则返回 prev）。
- 键盘：`onFocus` 用 `setHovered({marker, top: Math.max(0, event.currentTarget.offsetTop - 36)})`，`onBlur` 清空。
- CSS：`.minimap-popover { position: absolute; left: 34px; z-index: 7; width: 248px; padding: 10px 12px;
  border: 1px solid var(--ds-border-default); background: var(--ds-bg-elevated-opaque); pointer-events: none; }`，
  `.minimap-popover-text { -webkit-line-clamp: 5; white-space: pre-wrap; overflow-wrap: anywhere; }`。

### 2.6 点击 / 拖拽跳转

- **只有 click，没有拖拽/擦洗**：`onClick={() => jumpTo(marker.id)}`。
- `jumpTo(id)`：
  ```ts
  const target = getOffsets().find(entry => entry.id === id);   // 新鲜像素级查询
  if (!target) return;
  onReleaseFollow?.();                                          // 先脱离 follow
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  el.scrollTo({ top: Math.max(0, target.offset - 24), behavior: reduceMotion ? "auto" : "smooth" });
  ```
  即滚到该行上方 **24 px**；`onReleaseFollow` 传的是 `useTranscriptScroll` 的 `releaseFollow`，
  注释写明「While follow is still pinned, the jump's scroll carries no input gesture, so the scroller reads it as a
  layout clamp and re-bottoms the view」——这是必须的，不是副作用。
- `getOffsets()` 与 `recomputeOffsets()` 实现相同但**不写缓存**（跳转需要像素级新鲜数据）。

### 2.7 「更早历史」条目

- 仅当 `hasEarlier` 时渲染，id 为 `EARLIER_HISTORY_MARKER_ID = "__earlier-history__"`，是一个 `TooltipButton`：
  `className={\`minimap-marker history ${loadingEarlier ? "loading" : ""}\`}`，
  `ariaLabel`/`tooltip` = `loadingEarlier ? t("chat.loadingEarlierMessages") : t("chat.showEarlierMessages")`，
  `aria-busy={loadingEarlier || undefined}`，`disabled={loadingEarlier || !onRevealEarlier}`，`onClick={onRevealEarlier}`。
- `revealEarlierHistory()`（`useTranscriptScroll`）：若 `isHistoryRevealPosition(el)` 为真 → `reachTop()`
  （先扩挂载窗口、再按需取更早一页）；否则 `releaseDisclosureAnchor(); releaseFollow();`
  然后 `el.scrollTo({ top: 0, behavior: reduceMotion ? "auto" : "smooth" })`。
- CSS 用虚线区分：`--dash-w: 13px`，
  `background: repeating-linear-gradient(90deg, var(--history-marker-color) 0 2px, transparent 2px 4px)`；
  `:disabled { cursor: progress }` + `opacity: 0.55`。

### 2.8 尺寸常量（`styles/chat-shell.css`）

```css
.minimap-rail {
  position: absolute; left: 8px;
  top: var(--ds-toolbar-height);
  bottom: calc(var(--composer-dock-height, 200px) + 16px);
  z-index: 6; display: flex; width: 26px;
  flex-direction: column; align-items: flex-start; justify-content: center;
  gap: clamp(0px, calc(4px - var(--minimap-marker-count) * 0.05px), 2px);
  -webkit-app-region: no-drag; app-region: no-drag;
}
.minimap-marker { display: flex; align-items: center; flex: 0 1 auto; width: 100%; height: 8px; min-height: 0; … }
.minimap-marker::before { content: ""; height: min(2px, 100%); width: calc(var(--dash-w) * var(--magnify, 1));
  border-radius: var(--radius-full); background: color-mix(in oklab, var(--ds-text-primary) 14%, transparent);
  transition: width 90ms var(--motion-ease-out), background var(--motion-duration-fast) var(--motion-ease-out); }
.minimap-marker.user      { --dash-w: 13px; }
.minimap-marker.assistant { --dash-w: 8px; }
.minimap-marker.history   { --dash-w: 13px; --history-marker-color: color-mix(in oklab, var(--ds-text-primary) 14%, transparent); }
.minimap-marker:hover::before, .minimap-marker:focus-visible::before { background: var(--ds-text-secondary); }
.minimap-marker.active::before { background: var(--ds-text-primary); }
```
- 内联样式由组件发布：`style={{ "--minimap-marker-count": markers.length + Number(hasEarlier) }}`，
  所以 gap 随条目数从 4px 线性降到 0（下限 0、上限 2px）——密集堆叠靠**缩 gap**而非溢出。
- 注意 `.thread-scroll` 的 `mask-image` 注释明确把 minimap 排除在遮罩之外：
  「The mask belongs here rather than on `.thread-wrap`: its other children - the minimap rail, the jump-to-latest
  button, the settle veil, and the navigation status - must stay fully painted.」
  同时 `.thread-scroll { overflow-anchor: none }`、`.jump-latest-btn { bottom: calc(var(--composer-dock-height, 168px) + 12px) }`。

### 2.9 可访问性

- 容器是 `<nav className="minimap-rail" ref={railRef} aria-label={t("chat.minimap")}>`。
- 每个 dash 是真实 `<button>`（`type` 缺省为 submit，但不在表单内），带 `aria-label`（角色名）与活跃项 `aria-current="true"`。
- 历史条目是 `TooltipButton`（`ariaLabel` + `tooltip` + `aria-busy` + `disabled`）。
- **没有 listbox 语义、没有 roving tabindex、没有方向键导航** —— 每个 dash 都可 Tab 到。
- 组件是 `memo(...)`；大量回调用 `useCallback` 包裹以避免 memo 失效。

### 2.10 长历史的窗口化/虚拟化（`lib/transcript-window.ts`）

```
export const TRANSCRIPT_INITIAL_MOUNT = 15;   // 会话切换后首次提交挂载的历史行
export const TRANSCRIPT_WINDOW_MIN   = 60;    // 稳态挂载上限
export const TRANSCRIPT_WINDOW_STEP  = 40;    // 每次触顶新增的行

reduceTranscriptWindow({historyLength, windowSize, initialCommit}):
  budget  = initialCommit ? TRANSCRIPT_INITIAL_MOUNT : Math.max(TRANSCRIPT_WINDOW_MIN, windowSize);
  mounted = Math.min(length, budget);
  hiddenAbove = length - mounted;
  return { mounted, hiddenAbove, bounded: hiddenAbove > 0 };

growTranscriptWindow(windowSize, historyLength):
  current = Math.max(60, windowSize); if (current >= length) return current;
  return Math.min(length, current + 40);
```
设计注释（ADR 0120 / D261）：「bounded what crosses the IPC boundary, not what the renderer keeps in the DOM」——
所以窗口是**挂载窗口**，不是像素虚拟化；`content-visibility` 只跳过布局/绘制但保留全部内容，对低内存机型是错的资源。

在 `useTranscriptScroll` 里的接线：
- `historyEntries = useMemo(() => bounded ? allHistoryEntries.slice(-mounted) : allHistoryEntries, [allHistoryEntries, bounded, mounted])`
  （memo 化以便 `TranscriptHistory` 按数组 identity bail）。
- `historyLengthRef.current = allHistoryEntries.length`（供 `reachTop` 读取，保持 `reachTop` 引用稳定）。
- **两段式升级**：`reachTop()` 先 `growTranscriptWindow`，只有 `grown === windowSize`（窗口已覆盖全部已加载）才 `loadOlder()`。
  两段都走同一套锚定：`prependHeightRef.current = el.scrollHeight`，然后在
  `useLayoutEffect(..., [messages.length, windowSize])` 里 `delta = el.scrollHeight - previousHeight; if (delta > 0) el.scrollTop += delta;`
  并同步 `lastScrollTopRef` / `lastLaidOutScrollTopRef`（prepend 与扩窗都是在阅读位置**上方**加高度）。
- 首次提交的 hydration 门（渲染期派生，不是 effect 里设置）：
  `hydrationBounded = !readingWindow && firstCommit && allHistoryEntries.length > TRANSCRIPT_INITIAL_MOUNT`；
  展开在 `requestAnimationFrame` 里落 `firstCommitRef.current = false` 并 `setHydrationTick(t=>t+1)`；
  随后一个 layout effect「仅当仍 pinned」重新贴底（用户已上滚则保留位置），并配
  `.transcript-hydration-spacer { min-height: 100vh }`（刻意不是按条数估算——估算误差就是切换会话时的页面跳动）。
- 历史触顶的**第二触发器**是 IntersectionObserver（而不只是 scroll 事件）：观察 `historyBoundaryRef`（`.transcript-history-loading`），
  `root: scrollRef.current`，`rootMargin: \`${HISTORY_REVEAL_THRESHOLD_PX}px 0px 0px 0px\`` → `120px`；
  依赖里含 `transcriptWindow.hiddenAbove`（因为边界持续可见时 IO 不会再通知，没有它就只能升级一次然后卡住）。
  没有 IO 时回退为「立即判一次 + rAF」。
- **minimap 只描述已挂载行**：
  ```ts
  const minimapMessages = useMemo(() =>
    transcriptWindow.bounded
      ? transcriptEntryMessages(tailEntry ? [...historyEntries, tailEntry] : historyEntries)
      : visible,
    [historyEntries, tailEntry, transcriptWindow.bounded, visible]);
  ```
  注释：「a dash for a withheld row would jump nowhere (D261)」。
- `tailEntry` 永远挂载（`historyLength` 的定义即「排除 tail 项」）。
- `readingWindow = true` 时（历史搜索阅读模式）窗口被绕过：`windowSize: allHistoryEntries.length`，
  并且 `handleScroll` 直接 `pinnedRef.current = false; setShowJump(true); return;`。

### 2.11 展开锚定（`lib/disclosure-anchor.ts` + `hooks/use-disclosure-anchor.ts`）

问题陈述（源码注释）：`.thread-scroll` 设了 `overflow-anchor: none`，浏览器原生锚定不可用；
pinned follow 会在每次内容 resize 时重新贴底，正好把刚点击的工具/思考/活动标题拖出视野。

```
export const DISCLOSURE_ANCHOR_TOLERANCE_PX = 0.5;
DisclosureAnchor       = { offset }                       // 标题相对 scroller 顶边的偏移，不是 scrollTop
DisclosureAnchorFrame  = { elementOffset, scrollTop, scrollHeight, clientHeight }
disclosureAnchorOffset(scrollerTop, elementTop) = elementTop - scrollerTop
disclosureContentTop(frame) = frame.elementOffset + frame.scrollTop
resolveDisclosureAnchor(anchor, frame):
  maxScrollTop = max(0, scrollHeight - clientHeight)
  target = min(maxScrollTop, max(0, disclosureContentTop(frame) - anchor.offset))
  return Math.abs(target - frame.scrollTop) < DISCLOSURE_ANCHOR_TOLERANCE_PX ? null : target
adoptDisclosureAnchor(frame) = { offset: frame.elementOffset }
```
- 用「相对顶边偏移」而非 `scrollTop`，这样**同时发生在标题上方的高度变化**（折叠行、前插历史页）也被补偿。
- 返回 `null` 表示视口已经持有该锚点 → 不写 scroller（每次写入都会发出 scroll 事件）。
- `adoptDisclosureAnchor` 在纠正后重新采样标题**实际到达**的位置：边界 clamp 是浏览器的答案，采纳它，避免下一帧继续对抗。
- `useDisclosureAnchor(scrollRef, onHold, onPosition)`：
  - `notifier(title)` 在手动展开**改变状态之前**同步调用，`measure` 记录
    `{elementOffset: element.getBoundingClientRect().top - scroller.getBoundingClientRect().top, scrollTop, scrollHeight, clientHeight}`，
    存 `heldRef.current = { element, offset }`，然后 `onHoldRef.current()`（在转写里是 `enterDisclosureReading = releaseFollow`），
    并把 hold **向外传递**：`outerNotifier?.(title)`（读 `DisclosureAnchorContext` 的 ambient 值，绝不会读到自己的值）。
    这对嵌套滚动器（D302 的 delegate dock）是必需的：内层长高会撑高外层内容，外层若仍在 follow 就会重新贴底、把同一个标题拽走。
  - `restore()`：测当前帧 → `resolveDisclosureAnchor` → 非 null 则 `scroller.scrollTop = target` 并
    `onPositionRef.current(scroller.scrollTop)` → 再测一次并 `adoptDisclosureAnchor`；返回 `true` 表示「本帧有 hold」。
  - `release()` 清空；`isHeld()` 供排队 follow 的调用方判断。
- 调用点是 scroller 自己的 ResizeObserver 回调 `followScrollNow()`：
  ```ts
  if (paneVisibleRef.current && restoreDisclosureAnchor()) return;   // 先恢复标题，本帧不再贴底
  if (!paneVisibleRef.current || !pinnedRef.current) return;
  cancelFollowScroll(); scrollToBottom();
  ```
  注释解释为何在 observer 回调内直接滚（而不是再排一个 rAF）：从 rAF 里滚会先画一帧未贴底的内容再在下一帧弹回（D287）。
- 真正的手势（`markScrollGesture`）与 `jumpToLatest` 会 `releaseDisclosureAnchor()`，把视口交还用户。
- 相关滚动常量（`lib/transcript-scroll.ts`）：`TRANSCRIPT_REPIN_THRESHOLD_PX = 48`、
  `TRANSCRIPT_SCROLL_ROUNDING_TOLERANCE_PX = 1`、`HISTORY_REVEAL_THRESHOLD_PX = 120`、
  `TRANSCRIPT_SCROLL_GESTURE_WINDOW_MS = 200`、`SCROLL_OWNER_ATTRIBUTE = "data-scroll-owner"`（`.thread-scroll` 上是 `data-scroll-owner="transcript"`）、
  `SCROLL_GESTURE_KEYS = {ArrowUp, ArrowDown, PageUp, PageDown, Home, End, " "}`。
  `reduceTranscriptScroll` 只在「真实手势 + 上移 + distanceFromBottom > 0」时释放 follow；
  非手势的 releasedFollow 会 `pinnedRef.current = wasPinned; setShowJump(!wasPinned); scheduleFollowScroll();`（当作布局噪声重新基准化）。
- `use-follow-scroll.ts` 是同一契约的**嵌套**版本（delegate dock，D302），导出
  `{ scrollRef, contentRef, showJump, handleScroll, jumpToLatest, scheduleFollowScroll, releaseFollow, disclosureAnchorNotifier }`
  并同样 `ro.observe(content, {box:"border-box"})` + `ro.observe(scroller, {box:"border-box"})`。
  `hooks/use-transcript-view.ts` 只有 1018 字节，负责把 `messages / hasMoreBefore / hasMoreAfter / focus / parentMessage / historical / loading` 从 store 投影出来。

---

## 簇 3 — 上下文用量检查器

### 3.1 触发控件

`components/ContextUsageInspector.tsx` 由 `features/chat/composer/ComposerToolbar.tsx` 在 `composer-right` 区渲染：
`{contextUsage ? <ContextUsageInspector {...contextUsage} /> : null}`。
props 由 `components/Composer.tsx` 生成：
`useMemo(() => latestTurnContextInspector(liveMessages, providerModels, providers, sessionCompactions), [...])`，
`lib/latest-turn-context.ts` 产出 `{usage, turnUsage, contextWindow, tools, responseDurationMs, responseOutputTokens, responseOutputEstimated}`
—— 取**最新一条带 usage 且 `!parentToolCallId` 的父消息**，工具的用量/时长取最新的 assistant turn 摘要，避免把后续无总量的活轮当成来源。
返回值用 `WeakMap` 按消息快照 owner 缓存（逐字段比较后才复用）。

- 触发控件是 `TooltipButton`，`className="context-inspector-trigger"`，`aria-haspopup="dialog"`、`aria-expanded={open}`、
  `aria-controls={open ? panelId : undefined}`（`panelId = useId()`），
  `tooltip`/`ariaLabel` = `t("chat.usageContextAria", { percent: display.percent, count: formatCompactTokenCount(display.tokens), state })`，
  其中 `state` 为 `chat.usageContextAriaUsed` / `chat.usageContextAriaRemaining`（取决于显示模式）。
- **点击切换，不是悬停打开**：注释「The panel is click-toggled rather than hover-opened: reading the token breakdown
  takes long enough that a pointer leaving the trigger should not dismiss it.」
- 外形：SVG 环 + 百分比文本（见 3.4）。外层 `.context-inspector` 带 `data-level` 与 `data-open`。
  `composer.css` 只加了一条 `.composer-right .context-inspector-trigger { min-height: 28px; }`。

### 3.2 展示的分解项（精确 i18n key，按 DOM 顺序）

| 区块 | class | 文案键 |
|---|---|---|
| 标题 | `.context-inspector-heading` | `chat.usageContextSpent`（used 模式）/ `chat.usageContextLeft`（remaining 模式），值 `formatCompactTokenCount(display.tokens)`；右侧 `.context-inspector-heading-percent` = `{display.percent}%` |
| 窗口 | `.context-inspector-window` | 标签 `chat.usageContextWindow`；值 `chat.usageContextTokens` 带 `{used, window}`；右侧 `.context-inspector-window-percent` = `{context.usedPercent}%` |
| KPI 1 | `.context-inspector-kpis` | `chat.usageTurnTotal` → `formatCompactTokenCount(turnTotal)` |
| KPI 2 | 同上 | `chat.usageThroughputLabel` → `chat.usageThroughputUnavailable` 或 `chat.usageThroughput` / `chat.usageThroughputEstimated`（`{count}`，由 `responseOutputEstimated` 选择） |
| 提供方 | `.context-inspector-summary-row` #1 | 标题 `chat.usageProviderUsage`；值依次 `chat.usageInput`、`chat.usageOutput`，可选 `chat.usageCacheRead`、`chat.usageCacheRate`、`chat.usageCacheWrite`、`chat.usageReasoning`（各自以 `usage.*Tokens !== undefined` 为门；cacheRate 以 `!== undefined` 为门） |
| 工具 | `.context-inspector-summary-row` #2 | 标题 `chat.usageTools`；值 `chat.usageToolsSummary`（`{count: toolRows.length, calls: tools.length, tokens}`）或 `chat.usageNoTools` |
| 压缩 | `.context-inspector-compaction` | `chat.usageCompaction`（`{times: compaction.generation}`）+ `~{formatCompactTokenCount(compaction.summaryTokens)}`；`title` 属性仅在 `compaction.summarized && !compaction.fallback && compaction.summary?.trim()` 时给出摘要 |

- 压缩来源：`useAppStore(s => s.activeSessionId ? s.sessionCompactions[s.activeSessionId]?.at(-1) : undefined)`
  （`ContextCompactionStatus = { generation, summaryTokens }`，见 `packages/shared/src/types/sessions.ts`）。
- 弹层容器：`role="dialog"`、`aria-label={t("chat.usageContextLabel")}`、`id={panelId}`，
  仅当 `popoverPosition` 非空时带 `is-open`，内联写 `top/left/maxWidth` 三个 px 值；用 `portalToBody(popover)` 挂到 body。
- 等级：`const level = context.remainingPercent <= 10 ? "critical" : context.remainingPercent <= 25 ? "warning" : "comfortable";`
  **两种显示模式下容量配色都跟随 remainingPercent**（注释：「'used 78%' still warns when only 22% is left」）。

### 3.3 百分比与 token 计算（`lib/context-usage.ts`）

```
export const DEFAULT_CONTEXT_WINDOW = 128_000;
positiveTokenCount(v) = typeof v === "number" && Number.isFinite(v) && v > 0 ? Math.round(v) : 0;

usageTokenTotal(usage)      = totalTokens 若 > 0，否则 input + output
contextOccupancyTokens(u)   = input + output + reasoning + cacheRead + cacheWrite
                              （>0 时返回；否则退回 usageTokenTotal）—— 对应 OpenCode 的 last-message 记账
calculateContextUsage(usage, contextWindow):
  safeWindow       = positive(contextWindow) || 128_000
  usedTokens       = contextOccupancyTokens(usage)
  usedRatio        = Math.min(1, usedTokens / safeWindow)
  remainingRatio   = 1 - usedRatio
  usedPercent      = Math.round(usedRatio * 100)
  remainingTokens  = Math.max(0, safeWindow - usedTokens)
  remainingPercent = 100 - usedPercent
resolveContextUsageDisplay(value) => value === "used" ? "used" : "remaining"   // settings.contextUsageDisplay
contextUsageView(usage, display)  => used 模式取 {usedPercent, usedTokens, usedRatio}，否则取 remaining*
calculateTokenRate(outputTokens, responseDurationMs) = Math.round(outputTokens / (responseDurationMs / 1000))
   // 任一非有限或 <= 0 时 undefined
calculateCacheRate(inputTokens, cacheReadTokens) = Math.round(cacheReadTokens / (inputTokens + cacheReadTokens) * 100)
   // cache write 不进分母；promptTokens <= 0 时 undefined
```
`contextWindow` 的解析顺序（`resolveContextWindow(providerId, modelId, providerModels, providers)`）：
1. 目录模型 `providerModels[providerId]` 里 `modelWireIdsEqual(model.modelId, modelId)` 的 `model.contextWindow`；
2. 已保存绑定的 `effectiveContextWindow(catalogWindow, binding.contextWindow, binding.contextWindowSource)`（provenance 跟着值走）；
3. `provider.contextWindow`（**仅当**没有 modelId 或 provider 没有 models 列表，避免窗口描述的是另一个模型）；
4. 兜底 `DEFAULT_CONTEXT_WINDOW = 128_000`。

工具 token 估算：`estimateToolTokenUsage` 用 **4 字符 ≈ 1 token**（`Math.ceil(chars / 4)`），
字符数来自 `JSON.stringify({tool: toolName ?? "", arguments: toolArgs ?? null}).length` 与
`JSON.stringify(toolResult ?? content ?? "").length`（`serializedLength` 对字符串直接取 `.length`）；`estimated: true`。
`toolTokenUsage(message) = message.toolUsage ?? estimateToolTokenUsage(message)`。
`aggregateToolTokenUsage(messages)` 按 `toolName?.trim() || "__unknown_tool__"` 分组，保留首次出现顺序，
累加 `callCount / argumentTokens / resultTokens / totalTokens / durationMs`。

### 3.4 环/条渲染方式

纯 SVG，不是 canvas、不是 conic-gradient，也不是进度条数组：

```tsx
const CONTEXT_RING_RADIUS = 9;
const CONTEXT_RING_CIRCUMFERENCE = 2 * Math.PI * CONTEXT_RING_RADIUS;
<svg className="context-inspector-ring" viewBox="0 0 24 24" aria-hidden="true">
  <circle className="context-inspector-ring-track" cx="12" cy="12" r={CONTEXT_RING_RADIUS} />
  <circle className="context-inspector-ring-progress" cx="12" cy="12" r={CONTEXT_RING_RADIUS}
          strokeDasharray={CONTEXT_RING_CIRCUMFERENCE}
          strokeDashoffset={CONTEXT_RING_CIRCUMFERENCE * (1 - display.ratio)} />
</svg>
<span className="context-inspector-ring-value">{display.percent}%</span>
```
CSS（`styles/messages.css`）：
`.context-inspector-ring { width: 17px; height: 17px; overflow: visible; transform: rotate(-90deg); }`；
`.context-inspector-ring-track, .context-inspector-ring-progress { fill: none; stroke-width: 2.5; }`；
track `stroke: color-mix(in oklab, var(--ds-text-primary) 14%, transparent)`；
progress `stroke: currentColor; stroke-linecap: round; transition: stroke-dashoffset var(--motion-duration-normal) …`。
`currentColor` 由 `.context-inspector`（`--ds-accent`）/ `[data-level="warning"]`（`--ds-warning`）/
`[data-level="critical"]`（`--ds-error`）决定。环值文本 `font-variant-numeric: tabular-nums`。
弹层内没有条形图，只有文本行（`.context-inspector-kpis` / `-summary-row` 用 `justify-content: space-between`）。

### 3.5 弹层定位算法（`lib/context-inspector-position.ts`）

```
export const CONTEXT_INSPECTOR_MARGIN = 16;
export const CONTEXT_INSPECTOR_GAP = 8;

placeContextInspector({ trigger, popover, pane, viewport, margin = 16, gap = 8 }): { top, left, maxWidth } | null
  left        = (pane ? pane.left  : 0)             + margin;
  right       = (pane ? pane.right : viewport.width) - margin;
  maxWidth    = Math.floor(right - left);
  if (maxWidth <= 0) return null;                        // 调用方视为「保持关闭」
  width       = Math.min(popover.width, maxWidth);
  maximumLeft = Math.max(left, right - width);
  clampedLeft = Math.min(Math.max(left, trigger.left), maximumLeft);
  above       = trigger.top - popover.height - gap;
  below       = trigger.bottom + gap;
  maximumTop  = Math.max(margin, viewport.height - popover.height - margin);
  top = above >= margin && above <= maximumTop ? above
      : below >= margin && below <= maximumTop ? below
      : Math.min(Math.max(margin, below), maximumTop);
```
- **水平方向以会话面板（`.main-pane`）而非视口为界**。源码注释（D357）：工作面板内嵌的浏览器/插件视图是原生
  `WebContentsView`，合成在所有 renderer 层之上，所以 popover 越过面板右边缘的部分「无论 z-index 多高都会被盖住」，
  因此 clamp 用 `trigger.closest(".main-pane")?.getBoundingClientRect()`，并回报 `maxWidth` 让窄面板把弹层**压窄**而不是让它钻到面板下面。
- 调用侧 `updatePopoverPosition()`：
  - `triggerRect.bottom > 0 && triggerRect.top < window.innerHeight` 不成立 → 自己关掉（`setOpen(false)`）；
  - 结果缓存用三字段 identity 守卫（`previous?.top === placement.top && previous.left === placement.left && previous.maxWidth === placement.maxWidth`）；
  - 失败（`placement === null`）也关掉。
- 重算触发点：
  1. `useLayoutEffect` 在 open 时 `requestAnimationFrame(updatePopoverPosition)`，依赖
     `[compaction, context.usedTokens, contextWindow, open, toolRows.length, toolTotal, turnTotal, throughput, updatePopoverPosition]`；
  2. `window.addEventListener("resize", …)` 与 `window.addEventListener("scroll", …, true)`（捕获阶段，覆盖任意滚动容器）；
  3. `ResizeObserver` 观察弹层自身；
  4. `ResizeObserver` 观察 `triggerRef.current?.closest(".main-pane")` —— 侧栏开关/缩放、工作面板开合与入场动画都会移动面板右缘却
     **不发出 window resize 或 scroll 事件**（issue #246），只看前两者会留下被原生面板遮住的陈旧 clamp。
- 关闭路径：`window.addEventListener("pointerdown", handler, true)`，若 target 不在 trigger 也不在 popover 内则关闭；
  `window.addEventListener("keydown", handler)` 中 `event.key === "Escape"` → `closeInspector(); triggerRef.current?.focus();`
- CSS（`messages.css`）：`.context-inspector-popover { position: fixed; z-index: 60; display: flex;
  width: min(376px, calc(100vw - 32px)); max-height: min(560px, calc(100vh - 32px)); overflow-y: auto; padding: 16px;
  border: 1px solid var(--ds-border-default); border-radius: var(--radius-md-plus);
  background: var(--ds-bg-elevated-opaque); box-shadow: var(--ds-shadow-dialog);
  opacity: 0; pointer-events: none; transform: translateY(4px); visibility: hidden;
  transition: opacity …, transform …, visibility 0s linear var(--motion-duration-fast); }`，
  `.is-open { opacity: 1; pointer-events: auto; transform: translateY(0); visibility: visible; transition-delay: 0s; }`。
  分区之间「只靠留白分隔」（`.context-inspector-window, -kpis, -summary, -compaction { margin-top: 14px; }`，D297）。
  `@media (prefers-reduced-motion: reduce)` 把 ring-progress / trigger / popover 的 transition 全部设为 none。

### 3.6 是否键盘可访问

是（基本可访问，但不完整）：触发控件是原生 `<button>`，可由 Tab 聚焦、Enter/Space 切换，
有 `aria-haspopup="dialog"` / `aria-expanded` / `aria-controls`，`:focus-visible` 有 2px outline
（`.context-inspector-trigger:focus-visible { outline: 2px solid color-mix(in oklab, currentColor 54%, transparent); outline-offset: 2px; }`），
Escape 关闭**并把焦点还给触发控件**。
缺口：没有焦点陷阱、打开时焦点不进入弹层、`role="dialog"` 上**没有 `aria-modal`**，弹层内部没有可聚焦元素。

### 3.7 token 上限预设（`lib/model-limit-presets.ts`）

用途写在文件头：**Settings → Agent → 某模型的 Advanced 面板（issue #202）**，不是检查器本身。
点预设把 token 数写进数字输入框，输入框仍可手改，与当前值相等的 chip 高亮。

```ts
export const CONTEXT_WINDOW_PRESETS: readonly LimitPreset[] = [
  { label: "128k", tokens: 128_000 },
  { label: "256k", tokens: 256_000 },
  { label: "312k", tokens: 312_000 },
  { label: "500k", tokens: 500_000 },
  { label: "1M",   tokens: 1_000_000 },
];
export const MAX_OUTPUT_PRESETS: readonly LimitPreset[] = [
  { label: "4k",   tokens: 4_000 },
  { label: "8k",   tokens: 8_000 },
  { label: "16k",  tokens: 16_000 },
  { label: "32k",  tokens: 32_000 },
  { label: "128k", tokens: 128_000 },
];
export function matchPresetIndex(presets, value): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) return -1;
  return presets.findIndex(preset => preset.tokens === value);   // 精确相等，无取整/容差
}
```
**是绝对 token 阶梯，不是百分比步进**（与任务描述里的假设不同）。`matchPresetIndex` 返回 `-1` 表示当前值不匹配任何预设。

---

## 可移植性陷阱（pywebview + WebView2，单一 RPC 桥）

**簇 1（搜索）**
- 高亮是 **CSS Custom Highlight API**：`new Highlight(...ranges)` + `CSS.highlights.set("transcript-search", h)` +
  `::highlight(transcript-search)`。WebView2 是 Chromium，API 存在；但 `::highlight()` **没有 polyfill**。
  如果移植时改写 DOM 注入 `<mark>`，React 下一次渲染就会抹掉/打架——Pi 正是为此才用 text node + Range 而不动 DOM。
  同时 `Range.getBoundingClientRect()`（可能跨内联元素）是对齐的唯一几何来源。
- `document.createTreeWalker` 的接受/拒绝规则必须一起搬：`NON_CONTENT = "button:not(.chat-text-link):not(.chat-file-chip):not(.chat-code-link), textarea, [aria-hidden='true']"`
  决定了哪些文本参与匹配；漏掉就会在按钮标签、textarea、aria-hidden 装饰里匹配到东西。
- `CSS.escape` 用在 `[data-message-id="${CSS.escape(id)}"]`。去掉它，含引号/反斜杠的 id 会直接抛异常。
- `content-visibility: auto` + `contain-intrinsic-size: auto 140px` 让屏幕外的行**不产生真实几何**：
  Pi 在测量前先加 `.transcript-search-target { content-visibility: visible }`。若移植改用绝对定位 spacer 的像素虚拟化，
  就必须自己实现「先渲染再测量」这一步，否则 `getBoundingClientRect()` 全是跳渲染结果。
- 「上一处/下一处」在 Pi 里**不在对话框**：它是宿主 `sessionSearchContext` 返回的
  `previousMatchId` / `nextMatchId` + 转写侧的 1500 ms 对齐窗口。移植时如果只想做一个「下一个」按钮，
  必须自己定义 `paneVisible→releaseFollow→scrollTop 写入` 这条链，否则 follow 模式会把视图拽回底部。
- 手势归属是硬需求：`isRecentScrollGesture`（窗口 200 ms）+ `tolerancePx: gesturing ? 0 : 1`。
  Python 侧发起的任何 `scrollTo`（例如「跳到消息」RPC）都是**程序化滚动**，不带输入事件，
  会被 `reduceTranscriptScroll` 判成布局 clamp 而重新贴底。必须走 minimap 用的同一条 `releaseFollow()` 路径。
- 分数 devicePixelRatio：容差 1px 的存在理由是 DPR 1.1 时请求 841 会读回 840.909。删掉它，follow 模式随机脱落。
- 搜索**必须**在宿主侧做：SQLite + `pi_search_contains` 标量函数（`to_lowercase().contains(&query.to_lowercase())`）。
  用 SQLite 的 `LIKE` 代替会丢 CJK 与土耳其语 İ/ı 行为；FTS 分支只在
  `查询字符数 >= 3 && 不含 U+0307 && 全为 ASCII 或无大小写字符` 时启用，其余走字面扫描。移植要复刻这个判据。
- **排序不是相关性**：`ORDER BY s.updated_at DESC, s.id ASC`，每页 30 个会话（`LIMIT 31` 前瞻）、每会话 2 条片段、
  片段预算 180 字符。任何「打分排序」都是行为改变。
- 分页协议是 offset+nextOffset，且渲染侧 `SessionSearchController.load` 用 `Set` 按 `session.id` 跨页去重；
  两个防抖（会话 150 ms、命令 80 ms）都靠 generation/query 归属，桥接层若把两次请求并发返回，旧结果会覆盖新结果。
- DOM 契约：选项 id 必须是 `global-search-option-${index}`（`aria-activedescendant` 与
  `scrollIntoView({block:"nearest"})` 都依赖它），且扁平索引算术要计入「命中消息行」占用的额外槽位，
  否则 combobox 的 ARIA 指认会错位。

**簇 2（缩略图 + 窗口化）**
- 导轨几何依赖两个 CSS 变量的**运行时发布**：`--composer-dock-height`（由 `Composer` 用
  `ResizeObserver` + `Math.round(el.getBoundingClientRect().height)` 写到 `document.documentElement`，且只在值变化时写）
  和 `--minimap-marker-count`（组件内联）。若移植把 composer 渲染在转写 DOM 之外（或另一个 WebView），
  导轨高度、转写底部留白、`.thread-scroll` 的 mask 渐变会同时失效。
- 三个观察者缺一不可：scroll（rAF 合并）、内容 ResizeObserver + window resize、**导轨自身 ResizeObserver**。
  去掉第三个，composer 随草稿增高时 dash 中心会失准（放大吸附错位）。
- 放大是命令式写 `--magnify`（三位小数）。若改成 React state 或每帧读 `offsetTop`，
  每条 dash 每帧一次强制同步布局（O(markers) layout/frame）——这正是 `magnifyCentersRef` 存在的理由。
- **没有拖拽/擦洗**。想要 scrub 就必须自己实现 pointer capture，并自己决定是否 `releaseFollow`。
- 窗口化是**挂载窗口**（15 / 60 / 40）而非像素虚拟化。改成像素虚拟化后，
  `minimapMessages` 的语义（只描述已挂载行）和「dash 必须能查到对应 DOM 节点」的约束要重新设计，
  否则会出现「跳到一棵不存在的行」。
- `overflow-anchor: none` 是**故意**关掉原生锚定的，所有位置稳定都靠 `disclosure-anchor` 与 prepend 补偿。
  移植若保留原生锚定又不关它，会和 follow 模式互相打架。
- 展开锚定必须**向外传播**（`DisclosureAnchorContext`）：嵌套的 delegate dock（`.subagent-run-rows`，
  `max-height: min(420px, 48vh)`，同样 `overflow-anchor: none`）长高会撑高外层转写，
  外层若仍在 follow 就会把用户刚点开的标题拖走。
- 隐藏窗格（`content-visibility: hidden`）报告 `scrollTop === 0`，会被读成「用户在顶部」。
  Pi 用 `lastLaidOutScrollTopRef` 采样最后一个有布局的偏移，并用 `paneVisible` 门禁 IO/采样/follow。
  多标签或后台预渲染的移植版必须做同样的门禁，否则会为一个没人看的会话翻历史。

**簇 3（上下文用量）**
- `ResizeObserver` 观察 `.main-pane` 是**不可省**的一条：侧栏开关/缩放、工作面板开合与入场动画都会移动面板右缘，
  却不产生 window resize 或 scroll。少了它，clamp 会在这些时刻变陈旧。
- 水平 clamp 针对**会话面板**而非视口，原因是原生 `WebContentsView` 合成在一切 renderer 层之上，`z-index` 无法解决。
  纯 pywebview 单 WebView 场景没有这个约束，但**一旦工作面板也用 WebView2 或独立窗口承载，同一约束立刻出现**，
  必须沿用 `pane` 分支而不是退回 viewport。
- `portalToBody` + `PortalVisibilityProvider`：弹层挂在 `document.body`，只在面板可见时渲染。
  没有等价机制时，路由切换会留下孤儿弹层（`trigger.closest` 已不存在 → 每帧 `updatePopoverPosition` 直接 return，弹层永不关闭）。
- 环形进度是 SVG stroke-dashoffset + `transform: rotate(-90deg)` + `stroke-linecap: round` + `stroke-width: 2.5`，
  半径 9、`2*Math.PI*9` 周长、`viewBox 0 0 24 24`、显示尺寸 17×17。用 CSS conic-gradient 重画会丢掉
  `tabular-nums` 的对齐和 dashoffset 过渡，也会与 `data-level` 的 `currentColor` 配色脱钩。
- 4 字符 ≈ 1 token 的估算在**两处**必须一致：`estimateToolTokenUsage` 与
  `estimateResponseOutputTokens`（`Math.max(1, Math.ceil(Array.from(visible).length / 4))`，
  用码点而非 UTF-16 长度）。宿主运行时也用同一启发式，改一处就会让历史行与实时行的数字互相矛盾。
- `matchPresetIndex` 是精确相等；`resolveContextUsageDisplay` 对未知值回退 `"remaining"`（持久化里的错别字不会让触发器变空）。
  这两个「不取整、不容错扩张」的语义要保留。

## 依赖 Pi 全局 app-store / Electron IPC，移植时必须替换的部分

- **zustand `useAppStore` 切片**（三簇共读约 20 个）：`sessions`、`sessionMeta`、`openProjects`、`workspace`、
  `runningSessions`、`refreshSessions`、`selectSession`、`newSession`、`setPage`、`setSettingsTab`、`setSettingsAnchor`、
  `showToast`、`navigateTranscript`、`settings.developerMode`、`settings.contextUsageDisplay`、`settings.keybindings`、
  `settings.fontScale/fontSize/fontFamily`、`activeSessionId`、`selectingSessionId`、`messages`、`retainedTranscripts`、
  `sessionHistory`、`transcriptViews`、`sessionCompactions`、`providers`、`providerModels`、`latestTurnResults`、
  `pendingPlans`、`agentStatuses`、`queuedPrompts`、`pendingAsks`、`planCheckpoints`、`pluginThemes`、`plugins`。
- **`api.*` IPC（`window.piDesktop.invoke/.on`）**：`api.searchSessions`（`IPC.invoke.sessionSearch`）、
  `api.getSearchContext`（`IPC.invoke.sessionSearchContext`）、`api.searchCommands`（`IPC.invoke.commandPaletteSearch`）、
  `api.executeCommand`、`api.getSession`、`api.onMenuCommand`、`api.onSessionsChanged`、`api.onAgentEvent`、
  `api.onSettingsChanged`、`api.onPluginChanged`、`api.setNotificationViewingSession`、`api.menuRendererReady`、
  `api.nativeMenuAction`、`api.togglePluginLauncher`、`api.setWindowBackgroundColor`、`api.setWorkPanelReservation`。
  返回值统一是 `Result<T>` 信封（`{ok:true,data} | {ok:false,error:{message,code,details}}`），
  `invoke()` 失败时抛 `Error` 并挂 `error.code`/`error.details`。
- **Electron 专有、必须替换**：context-isolation preload 桥（`window.piDesktop.invoke/on/channels/platform`）；
  `window.piDesktop.platform` —— 它决定 `Mod` 映射到 Meta 还是 Ctrl（`keybindingFromEvent`），
  pywebview 必须提供等价的平台事实；原生菜单 / 托盘命令（`openSearch`、`openCommandPalette`、`newTask`、`toggleSidebar`）；
  `app-region: drag` / `-webkit-app-region` 拖拽带（标题栏、聊天宽度手柄）；原生 `WebContentsView`（工作面板/浏览器视图）；
  `api.setWindowBackgroundColor` 的 macOS 玻璃/vibrancy 语义；`@electron/remote` 类能力（无）。
- **非 Electron 但同样不可直接搬运的依赖**：
  - `react-i18next` 的全量 key（本规格里所有 `chat.*` / `search.*` / `nav.*` 文案都只是 key）；
  - `@pi-desktop/shared` 的 `formatCompactTokenCount`、`messageContentFacts`、`dedupeSessionMessages`、
    `mergeLiveSessionMessages`、`upsertLiveSessionMessage`、`effectiveContextWindow`、`modelWireIdsEqual`、
    `KEYBOARD_SHORTCUTS` / `resolveKeybinding` / `keybindingDisplayParts` / `keybindingMatchesEvent`；
  - `getTranscriptProjection` / `getSessionMessageSnapshot` 的 `WeakMap` 缓存（**按数组 identity 命中**）：
    桥接层若每次轮询都重新序列化消息数组，这些缓存每帧失效，长会话会退化成全量重建；
  - `models.dev` 目录快照（`apps/desktop/resources/models.dev/api.json`，5.28 MB）与
    `settings-operation-metadata.json`（62 KB）等静态资源；
  - `--composer-dock-height`、`--minimap-marker-count`、`--chat-content-max-width`（760px）、
    `--chat-prose-max-width`（720px）、`--ds-toolbar-height`（46px）以及全套 `--ds-*` 设计令牌（`styles/tokens.css`）。
