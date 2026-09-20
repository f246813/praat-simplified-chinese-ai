# Praat ZH AI Agent 维护指南

本文件面向后续接手本仓库的 AI agent。它不是项目宣传稿，而是任务执行手册：先判断任务属于哪条工作流，再按现有代码结构修改、生成和验证，避免被旧说明或表面文件误导。

## 0. 接任务后的默认动作

1. 先看工作区状态，不要覆盖用户已有改动：

   ```powershell
   git status --short
   git diff --stat
   ```

2. 再按任务类型定位源码：

   - UI / 菜单 / 对话框文字：优先看 `tools/generate_translation_map.py` 和 `sys/praat_translate.cpp`。
   - 内置帮助手册：看 `fon/manual_*.cpp`，必要时用抽取脚本生成双语审校材料。
   - Windows 文件拖拽：看 `sys/motifEmulator.cpp`、`sys/GuiMenu.cpp`、`sys/praat_objectMenus.cpp`。
   - 启动时图像窗口隐藏：看 `sys/praat_picture.cpp` 和 `sys/praat_objectMenus.cpp`。
   - 发布打包：看 `.github/workflows/release-windows.yml`、`README.txt`。

3. 修改前先读相关上下文。不要只凭英文字符串全局替换；Praat 有大量手写宏、菜单别名和旧拼写，错误替换很容易导致启动时报错或 UI 不匹配。

4. 如果用户给的是截图里的“漏网之鱼”，先把截图转成受控清单和定位表，不要立刻做全仓库审计。清单越窄，修改越快也越安全。

## 1. 项目现状速览

本仓库是 Praat 源码的非官方简体中文本地化版本，不是基于 gettext/Qt/i18n 框架的普通翻译项目。当前中文化主要由三部分组成：

- 运行时 UI 翻译：`sys/praat_translate.cpp` 中的 `g_translation_map`，通过 `praat_translate()` 被 GUI 和表单代码调用。
- 内置手册翻译：直接改 `fon/manual_*.cpp` 中的 Praat 手册源字符串。
- 本地化功能差异：Windows 原生拖拽打开文件、启动时默认隐藏 Picture window，并在 Objects 窗口的 Praat 菜单提供打开入口。

当前仓库还包含若干用于抽取、恢复、审校翻译的 Python 脚本和中间产物。永久性翻译维护应优先改规范源头，不要把临时审校输出当作唯一真相。

## 2. UI 翻译工作流

### 2.1 真正的入口

UI 翻译运行时入口是：

- `sys/praat_translate.h`
- `sys/praat_translate.cpp`

翻译函数已接入这些常见控件路径：

- `sys/GuiButton.cpp`
- `sys/GuiCheckButton.cpp`
- `sys/GuiDialog.cpp`
- `sys/GuiLabel.cpp`
- `sys/GuiMenu.cpp`
- `sys/GuiMenuItem.cpp`
- `sys/Ui.cpp`

如果某个新 UI 文本完全没有被翻译，先确认它是否经过上述 GUI/Ui 创建路径。不要只往翻译表里加词条后就假定完成。

### 2.2 推荐修改方式

`sys/praat_translate.cpp` 是可编译产物，但当前更稳的维护入口是 `tools/generate_translation_map.py` 里的 `EXACT_MAP`。

常规流程：

1. 在源码中找到未翻译英文原文，保持原文逐字符准确。
2. 在 `tools/generate_translation_map.py` 的 `EXACT_MAP` 里添加或修正映射。
3. 运行生成脚本：

   ```powershell
   python tools/generate_translation_map.py
   ```

4. 检查生成结果：

   ```powershell
   git diff -- tools/generate_translation_map.py sys/praat_translate.cpp
   Get-Content -TotalCount 40 tools/debug_translations.txt
   Get-Content -TotalCount 40 tools/translation_candidates.txt
   ```

5. 需要给其他 AI 或人工审校导出翻译库时，再运行：

   ```powershell
   python tools/extract_translations.py
   ```

注意：

- `tools/debug_translations.txt` 和 `tools/translation_candidates.txt` 是生成/审校辅助文件，默认被 `.gitignore` 忽略，不要把它们当作需要发布的源码。
- `tools/praat_translations.json` 和 `tools/praat_translations.txt` 是从 `EXACT_MAP` 导出的参考资料，不是运行时读取的文件。
- `recovered_exact_map.py` 和 `scratch/` 更像恢复或实验材料。除非任务明确要求恢复旧翻译，否则不要把它们并回主流程。

