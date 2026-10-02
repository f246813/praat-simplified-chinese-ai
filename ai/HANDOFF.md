# AI 前端交接要点

## 最新交接：2026-10-02 夜：测量 VOT「没完成」= 目录 Low 标签 + 投递事实被搞错（**已真机+真云端验过**）

用户报「最近的一次测量 VOT 请求没有正确完成」。19:44 那次请求的轨迹完整留在
`ai/runtime/conversations.sqlite3`（会话 `c408e322…`）。查下来是**三层**，前两层都动手了，
第三层是产品 bug 一并修了；详细证据见 `docs/2026-10-02-阶梯逃逸投递事实修复验收.md`。

### 第一层（环境，**已按用户选择处理**）：`稳定早期版\Praat.exe` 曾是 Low 完整性

这个仓库目录（`C:\Users\f2468\Desktop\Praat`，含 `稳定早期版`）带 **Low 完整性标签**；
Windows 按**映像文件**的标签决定新进程的完整性级别，所以从这里启动的 `Praat.exe` 一定是
Low（实测 `0x1000`；父进程是 Medium 也一样），Low **写不了** Medium 的
`%APPDATA%\Praat\Message.txt` → 对话前端**一条指令都送不出去**
（`[Errno 13] Permission denied`）。把同一份 `Praat.exe` 复制到 `%TEMP%` 再启动就是
Medium（`0x2000`）、消息文件可写。**不是**「谁启动的」问题：用户双击也一样 Low。

**处置（用户 2026-10-02 晚选定方案 A）**：只把 `稳定早期版\Praat.exe` 这一个文件的标签
显式改成 Medium（不动目录、文件名、后缀、内容）：

```powershell
icacls "C:\Users\f2468\Desktop\Praat\稳定早期版\Praat.exe" /setintegritylevel Medium   # 改
icacls "C:\Users\f2468\Desktop\Praat\稳定早期版\Praat.exe" /setintegritylevel Low      # 回退
```

改后实测：`Mandatory Label\Medium Mandatory Level:(NW)`，用这份 Praat 启动 = Medium
（`0x2000`），`verify_delivery_live.py` **12/12 通过**（含用户录音 38.0 毫秒）。改之前先用一个
无关小文件（`cmd.exe`）验证过「只改文件标签就足够，且可逆」。

⚠️ 代价（**下一代务必知道**）：①受限（沙箱）会话从此**不能覆盖这个 exe**——重新编译或重新
打包写 `Praat.exe` 会 `Permission denied`，要么先切完全权限、要么先改回 Low；②**重新构建出来的
新 exe 会继承目录的 Low**，需要把上面那条 Medium 命令再执行一次。兜底脚本：
`python ai/tools/launch_praat_medium.py`（把同一份 exe 复制到 `%TEMP%` 启动，并用
`PRAAT_AI_PROJECT_DIR` 把原生侧项目目录指回仓库 `ai`；原生侧按「工作目录 → exe 目录」找 `ai`，
换位置不指就会把 runtime 写到工作区根目录）。

### 第二层（产品真 bug，已修）：把「根本没送出去」当成「执行状态不明」

`_send_script()` 失败时只返回 `(False, 说明)`，「消息文件写不进去」和「交出去了没等到完成标记」
分不出来；而 `cloud_workflow.execute()` 一律 `execution_unknown = True`，之后整轮投递都被
`'此前执行状态不明，本轮禁止继续投递'` 挡死。于是：阶梯开始**之前**那次预导出快照失败 →
模型唯一那次 `vot` 调用被拒 → 拒绝语里有「状态不明」→ `cloud_agent` 按文字判成 `unknown` →
`permanent=True` → 立刻 `BranchExit`。最后报告里只有那句拒绝语，真正的
`Message.txt` 权限原因留在 `state.attempts` 里没进报告 → 模型把「测不出来」解释成
**「audio_input 为 false，模型不能听音频」**（`evidence: []`、`requests: 2`，一个数值都没测到）。

### 改了什么（源码交付，没有重建安装包）

- 新增 `ai/praat_ai/delivery.py`：`DELIVERED` / `NOT_DELIVERED` / `EXECUTION_UNKNOWN` /
  `EXECUTION_BLOCKED` 四种**投递事实**，三个模块共用，别再靠说明文字猜。
- `chat.py`：`_send_script(..., outcome=[…])` 可选出口写回「到底送出去没有」；
  `_send_script_via_argv` 同理（`Popen` 失败 = 没送出去）；`AgentStep.execution` 新字段把事实带出执行层。
  不传 `outcome` 的调用方（本地路径、各 verify 脚本）行为**逐字节不变**。
- `cloud_workflow.py`：只有**真的交出去但没等到完成**才置 `execution_unknown`；「没送出去」返回确定失败
  （说明里明确「Praat 没有收到这条指令」）+ 允许一次有区别的修正；闸门关闭时的拒绝语不再含「状态不明」，
  带 `EXECUTION_BLOCKED`。另：预导出快照只在 `api.audio_input_enabled` 为真时做——能力关闭时
  `report()` / `should_escalate_audio()` 永远不会用这份材料，白花一次投递。
- `cloud_agent.py`：`tool()` 先看 `step.execution`（`unknown` 只给「交出去没等到完成」；`not_delivered`
  是普通失败；`blocked` 记 `not_executed` 并停止投递）；`execution` 为空（外部替身/本地工具）时才退回
  按文字判断，对自定义执行器仍然保守；新增 `blocked_attempts(state)` 进报告上下文（原来只有
  `missing_reason`，装不下真正的原因）；`report_instructions(config, state)` 只在**本轮真有失败记录**时
  追加失败说明（`audio_input=false` 不等于无法测量）。⚠️ 提示词预算很紧：`drive()` 把系统提示算进输入
  开销，2048 上下文的预算用例只剩约 100 token 余量，**加一句就要量一遍**（`test_low_context_reserves_report`、
  `test_general_continue_preflight_matches_actual_dialogue_context` 会红）。

### 验证（含真机 + 真云端 + 重新打包）

- 新回归 `ai/tests/test_delivery_state.py`：**10/10 通过**；把两个文件回退成修复前语义后
  **7/10 失败**（`verify-delivery-state-red.log` / `-green.log`）。
- 相关 249 项、完整套件 **798 项 0 failures + 5 errors**（5 个都是既有环境问题：
  4×`test_cloud_protocol` 的 `httpx2` 代理解析、1×`test_report` 缺 `parselmouth`）。
- **真机**（Medium Praat）：`ai/tests/verify_delivery_live.py` **11/11**——消息文件可写、真实投递、
  两条 vot 都 `DELIVERED`、合成声音（真值 15 毫秒）自动 24.0 / 两点相减 15.0 毫秒、
  写不进去时是 `NOT_DELIVERED`、报告上下文带真实原因；**用户自己的 `あなた.wav`（选区
  0.437403–0.635206）测出 `VOT = 38.0 毫秒`**（`verify-delivery-live.json`）。
