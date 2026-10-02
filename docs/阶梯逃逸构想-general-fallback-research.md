# 通用“阶梯逃逸”设计调研

调研日期：2026-09-30。本文扩展此前语音前端调研，涵盖通用 Agent、对话系统、RAG、模型网关和传统服务可靠性。本文是研究记录，不是已批准的实施方案；未安装框架、修改产品代码或调用用户的云端模型。

## 用户目标和已有约束

专用前端在工具或本地脚本失败时，应能逐步改用其他方法，继续完成用户任务。用户希望避免重复造轮子，在比较现成设计后再作决定。

用户指定：启用回复／上下文限制时，转入更自由的分析模式需要用户选择；未启用时，可以允许自动转入。自动转入不等于无限执行，也不能解释为自动取消用户的其他明确限制。

## 结论

最相关的通用术语是 graceful degradation、fallback chain、bounded recovery、stall detection、handoff 和 circuit breaker。它们覆盖不同层次：服务是否可用、任务有没有进展、当前策略是否适合、是否需要用户参与。

现成框架已经提供大部分流程组件。当前仍需定义的是 Praat 任务的失败分类、证据是否足够，以及各模式允许哪些工具、输入和输出。未发现检查过的项目直接提供完整的“逐级放松专用前端约束直到普通聊天”成品。

## 重点参考

| 项目／来源 | 已有机制 | 可借鉴部分 | 边界 |
|---|---|---|---|
| AWS Agentic AI Lens | 按顺序尝试等效备用 Agent、简化 Agent、缓存结果、失败响应 | 为每一级明确能力损失；永久失败可以直接跳级 | 架构指导，非可直接装入前端的组件 |
| Microsoft Magentic / Magentic-One | 检查任务进展和循环；连续停滞后重新规划；限制轮数、停滞和重置次数；可选人工审阅 | 识别“没有报错，但一直绕圈” | 多 Agent 实现较重；进展判断也使用模型，需辅以程序计数 |
| Rasa Two-Stage Fallback | 确认意图、请求重述、最终 fallback／转交；恢复时撤销澄清过程对策略状态的影响 | 多阶段用户选择，以及恢复前清理失败过程 | 引用的是 Rasa Open Source 历史文档，原场景是 NLU 低置信度 |
| Haystack ConditionalRouter | 文档无法回答时转入网页检索，使用另一个提示词和生成分支 | 改换知识来源和执行分支，无需一直修补原提示词 | 示例用 `no_answer` 文本判断；我们的失败路由宜采用结构化状态 |
| Vercel AI SDK | `prepareStep` 可改变模型、消息和可用工具；`stopWhen` 控制停止；工具调用可修复 | 逐阶段替换配置和上下文，最终进入答复阶段 | TypeScript；不是安装后自动得到业务降级阶梯 |
| Pydantic AI | `FallbackModel` 支持模型顺序切换；可检查响应中的截断／原生工具失败 | 除 HTTP 错误外，也识别返回内容的失败 | 响应触发的 fallback 当前仅非流式；参数验证重试与模型 fallback 分开 |
| LangChain Runnable fallbacks | 失败后顺序执行其他完整 Runnable，可按异常分类 | 可以替换整个“提示词＋模型＋解析器”流程 | 更换完整流程是应用配置；接口本身不规定怎么放松约束 |
| LiteLLM | 同组部署重试、跨组模型 fallback、上下文超限专用路由、冷却 | 处理模型服务层失败 | 不解决 Praat 脚本故障、任务停滞和报告证据不足 |
| Polly | Retry、Timeout、Circuit Breaker、Fallback 可组合 | 区分重试同一操作与切换备用操作；熔断持续失败依赖 | .NET 通用可靠性库，主要借鉴机制 |

## 官方来源

1. AWS，有序 fallback chain 与透明降级：
   https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/agentrel04-bp03.html
2. Microsoft Agent Framework，Magentic 停滞检测、重规划和计划审阅：
   https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/magentic
   原始 Magentic-One 架构：
   https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/magentic-one.html
