# Praat 本地 AI 纠音前端

本目录在 `praat-simplified-chinese` 的 Python 桥接之上实现 Qwen3.5-0.8B 本地纠音前端。

## 快速开始

1. 安装 Python 3.10 或更高版本，并在 Praat 的 `Python settings...` 中设置解释器路径。
   本机已经创建好独立环境，可直接填写：

   ```text
   D:\Praat-work\venv-ai\Scripts\python.exe
   ```

2. 安装基础依赖：

   ```powershell
   python -m pip install -r ai/requirements.txt
   ```

3. 下载 Qwen3.5-0.8B 与视觉投影：

   ```powershell
   pwsh -NoProfile -File ai/Download-Qwen35.ps1 -OutputDirectory D:\models
   ```

4. 将 `ai/ai_config.example.json` 复制为 `ai/ai_config.json`，修改模型路径。
5. 将 `ai/run_ai_tutor.py` 作为 Python 脚本打开或在 Praat Python 编辑器中运行。
6. 选中标准 Sound 和学习者 Sound。
7. 填写目标语言音位、范本对象、学习者对象和阈值。
8. 运行后查看自动导回的 `ai_errors.TextGrid`、`ai_overlay.png` 和 `ai_report.json`。

## Qwen 服务

默认连接本地 OpenAI 兼容接口：

```text
http://127.0.0.1:8000/v1
```

也可以通过环境变量配置：

```powershell
$env:PRAAT_AI_QWEN_BASE_URL = 'http://127.0.0.1:8000/v1'
$env:PRAAT_AI_QWEN_MODEL = 'Qwen/Qwen3.5-0.8B'
```

本地 llama.cpp 可执行文件和模型路径写在 `ai/ai_config.example.json` 中。

切换模型（菜单「前端 → 添加模型路径…」或配置里的 `server.model_path`）会真正重启
llama-server：只要端口上运行的不是配置里的模型，前端会先停掉旧服务再用新配置启动。
状态里的「前端模型」来自服务实际加载的模型，配置值单独放在
`frontend_model_configured`，两者不一致时 `frontend_model_mismatch` 为 true。

### 模型预设

在 `ai/ai_config.json` 的 `server.presets` 里声明常用模型，就可以在对话窗口顶部的
「模型预设」下拉框里一键切换，不用每次去选文件路径。每个预设包含：

```json
"presets": [
  {
    "id": "qwen3.5-2b-vision",
    "label": "Qwen3.5-2B（视觉，操作更准）",
    "model_path": "D:\\llama.cpp-Qwen\\Qwen3.5-2B-UD-Q5_K_XL.gguf",
    "mmproj_path": "D:/models/mmproj-2B-F16.gguf",
    "vision": true,
    "context_tokens": 8192,
    "qwen": {"plan_max_tokens": 900}
  }
]
```

- `id` 是稳定标识，`label` 只用于显示；`active_preset` 记录当前选中的预设。
- `context_tokens` 覆盖按显存自动选择的上下文长度；`qwen` 里的键覆盖 `qwen` 配置节
  （例如给 2B 模型放宽 `plan_max_tokens`），点「应用预设」时一起写进配置。
- 预设里的 `model_path` 和 `mmproj_path` 必须成对：切换时前端会把这一对写进
  `mmproj_by_model`，避免把 0.8B 的投影文件带给 2B 模型。
- 声明 `vision: true` 但没有 `mmproj_path` 的预设只能纯文本运行，界面会直接标成
  「纯文本」。
- 模型文件不存在时，预设在下拉框里显示「文件缺失」，切换会给出中文错误，不会
  改动配置。

对话框顶部还会显示服务实际加载的模型和投影文件；如果端口上跑的不是配置里的模型，
点「应用预设」会先停掉旧服务再用新配置重启（服务不是本前端启动的则拒绝，避免误杀
别人的进程）。命令行也可以切换：

