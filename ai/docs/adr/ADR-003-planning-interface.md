# ADR-003: 用原生 function calling 选工具，JSON 提示词只作兜底

**日期：** 2026-09-20
**状态：** Accepted

## 背景

前端的规划层要把「用户的一句话」变成「哪个工具 + 哪些参数」。旧做法是把工具清单
和十几条格式规则写进系统提示词，要求模型只输出一个 JSON 对象
（`response_format: {"type":"json_object"}`）。模型（Qwen3.5-2B）得同时保证：
JSON 合法、工具名正确、参数名和类型都对。规则越攒越多（14 条），而
`guide.md` §8.4 早就写着「加工具比加提示词管用」。

## 决策

工具自带 **JSON Schema**（`tools.TOOL_PARAMETERS`），交给 llama-server 的原生
function calling（`tools=[…]`），读回来的 `tool_calls` 就是工具名 + 参数
（`qwen.QwenClient._plan_with_tools`）：

1. `PRAAT_AI_PLANNER=tools`（默认 `auto`）走这条路；`json` 保留旧的提示词接口，
   排障或换成不支持工具调用的服务端时用。
2. 提示词只剩业务规则（不列工具、不写 JSON 格式）；`custom_script` 也做成一个工具，
   参数的 JSON Schema 就是「一段 Praat 脚本」。
3. 一次响应可能带**多个** `tool_calls`（实测「0.25 秒和 0.75 秒的基频」会给两个
   `pitch` 调用）：按顺序拼成同一条脚本投递，最多 3 个动作
   （`tools.plan_actions`、`MAX_ACTIONS_PER_REQUEST`）。
4. 模型只回话不调工具时，那句话就是回答；既没有工具调用也没有正文时，`auto` 退回
   JSON 接口（`tools` 模式直接报错，不猜）。
5. 已登记的 schema 和 `Tool.signature` 由单测对拍，防止改了工具忘了改 schema。

## 取舍与证据

**实测（本机 llama-server，`--ctx-size 8192`，**没有** `--jinja`）**：

- 带 `tools` 的请求返回了原生 `tool_calls`（`{"name":"rename_object","arguments":"{\"new_name\":\"test\"}"}`），
  `reasoning_content` 单独成字段；
- `response_format: {"type":"json_schema","strict":true,…}` 的约束解码也生效（用于
  `custom_script` 那条兜底路）；
- 真机规划回归 `ai/tests/verify_chat_planning.py`（真实模型 + 真实 Praat）19/19 通过，
  切到原生工具调用之后不再有「模型自编脚本被安全检查拦下」的警告。

**代价**：工具集变化时要同步 schema（有单测）；`auto` 模式下首次「什么都没有」的响应
会多花一次往返（换服务端时建议直接设 `PRAAT_AI_PLANNER=json`）。

**踩过的坑**：换成工具调用时丢掉了旧提示词里的少样本示例，模型立刻把「读取 D:/in/a.wav」
理解成 `save_sound`（方向反了，而且还跑得"成功"）。修法不是补提示词，而是加工具：
`read_file`（`guide.md` §8.4 的同一条约定）。

## 备选方案

| 方案 | 为什么不选 |
| --- | --- |
| 继续用提示词 + `json_object` | 模型要自己保证格式和工具名，规则越堆越长；schema 能免费拿到类型/枚举/必填校验 |
| 直接用 `json_schema` 约束解码代替工具调用 | 也是好路子（实测可用），但工具调用是服务端和模型的既有协议，返回里还能带 `reasoning_content`；两者可以并存（兜底用前者） |
| 引入 Qwen-Agent 之类的框架 | 我们只需要它的三个模式（schema 传参、结果回灌、错误当观察），引入整套依赖（GUI/RAG/MCP/pydantic）不划算 |

## 相关

- 代码：`ai/praat_ai/qwen.py`、`ai/praat_ai/tools.py`、`ai/praat_ai/chat.py`
- 单测：`ai/tests/test_planner_tools.py`
- 真机：`ai/tests/verify_chat_planning.py`
