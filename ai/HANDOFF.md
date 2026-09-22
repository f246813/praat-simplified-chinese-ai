# AI 前端交接要点

给下一次接手 AI 纠音前端（对话窗口 + 工具模板 + 编辑器选区链路）的会话。
约定和坑的权威版本仍然是 [guide.md](../guide.md) §8，这里只写「接手时先看什么、
哪些东西不能碰坏、下一步」。

（本文件 2026-09-23 重写过一次：只保留仍然成立的旧内容，§1 是 9/22 那一轮的交接。）

## 0. 现状与先跑一遍

- 分支 `modern`，HEAD `62e842079`，**已 push 到 `public`**。工作区只剩一个未跟踪文件
  `PraatZHcn.lnk`（用户自己的快捷方式，别动）。
- 最近三段提交：
  - `b2a7fdcb5` 界面改版：对话窗口 / 迷你进度窗 / API 配置窗 / 纠音表单对齐
    TW-Elements 的设计语言（新增 `ai/praat_ai/ui_theme.py`、`ui_widgets.py`，
    见 guide.md §8.16）；
  - `447bb48c5` 修「菜单启动/停止前端没反应」「切回本地 WinError 10061」
    「Sound 编辑器里语图上方的白条」，并新增 `api.stop_local_service`（见 §1）；
  - `62e842079` 文档：API 模式下菜单里到底看得见什么。
- **本机 2026-09-23 00:11 重启过**：现在没有 Praat、没有 llama-server，8000 端口空着。
  `ai/runtime/status.json` 是 9/22 的旧快照（里面 `frontend_running: true` 是假的），
  Praat 或菜单下一次刷新就会覆盖它；`ai/runtime/qwen.pid` 已经不存在。跑真机回归
  之前，先按 §5 把本机服务（重新）起起来。
- **用户配置 `ai/ai_config.json` 一个字都别动**（key 就在里面，这个文件在 .gitignore
  里）。当前是本地模式：`api.enabled=false`、`api.model=deepseek-chat`（key 35 字符）、
  `api.stop_local_service=true`（用户 9/22 21:11 自己保存过一次）、预设
  `qwen3.5-2b-vision`（`Qwen3.5-2B（视觉，操作更准）`）/
  `qwen3.5-0.8b-fast`（`Qwen3.5-0.8B（快速，省显存）`），
  `active_preset=qwen3.5-0.8b-fast`。真机回归需要别的配置就用 `PRAAT_AI_CONFIG_PATH`
  带一份临时副本（见 §5）。
- **改了 `ai/praat_ai/**.py` 之后，已经开着的对话窗口不会重新加载代码**：要么关掉重开
  窗口，要么让 Praat 重新拉起它。这条每次都会有人踩。
- **远端与权限（约束，不是待办）**：`origin`（KasumiKitsune/praat-simplified-chinese）
  **只有读权限**——推不上去，除非那边给 `f246813` 加写权限（或改用有写权限的 token）。
  改动镜像在 `public` = f246813/praat-simplified-chinese-ai（默认分支 `modern`）。
  两条规矩：①不要把它列成「下一步」；②**更不要因为「推不了 origin」就删掉这里记的
  任何内容**（用户明确要求保留这条权限说明）。
- 验证命令（必须用项目自带的 Python，PATH 里的 `python` 是商店存根、缺依赖）：

  ```powershell
  cd D:\Praat-work\praat-simplified-chinese
  $venv = 'D:\Praat-work\venv-ai\Scripts\python.exe'
  $env:PYTHONPATH='ai'; $env:PYTHONIOENCODING='utf-8'
  & $venv -m unittest discover -s ai/tests     # 497 个，约 80 秒（8000 端口在跑时更慢）
  & $venv ai/tests/verify_chat_templates.py    # 98 个模板用例，约 7 秒
  ```

- 改了 `sys/` 或 `foned/` 下的 C++ 才需要重编（**先关掉 Praat**，否则链接会
  `Permission denied`）：

  ```powershell
  $env:MSYSTEM='CLANG64'
  C:\msys64\usr\bin\bash.exe -lc "cd /d/Praat-work/praat-simplified-chinese && make PRAAT_COMPILER=clang -j16"
  # 只动 .cpp：增量约 80 秒；动了 .h（FunctionEditor.h / FunctionArea.h 这种）会牵连
  # 大半个 foned/，几分钟
  ```