- **真云端**：`ai/tests/verify_delivery_live_cloud.py --send`（会花额度）走
  `process_cloud`：模型调 `vot` → `success/delivered` → 38.0 毫秒 → L2 报告正确区分
  「工具测量」与「缺听感」，不再说「audio_input=false 所以测不了」；3 次请求 46.8 秒
  （`verify-delivery-live-cloud.json`）。
- 回退点：`backups/delivery-state-20261002/`（改动前的 `chat.py` / `cloud_agent.py` /
  `cloud_workflow.py` + `*.diff`；`chat.py` 反向还原后核对到改动前 137748 字节）。

### 重新打包与发布（v7.0-zh.5，等用户的 token）

- 用户问「改过的前端有没有和 install 合并」→ **没有**：19:17 那版清单里 `chat.py`/`cloud_agent.py`/
  `cloud_workflow.py` 哈希与当前源码不同，新模块 `delivery.py` 不在清单里。已重新打包。
- 新包：`AIPraat-install.exe` **55,732,224 字节**，SHA-256
  `ed2e8abc91ada789983e22fc7c0979df2be28cf8c00fcb70c7cd4dc6b88fbdb0`；载荷 74 个文件、清单 73 条
  全部与当前源码一致；`Praat.exe` 与上一版包内相同（本轮没重编原生程序）。
  校验脚本：`python installer/verification/verify-delivery-package.py`（本轮新增，73/73 通过，
  产物写 `installer/verification/delivery-artifacts.json`）。
- ⚠️ **`Praat.exe` 的哈希不是文档里写的 `cca8ef98…`**：现在（以及 19:17 那版包里）都是
  `777b54ff1ed57484be27aba83f79c22c62b87c3ce8406b2a4f2b0f3b8e7ab37f`（98,873,344 字节，
  mtime 今天 15:42）。旧文档那一条是过时的；`verify-staircase-package.py` 里把它写死成基线，
  所以那个脚本现在会红——本轮改用「与重打包前记录一致」的方式断言。
- ⚠️ **`installer/build.ps1` 补了 UTF-8 BOM**（6049 → 6052 字节）：它一直是 UTF-8 无 BOM，5.1
  按 ANSI 读会把载荷里「使用说明」的文件名打成乱码 `AIPraat-浣跨敤璇存槑.md`（我第一版重打包
  就是这样，被包校验抓出来的）。以后直接 `powershell -File installer\build.ps1` 即可。
- 发布脚本：`installer/publish-release.ps1`（纯 ASCII、参数化，只新建 release，同名就停下、
  不动既有资产）。默认新建 tag `v7.0-zh.5`，正文取
  `docs/2026-10-02-release-notes-v7.0-zh.5.md`，上传安装包 + `AIPraat-frontend-fix-20261002.zip`
  （源码修复包，由 `installer/build-frontend-asset.py` 生成，已核对不含 API Key）：
  `powershell -NoProfile -ExecutionPolicy Bypass -File installer\publish-release.ps1`
  **需要用户自己的 GitHub token**（本机没有凭据、没有 `gh`；脚本交互式隐藏输入）。
  重打包前的产物备份在 `backups/installer-before-repack-20261002-delivery-fix/`。

### 分支推送（2026-10-02 夜，tag v7.0-zh.5 之后）

用户要求「包括主页面的其他文件也一块推上去」。**`modern` 已推送**：
`2740ae17a071` → **`84f5d3ec5fe3dfde1e1efc0d641b9e61a045c6ab`**（327 个文件 / 4.78 MiB）。

- 推送**没有克隆仓库**：本机代理会把大响应截断（递归树 JSON 1.78 MB 每次短几千字节、
  55 MB 附件只有 ~13 KB/s），所以用 Git Data API（blob → tree → commit → 更新 ref），
  逐路径查状态。工具：`python installer/push-frontend.py`（默认 dry run，`--push` 才推，
  需要 `GITHUB_TOKEN`）。
- ⚠️ **原生 C++ 一律不推**（3070 个文件跳过）：线上 `modern` 的原生侧比本地快照新
  （`PraatAiControl_addModelMenu` 被线上 `sys/praat_objectMenus.cpp` 调用、
  `fon/SegmentAcoustic*` 分段声学分析、`MelderFile_replaceAtomically`、
  `v_createExtraToolbarButtons`）。本地缺这些，推上去**原生树会链接不过、还会删掉上游功能**。
  这条规则已写进推送脚本（按后缀/文件名识别原生文件）。
- 另外跳过：会丢线上内容的文件 1 个（`docs/ai-frontend/DESIGN.zh-CN.md`）、非文本 543、
  >8 MiB 2 个、安装验证夹具与 `ai_config.json`（后者绝不进仓库）。
- 建树用 `base_tree = 线上树` → **不删除任何线上路径**；上传前对每个字节做密钥扫描。
- 推送后核对：前端 7/7 与本地一致、原生 6/6 未变、线上独有 6 个文件仍在。
- 回退：`refs/heads/modern` 指回 `2740ae17a07181f8dae3d6aa927ae18cf9ac9ad1`。
- 注意：release tag `v7.0-zh.5` 仍指向 `2740ae17`，release 页的 "Source code" 归档是推送前的
  源码；本次修复的源码在附件 `AIPraat-frontend-fix-20261002.zip` 里。若想让归档也是新的，
  需要在 `84f5d3ec` 上再建一个 tag/release（**没有擅自移动已发布的 tag**）。

### 本会话环境的两个坑（下次省时间）

1. **大响应会被代理截断**：GitHub API 的递归树（1.7 MB）稳定短几千字节 → 用逐路径
   `/contents/<path>` 小请求代替；PowerShell 的 `Invoke-WebRequest` 下 55 MB 附件只有
   ~13 KB/s 且会卡死，10 个并发分块又被代理 TLS 拒（`schannel: failed to receive handshake`）。
   上传方向反而很快（55 MB 的 release 附件几分钟就传完）。
2. **`Start-Process` 在本机会直接报错**：环境里同时存在 `NO_PROXY`/`no_proxy`、
   `HTTPS_PROXY`/`https_proxy` 这类大小写重复的环境变量，PowerShell 建子进程环境字典时
   「已添加了具有相同键的项」。要用 .NET `ProcessStartInfo`（`UseShellExecute=false`）
   或 `cmd /c start`。<br>同理，`NO_PROXY` 里的 `[::1]` 会让 `httpx2` 在构造 OpenAI 客户端时
   抛 `Invalid port: ':1]'`（云端的假红来源）。

### 下次继续

1. **Low 标签已按方案 A 处理**（只改了 `稳定早期版\Praat.exe`），但**重新构建会前功尽弃**：
   新生成的 exe 继承目录的 Low，需要重跑那条 `icacls ... /setintegritylevel Medium`；受限会话
   也写不了现在这个 Medium 的 exe（重编译前先切完全权限或先改回 Low）。
2. 真机复验时别用已经死掉的 `chat.pid`：`start_ai_chat.py` 会看 pid 决定「新建还是置前」。
   Praat 重启后对象列表是空的，`Sound あなた` 需要用 `あなた.wav` 重新打开（这次验证脚本会自动
   读回来并留下一个 Sound）。