```powershell
python ai/run_ai_control.py presets
python ai/run_ai_control.py set-preset qwen3.5-0.8b-fast
```

`server.mmproj_path` 只对匹配的模型有效：如果它和所选模型不匹配（例如 0.8B 的
mmproj 配 2B），前端会自动按纯文本模式启动并在 `ai/logs/qwen-server.log` 记录原因，
此时状态里的 `frontend_vision` 为 false。需要视觉能力就要给对应模型配自己的 mmproj。

同时使用多个模型时，用 `server.mmproj_by_model` 给每个模型各配一个投影文件，
键可以是模型的完整路径或文件名（不区分大小写），例如：

```json
"server": {
  "mmproj_path": "D:/models/mmproj-F16.gguf",
  "mmproj_by_model": {
    "D:\\models\\Qwen3.5-0.8B-Q4_K_M.gguf": "D:/models/mmproj-F16.gguf",
    "D:\\llama.cpp-Qwen\\Qwen3.5-2B-UD-Q5_K_XL.gguf": "D:/models/mmproj-2B-F16.gguf"
  }
}
```

启动时会先查这张表，命中就用该模型自己的投影文件，没有命中才退回 `mmproj_path`；
用菜单给某个模型设置过 mmproj 后，这条映射会自动写入配置。挑选投影文件时要确认
`clip.vision.projection_dim` 等于模型的 `qwen35.embedding_length`
（Qwen3.5-0.8B 是 1024，Qwen3.5-2B 是 2048），否则 llama-server 会以
`mtmd_init_from_file: mismatch between text model … and mmproj` 退出。

## 音素强制对齐

对齐器是可插拔的：

- `mfa`：配置 `alignment.mfa.enabled`、MFA 可执行文件、发音词典和声学模型。
- `wav2vec2`：配置 `alignment.wav2vec2.model`，安装可选依赖：

  ```powershell
  python -m pip install -r ai/requirements-wav2vec2.txt
  ```

- `auto`：同时启用可用后端，合并边界；不一致时降低置信度。
- 没有任何强制对齐后端时，自动回退为比例分段，并在报告中给出警告。

本机可以使用以下脚本复现环境：

```powershell
pwsh -NoProfile -File ai/Install-MFA.ps1
pwsh -NoProfile -File ai/Download-MFA-Models.ps1
```

当前实现为每次学习者录音动态创建 MFA 词典条目，因此可以直接使用给定的
IPA 音素序列，不要求先准备整段文本的词典。实际语言仍需要对应的 MFA 声学
模型，wav2vec2 模型也需要包含目标音素的 tokenizer。

## 说明

- Qwen 只负责自然语言前端、工具选择和解释。
- 音素对比和错误区间由确定性的声学算法生成。
- 没有 Qwen 服务时，基础纠音仍然可用。

## 对话窗口（自然语言操作 Praat）

在 Praat 菜单「前端 → 启动前端」成功启动模型后，会自动弹出独立的
「Praat AI 对话」窗口。它的执行链路是：

1. Praat 把当前对象列表写到 `ai/runtime/chat_context.tsv`（id、类、名称、是否选中）；
   某个对象开着编辑器时，还会在它的行尾多写 `sel_start`/`sel_end` 两列，也就是用户
   在波形上手动拖出来的选区（只点了光标就是空的，不算选区）。
2. 对话窗口把用户请求交给本地 Qwen3.5-0.8B；模型只负责选择工具并填写参数。
3. Praat 脚本由 `ai/praat_ai/tools.py` 的固定模板渲染，不直接执行模型自由文本。
4. 脚本由 `ai/praat_ai/sendpraat.py` 自己投递：写好 Praat 的消息文件
   `%APPDATA%\Praat\Message.txt`，再给对象窗口发一条 `WM_APP`。**不启动
   `Praat.exe`、也不激活 Praat 的任何窗口**——所以发指令时「Praat Info」不会
   弹出来，声音编辑器也不会跳到对话窗口前面（老实现用的是
   `Praat.exe --send`，它会对 `FindWindow("PraatChildWindow…")` 找到的那个窗口
   做 `ShowWindow(SW_RESTORE) + SetForegroundWindow`，这就是那两个毛病的根因，
   详见 guide.md §8.5）。