- 真机回归（真开 GUI、真起停 8000 端口上的模型，逐条手动跑）：
  `verify_model_progress_live.py`、`verify_presets_live.py`、`verify_chat_window_ui.py`、
  `verify_api_mode.py`、`verify_api_dialog_live.py`、`verify_frontend_follows_praat.py`、
  **`verify_api_switching_live.py`（本轮新增，见 §1.2）**、`verify_chat_templates.py`。
  会花钱的只有 `verify_cloud_knowledge_live.py --send`（真发云端请求），跑之前先跟
  用户说一声。
- PowerShell 没有 `head`/`sed`：用 `rg` + `Get-Content | Select-Object -Skip N -First M`。
- **提示词预算很紧**：本项目触发过 3 次 HTTP 433，planner 提示词
  （`ai/praat_ai/qwen.py`）每加一句都要付代价。新能力优先做成脚本层逻辑
  （模板、`*_build_*` 里的兜底），只有脚本层兜不住时才动提示词。

## 1. 2026-09-22 这一轮：三处根因 + 一个新选项

详细版在 guide.md §8.13 / §8.15.7 / §8.16.6。这里只留「接手要知道的结论」。

### 1.1 菜单里点「启动前端 / 停止前端」没反应

`control.py` 两个函数在 API 模式下第一句就 `return collect_status(...)`，**一条
`PRAAT_PROGRESS` 都不打**；而 Praat 的「正在处理中」小窗只认这行标准输出
（`sys/praat_python.cpp` → `Melder_progress`，见 §8.14）。加上 API 模式下状态里
`frontend_running=true`，`PraatAiControl_startFrontend()` 只把**已经开着**的对话窗口
置前——窗口本来就在最前面，用户看到的就是「什么都没发生」。

现在：API 模式下也报进度（0.10 → 1.00）；`sys/PraatAiControl.cpp` 在
`api_enabled=true` 时把菜单状态行换成 `API 模式（<api_model>，不需要本机模型服务）`。

实测（`ai/runtime/api_status_menu_live.py`：API 临时配置 + 真 Praat + Sound 编辑器）：
点之前 `状态: 已停止`，点之后 `模型: deepseek-chat；状态: API 模式（deepseek-chat，
不需要本机模型服务）`；「停止前端」把 8000 端口收空。**注意**：这两步毫秒级结束，
Praat 的进度小窗是懒创建的，所以那条路上肉眼看不到小窗——可见反馈是状态行 + 被置前的
窗口，别把它当成 bug 再修一遍。

### 1.2 切回本地（或换本地预设）之后 `[WinError 10061] 目标计算机积极拒绝`

真正的根因：**没有任何代码去启动 llama-server**。`apply_preset()` /
`set_frontend_model()` 只在 `server_model_state(...) is False`（端口上有服务、但加载的
是别的模型）时重启；端口**空着**时 `server_model_state()` 返回 `None`（读不到
`/v1/models`），于是既不重启也不启动，直接回报状态。对话窗口那边同理：勾上 API 会发
`stop-local-service`，取消勾选却只写一行提示——一进一出，本机服务就没了。

现在有统一入口 `control.ensure_local_service(config, config_path, progress=...)`：

| 端口状态 | 行为 |
| --- | --- |
| 空着 | `_launch_server()` 启动 |
| 上是别的模型（`is False`） | `_restart_service()` 重启 |
| 就是配置里的模型（`True`） | 只 `collect_status()`，什么都不动 |
| 读不到模型列表（`None`） | 保持原语义，不擅自重启别人的服务 |

接到四条路：`apply_preset()`、`set_frontend_model()`、`start_frontend()`（本地分支）、
对话窗口 `ChatWindow.on_api_settings_saved()`（取消勾选 API → 发 `start-local-service`
→ `start_local_service_worker` 把服务起起来）。另外 `qwen.connection_hint()` 把
「本机地址被拒绝」翻成能照着做的中文提示（点菜单「前端 → 启动前端」或重新应用一次
预设），只对 127.0.0.1 / localhost / ::1 生效；云端地址、超时、DNS 失败保持原文。

真机回归 `verify_api_switching_live.py`（自带临时配置，不动用户文件）：
① `stop_local_service=true` 切到 API → 8000 端口必须空；
② `false` 切到 API → 端口仍在、模型没变；
③ 取消 API → 自动把服务起起来，随后发一条真消息不再 10061；
③′ 切本地预设 → 同样自动起服务。

**坑**：API 模式下 `config.qwen.base_url` 被 `apply_api_to_qwen` 换成了**云端**地址，
拿它去 `endpoint_available()` 或等端口释放会去请求云端（白等 20 秒 + 打网络）。
凡是要探本机端口，用 `control.local_base_url(config)`（从 `server.host/port` 拼）。

