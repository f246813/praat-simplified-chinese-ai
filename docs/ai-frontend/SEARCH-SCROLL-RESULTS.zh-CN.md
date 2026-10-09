# 搜索修订与滚动保持

`src/codex/useSessionSearch.ts` 使用按 ID 排序的会话 ID、标题、更新时间与归档状态生成搜索修订。阅读位置、草稿、预览加载、分区排序及数组引用变化不触发新搜索；查询、会话增删、改名、持久正文更新与归档变化会更新结果。

效果是浏览正文命中列表时，未变化的历史读取不会清空命中行或重复调用宿主搜索。结果仍使用 Codex 100ms 防抖、请求代次检查和 SQLite 数据流，见 [搜索说明](SEARCH-PERFORMANCE-RESULTS.zh-CN.md)。

可复现检查入口为 `ai/tests/verify_search_scroll_desktop.py`；检查应记录初次请求、阅读／预览后的请求数、结果节点与滚动位置，并写入真实新消息核对修订变化。