5. 脚本把数值结果写入 `ai/runtime/chat_result.tsv`，最后写完成标记
   `ai/runtime/chat_state.txt`；窗口轮询到标记后把结果显示在对话里。

已内置的工具：

| 类别 | 工具 |
| --- | --- |
| 查看 | `object_info`、`duration` |
| 声学查询 | `formant_frequency`（同时给带宽，可一次查 1,2…）、`formant_bandwidth`、`formant_statistics`、`pitch`、`pitch_statistics`、`intensity`、`intensity_statistics`、`harmonicity_statistics`（HNR） |
| 编辑 | `select_object`、`rename_object`、`duplicate_object`、`remove_object`、`resample_sound` |
| 生成与导出 | `create_sound`（纯音/静音）、`extract_part`、`concatenate_sounds`、`spectrogram`、`save_sound`（WAV，缺目录会先建好） |
| TextGrid | `textgrid_info`（层、区间、标签）、`textgrid_set_interval`（标注时间段，自动补边界）、`textgrid_insert_boundary` |
| 测量 | `vot`：给了 `burst`/`voicing` 两个时刻就直接相减（TextGrid 会补边界）；只给 `from`/`to`（大概范围）就在范围里分两步自动估计——先按 2–8 kHz 带通包络的上升沿定爆破，再按自相关基频定浊音起始，结果里分别写明依据，属于估计值；范围里还包含第二个音素时只报第一个，并提示范围偏大、建议收紧；话里完全没给范围时，直接用在波形上拖出来的选区，并注明「按编辑器圈选」（模型把选区抄成 from/to 时也照样注明） |
| 交互 | `view_edit`、`play` |
| 现成脚本 | `run_praat_script`：把社区 `.praat` 脚本当**批处理**跑（输入是当前声音的副本，脚本表单的默认值会自动填进去），脚本自己打印的结果回到对话里；批处理里看不到你当前的对象列表，也不能用编辑器/交互窗口（见下） |

一次问多个时刻也支持：`time` 可以写 `0.25,0.75`，「查询 0.25 秒和 0.75 秒的基频」
会一次返回两行结果；`formant` 同样可以写 `1,2`。

在编辑器里拖出选区后，话里没给范围时这些工具都用它：`pitch_statistics`、
`intensity_statistics`、`formant_statistics`、`harmonicity_statistics`（「选区的 F1–F4 平均」）、
`extract_part`（「把这段截出来」）和 `textgrid_set_interval`（「把这段标成 a」）
都取选区，回话里注明「按编辑器圈选 x–y 秒」；`pitch`、`intensity`、`formant_frequency`
没给 `time` 时用选区中点，而不是整个对象的中点（`vot` 本来就走这条路）。

只对某类对象有效的工具（TextGrid 标注、播放/另存/重采样等）在模型指错对象类型时，
会退回到列表里唯一的合格对象，并把实际用到的对象名写进结果，不会直接报错。

除了基频/强度/共振峰这些常规查询，还可以直接问这些测量量（公式来自 Chen Gafni 的
Praat 插件，出处见各自说明）：

| 说法 | 算什么 |
| --- | --- |
| 「谱强调是多少」 | 谱强调：低通滤波前后损失多少强度 dB（Traunmüller & Eriksson 2000） |
| 「高低频能量比 / H/L」 | 4–8 kHz 能量 ÷ 0–4 kHz 能量（频段可以自己说） |
| 「Hammarberg 指数」 | 0–2 kHz 最大电平 − 2–5 kHz 最大电平（Hammarberg et al. 1980） |
| 「基频峰值延迟」 | （基频最高点 − 区间起点）÷ 区间时长，0.5 = 峰值在中间 |
| 「峰值和平均值比」 | 峰值幅度 ÷ 有效值（Hillenbrand et al. 1994） |
| 「强度斜率」 | 强度曲线的平均斜率 dB/s（局部逐点，或者说「整体」看首尾） |

