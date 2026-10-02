# Praat AI 前端失败降级与音频输入调研

调研日期：2026-09-30。本文为候选方案调研，不是已批准的实现规格。没有安装框架、修改前端或发送用户音频。

用户偏好：启用回复／上下文限制时，转入音频分析前由用户选择；未启用限制时，可以自动转入。自动转入仍需满足音频模型可用等实际条件。

## 调研结论

已找到可复用的失败路由、暂停恢复、工具限额、音频消息适配机制。此次检查的项目中，没有发现开箱即用的“Praat 脚本失败后，按 token 限制决定人工或自动转入音频报告”的完整方案。

最接近的组合是：LangGraph 的失败恢复和条件暂停，Dify 的独立失败分支，以及 LibreChat 的原始音频输入适配。Open WebUI 可参考前端交互，但单纯设置循环上限不能完成报告降级。

## 1. LangGraph / LangChain：优先评估执行层复用

官方 Graph API 支持节点重试策略；重试耗尽后，error_handler 接收状态及错误，通过 Command(goto=...) 转入恢复分支。文档标明节点级 error_handler 需要 langgraph >= 1.2。

interrupt() 可按应用条件暂停、保存状态、等待输入；Command(resume=...) 用于恢复。这与“有限额时询问、无有限额时自动继续”相符。

LangChain 另有 ToolRetryMiddleware、ToolCallLimitMiddleware、ModelCallLimitMiddleware。ToolCallLimitMiddleware 的 continue 行为仍由模型决定何时结束，不应误认为它自动实现报告降级；需要显式恢复路径。

适用方式：保留 Praat 的工具构建器和桥接，将工具阶段、用户选择和报告阶段组织为独立节点。是否引入依赖，需要进一步比较集成成本与长期维护收益。现有 requirements.txt 只包含 numpy、Pillow、parselmouth，没有 LangGraph。

特别注意：interrupt 恢复时会重新运行所在节点开头。已执行的 Praat 操作应与等待用户的节点分开，保留请求编号与去重机制，避免恢复触发重复操作。

来源：

- [Graph API：错误处理与恢复路由](https://docs.langchain.com/oss/python/langgraph/use-graph-api#handle-node-errors)
- [Interrupts：条件暂停与恢复](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [工具限额 API](https://reference.langchain.com/python/langchain/agents/middleware/tool_call_limit/ToolCallLimitMiddleware)
- [工具重试 API](https://reference.langchain.com/python/langchain/agents/middleware/tool_retry/ToolRetryMiddleware)

## 2. Dify：独立失败分支的清楚范例

官方文档规定，LLM、HTTP、Code 和 Tool 节点失败后可以停止、采用默认值，或进入 Fail Branch。失败分支可尝试替代方法、备用服务和记录错误。

适用方式：借鉴“测量失败是一个可路由的状态”的设计，将报告／音频分析设为明确分支。不要不断给原失败会话追加“再试一次”和更宽松提示。

Dify 是完整应用平台。对于当前 Windows / Tkinter / Praat 结构，直接迁移是否合算尚未评估；参考其流程设计与整个平台替换是不同选择。该文档不能证明所有 Agent 节点都有相同自动恢复能力。

- [Dify：Handle Errors](https://docs.dify.ai/en/cloud/use-dify/build/predefined-error-handling-logic)

## 3. LibreChat：原始音频输入的实际代码

已检查主仓库 packages/api/src/files/encode/audio.ts 的实际实现：

- Google / Vertex 使用媒体内容块；
- OpenRouter 和显式配置了音频支持的兼容端点使用 input_audio；
- 先验证音频，并确定正确格式；
- 区分真正的音频消息与普通附件元数据。

该路径发送原始音频，不是先转写再让文字模型阅读。可以参考其媒体能力检测、格式校验及各供应商适配，不必自行从零设计音频附件协议。

限制：这些代码解决传输与前端接入，不保证专业发音诊断质量，也没有直接实现本项目的阶梯降级政策。前端和后端以 TypeScript 为主，不能直接把文件拷入当前 Python 项目使用。

- [LibreChat 音频编码源码](https://github.com/LibreChat-AI/LibreChat/blob/main/packages/api/src/files/encode/audio.ts)
- [已合并的音视频上传 PR](https://github.com/LibreChat-AI/LibreChat/pull/11070)

## 4. Open WebUI：交互可借鉴，循环上限不能替代恢复流程

Events 支持状态更新，以及需要用户响应的 confirmation / input / select。可参考失败后在聊天中呈现可选择的继续方式。

其 CHAT_RESPONSE_MAX_TOOL_CALL_ITERATIONS 限制工具规划轮次；成功和失败都计数，达到上限显示错误。仅照搬这个上限，仍不会自动转为完整语音报告。

官方 Audio 页面主要描述 STT / TTS，不能据此认定所有上传音频都会原样交给音频理解模型。原生音频分析应核对实际供应商消息路径。

- [交互事件](https://docs.openwebui.com/features/extensibility/plugin/development/events/)
- [工具循环配置](https://docs.openwebui.com/reference/env-configuration/)
- [Audio 功能范围](https://docs.openwebui.com/features/chat-conversations/audio/)

## 当前供应商的能力约束

阿里云官方 qwen3.7-flash 模型页将输入列为 Image / Text / Video，未列音频。官方 Qwen-Omni 文档支持音频理解，并提供文本分析接口。

因此，当前模型不能仅靠放松提示词变成直接听音频的模型。需要单独配置音频分析模型、检查服务地域和能力，并使用相应输入格式。音频路由也不能盲目继承文字模型的所有请求参数。

- [qwen3.7-flash 模型能力](https://help.aliyun.com/zh/model-studio/qwen3-7-flash)
- [Qwen-Omni 音频理解](https://help.aliyun.com/zh/model-studio/qwen-omni)

## 初步推荐，尚未作最终实现选择

优先评估 LangGraph 作为恢复流程的执行组件，保留当前 Praat 操作桥接；使用 Dify 的失败分支模式作为流程参考；使用 LibreChat 的音频适配作为供应商接入参考。

完整迁移到 LibreChat / Open WebUI 也应列为备选，尤其当用户希望以后主要使用通用聊天界面、文件上传和多模型功能时。但需另行评估部署、Windows 本地 Praat 接入、数据保存和界面迁移成本。

需要补充的业务逻辑仅包括：错误分类与无进展判断、成功测量证据整理、有限额时用户选择的路由，以及 Praat 目标片段的可靠导出。现有项目已经有 extract_part、save_sound 等能力，可评估复用。

后续决策应比较“保留当前界面、复用执行框架”和“使用成熟聊天前端、将 Praat 作为工具后端”两条路径；在此之前不继续实现自制阶梯机制。