### 2.3 匹配规则和坑

翻译键必须精确匹配 Praat 传入 `praat_translate()` 的原文。

- 保留上游拼写错误。例如当前有 `"- Draw spectogram to picture window:"`，这里的 `spectogram` 少了 `r`，但必须照抄。
- 保留前后缀、空格、冒号、省略号、换行和别名分隔符。`"Open Picture window"`、`"Open Picture window..."`、`"- Query pitch:"` 是不同键。
- `tools/generate_translation_map.py` 会按 Python `sorted()` 输出 `g_translation_map`，不要手动维护排序。
- 中文在生成的 C++ 里会转为 `\uXXXX` 形式，这是脚本行为。不要手写一半 UTF-8、一半转义导致 diff 难审。
- `praat_translate()` 只额外处理前导空格复用；其他变化不会自动模糊匹配。

### 2.4 什么时候可以直接改 `sys/praat_translate.cpp`

只有在做非常小的临时验证时才考虑直接改生成后的 C++。如果最终要保留改动，必须同步回 `tools/generate_translation_map.py`，否则下一次运行脚本会把改动覆盖。

### 2.5 截图漏网 UI 的高效处理

当用户只给截图并说“把这些漏网之鱼翻译一下”时，不要从截图直接扩展成全项目翻译审计。先要求或自行整理一个最小清单：

```text
类型：菜单 / 按钮 / 对话框 / 弹窗 / 手册
英文原文：Extract intervals
建议中文：提取区间
出现场景：TextGrid 编辑器菜单
截图：用户已附
备注：只处理本条，不扩大到相邻菜单
```

推荐执行顺序：

1. 先抄出截图中可见的英文原文，保持大小写、冒号、省略号和前后空格。
2. 给出定位表，再动手修改：

   ```text
   英文原文 | 类型 | 命中的文件 | 修改入口 | 建议中文 | 状态
   ```

3. 每个英文原文优先做精确搜索，搜索预算控制在 2 次左右。找不到就列入“未定位”，不要因为一个短词把全仓库都扫一遍。
4. 普通 UI / 菜单 / 按钮优先回到 `tools/generate_translation_map.py` 的 `EXACT_MAP`；确认不经过 `praat_translate()` 时，才继续追具体 GUI 创建路径。
5. 弹窗、报错、警告要单独标记。许多 `Melder_throw` / `Melder_warning` 文案可能不经过普通 UI 翻译表，不要硬塞进 `EXACT_MAP` 后就宣称完成。
6. 用户只要求修截图里的几条时，不要生成大而全的 `implementation_plan.md`；定位表足够，确认后直接按清单改。

可直接复用的任务提示：

```text
请根据下面的漏网英文清单补翻译。不要做全项目审计，不要写 implementation_plan。
只处理我列出的字符串；每个字符串最多精确搜索 2 次，找不到就报告未定位。

规则：
1. 普通 UI / 菜单 / 按钮优先修改 tools/generate_translation_map.py，并按项目流程更新 sys/praat_translate.cpp。
2. 手册正文只修改 fon/manual_*.cpp，不修改 docs/manual 生成结果。
3. 弹窗 / 报错单独标记；如果不经过 praat_translate，不要硬塞进 EXACT_MAP。
4. 修改前先给出“英文原文 | 位置 | 修改入口 | 建议中文”的定位表。
5. 我确认后再执行修改。

漏网清单：
- ...
```

## 3. 内置帮助手册工作流

### 3.1 真正的入口

内置手册位于各模块的 `manual_*.cpp`，其中高频文件包括：

- `fon/manual_tutorials.cpp`
- `fon/manual_annotation.cpp`
- `fon/manual_sound.cpp`
- `fon/manual_soundFiles.cpp`
- `fon/manual_glossary.cpp`
- `fon/manual_Fon.cpp`

这些文件不是 Markdown。它们使用 Praat 自研手册宏，例如 `MAN_BEGIN`、`INTRO`、`NORMAL`、`LIST_ITEM`、`ENTRY`、`TERM`。

### 3.2 手册漏网内容的快速定位

手册相关任务也不要从 `docs/manual/*.html` 或全仓库英文短词开始搜。更高效的定位顺序是：