这些只是「专用工具」。剩下的声学参数走**表驱动的 `measure` 工具**：参数表在
`ai/praat_ai/measures.tsv`，**加一个参数 = 加一行**（工具 schema 的 enum、说明文字、
脚本模板、真机用例都是从表里生成的）。目前 41 个参数，覆盖：

| 类别 | 参数（`measure` 的 `parameter`） |
| --- | --- |
| 基频 | `mean_pitch`、`minimum_pitch`、`maximum_pitch`、`median_pitch`、`sd_pitch`、`pitch_slope`、`pitch_slope_octave_free`、`pitch_start`、`pitch_end` |
| 强度 | `mean_intensity`、`minimum_intensity`、`maximum_intensity`、`median_intensity`、`sd_intensity` |
| 嗓音质量 | `hnr`、`cpps`、`local_jitter`、`rap_jitter`、`local_shimmer_percent`、`local_shimmer_db`、`apq3_shimmer` |
| 共振峰 | `f1`、`f2`、`f3`（平均频率）、`b1`、`b2`、`b3`（带宽中位数） |
| 频谱 | `centre_of_gravity`、`skewness`、`kurtosis` |
| 幅度 | `rms`、`peak_amplitude`、`mean_amplitude` |
| 多步的（交给各自的专用工具） | `hl_ratio`、`spectral_emphasis`、`hammarberg_index`、`pitch_peak_latency`、`peak_to_average_amplitude`、`intensity_slope_local`、`intensity_slope_global` |

用法就是说出来：「这段的 jitter 和 shimmer 是多少」「F1–F3 的平均频率和带宽」。
一次可以要多个参数（`parameter` 写 `f1,f2`），它们共用一个中间对象；`from`/`to`
（或编辑器圈选）对按时间段查的参数生效。写分析设置（`pitch_floor`、`pitch_ceiling`、
`formant_max`…）也能直接说，默认值在表里。表里 `@@ editor_only` 的参数
（`mean_autocorrelation`）只能在声音编辑器的 Voice report 里查，前端会直接用中文
说明，而不是让 Praat 弹英文错误框。

## 在 Praat 菜单里直接用（原生插件）

`ai/plugin/praat_ai/` 是一个可以装进 Praat 的原生插件：选中一个 Sound 就能从菜单里
「AI 声学测量...」（结果写进 Table「AI 测量结果」），在声音/TextGrid 编辑器的
`Analyses` 菜单里能对圈选段一键测全部参数，Praat 菜单里还能直接启动这个对话窗口。
它和对话前端**共用 `measures.tsv` 这张表和同一套命令**，所以两边数值一致；
**不需要重新编译 Praat**，没装这个 fork 的人也能用。

```powershell
powershell -ExecutionPolicy Bypass -File ai\plugin\install.ps1   # 装到 %APPDATA%\Praat\plugin_praat_ai
python ai\tests\verify_plugin.py                                  # 真机回归（4 条）
```

卸载就是删掉 `%APPDATA%\Praat\plugin_praat_ai`；细节和已知边界见
`ai/plugin/README.zh-CN.md`。

手上有现成的社区脚本时，可以直接说「用 D:/scripts/vot.praat 跑一下这个声音」：
`run_praat_script` 会先把当前声音（列表里只有一个 TextGrid 时连它一起）导出成副本，
再让另一个**批处理** Praat 去跑那个脚本——脚本里的表单用它自己的默认值，脚本自己
打印的结果（以及它在自己目录里新写的文件）会回到对话里。这条路不碰你开着的 Praat，
所以脚本报错、或者脚本自己弹对话框，都不会把对话卡住。反过来，批处理里**看不到你
当前的对象列表**，也不能用编辑器：对「编辑器里圈选的那一段」做分析的脚本，还是得在
Praat 里自己点运行。

