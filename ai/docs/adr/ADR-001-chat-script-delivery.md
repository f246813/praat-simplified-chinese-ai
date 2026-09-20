# ADR-001: 把脚本交给正在运行的 Praat，而且不碰它的任何窗口

**日期：** 2026-09-20
**状态：** Accepted

## 背景

对话窗口要把 Praat 脚本交给**用户正在用的那个 GUI Praat**（对象列表、编辑器圈选、
播放都在那个进程里）。可选通道有三种：

1. `Praat.exe --FULL-TRUST --send <脚本>`：Praat 自己写消息文件再通知已开的实例；
2. 自己写 `%APPDATA%\Praat\Message.txt` + 给目标窗口发 `WM_APP`；
3. `Praat.exe --run <脚本>` 批处理：起一个独立进程跑完就退。

用户报的现象（2026-09-20）：每发一条指令，「Praat Info」自己从任务栏弹出来，
声音编辑器跳到前面盖住对话窗口。真机取证后确认根因在第 1 条通道：Windows 上
`sys/praat.cpp` 的 `tryToSwitchToRunningPraat()` 会
`FindWindow("PraatChildWindow… Praat", NULL)`（拿到的是 z 序最上面那个子窗口，
实测就是 Info 或声音编辑器）然后 `ShowWindow(SW_RESTORE) + SetForegroundWindow`。
接收端（`motifEmulator.cpp` 的 `WM_APP` 分支）那两行激活代码本来就是注释掉的。

## 决策

用第 2 条通道（`ai/praat_ai/sendpraat.py`），并按下面的约定把它用对：

1. **消息自消费**：投递的消息第一句就把 `Message.txt` 覆写成空操作。因为
   `cb_userMessage()`（`sys/praat.cpp`）每收到一条 `WM_APP` 都重新读一次
   `Message.txt`，而 `praat_executeScript_noGUI()` 执行完并不删它——排队中的两条
   `WM_APP` 会让同一个脚本跑两遍（「删除」就删两次）。
2. **一请求一脚本文件**：`runtime/commands/chat_command_<编号>.praat`。`Message.txt`
   全局唯一，旧消息醒来时如果读到的还是那个共用文件名，执行的就会是**新写进去的
   脚本**；文件名分开之后，旧消息最多把它自己那条再跑一遍。
3. **请求编号**：脚本开头把自己的编号写进 `runtime/chat_started.txt`；等完成时对一下
   编号，就能认出「上一条超时指令刚刚才跑完」，把它的完成标记和结果一起丢掉，而不是
   当成本次结果（`chat._wait_for_result`）。
4. **超时兜底**：仍然调用 `sendpraat.cancel_pending()` 把消息文件换成空脚本。
5. `--send` 只在 `PRAAT_AI_SEND_MODE=argv` 时用于排障——那条路会激活窗口，而且
   Praat 被模态框挡住时 `--send` 会一直阻塞（实测 > 60 秒），所以它也必须用
   「后台 Popen + 轮询」，不能回到 `subprocess.run(timeout=60)`。

**补记（同一天）**：对象列表要在每条 app 消息之后重新导出。以前列表文件只在
「对象被创建/删除」或用户改选中时才重写，只写文件的空脚本两条都不占，于是前端会拿着
**上一个 Praat 实例**留下的旧列表去规划（挑一个不存在的 9 号对象 → Praat 弹英文错误框
→ 后面的消息全被挡住）。现在 `cb_userMessage()` 执行完消息后调用
`PraatAiControl_refreshChatContext(true)` 强制重写一次。

## 备选方案

| 方案 | 为什么不选 |
| --- | --- |
| `Praat.exe --send` | 会 `SW_RESTORE` + `SetForegroundWindow` 一个子窗口，正是用户报的 bug；被模态框挡住时还会一直阻塞 |
| 常驻 daemon / 命名管道 | 生命周期、协议版本、崩溃恢复都要自己管；单用户逐条同步的用法完全不需要 |
| `--run` 批处理作为主通道 | 看不见用户正在编辑的对象列表和圈选范围（我们要的恰恰是这个）；批处理下 `PraatAiControl_refreshChatContext()` 也直接返回 |
| 直接改 `tryToSwitchToRunningPraat()` 不再激活窗口 | 动的是 Praat 自己的命令行语义（`Praat.exe --send` 对所有用户都会变），影响面比前端自己投递大 |

## 后果

**好处**

- 发指令时 Praat 的窗口状态和前台焦点都不变（真机验证：`ai/tests/verify_chat_no_popup.py`，
  同一台机器上把窗口收进任务栏再发指令，窗口一个都没动；`--legacy` 反证老路径会把
  Info 窗口拽出来并抢走前台）。
- 省掉一次 `Praat.exe` 进程启动。
- 每个请求有编号，任何「谁执行的」都能对上账。

**代价与风险**

- `Message.txt` 是 Praat 硬编码的全局唯一文件名，同一时刻只能有一条指令在飞；
  前端逐条同步执行刚好满足，但**不能再并发投递**。
- Praat 里有没关掉的对话框时，消息会排在队列里（表现为超时），要提示用户关掉。
- 脚本自己失败时 Praat 仍会弹它自己的错误对话框（`Melder_flushError`），对话窗口
  读不到那些文字。
- `runtime/commands/` 会攒脚本文件：只删「数量超过 40 且超过一小时」的那些
  （`chat.prune_command_scripts`），因为 `Message.txt` 里可能还引用着最近几个。

## 相关

- 代码：`ai/praat_ai/sendpraat.py`、`ai/praat_ai/chat.py`
- 真机验证：`ai/tests/verify_chat_no_popup.py`、`ai/tests/test_sendpraat.py`
- 踩坑清单：`guide.md` §8.5