1. 如果截图或页面顶部能看到手册页标题，先精确搜索标题：

   ```powershell
   rg -n 'MAN_BEGIN\s*\(\s*U"TextGridEditor"' fon dwtools stat gram
   ```

   如果标题来自生成的 HTML 文件名，例如 `TextGridEditor.html`，优先回到 `fon/manual_*.cpp` 查对应 `MAN_BEGIN`。

2. 如果只有正文里的英文短句，先限定手册源文件：

   ```powershell
   rg -n -F "every interval whose label" fon/manual_*.cpp
   rg -n -F "every interval whose label" dwtools/manual_*.cpp stat/manual_*.cpp gram/manual_*.cpp
   ```

3. 如果短句太普通，例如 `the text`、`is equal to`、`click`，不要直接全仓库扫。先结合截图里的页面标题、对象名、菜单名、章节名或相邻句子扩大成更长的搜索片段。
4. 定位到页面后，只改包含该页面的 `manual_*.cpp` 段落；不要修改 `docs/manual/*.html`，这些是生成产物。
5. 找不到源头时，输出“未定位：英文原文 + 已搜索范围 + 下一步建议”，不要为了凑结果扩大成手册全量审计。

手册漏网清单建议使用这种格式：

```text
页面标题：TextGridEditor
英文原文：every interval whose label...
建议中文：每个标签为……的区间
源文件范围：fon/manual_annotation.cpp 优先
是否允许调整链接文本：否，链接目标保持英文
```

现有 `tools/extract_full_manuals_bilingual.py` 和 `tools/extract_manuals_bilingual.py` 更适合“已有手册改动后的审校”，不是截图漏网任务的第一步。截图漏网任务应先定位源文件和页面，再按需要运行脚本导出审校材料。

### 3.3 链接和页面标题规则

手册最容易踩坑的是 dangling link。

- `MAN_BEGIN (U"PageTitle", ...)` 的页面标题必须保持官方英文标题，除非你同时能证明所有引用都同步更新且不会破坏上游页面查找。
- `@PageTitle` 和 `@@PageTitle@` 中的链接目标必须是存在的英文页面标题。
- 如需显示中文链接文本，用这种形式：

  ```cpp
  NORMAL (U"请参见 @@waveform|波形图@。")
  ```

- 不要写成 `@波形图` 或 `@@波形图@`，这会让 Praat 在启动/打开手册时查找不存在的页面。
- `##Command#`、`%emphasis%`、`\xx`、`\uXXXX`、`@@Page|label@` 这些标记要按 Praat 语法保留。

### 3.4 审校辅助脚本

当前有两条脚本路径，但要注意它们的比较基准：

- `tools/extract_full_manuals_bilingual.py`：从当前源码和 `git show HEAD:<file>` 抽取核心页面，输出 `tools/manuals_bilingual_review.txt`。因为当前 `HEAD` 已经包含中文手册翻译，所以它不能稳定代表“官方英文原文”；更适合在你刚做了未提交手册改动时查看当前工作区相对 HEAD 的变化。
- `tools/extract_manuals_bilingual.py`：基于 `git diff fon/` 提取未提交 diff。只适合当前有手册改动时使用。
- 如果需要真正的上游英文原文，应改用 `upstream/master` 或匹配发布版本的上游 tag，例如 `git show upstream/master:fon/manual_tutorials.cpp`，然后再和当前中文源码对照。

使用建议：

```powershell
python tools/extract_full_manuals_bilingual.py
```

或在有手册 diff 后：

```powershell
python tools/extract_manuals_bilingual.py
```

`tools/manuals_bilingual_review.txt` 是审校材料，不是手册源码。发现问题后要回到 `fon/manual_*.cpp` 修改。

### 3.5 术语表维护

术语表文件是 `tools/praat_glossary.md`，生成入口是 `tools/build_glossary.py`。如果发现术语不准，优先改 `tools/build_glossary.py` 里的 `MANUAL_OVERRIDES`，再重新生成：

```powershell
python tools/build_glossary.py
```

术语原则：

- Praat 对象类型和编辑器类名优先保留英文专名，再用括号给中文释义，例如 `TextGrid（文本标注）`、`SoundEditor（声音编辑器）`。
- UI 命令尽量和 `tools/praat_translations.json` / `tools/generate_translation_map.py` 保持一致，例如 `Remove` 对应“删除”，`Inspect` 对应“检查”。
- 声学概念避免过度合并。`tier` 译为“层”，`boundary` 译为“边界”，`time domain` 译为“时间域”；只有在上下文需要时再补充说明。
- 不要把 `tools/praat_glossary.md` 当作手工孤立文件长期维护；否则下一次运行生成脚本会覆盖手改结果。