3. 本机跑套件要设 `TMPDIR/TMP/TEMP` 到工作区内 + 一个只把 `tempfile.mkdtemp` 换成 `os.makedirs` 的
   `sitecustomize.py`：0700 目录在沙箱下之后写不进去（连 `rmtree` 都失败），否则会出现与本改动无关的假红。
4. 本会话环境还有一个坑：`NO_PROXY` 里的 `[::1]` 让 `httpx2` 在 `AsyncOpenAI(...)` 构造时抛
   `Invalid port: ':1]'`，**任何**云端请求都发不出去（`verify_delivery_live_cloud.py` 里只在自身进程
   换成可解析的值）。这是环境/网络层的问题，值得当反馈发出去。
5. 既有小毛病（本次没改）：`vot` 自动估计跑完留下一个 `Harmonicity` 派生对象（`_build_vot_auto`
   建了 `hnrId` 没删）；继续（`continued()`）不复制 `attempts`，继续轮次的 `blocked_attempts` 为空。

## 2026-10-02 晚：折叠区「又打不开了」复查（**没有找到被回退的代码**）

用户报「GPT 干完活之后折叠修复好像被回调了，现在无法展开」。复查结论：

1. **折叠相关代码一个字没被改。** 与 `backups/dialogue-fastpath-20261002-d5ed1a31`
   （改动前的工作版本）逐方法比对：`_process_block_at` / `_on_process_right_click` /
   `append_hint` / `_begin_process` / `_finish_process` / `_render_process_header`
   **全部字节相同**；`<Button-3>` 绑定仍在（`chat.py` 第 1805 行）。
   `chat.py` 相对那个版本只多了三处：流式回复（`_begin_stream_reply` /
   `_append_stream_reply` / `_finish_stream_reply`）、`flush_messages` 里的
   `assistant-start/delta/final` 三个分支、以及 `close()` 里多一句 `_close_cloud_runtime()`。
2. **当前源码在本机真机环境（Python 3.14.8 + Tk 9.0.4）实测能开合**：真窗口 +
   真实 win32 右键（`SetCursorPos` + `mouse_event`，坐标按 1.25 反算 DPI 虚拟化）
   点标题行，`elide` 1→0→1 正常。
3. 19:17 那次重建的安装器（`AIPraat-install.exe` 56,220,672 字节）里嵌的
   `chat.py` **与当时的源码逐字节相同**，也带折叠功能。

所以「打不开」的成因**没能在本机复现**。本轮做的是「加固 + 留证据」：

- 新增同一次右键的**去抖**（`_ProcessBlock.last_toggle_at` +
  `_set_process_collapsed(..., debounce=True)`，窗口 `_TOGGLE_DEBOUNCE_SEC = 0.28`）。
  动机：一次右键若被投递成两个事件（`<Button-3>` + `<ButtonRelease-3>`，或按下后
  拖动又触发一次），两次取反会**互相抵消**，表现正是「点了没反应 / 闪一下又收起」。
  已用并排实验证明：旧写法连调两次 → 状态被抵消（先展开再收起）；新写法第二次被吃掉
  → 保持展开。（实测本机 Tk 9.0.4 只把 `<Button-3>` 送到处理器，所以这条是
  **契约级**加固，不依赖平台的事件投递细节。）
- 折叠相关回归从 12 条加到 **15 条**：新增「同一次右键的重复事件只切一次」
  「去抖窗口内的右键拖动不再切换」「间隔开的两次点击照旧各切一次」。
- 交接提醒：**改完 `ai/praat_ai/*.py` 必须关掉对话窗口重开**，否则跑的还是内存里的旧代码
  ——这是「修了但还是打不开」的最大嫌疑。

### 本次验证与已知的环境性失败（与改动无关）

- `ai/tests/test_chat_process_fold.py`：**15/15 通过**。
- 完整套件：**788 条，762 通过，21 failures + 5 errors**：
  - 21 条 `test_analysis_object_types` 真机用例：Praat 子进程写 `%TEMP%` 被拒
    （`No permission to create file`）。
  - 4 条 `test_cloud_protocol`：本机 `httpx2` 解析 localhost 代理串抛
    `invalid literal for int() ... ':1]'`（环境/代理问题）。
  - 1 条 `test_report`：这个 Python 环境没有 `parselmouth`
    （`requirements.txt` 里是 `python_version < "3.13"` 的可选依赖）。
- 过程中用 PowerShell 改 `chat.py` 踩过一次坑：`Set-Content -Encoding utf8` 在
  Windows PowerShell 5.1 下会把中文写成 GBK → 文件当场损坏。**改这个仓库的 Python 文件
  别用 PowerShell 的 `Set-Content`**，要么用编辑器，要么用 Python 读写（`encoding='utf-8'`）。
  这次靠改前的副本完整还原了（还原后 `ast.parse` 通过、字节数与副本一致）。

### 待办

- 若用户确认要重新发布，需要**再次重建安装器**：`chat.py`（19:38）比 19:17 那版新，
  当前 `installer/build/payload.zip` 里嵌的是 19:02 的 `chat.py`。
  命令：`powershell -NoProfile -ExecutionPolicy Bypass -File installer\build.ps1`。

## 最新交接：2026-10-02 单 API 阶梯逃逸首版

已按确认设计完成云端 Pydantic AI / Graph 编排、独立报告、直接音频能力设置与明确错误纠正、窗口内原目标继续、SQLite 查看记录及材料清理。本地 Qwen 规划路径保留。核心新增模块是 `cloud_agent.py`、`cloud_workflow.py`、`escape_policy.py`、`model_capabilities.py`、`materials.py`、`audio_probe.py`、`conversation_store.py`；框架依赖见 `requirements.txt`。

安装器和路径窗口已补齐依赖安装与检测；本次 `AIPraat-install.exe` / `AIPraat-paths.exe` 已重新构建，载荷包含当前源码（包括既有折叠区修正）。此前下方“部署缺口”属于历史记录，不能作为当前包的状态。主环境完整回归 706 项通过；验收与后续验证边界见 `docs/2026-10-02-阶梯逃逸实现验收.md`。模型功能探针只用随机合成音频，未使用真实 API 或用户录音验收细微发音准确度。

## 最新交接：2026-10-02 思考链折叠区「右键点不开」

用户报的现象：AI 前端的思考链折叠区（「已完成，用时X分Y秒 ▾」那一行）**右键点不开**。

### 结论先说

1. 折叠区的右键机制**本身是好的**。本轮在**用户真实运行环境**（Python 3.14.8 +
   Tk 9.0.4，`%APPDATA%\Praat\Preferences.txt` 里的 `Python.executablePath`）里，用
   **真实 Win32 右键**（`SetCursorPos` + `mouse_event`，不是 `event_generate`）点中
   标题行，`process_body` 的 `elide` 确实从 1 翻到 0、正文显示出来。
