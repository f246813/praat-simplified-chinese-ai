# ADR-006: 对象列表带上 Praat 的进程标记，省掉每条消息的刷新往返

**日期：** 2026-09-21
**状态：** Accepted

## 背景

对话窗口每处理一条消息，都要先送一条空脚本让 Praat 重写对象列表
（`chat.refresh_object_context`）：投递 + 等完成标记 = 一次完整往返；Praat 正被模态
窗口挡住时还要白等 25 秒。但这笔开销大多数时候是白花的：Praat 自己会在
「每条 app 消息之后」「用户改选中」「增删对象」时重写那个文件
（`sys/praat.cpp` 的三处 `PraatAiControl_refreshChatContext`），所以上一轮投递完
之后，文件本来就是新的。

难点是「我怎么知道这份文件是**现在这个** Praat 写的」：文件路径只有一个，
`%TEMP%` 里也没有能区分进程的东西；Praat 重启之后旧文件还在，拿着旧 id 去规划会
让脚本报「没有编号为 N」。

## 决策

让 Praat 在文件里报名字：`sys/PraatAiControl.cpp` 的 `writeChatContext()` 在末尾写
一行 `# praat-pid=<GetCurrentProcessId()>`（非 Windows 用 `getpid()`）。

前端 `chat.context_pid()` 解析这一行（`praat_ai.tools.parse_object_context` 会忽略
非数字开头的行，不受影响），`refresh_object_context()` 的判定变成：

| 情况 | 行为 |
| --- | --- |
| 文件在、标记 ∈ 正在跑的 Praat 进程号 | **一条消息都不发** |
| 文件缺失 / 标记对不上 / 对方不写标记 | 投一条空脚本刷新（老行为） |
| `force=True` | always 刷（验证脚本用） |
| `assume_fresh=True` 且文件在 | 也算新鲜（老版本 Praat 的捷径：这一轮之前投递过脚本，Praat 就会重写列表） |

## 备选方案

| 方案 | 为什么不选 |
| --- | --- |
| 继续每条消息都刷 | 白花一次往返，Praat 卡住时还要搭上 25 秒超时 |
| 只看文件的 mtime（比如「10 秒内写过就算新」） | 用户空闲一小时之后文件仍然是最新的（Praat 只在变化时写），会误判为旧而白刷；反过来 Praat 刚重启时旧文件也可能「很新」 |
| 查 Praat 进程的启动时间（wmic/PowerShell）再和 mtime 比 | 每次会话要多起一个进程、慢几百毫秒，还得解析时间格式；进程号标记一行就够 |
| 把对象列表换成「每次请求现问一次」（不用文件） | 那正是要省掉的那次往返 |

## 后果

**好处**

- 稳态下每条消息少一次投递 + 等待（实测 `verify_context_marker.py`：标记对上之后
  `refresh_object_context()` 不产生任何命令脚本文件）；
- Praat 重启、多实例、老版本 Praat 这些边界自动退回老行为，不会拿着旧 id 去规划。

**代价与风险**

- 对象列表文件是**所有 Praat 共用**的：同时开着第二个 Praat 时它会覆盖标记，前端
  按「标记对不上」处理（退回刷一次）——只是省不下那一趟，不会出错；
- C++ 改了三处（写标记 + `praatProcessId()` + 头文件），改了必须重编 Praat.exe；
- 第一版 `context_pid(text="")` 的默认参数写错了（解析空字符串，等于永远 ping），
  是 `verify_context_marker.py` 抓出来的——这类「默认参数走哪条路」的 bug 单测容易
  漏，所以补了 `test_default_argument_reads_the_context_file`。

## 相关

- 代码：`sys/PraatAiControl.cpp`（`writeChatContext` / `praatProcessId`）、
  `ai/praat_ai/chat.py`（`context_pid` / `context_belongs_to` /
  `refresh_object_context`）
- 单测／真机验证：`ai/tests/test_context_freshness.py`、
  `ai/tests/verify_context_marker.py`、`ai/tests/verify_chat_live.py`
- guide.md 对应章节：§8.10