### 1.3 新选项 `api.stop_local_service`

| 场景 | `true`（默认） | `false` |
| --- | --- | --- |
| 对话窗口保存并启用 API | 发 `stop-local-service` 收掉本机服务（省显存） | 不停，本机服务继续跑 |
| 菜单「停止前端」（API 模式） | 真的 `_stop_running_service()` | 不碰本机服务，但有进度 + 说明 |
| 取消勾选 API / 切回本地预设 | 一律 `ensure_local_service()`（与这个开关无关） | 同上 |

- 键名 `api.stop_local_service`（bool）；老配置没有这个键时**按 true 读，不写迁移**。
- 界面在「API 配置」小窗的**「连接」卡片**里（「超时(秒)」下面那个复选框）；
  `DEFAULTS` / `settings_from_config()` / `normalize_settings()` / `Dialog.collect()`
  四处都要带上它（和 `thinking_level` 一样的写法）。
- 用户 9/22 21:11 自己保存过一次，他们配置里现在这个键是 `true`。

### 1.4 Sound 编辑器「语图上方的白条」

结论：那是**画布里没人画的预留行**，不是我们改坏的东西（`df10c41a8` 早就删掉了 30px 的
自绘按钮条，`createAiToolbar` / `aiToolbarHeight` 在源码里已经不存在）。

量出来的几何（画布 1812×841，客户区 1810×839）：

- 最上面数据区顶边在画布**第 49 行** = `TOP_MARGIN(3) + space(30) = 33 pxlt` 的画布预留
  ＋ 每个 `FunctionArea` 自己 `top_pxlt()` 减掉的 `legendMargin(23 pxlt)`；
  `height_pxlt = 像素高 + 111`、`width_pxlt = 宽 + 21`，所以 33+23 pxlt ≈ 49 px。
- 这些行没人画，于是保留 `DataGuiColour_WINDOW_BACKGROUND`（**#F5F6F8**），而数据区是
  `DataGuiColour_AREA_BACKGROUND`（**#FFFFFF**）→ 顶部一条、两块数据区之间一条，
  都看得到（用户叫它「白条」）。
- 另外 Win32 的 lookAndFeel 是 **Motif**，`Machine_getMenuBarBottom()` 返回 **26**
  （不是 0），于是 `contentTop=26`——那是画布**外面**的窗口缝，属于窗口布局，没动。

修法（最小、不动布局）：`FunctionEditor::v_draw()` 里画完窗口底色、**在按钮和数据区
之前**，把数据区那一列（`dataLeft_pxlt()…dataRight_pxlt()`、
`dataBottom_pxlt()…height_pxlt`）再填一遍 `DataGuiColour_AREA_BACKGROUND`；
`TOP_LEGEND_MARGIN` 从 `FunctionArea.h` 里的局部 `23.0` 提成 `FunctionEditor.h` 的共享
常量，免得以后改一处忘一处。

像素判定（前后对照，整列取样）：

```
修复前: 画布 1–48 行主色 #F5F6F8（74210/75840 像素）｜波形区与频谱区之间的缝 396–415 行 #F5F6F8（28699/31600）｜最上面数据区顶边 = 第 49 行
修复后: 画布 1–48 行主色 #FFFFFF（74210/75840 像素）｜波形区与频谱区之间的缝 396–415 行 #FFFFFF（28699/31600）｜最上面数据区顶边 = 第 49 行
```

证据都在不入库的 `ai/runtime/`：`ui_snapshots/sound_editor_before/after.png`（整窗）、
`canvas_printwindow_before/after.png`（画布）、`canvas_top_*`、`canvas_between_*`
（放大裁剪）。复现脚本 `ai/runtime/whitebar_shot.py [before|after]`：开 Praat → 建
Sound → View & Edit → 把窗口挪到 1828×954 @ (20,13) → 抓画布子窗口 + 打印逐行主色。
诊断要点：画布子窗口的类名是 `PraatDrawingArea1 Praat`，对它 `PrintWindow` 能拿到干净
的颜色；**屏幕 BitBlt 会偏色**（同一块区域量出来是 #F6F6F6/#F3F3F4），别用它。

### 1.5 界面改版（前一段，TW-Elements 设计语言）