## 4. 本地化功能改动入口

### 4.1 Windows 原生文件拖拽

现有实现已经有完整链路：

- `sys/motifEmulator.cpp`：Windows/Motif 层启用 `DragAcceptFiles`，处理 `WM_DROPFILES`，逐个调用打开回调。
- `sys/GuiMenu.cpp`：Cocoa 侧有 `openFiles` 回调，错误文案也走翻译表。
- `sys/praat_objectMenus.cpp`：`cb_openDocument` / `cb_finishedOpeningDocuments` 负责把文件读入 Praat 对象系统，并通过 `Gui_setOpenDocumentCallback` 绑定回调。

如果拖拽有问题，先追这条链路。不要另写一套文件读取逻辑绕过 Praat 的对象加载流程。

### 4.2 启动时默认隐藏 Picture window

现有实现不是删除 Picture window，而是在初始化后隐藏窗口：

- `sys/praat_picture.cpp` 中 `praat_picture_init(bool showPictureWindowAtStartUp)` 会先创建 Picture 相关对象和菜单，再在 `!showPictureWindowAtStartUp` 时隐藏实际窗口。
- `sys/praat_objectMenus.cpp` 在 Objects 窗口的 Praat 菜单注册 `"Open Picture window"`，中文显示由翻译表映射为“打开图像窗口 (Praat Picture)”。

不要为了“隐藏图像窗口”跳过 Picture 初始化；绘图、脚本和手册中的 Picture 功能仍依赖这些对象存在。

## 5. 构建、验证和打包

### 5.1 本地 Windows 构建

本地 Windows 开发通常使用 MSYS2 shell 调用仓库根目录的 `Makefile`。当前本机常用命令为：

```powershell
$env:MSYSTEM="CLANG64"   # 本机只装了 CLANG64 工具链（没有 mingw64 的 g++）
C:\msys64\usr\bin\bash.exe -lc "cd /d/path/to/Praat_ZH && make PRAAT_COMPILER=clang -j16"
```

链接写 `Praat.exe` 时如果报 `Permission denied`，说明 Praat 还开着：先关掉所有
Praat 窗口（包括对话窗口），再重新执行上面的命令，构建是增量的。

构建成功后根目录生成 `Praat.exe`。如果只改文档或 guide，不需要构建；如果改 C++、翻译表或手册源字符串，至少应尝试本地构建，或明确说明未构建原因。

### 5.2 最低验证清单

按改动类型选择验证：

- UI 翻译：运行 `python tools/generate_translation_map.py`，检查 `sys/praat_translate.cpp` 中目标键存在；能构建时再构建。
- 手册翻译：检查 `@@...@` / `@...` 链接目标仍是英文页面；能构建/启动时确认没有 dangling link 警告。
- Windows 拖拽：构建后把 `.wav`、`.TextGrid`、`.praat` 等文件拖入窗口，确认对象列表或脚本编辑器有响应。
- Picture window 行为：启动后确认 Picture window 默认不弹出；通过 Objects 窗口 `Praat -> Open Picture window` 可打开。
- 发布改动：确认 `README.txt`、`README.md` 和 workflow 中的说明一致。

### 5.3 本地打包

本地 Windows zip 包只包含运行必需项和简短说明：

```powershell
Compress-Archive -Path Praat.exe, README.txt -DestinationPath Praat-ZH-Windows-x64.zip -Force
```

`*.zip` 和 `Praat.exe` 默认被 `.gitignore` 忽略，不要误以为未跟踪就是源码遗漏。

## 6. GitHub Actions 发布工作流

发布工作流位于 `.github/workflows/release-windows.yml`，实际包含：

- `build-windows-x64`：在 `windows-latest` 上用 MSYS2 `CLANG64` 构建 `make PRAAT_ARCH=x64v3 -j2`，产出 Windows x64 zip。
- `build-macos`：在 `macos-26` 上准备 Xcode project，必要时从上游 release 下载 `praatXXXX_xcodeproj.zip`，并把 `sys/praat_translate.cpp` 注入 `praat_mac` target，产出 macOS universal dmg。
- `create-release`：下载两个构建产物，用 `gh release create` 创建 GitHub release。

该 workflow 是手动触发的 `workflow_dispatch`，输入包括：