模板覆盖不到的请求会退回 `custom_script`，此时脚本必须通过安全检查：单引号自动改成
双引号、禁止 `runSystem`、`deleteFile`、`exit` 等命令，并且**必须是 Praat 脚本**——
模型如果给出 Python 代码（`import`、`def`、`print(`、`numpy` 之类），前端会直接
拒绝并提示改用内置工具，而不是把 Python 送进 Praat 换回一句看不懂的英文报错。
自定义脚本里如果出现 `appendInfoLine` / `writeInfoLine`，前端会把它们改写成
`appendFileLine` 写进结果文件（内容照样显示在对话里）；`appendInfo` / `writeInfo`
同样处理，`printline` / `print` / `echo` 写的是字面文字，会整段抄进结果文件；
只有 `printtab` / `clearinfo` 没有内容可保留，才会改成注释——这些命令原本都会弹出
「Praat Info」窗口。

模型选工具走的是 **llama-server 的原生 function calling**（工具自带参数 schema，
类型/枚举/必填项由服务端约束）。如果换成不支持工具调用的服务端，设
`PRAAT_AI_PLANNER=json` 可以退回老的提示词接口。读入磁盘上的文件请用 `read_file`
（`Read from file:`），它和「另存为」`save_sound` 是两个方向，不要混。

一轮请求是**多轮循环**：模型先选工具，脚本在 Praat 里跑完，结果会被送回给模型，
它再决定要不要接着做、或者把结果讲清楚。所以：

- 回答里能直接看到数值（「0.5 秒处的基频为 220.000 Hz。」），不再只是「正在查询…」；
- 一句话里的多步操作可以落地（「把前 0.3 秒截出来再改名」= 两步）；
- 上一步失败（参数非法、对象类型不对）时模型会自己改参数重试，而不是直接报错；
- 窗口里会显示每一轮做了什么，例如
  `第 1 轮：pitch（time=0.25）→ 基频（0.250 秒处）= 220.000 Hz`。

最多 3 轮、最多 5 个动作，重复的调用只会执行一次——这些都是防小模型「顺手多做几步」
的护栏。**前提是 llama-server 用 `--jinja` 启动**（前端启动的服务已经自动带上；
自己手工起服务时请加这个参数），否则多轮行为会明显变差。

还有一条护栏：你说的事情里没有「然后 / 再 / 接着 / 顺便」这类词时，第二轮之后
**不会**再执行会改动对象的操作（建对象、改名、删除、标注、另存都算），只读查询不受
限制。想要一步接一步地做，就照「前半句，然后把……」这样的说法提要求。
选工具的准确率和模型大小关系很大：同一个请求 2B 预设实测每条都选对，0.8B 预设会
挑错工具（例如把「阅读当前对象的信息」做成频谱图），日常建议用 2B 预设。

注意事项：

- 查询类工具默认取声音的中间时刻，可以在请求里直接写秒数。
- 时间超出对象时长会自动截断到对象末尾，结果里会标注「已按对象时长截断」；
  静音段或清音段查基频时结果会写「该时刻没有周期性声源」，不会再出现
  `--undefined--` 这种没意义的输出。
- 共振峰查询会临时创建一个 `ai-chat-temp` 对象，脚本结束前自动删除并恢复原选中对象。
- 每条指令之后 Praat 都会把最新对象列表交给对话窗口（`cb_userMessage()` 里的
  `PraatAiControl_refreshChatContext(true)`），执行前再送一条空脚本确认 Praat
  还在响应，所以 Praat 重启过、对象改过名字之后仍然按最新列表规划，不会拿着旧 id
  去操作。每条指令有独立编号（`runtime/commands/chat_command_<编号>.praat`），
  配上消息文件「自消费」，超时的旧指令不会被执行两遍、也不会顶掉新指令。
