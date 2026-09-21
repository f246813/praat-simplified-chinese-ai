# AI 前端交接要点

给下一次接手 AI 纠音前端（对话窗口 + 工具模板 + 编辑器选区链路）的会话。
约定和坑的权威版本仍然是 [guide.md](../guide.md) §8，这里只写「接手时先看什么、
哪些东西不能碰坏」。

## 0. 现状与先跑一遍

- 分支 `modern`，工作区干净。本次改动已提交：`9b7afe6f`（C++ 上报编辑器选区）、
  `33db92b5`（AI 侧：VOT 两步检测 + 选区接入各工具 + 测试文档）。**未 push**。
  再往后还提交了投递方式的修改（`sendpraat.py`：自己写 `Message.txt` + 发
  `WM_APP`，不再用 `Praat.exe --send`，见 guide.md §8.5）。
- **远端与权限（约束，不是待办）**：`origin`（KasumiKitsune/praat-simplified-chinese）
  **只有读权限**——推不上去，除非那边给 `f246813` 加写权限（或改用有写权限的 token）。
  改动镜像在 `public` = f246813/praat-simplified-chinese-ai（默认分支 `modern`，
  `master` 也同步）。两条规矩：①不要把它列成「下一步」；②**更不要因为「推不了
  origin」就删掉这里记的任何内容**（用户明确要求保留这条权限说明）。
- 验证命令（必须用项目自带的 Python，PATH 里的 `python` 缺依赖）：

  ```powershell
  cd <仓库根目录>
  $env:PYTHONPATH='ai'; $env:PYTHONIOENCODING='utf-8'; $env:PYTHONDONTWRITEBYTECODE='1'
  & <venv>\Scripts\python.exe -m unittest discover -s ai/tests    # 185 个，约 53 秒
  & <venv>\Scripts\python.exe ai/tests/verify_chat_templates.py  # 43 个，真 Praat，约 4 秒
  & <venv>\Scripts\python.exe ai/tests/verify_chat_no_popup.py   # 真机：发指令不许动窗口
  ```

  第二种会反复启动 `Praat.exe`（每个用例一个新进程），会写 `ai/runtime/`；
  其余手动脚本（会真开 GUI、真重启模型）见 `ai/README.zh-CN.md`。
- PowerShell 没有 `head`/`sed`：用 `rg` + `Get-Content | Select-Object -Skip N -First M`。
- **提示词预算很紧**：本项目触发过 3 次 HTTP 433，planner 提示词
  （`ai/praat_ai/qwen.py`）每加一句都要付代价。新能力优先做成脚本层逻辑
  （模板、`*_build_*` 里的兜底），只有脚本层兜不住时才动提示词。选区和 VOT
  这两件事完全没动提示词。

## 1. 一条数据流：编辑器里拖出来的选区

```
foned/FunctionEditor.cpp:2060      FunctionEditor_selectionMarksChanged()
  → sys/PraatAiControl.cpp:432     PraatAiControl_noteEditorSelection()
  → sys/PraatAiControl.cpp:248     buildChatContext() 写 6 列
  → ai/runtime/chat_context.tsv    id / class / name / selected / sel_start / sel_end
  → ai/praat_ai/tools.py:211       parse_object_context() → ObjectRow.selection（:94）
  → ai/praat_ai/tools.py:781       _selection_range() / _range_lines() / _range_note()
```

谁在用选区：

| 工具 | 话里没给范围时的行为 |
| --- | --- |
| `pitch_statistics` / `intensity_statistics` / `formant_statistics` / `harmonicity_statistics` | 用选区（原来静默按整段统计） |
| `extract_part` | 用选区，即「把这段截出来」 |
| `textgrid_set_interval` | 用选区，即「把这段标成 a」 |
| `pitch` / `intensity` / `formant_frequency` | 没给 `time` 时用**选区中点**，不再是整个对象的中点 |
| `vot` | 本来就走这条路 |
| `textgrid_insert_boundary` | **故意不接**：单个时刻插边界，选区的起点/中点都说得通，猜错是改数据，宁可让模型问清楚 |

不能碰坏的几条约定：

1. 用了选区，回话里必须带「（按编辑器圈选 x–y 秒）」（生成脚本里是 `rangeNote$`），
   不许静默换范围。
2. 显式给了别的范围就让位；模型把 `sel_start`/`sel_end` 原样抄进 `from`/`to`
   （±2 ms 内）仍按圈选报。
3. 没圈选时行为必须和从前一模一样：统计整段、`extract_part` /
   `textgrid_set_interval` 缺 `end` 照旧报错，不自己猜区间。
4. 编辑器关掉后 C++ 那份记录自动失效（`editors[]` 指针变 null），所以
   `chat_context.tsv` 里不会残留上一次的旧选区。