3. Rasa Open Source，多阶段 fallback、状态撤销和人工转交：
   https://legacy-docs-oss.rasa.com/docs/rasa/fallback-handoff/
4. Haystack，可运行的 RAG → Websearch 分支示例：
   https://haystack.deepset.ai/tutorials/36_building_fallbacks_with_conditional_routing
5. Vercel AI SDK，步骤配置、消息整理和工具选择：
   https://ai-sdk.dev/docs/agents/loop-control
   工具调用、错误与修复：
   https://ai-sdk.dev/docs/ai-sdk-core/tools-and-tool-calling
6. Pydantic AI，异常和响应触发的模型 fallback：
   https://pydantic.dev/docs/ai/models/overview/
7. LangChain，完整 Runnable 的有序 fallback API：
   https://reference.langchain.com/python/langchain-core/runnables/base/Runnable/with_fallbacks
   注：搜索返回了接口文档正文，后续直接打开曾失败；没有据此宣称验证运行效果。
8. LiteLLM，部署和模型路由：
   https://docs.litellm.ai/docs/routing
   https://docs.litellm.ai/docs/proxy/reliability
9. Polly，组合重试与 fallback，以及熔断状态：
   https://www.pollydocs.org/strategies/fallback.html
   https://www.pollydocs.org/strategies/circuit-breaker.html
10. Salesforce，降级放在编排层的架构指导：
   https://architect.salesforce.com/docs/architect/well-architected/guide/agentic-enterprise-operational-excellence.html

本次依据主要是官方文档、API 定义和其中的代码示例。没有实际部署或运行这些框架，不能把文档支持等同于已经验证与当前 Praat 前端兼容。

## 对本项目的设计启发（推论，尚未决定）

### 1. 以模式切换表达“放松”

与其在原对话中不断追加“忽略前面的要求”，可定义几套明确配置：

- 专用执行：严格工具参数、固定测量流程、结构化执行结果。
- 有限修复：只修正可修复的调用错误，修复次数受限。
- 简化分析：禁用失败工具，允许用成功取得的部分证据回答。
- 通用分析：允许直接分析原始材料，必要时路由到相应模态模型。
- 完整收尾：输出可支持的结论、缺失项和下一步；或者在需要时等待用户。

以上是基于来源的应用设计建议，并非某一个现有产品已经提供的原样阶梯。报告中的事实、推测和缺失证据仍应区分；用户明确设定的限制不能自行消失。

### 2. 不要求每次从第一层顺序走到底

临时网络错误适合有限重试；工具参数错误适合有限修正；不存在的依赖或不支持的输入适合直接改道。重复调用没有增加证据也应触发恢复，不能只依赖异常。

### 3. 同一请求只朝可完成的状态推进

建议在同一请求内对失败工具设置熔断，不允许模式切换后再次无条件回到原失败分支。保留已完成工作的摘要和证据，使用新的报告上下文。收尾预算独立保留，达到执行上限不等于结束用户答复。

### 4. 将用户选择放在模式改变处

启用回复／上下文限制：显示已有结果、失败原因、下一模式会增加的输入／能力及可能消耗，等待用户选择。未启用：可自动进入事先配置的下一模式，并显示切换原因。两者仍受总执行预算约束。

### 5. 组件优先级仍需比较

最有价值的机制组合是 AWS 的有序降级、Magentic 的无进展检测、Vercel 的步骤配置，以及 Rasa 的状态恢复和选择交互。Python 落地候选包括此前的 LangGraph 与本次的 Pydantic AI／LangChain；是否引入整个框架，要继续比较改造范围和维护成本。不能因为机制来自四个项目就安装四套框架。

## 与前一轮调研的关系

LibreChat 和 Open WebUI 仍可作为聊天 UI／附件和交互参考；Dify 与 LangGraph 仍是执行流程候选。扩大范围后，判断标准应先看能否识别停滞、替换策略、保存有效状态并完整收尾，再看是否已有音频功能。

当前配置模型的音频能力问题仍有效，见 `2026-09-30-ai-fallback-research.md`。音频只是通用分析模式的一种输入；本次研究不把恢复机制绑定在语音任务上。