2. 但**命中范围太窄**，用户很容易点到「看着像标题、其实没有字符」的地方，表现就是
   「右键没反应」。这一轮修的就是命中范围。
3. **安装版（`AIPraat-install.exe`）里打包的 `chat.py` 是旧版，连折叠功能都没有**
   （见下面「部署缺口」）。

### 根因：Tk 的 `@x,y` 只落在**有字符**的位置上

`_on_process_right_click` 原来只做一件事：把点击坐标转成字符索引，再看这个字符上有没有
`process_header_N` tag。而标题行有两个地方「没有字符」：

- `hint` 的 `spacing1 = pad(4)` / `spacing3 = pad(6)` 是**行间空隙**，测试实测标题文字
  高 20px、而它所在的整行高 33px —— 上下各有 4~7px 的带子，点在那里 `@x,y` 会解析到
  相邻行，**差一行就完全没反应**；
- 标题文字右侧那一大片空白（实测 `bbox` 宽 906px，文字只有 154px 宽）：那里没有字符，
  `@x,y` 只能落在行尾的换行上，也拿不到 header tag。

用户说「右键点不开」，最可能就是点在这两种位置上。

### 改了什么

`ai/praat_ai/chat.py`，两处（没有动控件、没有动 `spacing`、没有动交互方式）：

- 新增 `_process_block_at(index)`：除了命中的那个字符，还看**该行行首/行尾**和
  **下一行的行首/行尾**。折叠时正文被 elide，正文那一行的字符索引正好紧接着标题行行尾
  （实测 `header tag range = ('7.0','8.0')`、`body tag range = ('8.0','10.0')`），
  所以「点在折叠区/标题下面那段行距」也能展开；展开状态下正文各行不会误命中。
- `_on_process_right_click` 改成调它，并补了 `tk.TclError` 保护。

回归：`ai/tests/test_chat_process_fold.py` 从 8 条加到 **12 条**，新增的四条分别钉住
「行尾空白」「标题下面那一行的行距」「标题上面的行距带」「离标题很远的地方右键不动任何
东西」。

### 复现/验收方式（下次别再用 `event_generate` 猜）

`event_generate("<Button-3>")` **测不出真机问题**：它不经过 Windows 的消息队列。本轮用的
办法是：主进程建真窗口、跑 Tk 事件循环，**另起一个进程**用 `SetCursorPos` +
`mouse_event(0x0008/0x0010)` 真点，再用 `transcript.bbox()` 量坐标。两个坑：

- 探针进程被 Windows 当成 **DPI 不感知**时会虚拟化坐标：`SetCursorPos(107,569)` 实际把
  指针放到 (134,711)，**要先把坐标除以 1.25 再传进去**（本机 125% 缩放）。
- 别在自己的线程里读 Tk（`RuntimeError: main thread is not in main loop`），
  要在 `root.update()` 所在的主线程里读状态。

### 部署缺口（重要，没动）

`installer/build/payload.zip` 里的 `ai/praat_ai/chat.py` 是 **20:17 构建时的旧版**，
`grep` 它**找不到** `elide` / `_begin_process` / `Button-3` —— 也就是**没有折叠功能**。
桌面 `稳定早期版` 里没有第二个安装副本，本机 C 盘也没有（`AIPraat.exe` 只在
`installer/build/` 下），所以「用户到底跑的哪一份」没定论。两种可能：

- 跑的是源码目录（`AI.projectDirectory: ai`，相对于 `Praat.exe`）：那么本轮修的是对的，
  **关掉对话窗口再打开**就会加载新代码（Python 不改已开着的窗口）；
- 跑的是安装版：那要先重新打包，命令是
  `pwsh -File installer\build.ps1`（会重新生成 `payload.zip` 与
  `AIPraat-install.exe`；`csc.exe` 在本机存在，不需要新装东西）。

**没有擅自重建 `AIPraat-install.exe`**：那是已验收过的交付物，包里的 `Praat.exe`
（98,627,072 字节）和仓库根目录的那份（98,643,968 字节）也不一样，重建前该先问清楚。

### 2026-10-02：已重新打包并**覆盖式更新**到 GitHub release

用户确认平时是从桌面 `稳定早期版` 跑源码，随后要求重新打包 exe 并上传。已完成：

- 打包命令：`powershell -NoProfile -ExecutionPolicy Bypass -File installer\build.ps1`
  （**必须用 Windows PowerShell**，本机没有 `pwsh`；脚本里有中文，**不能**用
  `pwsh -File` 之外的方式让 5.1 按 ANSI 读它——本轮踩过：UTF-8 无 BOM 的 .ps1 被
  5.1 当 ANSI 读，中文串错乱后 `releases/tags` 直接 404）。
- 新旧包差异（按 payload manifest 逐项比对，只有 3 个文件变了）：
  `ai/praat_ai/chat.py`、`AIPraat.exe`、`AIPraat-paths.exe`。
- 校验：61 项中 60 项哈希与 manifest 一致；包内 `chat.py` 与源码 SHA256 一致；
  包内 `Praat.exe` = `cca8ef98…24ee`（与仓库根目录一致）；没有混进
  `__pycache__` / `.pyc` / `ai_config.json` / `runtime` / `tests`。
- **覆盖后的线上资源**（release `v7.0-zh.4`，id `399223472`，未新建 tag）：
  - `AIPraat-install.exe` 55,586,304 字节，SHA256
    `812A1860C605AD76B623768338DA6A235C69F794F6BC31C71BD35B06DDA44E23`
  - `README.zh-CN.md` 5,238 字节，SHA256
    `D1FE0268A3FC0C16FE65998FD1A9CE0A912D30726284B5AA2D5024ADA9C58473`
  - release 说明也换成了本轮的中文 changelog。
  - 两个资源都**重新下载回来比对过 SHA256，与本地完全一致**。