- 对象列表**不再每条消息都刷**：Praat 会在 `chat_context.tsv` 末尾写自己的进程号
  （`# praat-pid=…`），标记就是正在跑的这个 Praat 时前端一条消息都不发（省一次
  往返）；Praat 重启过、或者对方是不写标记的老版本时才刷一次。
- 输入框旁边有「停止」：等 Praat 的结果、等社区脚本的批处理都能中途取消，不用干等
  25 秒。取消只是「不再等」，Praat 里已经在跑的脚本不受影响。
- 对话历史/对象列表按 **token 预算**裁剪（`ctx` 只有 8192，工具说明就占 ~6.6k），
  被省掉的部分会在窗口里提示一句，不再静默丢；想多带历史就在预设里把
  `context_tokens` 调大。
- 每次发送最多等 25 秒。如果 Praat 里有没关掉的错误对话框或模态窗口，脚本会卡在
  队列里，窗口会明确提示「Praat 在 25 秒内没有执行这个脚本」并告诉你关掉那些窗口，
  不会一直挂着（超时后前端会把排队中的消息换成空脚本，免得它稍后执行下一条指令）。
- 同时开着多个 Praat 时，脚本只会交给最新打开的那个窗口；窗口检测到多实例会提醒你
  关掉多余的 Praat。
- 脚本执行失败时不会再弹 Praat 的错误对话框：Praat 把错误原文写进
  `ai/runtime/chat_failure.txt` 和结果文件，对话窗口**立刻**把这一条标成失败并把
  原文显示出来（以前会白等 25 秒，错误还看不到）。注意你自己的操作（不是对话窗口
  发的指令）出错时，Praat 照旧弹它自己的错误框。
- 排障用的退路：设环境变量 `PRAAT_AI_SEND_MODE=argv` 可以退回老的
  `Praat.exe --send`（会激活 Praat 的一个窗口，而且没有「自消费」保护，平时不要开）。
- 修改 `ai/` 下的 Python 代码后，要重新从菜单启动前端，对话窗口才会加载新代码。

## 手工回归

改完 `ai/` 的模板或链路后，除了单元测试，还建议跑这两条真机回归：

```powershell
$env:PYTHONPATH = 'ai'
python -m unittest discover -s ai/tests -v      # 单元测试
python ai/tests/verify_chat_templates.py        # 每个工具模板在真 Praat 批处理里跑一遍
python ai/tests/verify_chat_planning.py         # 真机模型规划一批请求并真跑一遍（准确率）
python ai/tests/verify_chat_window_ui.py        # 对话窗口能不能正常建起来（会闪一下窗口）
python ai/tests/verify_chat_live.py             # 对话窗口链路（会临时开一个 Praat）
python ai/tests/verify_chat_no_popup.py         # 发指令时 Praat 的窗口一个都不许动（会收进任务栏）
python ai/tests/verify_plugin.py                # 原生插件（B2）：菜单注册 + 33 个参数在真 Praat 里算一遍
python ai/tests/verify_external_script.py       # 现成社区脚本当批处理跑（C3）：表单默认值、输出、报错
python ai/tests/verify_error_dialog.py          # 脚本报错不弹模态框、不挡后面的消息（会临时起一个 GUI Praat）
python ai/tests/verify_context_marker.py        # 对象列表里的进程标记（C5）：不再每条消息都刷列表
python ai/tests/verify_cancel_live.py           # 「停止」真的能停住等 Praat / 等批处理（C7）
python ai/tests/verify_presets_live.py          # 模型预设切换（会重启 llama-server）
```

后五条需要本机装好模型、并且在没有沙箱限制的终端里执行；
`verify_chat_no_popup.py --legacy` 是反证（用老路径跑，应当看到窗口被拽出来）。
