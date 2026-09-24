# 对话前端的架构决策记录（ADR）

`guide.md` §8 记的是「哪里容易踩坑」，这里记的是「为什么这么做、当时还考虑过什么」。
一条决策一个文件，改主意就新写一条并把旧的标成 Superseded，不要直接改旧结论。

| ADR | 主题 | 状态 |
| --- | --- | --- |
| [ADR-001](ADR-001-chat-script-delivery.md) | 把脚本交给正在运行的 Praat：不激活窗口、消息自消费、一请求一文件 | Accepted |
| [ADR-002](ADR-002-result-output-contract.md) | 结果怎么回到对话窗口：中文结果行 + 不静默丢输出 | Accepted |
| [ADR-003](ADR-003-planning-interface.md) | 用原生 function calling 选工具，JSON 提示词只作兜底 | Accepted |
| [ADR-004](ADR-004-agent-loop.md) | 一轮请求 = 规划 → 执行 → 回灌结果 → 再规划（有界） | Accepted |
| [ADR-005](ADR-005-table-driven-measurements.md) | 声学测量表驱动（`measures.tsv`），一次生成工具/插件/用例 | Accepted |
| [ADR-006](ADR-006-context-process-marker.md) | 对象列表写进程标记，省掉每条消息的刷新往返（C5） | Accepted |
| [ADR-007](ADR-007-cancellable-waits.md) | 等 Praat、等批处理都可以取消（C7） | Accepted |
| [ADR-008](ADR-008-context-token-budget.md) | 上下文按 token 预算裁，裁剪要看得见（A5） | Accepted |
| [ADR-009](ADR-009-cloud-api-backend.md) | 前端可以接云端大模型：`api` 节 + API key + 请求形状分叉 | Accepted |

写新 ADR 时照 [template.md](template.md) 的结构写。
