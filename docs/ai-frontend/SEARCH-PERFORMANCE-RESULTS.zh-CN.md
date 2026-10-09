# 搜索数据流与算法来源

侧栏标题在本地匹配；正文通过 `sessions.search` 搜索现有 SQLite，仅返回命中会话 ID。未打开会话的完整消息与附件不为搜索加载。100ms 防抖和请求代次检查防止过期结果覆盖新查询。

会话内查找在已渲染正文中计算字面量匹配，导航复用结果与 CSS 高亮。未挂载历史需要展开后才能计数／高亮。持久正文搜索与渲染文本查找的范围不同。

| Codex 固定来源 | 当前适配 |
| --- | --- |
| `tui/src/task_mentions.rs` | `src/codex/useSessionSearch.ts` 防抖与代次 |
| `rollout/src/search.rs` | `modern_search.py` 字面量、大小写不敏感正文匹配，存储接 SQLite |
| `thread-store/src/local/search_threads.rs` | 紧凑命中会话结果 |
| `thread-store/src/local/thread_history/search.rs` | `src/codex/literal-matcher.ts` 双指针，偏移适配 DOM UTF-16 |

来源固定于 `ab45264919aaeb8a421cc156f1a5459ef9d60b72`，原件、Git blob 与 SHA-256 保存在 `ai/third_party/codex/upstream/search/`，Apache-2.0 说明见 [来源说明](FRONTEND-SOURCES.md)。

可复现检查为 `ai/tests/verify_search_performance.py`、`verify_search_performance_desktop.py`、`verify_search_source.py`。性能比较需同时记录夹具规模、序列化／桥接／渲染范围、请求数量与传输体积；固定夹具结果不构成端到端速度保证。
