# ADR-007: 等 Praat、等批处理都可以取消

**日期：** 2026-09-21
**状态：** Accepted

## 背景

点「发送」之后前端只能干等：`chat._wait_for_result()` 每 0.15 秒轮询完成标记，最多
等 `EXECUTION_TIMEOUT_SEC = 25` 秒；`external_script.run_batch()` 更狠，直接
`subprocess.run(timeout=…)`——跑一个自己循环很久（或者自己弹了对话框）的社区脚本时，
用户没有任何办法停下来。实测：一个 4000 万次空循环的脚本要跑 9 秒左右，除了关窗口
没别的选择。

## 决策

给「等待」一个统一的取消标记（`threading.Event`），对话窗口加一个「停止」按钮：

1. `ChatWindow.cancel_event` 由 `cancel_turn()` 置上，按钮在空闲时禁用、处理请求时
   可用；
2. `chat._send_script(..., cancel=…)` → `_wait_for_result(cancel=…)`：轮询里看到标记
   就立刻返回 `(False, "已取消：不再等这一条的结果…")`，并调用
   `sendpraat.cancel_pending()` 把排队中的 `WM_APP` 换成空脚本（不这么做的話，
   那条消息以后醒来会执行**下一条**指令的脚本）；
3. `_run_agent_turn(..., cancel=…)`：每一轮规划之前、每个动作之前都看标记，置上就
   不再规划/执行，`TurnOutcome.reply` 直接是「已取消…」；
4. `tools.LocalEnvironment.cancelled`（`ChatWindow` 传 `self.cancel_event.is_set`）
   → `external_script.run_batch(..., cancelled=…)`：批处理改成 `Popen` + 每 0.2 秒
   `communicate(timeout=0.2)`，取消就 `terminate()`（超时则 `kill()`）。

语义写清楚（也写进 guide 和工具说明）：取消是「**不再等**」，不是「把 Praat 里正在
跑的脚本停下来」（Praat 没给外部程序这种能力）。脚本可能已经跑完，也可能还没被
Praat 取走（消息已被换成空脚本）——所以结果文件里可能还有它的输出。

## 备选方案

| 方案 | 为什么不选 |
| --- | --- |
| 只把超时从 25 秒调小 | 治不了「等 9 秒的批处理」，还让正常但稍慢的脚本更容易误判失败 |
| 用线程 interrupt / 强制结束 Praat | Praat 是用户的进程，脚本可能正在写文件；杀进程是破坏性操作 |
| 让 Praat 自己支持「取消正在跑的脚本」 | 要改 Praat 的脚本执行器（大手术），而且脚本是同步跑在 UI 线程上的 |
| 取消时不管排队中的 WM_APP | 实测过：那条消息以后醒来会执行**下一条**指令的脚本（见 §8.5 的自消费机制），必须一起换成空脚本 |

## 后果

**好处**

- 用户随时能停：取消等结果实测 0.00 秒返回；取消一个 9 秒的批处理实测 0.83 秒；
- 取消之后管道还是干净的（`verify_cancel_live.py` 第 2 条专门验「取消之后还能继续
  投递」）；
- 多轮循环不会「取消了一半又自己规划下一步」。

**代价与风险**

- 「已取消」和「超时」是两种失败，提示文案要分开写，别让用户以为脚本一定没跑；
- 批处理从 `subprocess.run` 改成 `Popen` + 轮询，要自己处理
  `terminate`→`kill`→`wait` 的收尾（`_stop_process()`）；
- 取消标记是**每个窗口一个**的，多个对话窗口各停各的（符合预期）。

## 相关

- 代码：`ai/praat_ai/chat.py`（`cancel_turn` / `_wait_for_result` /
  `_run_agent_turn`）、`ai/praat_ai/tools.py`（`LocalEnvironment.cancelled`）、
  `ai/praat_ai/external_script.py`（`run_batch` / `_stop_process`）
- 单测／真机验证：`ai/tests/test_cancel.py`、`ai/tests/verify_cancel_live.py`、
  `ai/tests/verify_chat_window_ui.py`
- guide.md 对应章节：§8.12