- 覆盖前的旧交付物备份在 `backups\installer-before-repack-20261002\`。
- **注意**：覆盖同一个 tag 的资源，之前下载过的人不会收到任何提示；GitHub 的
  release 资源删除后不可回滚，要退回只能用上面那个备份重传。
- 上传是用 GitHub API（`POST /releases/{id}/assets`，先 DELETE 旧资源）做的，
  **没有走 git push**，所以没有碰 guide.md 里那条「origin 只有读权限」的约束。
  用过的 personal access token 用完请去 revoke（本轮用的是用户给的 classic token）。

### 本轮验证记录

- `ai/tests/test_chat_process_fold.py`：**12/12 通过**（Python 3.12+Tk 8.6 与
  Python 3.14.8+Tk 9.0.4 各跑一遍都过）。
- 完整 unittest：**659 条，637 通过，21 failures + 1 error**，全部是**环境性**、与本次
  改动无关：
  - `ERROR: test_report`：这个 Python 环境没装 `parselmouth`
    （`requirements.txt` 里它是 `python_version < "3.13"` 的可选依赖）；
  - 21 条 `test_analysis_object_types` 的真机用例：Praat 子进程写
    `%TEMP%\tmpXXXX\result.txt` 被拒（`No permission to create file`，
    error 13/5）——那是本会话沙箱/confinement 限制，不是产品缺陷。
  - 判据：这两组在环境换成 `C:\Users\f2468\.cache\codex-runtimes\...\python.exe`
    （Python 3.12 + `.build-tools\python-libs` 的 `parselmouth`）后**报错条数一模一样**，
    而且都在 `test_chat_process_fold` 之外的模块。
- 过程中新建的一次性探针脚本（`ai/runtime/probe_*.py` 等）已全部删除，没有留垃圾。

### 下次继续

1. 先问清楚用户跑的是源码目录还是安装版，再决定要不要重新打包（见上面「部署缺口」）。
2. 提醒用户：**改了 `ai/praat_ai/*.py` 之后，已经开着的对话窗口不会重新加载代码**，
   要关掉重开。
3. 如果还想加「左键点标题也能开」，先想清楚和文本选择的冲突（现在标题栏只能右键）。

---

## 最新交接：2026-09-30 基频「假峰值」问题（598.5 Hz）

用户看千问输出时发现一处可疑数字：**「前半段基频高达 159.9 Hz，峰值 598.5 Hz（0.061 秒处）」**。
这个观察是对的，而且**不是降噪问题**，是**倍频误判被当成结论**。

### 根因（有实测证据）

`pitch_statistics` 原来是这样出结论的：

```
To Pitch: 0, 75, 600
maximum  = Get maximum: tmin, tmax, "Hertz", "Parabolic"
maxtime  = Get time of maximum: tmin, tmax, "Hertz", "Parabolic"
```

`Get maximum` 取的是区间内**最高的那一帧**——一帧就定结论。而短时自相关在
**浊音起始**（第一帧有声的位置）很容易把真实基频听成 2–4 倍。实测
`test/fon/examples/sounds/a.wav`：

| 取法 | 最高基频 | 时刻 | 中位数 | 95 分位 |
| --- | --- | --- | --- | --- |
| 裸 `Get maximum`（修前） | **496.65 Hz** | 0.2221 s | 110.46 Hz | 121.61 Hz |
| 逐帧限幅（修后） | **129.06 Hz** | 0.2521 s | 110.46 Hz | 121.61 Hz |

496.65 ≈ 4 × 121.6，而 0.2221 s 正好是**第一个有声帧**。用户那组数字形状完全一致
（598.5 / 159.9 ≈ 3.7 倍，0.061 s 在文件起头），所以基本可以确定是同一个机制。

**用户的两个猜测，实测结果**：

- 「0.061 秒那里只有噪音」→ 纯噪声**不会**造出假峰值。Praat 在噪声段直接返回
  `--undefined--`（受控实验：0.15 s 低电平噪声 + 120 Hz 正弦，噪声段没有伪值）。
  伪值来自**有声段的第一帧**，不是噪声段。所以这条不是「没做降噪」。
- 「很难到达这个频率」→ 对，那个数不是你的基频，是自相关的倍频误判。

**试过但不能用的修法**：给 `To Pitch (ac)` 显式传声学参数（浊音阈值、倍频程惩罚…）。
本机 Praat 7.0.02 的十参数形式**在任何静音阈值下都把全部帧判成清音**（0/157 有声），
而 3 参数版有 85/161。静音阈值从 0.03 试到 0.000003 都一样。所以那条路不通，
不要去「调 Praat 参数」，修法放在**怎么挑那一帧**上。

### 改了什么

把「最高/最低基频」和「最高点时刻」都改成**逐帧扫描 + 限幅**：

- 上限 = 中位数 × 1.5（倍频误判必然 ≥ 2 倍，1.5 够宽，不误伤真实高基频）；
- 下限 = 中位数 × 0.5（次谐波误判）；
- 原始最大值超过上限时，结果里**必须**写一句「该区间有一帧被自相关误判成 X Hz
  （中位数的 Y 倍），已按倍频误判剔除」——不静默改数，用户和模型都能看到。

三处都改了（两条路给出的数必须一致）：

1. `ai/praat_ai/tools.py` 的 `_pitch_extreme_lines()`，被 `_build_pitch_statistics`
   和 `_build_pitch_peak_latency` 用（后者原来也用裸 `Get time of maximum` 取峰值时刻，
   实测 `a.wav` 上峰值时刻从误判的 0.2221 s 修正到 0.2521 s）；
2. `ai/praat_ai/measures.tsv` 的 `maximum_pitch` / `minimum_pitch`（表里的 `measure`
   路径原来也是裸 `Get maximum`，同一条真机上又被抓到）；
3. `ai/plugin/praat_ai/praatAiMeasure.praat` 是**生成物**，用
   `python ai/tools/build_plugin.py` 重新生成（`--check` 现在通过）。

**注意别误判**：`maximum = Get maximum: tmin, tmax, "Parabolic"`（**没有单位参数**）
是**强度**的最大值，完全合法——强度没有倍频问题。只有带 `"Hertz"` 的才是基频极值。

### 顺带修掉的两个真 bug（都是这次改动暴露出来的）

1. **圈选范围会让脚本直接报错**。`Get frame number from time:` 返回的是**小数**
   （0.25 秒 → 31.5），而 `Get value in frame:` 要整数。整段分析时两端恰好落在整数帧上，
   所以没暴露；一旦用户圈选（0.25–0.5 秒）就报「should be a whole number」。
   **注意**：Praat **不允许把命令嵌在公式里**——`round (Get frame number from time: tmin)`
   会报 `Unknown symbol`，必须先取值再 `round`。
2. **收尾那轮失败会作废整轮结果**（真机验收时发现）：工具全跑完了，最后
   `planner.wrap_up()` 网络读超时抛 `QwenError`，异常直接穿到调用方，用户什么也看不到。
   现在重试一次，再失败退回本地拼的 `_summary_of(outcome)`，原因写进 `notes`。

### 测试与验证记录

- 完整 unittest：**621/621 通过**（日志 `verify-final-tests.log`）。
- 完整模板验收（真 Praat）：**101/101**（日志 `verify-final-templates.log`）。
- 真云端 + 真 Praat 组合验收：`ai/tests/verify_cloud_live_analysis.py --send`，
  轨迹 `verify-cloud-live-analysis.json`。**用的是 Praat 自带测试音频，不是你的录音。**
- 新增回归：`test_analysis_object_types.py` 两条（限幅契约、Pitch 对象不重复转换）、
  `test_chat_tools.py` 两条改成断言新契约、`test_measures.py` 一条、
  `test_plugin_build.py` 一条、`test_workflow_context.py` 两条（收尾降级）。
- 诊断过程用的一次性脚本已删除（不留垃圾）。

### 已知取舍（下次可以商量）

- 限幅用「中位数 × 1.5」。如果一段**真实**基频跨度超过中位数的 1.5 倍（例如刻意做了
  很大的语调起伏），最高的那些帧会被剔除。实测四段音频里只有真正误判的那段被改，
  另外三段数值**一字未变**。要更保守可以改成 2.0（但 2.0 正好是倍频的边界，会漏掉
  恰好 2 倍的误判）。
- 只改了「最高/最低/最高点时刻」。`pitch_slope`（平均绝对斜率）等仍然受倍频跳变影响，
  表里已经有 `pitch_slope_octave_free` 走 Praat 自己的 `Get slope without octave jumps`。
- **用户的 `plan_max_tokens` 是 1500，模型输出会被截断**。真机验收时出现过一次
  「模型回答未完成：模型输出达到长度上限…」——工具都跑完了，只有最后的回答被截断。
  用临时配置把 `plan_max_tokens` 提到 4000 后，同一条请求给出 2089 字的完整回答。
  这是**用户自己的配置选择**，没有替他改；建议在「API 配置」里调大。
  `verify_cloud_live_analysis.py` 目前用真机批处理跑，所以 `view_edit`
  （需要 GUI）在批处理里必然失败（`Cannot edit a Sound from batch`）——那是脚本环境的
  限制，不是产品 bug，验收里已按此理解。

---

## 最新交接：2026-09-30 接手复查（Harmonicity 故障链 + 同类错误排查）

本节覆盖下方 9/29 一节的部分结论；9/29 的修复本身仍然有效，这里只写**本轮新增**。

### 要修的故障（用户报的，已闭环）

现场：1 号是 `Sound あなた`，2 号是 `Harmonicity あなた` 且为当前选中。

```
1. select_object: 1        ← 成功选中 Sound
2. selectObject: 2         ← 后续脚本又选回了 Harmonicity
3. To Pitch / To Intensity / To Formant (burg)  ← 对 Harmonicity 全报错
```

两个根因在 9/29 已修好，本轮**复核并加了端到端回归**：

- 选择变化不同步到本轮工具上下文 → `chat.run_agent_loop` 每个动作之后重新读对象列表
  （`chat.py:834` 一带），失败就停后续动作。新回归
  `test_user_failure_chain_never_analyses_the_harmonicity` 直接复现这条链：先选 Sound、
  再连做基频/强度/共振峰，断言三个脚本第一行都是 `selectObject: 1`、且都不出现
  `selectObject: 2`。
- 类型检查过宽（原来看「有时长」就放行）→ 每个分析模板收窄到「Sound + 对应派生对象」
  （`_build_pitch*` = Sound/Pitch，`_build_intensity*` = Sound/Intensity，
  `_build_formant*` = Sound/Formant，`_build_harmonicity_statistics` = Sound/Harmonicity）。
  显式给错 id 直接报错，不偷偷换对象；没给 id 时才允许按类型找唯一候选。

### 本轮**新发现并修掉**的实质缺陷：时间参数别名不一致

云端的 `CLOUD_WORKFLOW_INSTRUCTIONS`（`qwen.py:111`）明确教模型：「整段、整个、完整声音的
请求必须使用 `from=0`，终点使用该对象实际 duration」，`pitch_statistics` /
`intensity_statistics` / `formant_statistics` / `harmonicity_statistics` / `measure` 的
schema 也确实只有 `from`/`to`。但 `extract_part` 和 `textgrid_set_interval` 的 schema
写的是 `start`/`end`：

| 工具 | `from`/`to` | `finish` | 修前行为 |
| --- | --- | --- | --- |
| `extract_part` | 认 | 认 | 正常（`dict.get` 的默认值是**先求值**的，别名真的取得到） |
| `textgrid_set_interval` | 不认 | 认 | 「把 0.2–0.6 秒标成 a」直接报「标注区间需要 end 参数」 |

也就是**同一句话在截取里能跑、在标注里报错**。已修：`_build_textgrid_set_interval` 改成和
`extract_part` 同一套别名，两个工具的 schema 与 `signature` 都补上 `from`/`to`。
注意 `test_planner_tools.test_schema_parameters_match_the_documented_signature` 会把
`signature` 里**括号内**的内容先删掉，所以别名必须写在括号**外面**，否则守卫会红。

新增回归：`ai/tests/test_range_aliases.py`（11 项，纯 Python，不需要 Praat），
外加模板用例 `textgrid_set_interval-from-to`、`extract_part-from-to`。

### 本轮复核过、确认**没有**问题的点（别重复怀疑）

- `TIME_DOMAIN_CLASSES` 里删掉 `Manipulation`/`Polygon`/`Cochleagram`/`Excitation` 是对的。
  用真实 Praat 逐个实测 `Get total duration`：只有 Sound / LongSound / Pitch / Formant /
  Intensity / Harmonicity / Spectrogram / MFCC / PointProcess / TextGrid / TextTier /
  PowerCepstrogram 支持；Manipulation / Spectrum / Ltas / Cochleagram **不支持**。
  （`IntervalTier` 从来没有作为对象类名出现过——`Extract one tier:` 出来的对象
  `selected$()` 报的是 `TextGrid words`，所以它留在拒绝名单里无害。）
- `measure` 的派生对象判定不是过窄：条件是「所需来源 ⊆ 该对象能提供的那**一个**来源」。
  实测 `PointProcess` 上的 `local_jitter`/`rap_jitter`、`PowerCepstrogram` 上的 `cpps`、
  `Spectrum` 上的 `centre_of_gravity`、`Harmonicity` 上的 `hnr` 都能跑；只有需要
  两个来源的 `local_shimmer_*`（`pointProcess+sound`）被拒，而那条本来就需要一个 Sound。
- 云端/本地 Prompt 是**分流**的，不是叠加：`planner_instructions()` 在 `provider=="api"` 时
  返回 `CLOUD_WORKFLOW_INSTRUCTIONS + analysis_instructions()`，本地才用
  `TOOL_PLANNER_INSTRUCTIONS`。`TOOL_PLANNER_INSTRUCTIONS` 全文只被本地分支引用一次，
  不会把「不要顺手多做」「一次只做一件事」这类本地小模型约束漏给云端。

### 本轮顺手收紧的小地方

- `chat._request_context` 原来用 `len(fields) >= 6` 清选区，列数更多时会**截断**掉多出来的列；
  现在只改「正好 6 列且首列是数字」的行，并把末尾换行补回来，行数/顺序/制表符都不变。
  整段识别也补上了 `整个波形` 和 `the whole recording` / `the entire file` 这类说法。
  新增 8 项断言（`RequestContextTests`）。
- **收尾那轮失败不再丢掉实测结果**（真机验收时发现）。收尾（`planner.wrap_up()`）只是把
  已经测到的数字写成一段中文；它遇到网络读超时抛 `QwenError` 时，原来会直接把异常抛到
  调用方——整轮的结果全部作废，用户什么也看不到。现在收尾失败**重试一次**，再失败就退回
  本地拼的 `_summary_of(outcome)`，并把原因写进 `outcome.notes`。
  回归：`test_wrap_up_failure_still_returns_measured_results` /
  `test_wrap_up_failure_recovers_on_retry`。

### 真机验收：真云端 + 真 Praat（2026-09-30，交接里一直标着「未组合」的那一项）

新增 `ai/tests/verify_cloud_live_analysis.py`（`--send` 才真发），用 **Praat 自带的测试音频**
`test/fon/examples/sounds/aaaa02.wav`（7.6 秒，**不是用户录音**），把真云端 HTTP 和真 Praat
批处理接在一起跑用户原话「分析整段语音，指出我的发音有哪些不足」。

结果 **8/8 通过**（轨迹存在 `verify-cloud-live-analysis.json`）：

- 7 个脚本**全部**在真 Praat 里跑完并写出完成标记，`selectObject` 全部指向现场对象或脚本
  自己的临时对象变量；
- 5 处 `To Pitch:` / `To Intensity:` / `To Formant (burg):` / `To Harmonicity (cc):` /
  `To Spectrum:` **全部作用在 Sound 上**（不是 Harmonicity）——这正是用户报的故障链；
- 整段请求的时间范围真的进了脚本（4 步带范围，`0–7.600`）；
- 拿到 25 行实测结果；最终回答 2161 字，区分了观测/一般知识/建议。
- **模型表现**：自己先 `duration` 探时长、再按 `from=0, to=7.6` 做整段测量，之后用
  `measure` 批量取 HNR/CPPS/频谱矩——说明放宽后的云端 Prompt 确实在驱动多步分析。

两个**新观察**（本轮没动手改，留作下次的输入）：

1. 云端有一次工具调用 `formant_frequency` 的参数是**不是完整合法的 JSON**，被
   `invalid_arguments` 机制在执行前挡下（没有拿空参数去动默认对象），模型随后改用
   `measure` 取到了共振峰。这条降级路径在真机上第一次被用到，行为是对的。
   `verify-cloud-live-analysis.json` 的 `failure` 字段留着这次记录。
2. 输入是一段**持续元音**（合成素材），模型却据此推断「语调单调、像念经」「可能嘶哑」。
   数值本身没编（F0 标准差 3.01 Hz、HNR 11.73 dB 都来自实测），但**把持续元音的性质
   当成了说话人的发音问题**。下次可以考虑在 `CLOUD_EVIDENCE_INSTRUCTIONS` 里补一句：
   分析素材是持续元音/单音节时，不得推断语流层面的语调、节奏问题。

### `Praat.exe` 已替换（2026-09-30 用户要求）

- 旧程序备份：`D:\Praat-work\稳定早期版-Praat-exe备份-20260930\Praat.exe`
  （SHA256 `6D6020954EAB4AD4D08C4A24FD589B72FE5530AD79CCE0DD67D5580EF1818EEC`）。
- 仓库根目录 `Praat.exe` 现在是 9/29 构建的新版
  （SHA256 `31E748DE244059237B72817C3D79C1CE422D34D4D3A49012EBBE33341C1E046F`，
  `Praat 7.0.02 (August 26 2026)`）。替换前确认过没有 Praat 进程占用。
- 同目录 `Praat-fixed.exe` 保留着（和现在的 `Praat.exe` 内容相同），可以用它做新旧对照；
  不再需要它，删掉也不影响任何脚本。
- 因此 `praat_app.find_praat()` 现在找到的就是新版，快捷方式不用改。
  `ai/tests/verify_callback_completion.py` 里的硬编码 `Praat-fixed.exe` 已改为读
  `PRAAT_AI_PRAAT_EXECUTABLE`、默认 `Praat.exe`。
- 替换后复验：`verify_callback_completion.py` **5/5 通过**（真实隔离 GUI，含
  `# praat-protocol=2`、提前写 `done` 仍等最终对象，以及「Harmonicity 转换失败后
  对 Sound 的基频/强度/共振峰仍然成功」），模板验收 100/100。
- **注意**：以后重新编译会生成新的 `Praat.exe`，那时同样要确认它包含协议修复
  （`verify_callback_completion.py` 会替你验）。

### 验证记录（本轮）

- 完整 unittest：**617/617 通过**，66 秒。日志 `verify-object-workflow-tests-rerun.log`。
  （9/29 是 596；本轮新增 21 项 = `test_range_aliases.py` 11 项 +
  `test_workflow_context.py` 10 项。）
- 完整模板验收（真 Praat）：**100/100 通过**，日志
  `verify-object-workflow-templates-rerun.log`。`read_file-missing` 已按 9/29 交接要求
  改成「必须中途失败」，靠新增的 `Case.expect_error`。
- 真机分析对象回归：`test_analysis_object_types.py` **18/18**（该文件现在认
  `PRAAT_AI_PRAAT_EXECUTABLE`，与 `praat_app.find_praat()` 同一优先级）。
- 真云端 + 真 Praat 组合验收：**8/8 通过**（见上面专门一节），轨迹
  `verify-cloud-live-analysis.json`，日志 `verify-cloud-live-analysis.log`。
- 真实隔离 GUI 回调验收：`verify_callback_completion.py` **5/5 通过**，日志
  `verify-callback-completion.log`。
- 本轮改的都是 Python（`ai/praat_ai/tools.py`、`ai/praat_ai/chat.py`）和测试、文档，
  **没有动 C++、不需要重新编译**。`Praat.exe` 按用户要求换成了 9/29 构建的新版
  （见上面专门一节）。
- 真机验收只用了 Praat 自带的测试音频，**没有发送用户录音**；没有改 `ai_config.json`、
  没有动用户的 API 密钥与模型选择。

### 下次继续（按价值排序）

1. **前端必须关掉重开**才会加载本轮 Python 修改。`Praat.exe` 已经是新版，快捷方式不用改。
2. 云端 Prompt 可以再补一条「分析素材是持续元音/单音节时不得推断语流层面的语调、
   节奏问题」（见上面「新观察」第 2 条）。
3. 边界补测：重命名/删除/导入后的下一步对象状态；同一工具在多个对象上部分失败时，
   失败状态会不会被「按工具名清除」过度清掉（`unresolved` 以工具名为键）。
4. 想要更贴近真实使用的话，用**用户自己的录音**再跑一次
   `verify_cloud_live_analysis.py`（把脚本里的 `AUDIO` 换掉）——那会把这段录音发到
   云端，跑之前先跟用户确认。

---

## 2026-09-29 对象工作流与 API Prompt（历史，仍有效）

**用户要求阶段收尾：额度将尽，当前步骤做完并更新交接，不再扩展任务。**
本节覆盖下方 9/23 历史现场状态；不要将旧分支、进程、端口和配置说明当作当前状态。

### 当前目录与授权

- 本次工作目录：`D:\Praat-work\稳定早期版`，为导出快照，没有 `.git`，因此没有提交、推送或新工作树。
- 原始授权：自主修复工作流、检查脚本和 Prompt 中同类错误，并放宽 API 模式 Prompt。
- 本次未更改用户 API 密钥、模型选择或录音。启动故障上一阶段已恢复本机已有的 `ai_config.json`；不要打印该文件全文或把密钥写进日志。
- 源码备份：`D:\Praat-work\稳定早期版-对象工作流修复备份-20260929`。此前启动修复另见 `D:\Praat-work\稳定早期版-前端修复备份-20260929`。
- 自主执行计划：`docs/superpowers/plans/2026-09-29-object-workflow.md`。

### 故障证据与已实现修复

用户请求“分析整段语音指出不足”，随后出现 Harmonicity 信息，以及 `To Pitch:`、`To Intensity:`、`To Formant (burg):` 不可用于当前选择。
保存的三份故障脚本都先 `selectObject: 2`，2 号实际上是 Harmonicity；1 号才是 Sound。
选中 Sound 的前一步虽然执行了，Python 后续仍使用请求开始时的旧对象列表。
仅凭现存脚本不能证明云端当时显式给了 2 号还是使用默认对象；没有保存那次 API 参数。

1. `ai/praat_ai/chat.py`：每一步刷新对象状态，原生与 JSON 规划器都同步最新列表；刷新失败停止后续操作。整段请求移除旧编辑器选区，显式时间参数仍有效。重复调用按对象状态区分，失败不会被重复缓存改成成功，同一工具改正后清除已恢复的失败状态。
2. `ai/praat_ai/tools.py`：分析工具只接受 Sound 或对应派生对象。明确错误 id 不偷偷替换；默认类型不匹配时仅使用唯一合法候选，多个候选或同名歧义报错。修复 LongSound 的播放/提取/信息命令、Intensity 斜率重复转换和原对象误删、时间参数别名、无效范围静默整段、多对象文件导入，以及缺文件被当成功。
3. `ai/praat_ai/qwen.py`：API 采用独立云端流程提示，支持 Markdown、完整多步分析、相关知识解释和透明计算；strict 知识模式只收紧依据，不恢复本地单操作限制。原生、JSON、纠音、视觉解释共享证据规则。不能编造实测、把失败当结果，或在未收到音频时声称听过录音。
4. API 执行预算为最多 8 轮、20 个实际动作；本地保留 3 轮、5 步。后续轮次允许分析所需的对象准备。到上限时为所有未执行 tool call 回灌说明，避免缺 `tool_call_id` 响应。原生 API 多轮重新核算消息预算，必要时截短过长工具结果，保留调用配对；完整结果仍在前端和文件中。
5. 损坏工具参数携带 `invalid_arguments` 并在执行前拒绝，不能退成空参数去删除默认选中对象。JSON 动作保留错误标记及 id；旧 JSON 顶层自定义脚本重新兼容。
6. 原生协议：`sys/PraatAiControl.cpp/.h`、`sys/praat.cpp`。修复错误文件晚于 `done` 的顺序；对象列表用临时文件原子替换。新列表声明 `# praat-protocol=2`；回调完成错误和最终对象写入后，最后写 `chat_finished.txt` 的 `finished <请求编号>`。Python 必须等匹配编号。旧程序无协议头时保留兼容路径，但完整时序修复需要新版程序。

### 验证与构建

- 新回归文件：`test_analysis_object_types.py`（18 个）、`test_cloud_prompt.py`（10 个）、`test_workflow_context.py`（13 个）。新增测试先确认失败再修复。
- 对象工具的真实隔离 Praat 批处理已通过：已有派生对象查询及保留、Sound 范围/别名与临时对象清理、LongSound 信息/提取、多对象导入、缺文件终止。未操作用户 GUI。
- `ai/tests/verify_callback_completion.py` 已通过 5 项真实隔离 GUI 消息测试：提前写 `done` 仍等到最终选择/改名；原生错误在完成返回前可读；报错后 Sound 的 Pitch、Intensity、Formant 三个统计继续成功。使用临时 USERPROFILE/APPDATA/AI 目录、指定自建进程 pid；只关闭自建进程。
- 云端 HTTP 测试拦截网络发送，不调用真实云端、不发送用户音频、不消耗 API 额度。本次没有实际云端完整语音分析验收。
- 全套 unittest 最终 **596/596 通过**，耗时 66.578 秒，见 `verify-object-workflow-tests.log`。前一次测试夹具用了本地 8192 上下文，改成 API 默认 32768 后重新跑完整套并通过。
- 构建命令：MSYS2 CLANG64，`make PRAAT_ARCH=x64v3 EXECUTABLE_FILE=Praat-fixed.exe -j12`，成功生成 `Praat-fixed.exe`；版本命令成功。构建日志：`verify-object-workflow-build.log`。
- 新程序 SHA256：`31E748DE244059237B72817C3D79C1CE422D34D4D3A49012EBBE33341C1E046F`。
- 原生回调测试日志：`verify-callback-completion.log`。
- **已打开的 Python 前端不会自动加载源码修改，必须关闭再打开。Praat 也需启动新版可执行文件。**
- 收尾时用户原程序仍为 pid **10600**，路径 `D:\Praat-work\稳定早期版\Praat.exe`。没有结束这个进程、覆盖运行中的程序或更改其声音对象。新版保留为同目录 `Praat-fixed.exe`，尚未替换旧 `Praat.exe`。下次先保存并关闭旧 Praat 与前端，再运行新版；若要继续使用原快捷方式，在旧进程退出后备份旧 exe 再将新版复制成 `Praat.exe`。不要删除唯一的旧程序备份。

### 下次继续的具体步骤（不重复已通过工作）

1. 核对文末本阶段最终 unittest 和可执行文件部署记录；优先做独立源码审查，尤其原生确认协议、状态刷新、取消、预算裁剪与失败恢复。
2. 更新 `ai/tests/verify_chat_templates.py` 中 `read_file-missing` 的旧期望：以前“找不到 + done”被当成功，现在必须提前失败。再运行完整模板验收；这次未因额度限制启动整套模板。
3. 补足“重命名/删除/导入后下一步对象状态”、同参数在状态变化后重新执行、JSON 大量观察的预算，以及多轮失败恢复的端到端覆盖。当前有新对象、选择、刷新失败、调用配对等单测，并非这些边界均已完整覆盖。
4. 将假 API 的 HTTP 请求与真实隔离 Praat 多步执行组合验证；现有 HTTP Prompt、执行循环和原生协议分别通过，尚未组合验收。随后在用户需要时用真实 API 重试“分析整段语音指出不足”。保持区分实测/推导/一般知识，没有收到音频或参照不能声称已听到具体发音问题。
5. 已发现但本次未扩展处理：非零时间原点对象的范围语义；运行时异常可能遗留临时分析对象；“不要分析整段”等否定语句的整段识别边界；极长新对象列表的逐轮预算；失败恢复目前按工具名清除错误，多个对象同工具的部分失败需核查是否过度清除。

### 复跑方式

```powershell
Set-Location 'D:\Praat-work\稳定早期版'
$env:PYTHONPATH = (Join-Path (Get-Location) 'ai')
$env:PYTHONIOENCODING = 'utf-8'
& 'D:/Praat-work/venv-ai/Scripts/python.exe' -B -m unittest discover -s ai/tests -v
& 'D:/Praat-work/venv-ai/Scripts/python.exe' -B ai/tests/verify_callback_completion.py
```

以下保留旧项目交接历史，其中远端权限说明仍须保留；旧现场状态不适用于本次导出目录。

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