- `tag_name`
- `release_name`
- `praat_upstream_tag`
- `praat_version_digits`
- `xcodeproj_url`
- `draft`
- `prerelease`

不要把它描述成自动随 push 发布，也不要说它构建 Linux 或 Windows ARM64。当前 release 产物只有 Windows x64 zip 和 macOS universal dmg。

如果新增了需要 macOS 编译的 `.cpp` 文件，必须检查 Xcode project 注入逻辑是否也要更新；否则 Windows 本地构建可能过了，macOS CI 会漏文件。

## 7. Agent 输出和提交前检查

完成任务前给出真实验证结果，不要只说“应该可以”。

推荐最后检查：

```powershell
git status --short
git diff -- guide.md
```

如果改了源码，再补充对应构建或脚本命令。若因为环境限制没有运行构建，要明确说明。

提交前注意：

- 不要提交 `Praat.exe`、zip 包、`.o`、`debug_translations.txt`、`translation_candidates.txt` 等忽略产物。
- 如果修改了生成后的 `sys/praat_translate.cpp`，确认 `tools/generate_translation_map.py` 中的源映射也同步了。
- 如果修改了手册源码，优先审查链接语法和页面标题，不要让中文显示文本变成链接目标。

## 8. 本地 AI 纠音前端

AI 纠音实验代码位于 `ai/`：

- `ai/README.zh-CN.md`：使用说明。
- `ai/praat_ai/`：Praat 桥接、Qwen 客户端、声学分析、DTW、报告和显存档位。
- `ai/run_ai_tutor.py`：在 Praat Python 编辑器中运行的入口。
- `docs/ai-frontend/DESIGN.zh-CN.md`：总体架构和分阶段方案。

重要边界：

- Qwen3.5-0.8B 是视觉语言模型，不是音频模型。
- Qwen 只能解析请求、选择受限工具和解释已有结果，不能直接计算发音分数。
- 音素对齐采用 MFA 主对齐、wav2vec2/CTC 交叉验证、比例分段兜底；特征比较和错误区间由 Praat/Parselmouth/NumPy 的确定性流水线完成。
- 配置入口是 `ai/ai_config.json` 的 `alignment` 节点；缺少模型时自动回退并记录警告。
- AI 前端必须复用 `praat.get_selected()`、`praat.call()` 和 `praat.get_output_dir()`，不要绕过桥接直接修改 Praat 内存对象。
- 修改 Python 代码后运行：

  ```powershell
  $env:PYTHONPATH = 'ai'
  python -m unittest discover -s ai/tests -v
  ```

### 8.1 对话窗口（自然语言操作 Praat）

`ai/praat_ai/chat.py` 是启动前端后自动弹出的独立对话窗口，除了上面的纠音流水线，
它还负责把自然语言请求变成 Praat 操作。维护时注意以下约定：

- 模型不直接执行自由文本：模型只选工具并填参数，脚本由 `ai/praat_ai/tools.py`
  的固定模板渲染；`custom_script` 只是兜底，并且要过 `validate_script()`。
- 结果回传是文件协议：脚本把数值写入 `ai/runtime/chat_result.tsv`，最后一行用
  `appendFileLine` 写 `ai/runtime/chat_state.txt`，窗口轮询完成标记后再读结果文件。
- 写结果文件依赖 `Praat.exe --FULL-TRUST --send`：`sys/praat.cpp` 的 Windows/UNIX
  分支必须在 message file 里写上 `# --FULL-TRUST`（与 macOS 分支一致），
  否则正在运行的 Praat 会以 “potentially dangerous action … not allowed without
  --FULL-TRUST” 拒绝整个脚本。不要再把这段标记删掉。
- `An instance of Praat that is not me is already running.` 是 `--send` 的常规提示，
  不是错误，不要让对话窗口把它当成执行结果。
- 自由脚本的常见坑（都已在 `tools.py` 里规避）：对象名必须带类名前缀
  （`selectObject: "Sound xxx"`，或直接用数字 id）；字符串只能用双引号，
  单引号是变量插值会报 `Unknown symbol`；`Formant: Get bandwidth/value at time`
  需要 4 个参数（编号、时间、单位、插值）。

### 8.2 模型加载与状态（llama-server）

「端口上有服务」不等于「加载的是配置里的模型」。维护这条链路时遵守以下几点：