## 2. VOT 自动估计（`ai/praat_ai/tools.py:1458`）

用户抱怨过「一次 47 毫秒、一次 41 毫秒」，根子是原来用「区间峰值 − 25 dB」当阈值：
范围里只要还夹着别的强段（后面的元音），阈值就漂。现在两步分开测：

1. **爆破**：`Filter (pass Hann band): 2000, 8000, 100` 带通 → `To Intensity: 2000, 0.001`
   → 找最陡的上升沿，并要求上升沿之后能量守住 5 ms（被硬切出来的爆音「来了就走」，
   拿它当爆破会把 VOT 报大几十毫秒）。升幅不到 6 dB 才退回全频段包络。
2. **浊音起始**：`To Pitch (ac): 0.002, …` 连续 3 帧成立基频才算。
   `To Harmonicity (cc)` 的 13 ms 窗口实测晚 8 ms，所以谐噪比只是回话里的佐证数字。

真机合成用例（真值 30 ms）三次是 30/32/32 ms，爆破点稳定在 0.300 秒。

性能：整段跑 `To Harmonicity (cc)` 在 10 秒的声音上要 0.301 秒（其余各步加起来
才 0.11 秒），用户能感觉出卡；现在只截「浊音起始 + 50 ms」来算，0.007 秒，数值不变。

## 3. 真机确认过的坑（别重踩）

- **投递脚本不许用 `Praat.exe --send`**：它会 `FindWindow("PraatChildWindow1 Praat")`
  （z 序最上面的子窗口，通常是 Info 窗口或声音编辑器）再做
  `ShowWindow(SW_RESTORE) + SetForegroundWindow`，于是每发一条指令都会弹
  「Praat Info」、把声音编辑器顶到对话窗口前面。前端现在自己写
  `%APPDATA%\Praat\Message.txt` 再对对象窗口发 `WM_APP`。细节和取证见
  guide.md §8.5；`verify_chat_no_popup.py --legacy` 是反证。
- **脚本里的 Info 输出命令也要挡住**：`tools.neutralize_info_commands()` 把
  `appendInfoLine` / `writeInfoLine` 改写成 `appendFileLine`（写结果文件），
  `print*` / `echo` / `clearinfo` 改成注释。模型写自定义脚本时会随手用这些命令。
- **C++ 侧异常不许穿出窗口过程**：AI 菜单回调以前只 `catch (MelderError)`，
  于是 `praat_runPythonScriptFile()` 里的 `std::filesystem::filesystem_error`
  会让 libc++abi 直接 `std::terminate` → `abort()`，Praat 无提示闪退。
  现在导出路径走 `utf8_to_path()`、两个运行器入口有 `guardPythonRunner()` 兜底、
  菜单回调走 `runAiMenuAction()`。真机回归：`ai/tests/verify_ai_menu_no_crash.py`。
- `To Harmonicity (cc)` 的 periodsPerWindow 给 0.5 会让 Praat 7.0.02 在
  `Sound_to_Pitch.cpp` 直接断言崩溃，只能 ≥ 1。
- `minPitch 250`（4 ms 窗口）在 220 Hz 上会判成「全是噪声」，窗口按 1/minPitch 走。
- Praat 脚本崩了会直接打印 UTF-16LE 的断言信息，看不出崩在哪一行：排查时往脚本里
  插 `appendFileLine` 检查点逐步二分。
- `Insert boundary` 用在已有边界（含 TextGrid 起止点）会报错，所以标注前先自己遍历
  `Get start time of interval` 自查。
- `Is interval tier` 不能直接写在 `if` 条件里（`Unknown symbol «Is» in formula`），
  必须先赋值再判断。
- Praat 里 `from` / `to` / `end` 都是保留字，脚本变量只能叫 `tmin` / `tmax` / `t1` / `t2`。

## 4. 下一步（可选，按价值排序）

1. 收尾 `praat_translate` 里几条中英混排的界面词条。
2. 真机复核 VOT：用真实录音（不是合成音）人工对一遍语图，必要时给
   `pitch_floor` 留个口径（默认 75 Hz，窗口 ≈ 3/pitch_floor）。
3. 想继续扩选区链路的话，还剩两个候选：`spectrogram`（只对选区做频谱图，
  会多出一个特定时长的对象）、`textgrid_insert_boundary`（见 §1 的取舍）。
4. 5 个 `verify_*.py` 手动脚本各测一段链路、都被 `ai/README.zh-CN.md` 引用；
  如果要合并（例如 `verify_chat_live.py` 与 `verify_chat_window_ui.py --ask`
  有重叠），记得同步改文档里的引用。
