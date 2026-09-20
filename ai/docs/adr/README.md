# 对话前端的架构决策记录（ADR）

`guide.md` §8 记的是「哪里容易踩坑」，这里记的是「为什么这么做、当时还考虑过什么」。
一条决策一个文件，改主意就新写一条并把旧的标成 Superseded，不要直接改旧结论。

| ADR | 主题 | 状态 |
| --- | --- | --- |
| [ADR-001](ADR-001-chat-script-delivery.md) | 把脚本交给正在运行的 Praat：不激活窗口、消息自消费、一请求一文件 | Accepted |
| [ADR-002](ADR-002-result-output-contract.md) | 结果怎么回到对话窗口：中文结果行 + 不静默丢输出 | Accepted |
| [ADR-003](ADR-003-planning-interface.md) | 用原生 function calling 选工具，JSON 提示词只作兜底 | Accepted |

写新 ADR 时照 [template.md](template.md) 的结构写。