- 判断必须走 `server_model_state()`（读 `GET /v1/models` 的 id 与配置路径比对，
  路径或纯文件名都接受）。`QwenServerManager.ensure_started()`、`start_frontend()`、
  `set_frontend_model()` 三处都要用它：不一致就停止旧服务并用新配置重启
  （`control._restart_service()`，先等进程退出、再等端口释放）。
- `collect_status()` 的 `frontend_model` 必须来自服务实际加载的模型
  （`running_model_info()`），配置值放在 `frontend_model_configured`，
  另外提供 `frontend_model_mismatch`、`frontend_model_source`、`frontend_vision`。
  旧实现直接返回配置里的文件名，会出现「界面显示 2B、实际在跑 0.8B」的假象。
- mmproj 只对匹配的模型有效。`ensure_started()` 会先用 mmproj 启动，若服务退出
  （典型报错 `mtmd_init_from_file: mismatch between text model (n_embd = …)`）
  则自动回退纯文本再启动一次，并在 `logs/qwen-server.log` 追加
  `=== PRAAT-AI: … ===` 说明；`frontend_vision` 由 `/v1/models` 的 capabilities 决定。
  需要视觉的模型必须配自己的 mmproj，否则只能纯文本运行。
- 多模型的投影文件用 `server.mmproj_by_model`（模型路径或文件名 → mmproj）配对，
  它优先于 `server.mmproj_path`；`set_frontend_model()` 在收到 mmproj 时会为该模型
  写入这条映射，因此切换模型不会把别人的投影文件带过去。
  取投影文件前先核对 `clip.vision.projection_dim` 是否等于模型的
  `qwen35.embedding_length`（0.8B = 1024，2B = 2048）。
- 服务不是本前端启动的（`runtime/qwen.pid` 不存在或进程已死）时不能自动重启，
  `_restart_service()` 会抛 `QwenServerError` 让用户手动停止，避免误杀别人的进程。
- 回归用例：`ai/tests/test_frontend_model.py`。

### 8.3 模型预设（server.presets）

「模型预设」把「用哪个模型、配哪个 mmproj、用多大上下文、用什么生成参数」固化成
一键切换，实现分布在四个地方，改的时候要一起看：

- `ai/ai_config.json` 的 `server.presets`：每条预设的 `id / label / model_path /
  mmproj_path / vision / context_tokens / n_gpu_layers / threads / qwen`。
  `active_preset` 记录当前选中的预设。
- `ai/praat_ai/presets.py`：解析、查表、展开成配置、按预设覆盖显存档位。
  这里是纯函数，不碰进程。
- `ai/praat_ai/control.py`：`apply_preset()` 先把预设写进配置（含
  `mmproj_by_model` 的合并），再复用 `set_frontend_model()` 那套「端口上的模型
  和配置不一致就重启」的判断；`collect_status()` 额外上报
  `frontend_preset / frontend_preset_label / frontend_preset_matches_live /
  presets`。
- `ai/praat_ai/chat.py`：对话窗口顶部的下拉框，切换后重新读配置并重建
  `QwenClient`（`reload_config()`）。

约定：

- 预设里的 `model_path` 与 `mmproj_path` 必须成对；`vision: true` 但没有 mmproj
  的预设按纯文本处理，`preset_view()` 和 `apply_preset_to_profile()` 必须给出
  同一个结论，否则界面会显示一套、实际跑另一套。
- 预设只覆盖启动参数，不能绕过模型一致性检查：服务不是本前端启动的依然拒绝重启。
- 手动用菜单选模型时（`set_frontend_model`）要同步 `active_preset`：命中预设就写
  预设 id，没命中就清空，否则状态栏会显示一个早就不在跑的预设。
- 回归用例：`ai/tests/test_presets.py`；真机切换用
  `python ai/tests/verify_presets_live.py`（会重启 llama-server，检查端口上的模型
  和 `ai/logs/qwen-server.log` 里的 mmproj 是否和预设一致）。

### 8.4 对话链路的行为约定（都踩过坑）

- **发送脚本不能阻塞等 60 秒。** `Praat.exe --send` 在 Praat 弹出错误对话框或
  被模态窗口挡住时会一直阻塞（实测 > 60 秒），脚本其实已经排队。所以
  `chat._send_script()` 现在是「后台 Popen + 输出重定向到 `runtime/chat_send.log`
  + 轮询 `chat_state.txt`」；超过 25 秒且发送进程还活着就杀掉它并提示用户关掉
  Praat 里的对话框。不要再改回 `subprocess.run(timeout=60)`。
