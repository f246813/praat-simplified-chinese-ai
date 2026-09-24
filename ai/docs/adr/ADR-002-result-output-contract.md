# ADR-002: 脚本结果写中文结果行，而且不许静默丢输出

**日期：** 2026-09-20
**状态：** Accepted

## 背景

脚本跑完要把结果交回对话窗口。`appendInfoLine` / `writeInfoLine` / `print` / `echo`
这些命令在 GUI 版 Praat 里都会走 `gui_information()`，把「Praat Info」窗口顶到
前面——这就是用户报的弹窗 bug。而 Praat 也不给脚本提供 stdout（那是 `--run`
批处理的待遇）。

## 决策

1. 脚本把结果**逐行**写进 `ai/runtime/chat_result.tsv`（`appendFileLine`），最后再写一行
   完成标记到 `chat_state.txt`；前端只把结果行原样显示在对话窗口里，不做结构化解析
   （要给人看的是中文句子，不是表格）。
2. 自定义脚本里会弹 Info 窗口的输出命令，一律**改写成写结果文件**，内容一句不丢
   （`tools.neutralize_info_commands`）：
   - 带值列表的 `appendInfoLine` / `writeInfoLine` / `appendInfo` / `writeInfo` →
     `appendFileLine`，参数原样带过去；
   - `printline` / `print` / `echo` 在 Praat 里写的是这一行剩下的**字面文字**
     （`sys/praat_script.cpp` 里直接 `MelderInfo_write(command + n)`），所以整段抄成
     一个字符串参数；
   - 只有 `printtab`（只写一个制表符）和 `clearinfo`（只清空 Info 窗口）没有内容
     可保留，改成注释并说明。
3. 工具模板自己的结果行也都是 `appendFileLine`，并且带上「已按对象时长截断」「按编辑器
   圈选」这类出处说明（`guide.md` §8.4）。

## 备选方案

| 方案 | 为什么不选 |
| --- | --- |
| 让脚本照旧写 Info，前端去读 Info 窗口 | 会弹窗（用户报的 bug），而且没有稳定 API 去读 |
| 把会弹窗的命令注释掉 | 用户的诉求是「模型想告诉我的那句话」，注释掉就是静默丢内容（旧版本 `print` / `echo` 就是这么丢的） |
| `KEY: value` 结构化结果（PraatPlugin ADR-006 的做法） | 他们的界面是结果表格，我们的界面是对话；对聊天来说「已读入文件：Sound x（路径）」这样的中文行更合适。需要结构化时再另开一条通道 |
| 用 `--run` 批处理读 stdout | 批处理看不到 live 对象列表，只能做离线计算（见 ADR-001） |

## 后果

**好处**

- 用户看到的与模型想输出的一致；`print` / `echo` 不再凭空消失。
- 真机守着这条约定：`ai/tests/verify_chat_templates.py` 的
  `custom_script-info-rewrite`、`custom_script-literal-output` 两个用例。

**代价与风险**

- `writeInfo` 的「先清空再写」语义变成追加（Praat 没有「不换行追加到文件」的命令，
  忠实还原做不到）；对结果文件没有影响，因为每次请求前都会先删掉它。
- `print` / `echo` 后面的文字如果在 Praat 里本来会被变量插值，改写后拿到的是字面
  文字；实测这几条命令本来就是按字面写的。

## 相关

- 代码：`ai/praat_ai/tools.py`（`neutralize_info_commands`）、`ai/praat_ai/chat.py`
- 单测：`ai/tests/test_chat_tools.py`
