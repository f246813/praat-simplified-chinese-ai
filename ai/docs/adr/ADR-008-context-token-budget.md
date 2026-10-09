# 上下文预算与摘要参考

本地 Qwen 路径由 `qwen.history_budget` 扣除系统提示、工具 schema、用户消息、输出预留和安全余量。对象快照保留表头与当前选择，历史从最近向前保留完整后段；省略信息通过 notes 展示。token 计数是估算，不能保证恰好等于供应商计数。

API 使用 `session_context.PhaseContext` 保存各阶段原生消息历史和稳定前缀，任务材料、技能内容和新证据追加到尾部。工具与报告共用原目标、预算、失败分支及投递状态。

现代会话由 `modern_budget.py` 估算容量，必要时请求真实摘要并持久化；摘要失败或仍装不下时报告限制，保留既有上下文。可见上下文用量包含估算来源和已知窗口。关闭额外 token 限制仍受供应商窗口、工作量预算和应用内存保护约束。

缓存指标在 `cloud_metrics.py` 中按供应商计数语义归一化，缺失计数保留 null。缓存命中是运行观测，不能保证每次请求命中，也不能仅凭缓存覆盖率推断延迟。

相关实现：`qwen.py`、`chat.py`、`session_context.py`、`modern_budget.py`、`cloud_metrics.py`。