- **每次执行前先刷新对象列表。** `chat.refresh_object_context()` 送一条
  `appendInfoLine` + 状态标记的空脚本：Praat 每执行完一条脚本命令都会走
  `praat_updateSelection()`，从而重写 `runtime/chat_context.tsv`。这样 Praat
  重启过、对象改名过之后不会拿着旧 id 去规划（旧 id 会让 Praat 报
  「没有编号为 1」）。注意批处理（`--run`）下 `PraatAiControl_refreshChatContext()`
  直接返回，所以**批处理验证不了上下文回传**，只能验模板语法。
- **多实例**：`--send` 只能把脚本交给最新打开的那个 Praat。`chat.py` 会数
  `tasklist` 里的 Praat 进程，多于一个就提醒用户关掉多余的窗口。
- **Praat 脚本保留字**：`from`、`to`、`end` 不能当变量名，会报
  `Symbol misplaced`；时间区间统一用 `tmin` / `tmax` / `t1` / `t2`。
  另外这个版本**不支持 `try` / `catch`**（`Unknown variable: try`），所以命令是否
  可用要在 Python 侧按对象类判断（见 `tools.TIME_DOMAIN_CLASSES`、`SOUND_CLASSES`）。
- **`--undefined--`**：时间越界或静音段查询不会报错，而是返回 `undefined`。
  模板要 `if value = undefined` 分支给中文说明，并先把时间夹进对象时长
  （结果里带「已按对象时长截断」），否则用户会看到 `--undefined--` 这种输出。
- **模型会拿 Python 当 Praat 脚本**。`tools.validate_script()` 先做
  `PYTHON_SCRIPT_PATTERNS` 检查，命中就报「模型给出的是 Python 代码」，
  不要放它进 Praat。想要减少这种情况就加工具（模型没工具可用时会自己编脚本）。
- **对象名写法不一致**：Praat 里有的对象名自带类名前缀（`Sound 思い出す`），
  有的没有。`ToolContext.resolve_object()` 用 `name_variants()` 做容错匹配，
  唯一命中才接受，多个候选/完全找不到时给中文错误。
- **规划提示要单独写「当前选中」**：只给 TSV 列表时，模型会习惯性挑 1 号对象
  （列表里可能是 TextGrid）。`qwen._selected_object_hint()` 把选中项写成一句话，
  并配一条「说『这个声音』时指它」的规则。
- **查询类命令可用范围有限**（都在真机批处理里试过）：`Play part` / `Play: 参数`
  对 Sound 不存在，只有整体 `Play`；Spectrogram 没有「最低/最高频率」查询，
  只能 `Get number of frames`；`View & Edit` / `Edit` 在批处理里必然失败
  （`Cannot edit a Sound from batch`），只能在 GUI 里验证。
- **字符串结果可以现场拼**：`bwText$ = "，带宽 " + fixed$ (bw, 3) + " Hz"` 有效，
  所以「频率和带宽」能在一次查询里输出一行；带宽是 `undefined` 时把它置空即可。
- **TextGrid 操作**：`Insert boundary` 在已有边界的位置（包括起止点）会直接报错，
  所以 `tools._insert_boundary_block()` 先遍历 `Get start time of interval` 自查；
  `Is interval tier` 这类查询命令**不能直接写在 `if` 条件里**（会报
  `Unknown symbol «Is» in formula`），必须先赋值再判断。
- **按类型兜底**：模型有时把 `object` 填成当前选中的 Sound，而用户问的是
  「这个 TextGrid」。`ToolContext.resolve_by_class()` 在类型不匹配、且列表里只有
  一个合格对象时直接用它，多个候选才报错。
- **没有工具的测量值不许顶替**：VOT 以前会被模型换成「共振峰带宽」之类交差。
  现在 `vot` 有两种用法：给了 `burst`/`voicing` 就相减（TextGrid 顺带补边界），
  只给 `from`/`to` 就在大概范围里自动估计；规则 14 要求其它没有工具的测量
  （例如 CPP）在 reply 里直说做不到。加工具比加提示词管用，提示词只留一行。
