# 本地规划接口参考

`QwenClient` 使用 `tools.TOOL_PARAMETERS` 提供 JSON Schema，通过原生 `tool_calls` 取得工具名和参数。`PRAAT_AI_PLANNER` 支持 `auto`、`tools`、`json`；JSON 模式供不支持工具调用的服务使用。原生接口没有正文和工具调用时，`auto` 可尝试 JSON 接口；`tools` 模式直接报告错误。

一次规划可返回多个调用，`tools.plan_actions` 按 `MAX_ACTIONS_PER_REQUEST` 限制动作数量。正文中的可识别工具调用由 `parse_text_tool_calls` 解析。返回正文不含工具调用时作为回答。

`custom_script` 也是有 schema 的工具，执行前接受 Praat 脚本检查。`read_file` 表示读入文件，`save_sound` 表示另存声音，方向由工具定义区分。

本页描述本地 Qwen 规划器。API 阶段通过 Pydantic AI 的 Agent 和原生 Hooks 执行，详见 [Hooks 与守卫](../native-hooks.md)。工具 schema 约束参数形状，不能保证模型选对工具或实现用户目标。

相关实现：`qwen.py`、`tools.py`、`chat.py`。
