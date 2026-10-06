# 搜索来源与速度修复：2026-10-04

来源核对确认：上一轮只搬运了 Pi 的输入法事件放行与输入样式。侧栏的消息匹配、会话内查找的匹配算法是本项目写的，并非直接复制的搜索服务。

侧栏瓶颈已复现：等待 300ms 后，串行加载所有未打开会话，传输完整消息、工具活动和附件元数据，多次更新前端；每次查询又拼接正文过滤。新流程接入 Codex 宿主搜索，只返回命中会话 ID，不加载未打开的完整历史。标题在本地立即匹配，正文在既有 SQLite 内匹配；100ms 去抖与请求代数检查来自 Codex，过期响应不会覆盖新查询。归档过滤、旧记录只读搜索、未持久化的生成正文均有检查。

会话内查找也复现了重复扫描：点 5 次下一个匹配，旧版扫描全文 5 次。现在匹配由 Codex 线性双指针算法提供；上下一个只切换当前高亮，扫描次数为 0。Pi 的高亮与输入法处理、原有匹配计数和显示更早消息行为保留。

实际来源是 [openai/codex ab452649](https://github.com/openai/codex/tree/ab45264919aaeb8a421cc156f1a5459ef9d60b72)：

| 原文件 | 接入与适配 |
| --- | --- |
| `codex-rs/tui/src/task_mentions.rs` | `src/codex/useSessionSearch.ts`：100ms 去抖、请求代数检查、宿主匹配与标题合并 |
| `codex-rs/rollout/src/search.rs` | `modern_search.py`：转义、大小写不敏感字面量匹配，仅搜索用户／助手正文；JSONL/ripgrep 边界改接现有 SQLite |
| `codex-rs/thread-store/src/local/search_threads.rs` | `sessions.search`：返回命中记录，不向渲染器加载完整历史；按原分区、归档与排序展示 |
| `codex-rs/thread-store/src/local/thread_history/search.rs` | `src/codex/literal-matcher.ts`：`LiteralMatcher::find_ranges` 双指针算法，Rust 字节偏移适配为 DOM UTF-16 偏移 |

四份完整原文件未经修改保存并校验 Git blob／SHA-256；Apache-2.0 许可、原件和修改后的前端／宿主随生产资源分发。这里是 Rust → TypeScript／Python 的源码移植与存储接口拼接，不声称复制了未公开的 Codex 桌面 React 搜索组件。没有引入 Codex／Pi Agent 内核、额外搜索服务或新数据库索引。

隔离性能夹具含 500 个会话、6000 条消息。旧侧栏流程在宿主侧加载与序列化完整历史需 999.30ms、传输约 12.68MB；新搜索匹配中位数 194.40ms、返回 24 字节（命中一个会话），约快 5.14 倍。该对比不含桥接、React 渲染和旧版额外 300ms 等待，不能当作每台机器上的端到端速度保证。见 [性能记录](verification/search-performance-result.json)。

真实生产 pywebview／WebView2 使用同一隔离数据，输入到结果约 1086ms，包括去抖、RPC 和渲染。只发送 1 次搜索请求，搜索期间完整历史加载数为 0，输入焦点与无绿色边框保持。见 [桌面记录](verification/search-performance-desktop-result.json)。

验证：4 项新增宿主搜索检查、29 项既有宿主检查、9 项分区检查通过；27 项相关前端单元检查和 10 项 Edge 浏览器检查通过，涵盖输入法、匹配导航、过期响应、多选、预览和滑条。Unicode 小写扩展的 DOM 偏移越界由 Codex 匹配器一起修复。TypeScript 与生产构建通过。

复核：`ai/tests/verify_search_performance.py`、`verify_search_performance_desktop.py`、`verify_search_source.py`。生产资源已更新，重开现代 AI 前端加载。