- **VOT 自动估计的取舍**（都在真机合成用例上量过，真值 30 ms）：爆破和浊音起始
  分成两步测，结果里分别给出各自的依据。**爆破**用 2–8 kHz 带通后的强度包络
  （`To Intensity: 2000, 0.001`，窗口 3.2 ms）找最陡的上升沿，并且要求上升沿之后
  能量守得住 5 ms——被硬切出来的爆音"来了就走"，拿它当爆破会把 VOT 报大几十毫秒；
  升幅不到 6 dB 才退回全频段包络。不再用"区间峰值 − 25 dB"当阈值：范围里只要还夹着
  别的强段（后面的元音），这个阈值就会漂，同一个音两次差 6 ms（实测 47 和 41 毫秒）。
  **浊音起始**用 `To Pitch (ac): 0.002, …` 连续 3 帧判出基频（默认 10 ms 步长会把起点
  推迟一个帧；`To Harmonicity (cc)` 13 ms 窗口实测晚 8 ms，所以只拿起点后 50 ms 内
  最高的谐噪比当佐证数字）。这套在同真值下跑三遍是 30/32/32 ms。
  **代价**：`To Harmonicity (cc)` 对整段声音做交叉相关很贵（10 秒的声音要 0.301 秒，
  其余各步加起来才 0.11 秒），所以谐噪比只截起点后 50 ms 那一小段算，实测 0.007 秒；
  它只是回话里的佐证数字，不是判定依据。
  `To Harmonicity (cc)` 的 periodsPerWindow 给 0.5 会让 Praat 7.0.02 在
  `Sound_to_Pitch.cpp` 直接断言崩溃，只能 ≥ 1；minPitch 250（4 ms 窗口）在 220 Hz 上
  会判成"全是噪声"，窗口就按 1/minPitch 走。范围整段都在浊音里时必须报"起点已是浊音"
  而不是给一个 1 ms 的假数，VOT < 5 ms 时也要加一句提醒。
- **圈大了不能静默取第一个**：范围内第一段浊音之后若还有 ≥20 毫秒无声、再出现
  连续两帧以上的浊音，就在结果末尾补一句"范围偏大：后面还有第 2 段浊音从 x 秒开始，
  本次只报了第一个候选"。它只是提示范围该收紧，不改报出来的那个 VOT，也不加提示词
  （纯脚本逻辑，避免把 planner 提示词撑大触发 433）。
- **编辑器圈选范围**：`chat_context.tsv` 的表头是
  `id / class / name / selected / sel_start / sel_end`，后两列只在对应对象开着编辑器时
  才有值，来自 `FunctionEditor::startSelection/endSelection`，由
  `FunctionEditor_selectionMarksChanged()` 推给 `PraatAiControl_noteEditorSelection()`。
  `endSelection <= startSelection`（只点了个光标）不算选区；编辑器关掉后
  `editors[]` 里的指针会变成 null，写上下文时会自动忽略那两列，不会残留旧范围。
  前端只在用户没在话里给范围时用它，并回一句"按编辑器圈选 x–y 秒"，避免静默换范围。
  模型常把这两列原样抄进 `from`/`to`：数值和选区对得上（±2 ms）时仍按圈选报，
  否则回话里就丢了范围出处。
  这条链路不只 VOT 用：`_range_lines()`（`pitch_statistics`、`intensity_statistics`、
  `formant_statistics`、`harmonicity_statistics` 四个按区间统计的工具）、
  `_build_extract_part()`（"把这段截出来"）和 `_build_textgrid_set_interval()`
  （"把这段标成 a"，用 TextGrid 编辑器里拖的选区）都走同一个 `_selection_range()`，
  点查询（`pitch`/`intensity`/`formant_frequency`）没给 `time` 时改用选区中点，
  不再是整个对象的中点；有选区时回话里一定带"按编辑器圈选"，纯脚本逻辑，不加提示词。
  没圈选、话里也没给范围时行为不变（统计整段 / 报错要 end）。
  `textgrid_insert_boundary` 故意不接：单个时刻插边界时选区的起点、中点都能说得通，
  猜错了是改数据，不如让模型问清楚。
  顺手修掉 `extract_part` 的 `finish` 别名：以前只检查了别名、取值只读 `end`，
  写 `finish` 会被当成没给而误报"开始时间必须小于结束时间"（`textgrid_set_interval` 同样的问题）。
- 回归用例：`ai/tests/test_chat_tools.py`、`ai/tests/test_chat_window.py`；
  真机链路用 `python ai/tests/verify_chat_live.py`（临时开一个 Praat，
  验证建对象、改名后对象列表会刷新、基频查询和截取片段）。
