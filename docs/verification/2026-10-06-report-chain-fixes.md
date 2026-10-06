# 2026-10-06 云端报告链路修复验收

基于任务 `5f171257690a44a0b48d6fc24bd28e82` 的 VOT 证据、包装超时和草稿遮罩案例。读取用户 SQLite 均使用 `mode=ro`；测试使用私有临时库、FunctionModel 和本地 HTTP 服务，无真实云端调用、Praat 投递或操作重放。

## 修改文件与行为

- `ai/praat_ai/report_guards.py`：对象目标解析和编号豁免共用模式，支持 `ID: 1`、`id：1`、`object: 1`，只接受快照或证据中已有的编号；未知编号仍走 `report.object_unknown`，普通无单位数字仍需核对。数值匹配器返回失败位置，救援按完整数值和单位遮罩，保留同值的合法测量、对象编号、小数、科学记数、证据引用与标签；定位不重复计守卫次数。
- `ai/praat_ai/cloud_agent.py`：沿显式异常原因链识别 OpenAI `APIConnectionError`／`APITimeoutError`，永久 HTTP 错误和单纯包含超时字样的消息不触发传输重试。通过公开 `message_history` 重开 SDK run 恢复待完成请求，避免重复提示与重复进入流式节点；单个待完成请求最多一次传输重试，沿用总预算、取消、已显示文本和原工具投递约束，报告修正仍最多一次。`AsyncOpenAI(max_retries=0)` 保留并注明应用负责重试。拒绝值随当前草稿更新，正文与 coverage 的救援只遮失败位置；失败草稿的 `report_verified` 为 false。
- `ai/praat_ai/modern_app.py`：取消发生在执行器返回与持久化之间时，明确将可见消息的 `formal` 设为 false。
- `ai/tests/test_report_guards.py`：增加已知／未知编号、普通无单位数字和真实 VOT 案例。
- `ai/tests/test_report_chain_regressions.py`：15 项离线回归，覆盖包装超时／连接失败、永久错误、预算／取消、流式已显示文本、无重复提示／工具执行、报告修正上限、数值遮罩和私有库正式历史排除。

七项报告闸门、七项自动修、逃逸阶梯、原目标绑定、投递事实、阶段隔离及缓存结构保持原有职责。配置仍为 qwen3.7-flash、high、120 秒；未改 SDK 或模型配置。

## 验证

先运行新案例形成失败回归，再改实现。日志：

- `_diag/report-chain-red.log`：原实现下重现编号、包装超时、遮罩和跨草稿问题。
- `_diag/report-chain-cancel-red.log`：原持久化路径把取消消息保存为 `formal=True` 的失败回归。
- `_diag/report-chain-required.log`：最终 **212 项全部通过**。

最终命令（仅测试子进程的 NO_PROXY 使用 `127.0.0.1,localhost`，避开既有 `[::1]` 解析问题）：

```powershell
$env:PYTHONPATH='ai;ai/tests'
$env:NO_PROXY='127.0.0.1,localhost'
& 'C:/Users/f2468/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe' -X utf8 -m unittest test_report_chain_regressions test_phase_context test_cloud_protocol test_dialogue_protocol test_cloud_escape test_report_guards test_tool_guards test_delivery_state test_dialogue_stream test_cancel test_report test_modern_execution test_modern_app -q
```

已按 `.agents/skills/aipraat-prompt-cache/SKILL.md` 检查 cloud_agent、session_context、cloud_metrics 和阶段回归。三轮 dialogue／planner／report 的最终 HTTP 前缀与静态声明保持稳定，重试请求没有重复目标或 RetryPromptPart；用量归一化、缺失缓存计数为 null、总预算和完整工具事务的现有测试通过。没有做真实云端缓存 A/B，也不据此声称延迟或费用降低。

扩大验证时运行了 231 项，230 通过、1 项既有失败：`test_staircase_review_fixes.ReviewFixTests.test_general_continue_preflight_matches_actual_dialogue_context`。用修改前备份在独立进程中复跑仍失败：其 4096 token 夹具在请求前被“最小报告上下文与输出预留无法容纳”挡下，模型请求数为 0。该项涉及旧上下文预算夹具，本轮未改阶段设计或预算以使其通过。详见 `_diag/report-chain-related.log`。

## 后端加载与用户状态

确认无 running／queued／cancelling 消息后，通过 `desktop_launch.close_desktop()` 正常 WM_CLOSE 和 `start_ai_chat.main()` 支持入口加载最终代码，未强杀进程。

最终后端 PID **5408**，启动于 **2026-10-06 14:50:54（Asia/Shanghai）**，`frontend-ready.json` 为 `react-connected`／`ModernExecutor`，启动晚于全部三个实现文件的修改时间。Praat PID **3056** 及其进程身份保持不变。最终重启前后 36 条消息、18 条证据、4 条模型事件的逐表 SHA-256 相同；原有会话 ID 全部保留。启动入口每次自动创建一个空会话，这是现有前端启动行为，本轮两次正常加载均未写入分析消息或重放任务。

加载证据：`_diag/report-chain-backend.json`。实现备份与可审阅 diff：`backups/report-chain-20261006/`。
