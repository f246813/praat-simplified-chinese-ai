# 本地循环与 API 阶段参考

本地 `chat.run_turn` 在规划、执行、回灌结果之间循环。默认 `MAX_AGENT_ROUNDS=3`、`MAX_AGENT_STEPS=5`，到上限后请求文字收尾。原生调用回灌 `role=tool` 与 `tool_call_id`；本地 llama-server 使用 `--jinja` 处理模型 chat 模板。

相同调用可跳过执行，工具错误作为观察返回模型。当前本地实现通过 `wants_second_step` 的关键词判定限制后续会改变对象的调用；这是一种实现启发式，不能完整理解多步骤意图。只读工具使用独立判定。

API 分析由 `cloud_agent.py` 管理工具、音频观察和报告阶段，共用每轮 12 次模型请求、20 次工具尝试，以及失败分支和停滞状态。专业工具、直接音频分析与普通讨论按任务分流。已有成功证据可复用；报告阶段不重放已完成操作。

投递成功、执行成功和目标完成分别记录。执行状态不明时停止后续投递，已有结果可用于说明进度和缺口。模型选工具的准确性仍依模型和任务而定。

相关实现：`chat.py`、`cloud_agent.py`、`escape_policy.py`、`modern_execution.py`。