四个界面（对话窗口、迷你进度窗、API 配置窗、AI 纠音表单）统一到 TW-Elements 的色板 /
层级 / 圆角：`ui_theme.py` 令牌 + 跟随系统深浅色（每 5 秒复查，无手动开关），
`ui_widgets.py` 的 Card / RoundedButton / RoundedProgressBar / Chip / Snackbar /
FieldCard / Spinner，消息区仍是 `tk.Text`（要能选中复制）。取舍原因和「改 UI 时不许动
的属性名清单」在 guide.md §8.16.5——回归脚本直接按那些名字读控件，改名就红。

## 2. 一条数据流：编辑器里拖出来的选区

（行号是 2026-09-23 的）

```
foned/FunctionEditor.cpp:2107    PraatAiControl_noteEditorSelection (…)
  → sys/PraatAiControl.cpp:577    PraatAiControl_noteEditorSelection()
  → sys/PraatAiControl.cpp:268    buildChatContext() 写 6 列
  → ai/runtime/chat_context.tsv   id / class / name / selected / sel_start / sel_end
  → ai/praat_ai/tools.py:251      parse_object_context() → ObjectRow.selection（:124）
  → ai/praat_ai/tools.py:831      _selection_range() / _range_note()(:855) / _range_lines()(:861)
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
3. 没圈选时行为必须和从前一模一样：统计整段、`extract_part` / `textgrid_set_interval`
   缺 `end` 照旧报错，不自己猜区间。
4. 编辑器关掉后 C++ 那份记录自动失效（`editors[]` 指针变 null），所以
   `chat_context.tsv` 里不会残留上一次的旧选区。

## 3. VOT 自动估计（`tools.py:1793` 分派；`_build_vot_explicit` :1337 / `_build_vot_auto` :1509）

用户抱怨过「一次 47 毫秒、一次 41 毫秒」，根子是原来用「区间峰值 − 25 dB」当阈值：
范围里只要还夹着别的强段（后面的元音），阈值就漂。现在两步分开测：

1. **爆破**：`Filter (pass Hann band): 2000, 8000, 100` 带通 → `To Intensity: 2000, 0.001`
   → 找最陡的上升沿，并要求上升沿之后能量守住 5 ms（被硬切出来的爆音「来了就走」，
   拿它当爆破会把 VOT 报大几十毫秒）。升幅不到 6 dB 才退回全频段包络。
2. **浊音起始**：`To Pitch (ac): 0.002, …` 连续 3 帧成立基频才算。
   `To Harmonicity (cc)` 的 13 ms 窗口实测晚 8 ms，所以谐噪比只是回话里的佐证数字。

真机合成用例（真值 30 ms）三次是 30/32/32 ms，爆破点稳定在 0.300 秒。

性能：整段跑 `To Harmonicity (cc)` 在 10 秒的声音上要 0.301 秒（其余各步加起来才
0.11 秒），用户能感觉出卡；现在只截「浊音起始 + 50 ms」来算，0.007 秒，数值不变。

## 4. 真机确认过的坑（别重踩）

- **投递脚本不许用 `Praat.exe --send`**：它会 `FindWindow("PraatChildWindow1 Praat")`
  （z 序最上面的子窗口，通常是 Info 窗口或声音编辑器）再做
  `ShowWindow(SW_RESTORE) + SetForegroundWindow`，于是每发一条指令都会弹
  「Praat Info」、把声音编辑器顶到对话窗口前面。前端现在自己写
  `%APPDATA%\Praat\Message.txt` 再对对象窗口发 `WM_APP`。细节和取证见 guide.md §8.5；
  `verify_chat_no_popup.py --legacy` 是反证。
- **脚本里的 Info 输出命令也要挡住**：`tools.neutralize_info_commands()` 把
  `appendInfoLine` / `writeInfoLine` 改写成 `appendFileLine`（写结果文件），
  `print*` / `echo` / `clearinfo` 改成注释。模型写自定义脚本时会随手用这些命令。
- **C++ 侧异常不许穿出窗口过程**：AI 菜单回调以前只 `catch (MelderError)`，于是
  `praat_runPythonScriptFile()` 里的 `std::filesystem::filesystem_error` 会让 libc++abi
  直接 `std::terminate` → `abort()`，Praat 无提示闪退。现在导出路径走
  `utf8_to_path()`、两个运行器入口有 `guardPythonRunner()` 兜底、菜单回调走
  `runAiMenuAction()`。真机回归：`ai/tests/verify_ai_menu_no_crash.py`。
- **本机 Praat 会被隐藏的模态对话框卡住**（2026-09-22 实测）：发脚本 25 秒不执行、
  `WM_CLOSE` 也不理、`CloseMainWindow` 无效。这时只能 `taskkill /PID <praat> /T /F`
  （重编 `Praat.exe` 之前必须先关掉它，否则链接 Permission denied）。别把它当成
  前端的 bug。
- **`To Harmonicity (cc)` 的 periodsPerWindow 给 0.5** 会让 Praat 7.0.02 在
  `Sound_to_Pitch.cpp` 直接断言崩溃，只能 ≥ 1。
- **`minPitch 250`**（4 ms 窗口）在 220 Hz 上会判成「全是噪声」，窗口按 1/minPitch 走。
- Praat 脚本崩了会直接打印 UTF-16LE 的断言信息，看不出崩在哪一行：排查时往脚本里插
  `appendFileLine` 检查点逐步二分。
- `Insert boundary` 用在已有边界（含 TextGrid 起止点）会报错，所以标注前先自己遍历
  `Get start time of interval` 自查。
- `Is interval tier` 不能直接写在 `if` 条件里（`Unknown symbol «Is» in formula`），
  必须先赋值再判断。
- Praat 里 `from` / `to` / `end` 都是保留字，脚本变量只能叫 `tmin` / `tmax` / `t1` / `t2`。
- **API 模式下别拿 `config.qwen.base_url` 探本机端口**（它已经是云端地址），用
  `control.local_base_url(config)`。见 §1.2。
- **单元测试对 8000 端口有隐性依赖**：没钉住 `endpoint_available` 时，真机上刚好有
  llama-server 在跑会让 `start_frontend` 走进「重启别人」的分支。写新测试时请显式
  patch `endpoint_available` / `_launch_server` / `server_model_state` 之一。见 §5。
- 截图别用屏幕 BitBlt（偏色），用 `PrintWindow`；窗口句柄从 `sendpraat.list_windows()`
  拿，画布子窗口类名是 `PraatDrawingArea1 Praat`。见 §1.4。

## 5. 测试与回归约定

- 单元测试：`& $venv -m unittest discover -s ai/tests`（497 个，`ai/tests/` 下 29 个
  `test_*.py`）。改完必须全绿再提交。
- **写新测试时注意端口**（本轮踩过）：凡是要走 `start_frontend` / `apply_preset` /
  `set_frontend_model` / `ensure_local_service` 的用例，都 patch 掉
  `endpoint_available` / `_launch_server` / `server_model_state` / `_wait_for_endpoint_gone`
  之一，别让结果取决于本机 8000 端口此刻有没有服务。
- 真机回归需要本地模型时，用 `PRAAT_AI_CONFIG_PATH` 带一份临时副本（`config.default_config_path()`
  认这个变量）：`verify_model_progress_live.py` 与 `verify_api_switching_live.py` 里有
  现成写法。**别把用户的 `ai/ai_config.json` 当测试夹具**。
- 起停本机服务（跑真机回归前常用，和菜单「启动/停止前端」走同一条路）：

  ```powershell
  & $venv -c "from praat_ai import control; control.ensure_local_service(control.load_config())"
  & $venv -c "from praat_ai import control; control.stop_frontend()"
  ```
- 改 UI 不许动属性名，清单在 guide.md §8.16.5（`status` / `preset_box` / `entry` /
  `transcript` / `MiniProgress.bar.cget("value")` 仍是 0–100 /
  `ApiSettingsDialog.key_entry.cget("show")` …）。
- 截图、日志、一次性脚本都写进 gitignored 的 `ai/runtime/`；`ui_snapshots/` 放对照图，
  `whitebar_shot.py` / `api_status_menu_live.py` / `chat_shot.py` / `dialog_shot.py` /
  `ui_probe.py` 是能复用的冒烟脚本。

## 6. 下一步（可选，按价值排序）

1. 真机复核 VOT：用真实录音（不是合成音）人工对一遍语图，必要时给 `pitch_floor` 留个
   口径（默认 75 Hz，窗口 ≈ 3/pitch_floor）。
2. 收尾 `praat_translate` 里几条中英混排的界面词条。
3. 想继续扩选区链路的话，还剩两个候选：`spectrogram`（只对选区做频谱图，会多出一个
   特定时长的对象）、`textgrid_insert_boundary`（见 §2 的取舍）。
4. 高 DPI（120% / 150%）下自绘控件的**观感**复验：本机只有 96 DPI，`scale_factor()`
   的单测覆盖 1.0/1.25/1.5，但没人真的在缩放机器上看过。
5. `verify_*.py` 手动脚本越来越多（19 个），要合并的话记得同步 `ai/README.zh-CN.md`
   里的引用（`verify_chat_live.py` 与 `verify_chat_window_ui.py --ask` 有重叠）。
