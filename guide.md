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
   - 本地 AI 纠音前端（对话窗口、工具模板、编辑器选区链路）：看 `ai/praat_ai/`，
     交接要点见 `ai/HANDOFF.md`（选区数据流、VOT 算法取舍、验证命令）。

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
- `ai/docs/adr/`：对话前端的架构决策记录（投递方式、结果契约、规划接口）。
  §8.4/§8.5 记「哪里容易踩坑」，ADR 记「为什么这么做、还考虑过什么」。
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
- **启动参数里必须有 `--jinja`**（`server.py` 的 `_build_command()`）：对话循环会把
  工具结果作为 `role: tool` 消息回灌给模型，只有让模型自带的 chat 模板处理它，
  小模型才不会跑偏。实测对照（同一台机器、同一个 Qwen3.5-2B）：「阅读当前对象的
  信息」在默认模板下被做成**三次频谱图**（还选错了工具），加了 `--jinja` 之后
  1 步 `object_info` + 直接回答。改启动参数时别把这行删掉，`test_frontend_model.py`
  会守着它；本机手工起的服务也要记得加（例如
  `llama-server -m … --jinja --mmproj …`），否则前端的多步/回灌行为会明显变差。
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

- **投递脚本不许激活 Praat 的窗口**（见 §8.5）。`chat._send_script()` 默认走
  `praat_ai/sendpraat.py`：自己写 `%APPDATA%\Praat\Message.txt` 再发一条
  `WM_APP`，不启动 `Praat.exe`。老的 `Praat.exe --send` 只在
  `PRAAT_AI_SEND_MODE=argv` 时用来排障，那条路仍然用「后台 Popen + 输出重定向
  到 `runtime/chat_send.log` + 轮询 `chat_state.txt`」，不要改回
  `subprocess.run(timeout=60)`（它在 Praat 弹出对话框时会一直阻塞，实测 > 60 秒）。
  决策与备选方案：`ai/docs/adr/ADR-001-chat-script-delivery.md`。
- **一条指令一个脚本文件 + 自己的编号。** 脚本写在
  `runtime/commands/chat_command_<编号>.praat`，开头先把自己的编号写进
  `runtime/chat_started.txt`。`Message.txt` 是全局唯一的，旧消息醒来时如果读到的
  还是那个共用文件名，执行的就会是**刚写进去的新脚本**；文件名分开之后，旧消息
  最多把它自己那条再跑一遍，而等待完成时对一下编号就能认出「上一条超时指令刚刚
  才跑完」，把它的完成标记和结果一起丢掉（`chat._wait_for_result`）——不要为了
  「省事」把编号和分文件去掉。旧脚本按「超过 40 个**且**超过一小时」删
  （`chat.prune_command_scripts`），删早了会让残留消息找不到文件、Praat 弹错误框。
  老的固定路径 `runtime/chat_command.praat` 只用于兼容和排障。
- **消息文件自消费。** 投递的消息第一句就把 `Message.txt` 覆写成空操作
  （`sendpraat.consume_statement()`）：`cb_userMessage()` 每收到一条 `WM_APP` 都
  重新读那个文件，而 `praat_executeScript_noGUI()` 执行完不删它，所以排队中的
  每条消息都会把**当前的**消息内容再跑一遍（「删除」执行两次就是这么来的）。
  `PRAAT_AI_SEND_MODE=argv` 那条排障路径没有这层保护（消息文件由 Praat 自己写），
  别拿它跑有副作用的动作。
- **对象列表由 Praat 主动交给前端。** `runtime/chat_context.tsv` 由
  `sys/PraatAiControl.cpp` 写：`cb_userMessage()` 里每条 app 消息执行完都会调
  `PraatAiControl_refreshChatContext(true)` 强制重写一次（2026-09-20 补的），
  用户在对象列表里改选中也会重写。**别以为「每条命令都会刷新」**：实测只写文件的
  空脚本、`clearinfo`、`select all`（列表为空时）都不触发重写，以前就是因为这个
  拿着**上一个 Praat 实例**的旧列表去规划（挑到不存在的 9 号对象 → Praat 弹英文
  错误框 → 后面的消息全被挡住）。`chat.refresh_object_context()` 仍然每次请求前
  送一条只写状态标记的空脚本：它的作用是确认 Praat 还在响应，并把列表刷到最新。
  批处理（`--run`）下这个钩子直接返回，所以**批处理验证不了上下文回传**，只能验
  模板语法。这条空脚本只能写文件：`appendInfoLine` 之类的命令会走
  `gui_information()`，把「Praat Info」窗口弹出来（§8.5 的 bug 就是这么来的）。
- **规划走原生 function calling。** 工具自带 JSON Schema
  （`tools.TOOL_PARAMETERS`），`QwenClient.plan_praat_command()` 把
  `tools.tool_schemas()` 交给 llama-server，读回来的是 `tool_calls`；
  `PRAAT_AI_PLANNER=json` 可以退回老的「提示词 + `json_object`」接口（换到不支持
  工具调用的服务端时用它）。一次响应里可能带**多个** `tool_calls`（实测
  「0.25 秒和 0.75 秒的基频」会给两个 `pitch`），按顺序拼成同一条脚本，上限 3 个
  （`tools.MAX_ACTIONS_PER_REQUEST`）。**加工具时必须同时加 schema**：
  `ai/tests/test_planner_tools.py` 会拿 `Tool.signature` 对拍。决策见
  `ai/docs/adr/ADR-003-planning-interface.md`。
- **一轮请求是一个有界循环**（`chat.run_turn`，见
  `ai/docs/adr/ADR-004-agent-loop.md`）：模型给动作 → 逐个执行 → 把结果（或失败
  原因）作为 `role: tool` 的观察结果回灌 → 再让模型决定下一步，直到它不再调工具
  （那句话就是回答）或者撞到上限（`MAX_AGENT_ROUNDS = 3` 轮、`MAX_AGENT_STEPS = 5`
  个动作，之后强制要一次纯文字回答）。三条实测出来的规矩：
  1. **服务端必须开 `--jinja`**（§8.2）。不开时小模型在多轮里会跑偏得很厉害
     （选错工具、顺手多做几步），这是我们这个循环能不能用的前提；
  2. **同一个动作只执行一次**（工具名 + 参数完全相同），重复调用只回灌「这一步刚才
     已经做过」——实测「截取 0.2–0.5 秒」被同一个模型连做三遍；
  3. **观察结果要带收尾提示**（「够回答就直接回答，不要顺手多做别的操作」），
     否则它会在成功之后继续调工具。
  4. **用户没说要第二步时，第二轮之后不许动对象**：`tools.MUTATING_TOOLS` 里的工具
     （建/删/改名/标注/另存/读入/频谱图/custom_script）在第二轮之后要执行，用户这句
     话里必须有「然后 / 再 / 接着 / 之后 / 并且 / 同时 / 顺便 / 先」（
     `chat.wants_second_step`），只读查询不受限制。实测 0.8B 预设下「打开当前声音的
     编辑器」会顺手做两次频谱图、把选中对象也换掉，后面的请求全被带偏。这条护栏管得住
     「回灌之后多做」，管不住**第一轮就选错工具**——那是模型能力问题：2B 预设实测每条
     都选对（`verify_chat_live.py` 六个用例全 1 步、`verify_chat_planning.py` 21/21），
     0.8B 会把「阅读当前对象的信息」做成频谱图。日常建议用 2B 预设。
  另外模型偶尔把工具调用写成正文里的 `<tool_call><function=…>` 文本
  （`qwen.parse_text_tool_calls`）：那也要当动作执行，XML 之外的文字才算回答——
  以前那串 XML 会被原样显示给用户。工具报错（参数不合法、对象类型不对）**不再直接
  判死**，而是回灌给模型让它改参数重试；只有模型同时给了脚本时才用脚本兜底，并在
  窗口里说明「改用模型给出的脚本」。
- **文件读入是独立工具**：`read_file`（`Read from file:`）和 `save_sound`
  （`Save as WAV file:`）方向相反，必须分开——换成 tool calling 时丢了少样本示例，
  模型立刻把「读取 D:/in/a.wav」做成了「另存为」。文件不存在时在脚本里用
  `fileReadable()` 判断并回一句中文，不要指望 Praat 的英文报错。
- **结果输出不许静默丢**（`tools.neutralize_info_commands`，见
  `ai/docs/adr/ADR-002-result-output-contract.md`）：`appendInfoLine` /
  `writeInfoLine` / `appendInfo` / `writeInfo` 改写成 `appendFileLine`；
  `printline` / `print` / `echo` 在 Praat 里写的是**字面文字**，整段抄成一个字符串
  参数；只有 `printtab` / `clearinfo` 没有内容可保留，改成注释。
- **借来的测量工具**（2026-09-20，B3）：公式照抄 Chen Gafni 的 Praat 插件脚本
  （https://github.com/chengafni/praat），出处都写在各自的 docstring 里：
  `spectral_emphasis`（谱强调 = 低通前后损失的强度，Traunmüller & Eriksson 2000）、
  `hl_ratio`（高频段能量 ÷ 低频段能量，默认 4–8 kHz ÷ 0–4 kHz）、
  `hammarberg_index`（0–2 kHz 最大电平 − 2–5 kHz 最大电平，Hammarberg et al. 1980）、
  `pitch_peak_latency`（（基频峰值 − 区间起点）÷ 区间时长）、
  `peak_to_average_ratio`（峰值 ÷ 有效值，Hillenbrand et al. 1994）、
  `intensity_slope`（强度平均斜率，`local` = 相邻点绝对差的平均 ÷ 步长、
  `global` = 首尾差 ÷ 时长）。两个和来源不同的地方要记住：
  ① `peak_to_average_ratio` 的分母用 **RMS**——原脚本用 `Get mean`（有符号均值），
  对语音来说那个值≈0，比值会跑到几万、同一个音两次能差一个数量级；
  ② 他的 `align_intervals` 靠编辑器命令 `Align interval`（对象列表上没有对应命令）、
  `label_words` 依赖交互式选文件，所以这两个没有收进来。
  这些中间对象（Pitch / Spectrum / Ltas / Matrix / 截出来的片段）用完就删，最后会
  回到用户原来选中的对象；`spectral_emphasis`、`hl_ratio`、`hammarberg_index`、
  `pitch_peak_latency`、`peak_to_average_ratio`、`intensity_slope` 一共九条真机用例
  在 `ai/tests/verify_chat_templates.py` 里（正弦的峰值/有效值正好是 1.41=√2，
  可以拿它当数值对不对的快速判断）。
- **测量参数是「表」驱动的**（2026-09-21，B1）：`ai/praat_ai/measures.tsv` 一张表
  管着 41 个参数（`@@ settings` 分析设置、`@@ derivations` 从 Sound 生成中间对象、
  `@@ queries` 一行一个参数、`@@ dedicated` 交给已有专用工具、`@@ editor_only`
  只能在编辑器里查的）。**加一个参数 = 加一行**：工具 JSON Schema 的 enum、catalog
  文字、`measure` 的脚本、插件脚本、真机用例全都是从这张表生成的。三条要记住：
  ① 命令字面量直接进脚本，**不要学 chengafni 在 Praat 端把命令拼成字符串再
  `'queryCommand$'` 动态求值**（Praat 6.0 时代可行，7.0 上很脆）；
  ② `To Pitch` / `To Formant` 这类命令**会把新建的对象选中**，所以每建一个派生
  对象之前都要重新 `selectObject:` 基础对象（实测第二段派生对象会做在中间对象上，
  `measure-many` 用例守着这条）；
  ③ 命令名和 FORM 标题不一致的有两个坑（都是实测）：`Get shimmer (local_dB)`
  （FORM 标题写的是 `local, dB`，脚本里不认）、`Get CPPS (hillenbrand)`
  （默认那条 `Get CPPS:` 有 12 个参数，不写全会报缺 `Tolerance`）。
  真机用例：`verify_chat_templates.py` 里每个参数一条 + 一条「一次测全部」，
  98/98；`ai/tests/test_measures.py` 守着表本身的一致性。
- **Praat 可执行文件由 `praat_ai/praat_app.py` 找**：环境变量
  `PRAAT_AI_PRAAT_EXECUTABLE` → 仓库根目录 → `PATH` → 常见安装位置；找到和没找到
  都缓存，没找到 30 秒后重试一次。**每条请求只查一次** `tasklist`
  （`chat.praat_process_ids()` 的结果同时用来判断「在不在跑」和「开了几个」），
  不要再各自调一遍 `praat_process_running()` / `praat_instance_warning()`。
- **多实例**：投递只能送给最新打开的那个 Praat（`sendpraat.choose_window()`
  取窗口号最大的进程，和 `--send` 一致）。`chat.py` 会数 `tasklist` 里的
  Praat 进程，多于一个就提醒用户关掉多余的窗口。
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
  **可选字段的占位 0**：走原生 tool calling 之后模型习惯把可选字段"填满"，
  「提取这段语音的 vot」会给 `burst: 0, voicing: 0`。两条都是 0 的 VOT 本来就没有
  意义，`_build_vot()` 把它当成"没给"、继续走自动估计；只给一条仍然按错误处理
  （那才是真的漏了）。同理，schema 里纯数字的字段只用 `"type": "number"`——
  允许字符串时模型会把说明文字（例如「默认按 Praat 自动」）当成值填进来。
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

### 8.5 投递脚本时不许动 Praat 的窗口（用户报的 bug）

现象（2026-09-20 用户报的）：从对话窗口发指令时

1. 「Praat Info」窗口自己弹出来；
2. 声音编辑器（Sound 窗口）从任务栏跳出来盖住对话窗口。

**根因是老的投递方式 `Praat.exe --send`**，不是脚本内容。`sys/praat.cpp` 的
`tryToSwitchToRunningPraat()` 在 Windows 上做两件事：

1. `GuiWin_initialize1()` → `FindWindow ("PraatChildWindow1 Praat", NULL)`，
   拿回来的是 **z 序最上面那个 Praat 子窗口**——实测就是「Praat Info」或者声音
   编辑器（对象窗口的类是 `PraatShell1 Praat`，反而不会被选中）；
2. `if (IsIconic (winWindow)) ShowWindow (winWindow, SW_RESTORE);
   SetForegroundWindow (winWindow);`

于是每发一条指令（包括每次请求前那条刷新对象列表的空脚本），那个窗口都会被
`SW_RESTORE` 拽出来并抢走前台。接收端完全无辜：`sys/motifEmulator.cpp` 的
`WM_APP` 分支里那两行激活代码是注释掉的。

真机取证（同一台机器，先让 Praat 的窗口最小化、把另一个窗口置前，再发同一条
查询指令）：

| 投递方式 | 窗口状态变化 | 前台窗口 |
| --- | --- | --- |
| `Praat.exe --send` | `Praat Info` 最小化 → 还原 | 「对话窗口」→ `Praat Info` |
| 自己写 `Message.txt` + `WM_APP` | 无 | 不变 |

修法是 `ai/praat_ai/sendpraat.py`：按 Praat 自己的 sendpraat 协议把消息写进
`%APPDATA%\Praat\Message.txt`（内容就是 `--send` 会写的那两行
`setWorkingDirectory:` / `runScript:`，前面必须带 `# --FULL-TRUST`，
否则脚本写不了 `runtime/` 之外的路径），再给对象窗口发一条 `WM_APP`
（`motifEmulator.cpp` 里 `WM_USER` / `WM_APP` 走同一个
`cb_userMessage()` → `praat_executeScript_noGUI()`）。

几条不能踩坏的约定：

- **消息文件是全局唯一的**（Praat 只认 `Message.txt` 这个名字），所以同一时刻
  只能有一条指令在飞。前端逐条同步执行刚好满足；三层保护一起用：
  ①投递的消息第一句**自消费**（把 `Message.txt` 换成空操作，`sendpraat.consume_statement()`），
  ②每条指令一个**自己的脚本文件**（`runtime/commands/chat_command_<编号>.praat`），
  ③超时兜底再调用一次 `sendpraat.cancel_pending()`。少掉①或②就会出现
  「排队的旧消息执行了新脚本」「同一个脚本跑两遍」这类事故。
- **每条 app 消息之后 Praat 都会重写对象列表**（`cb_userMessage()` 里
  `PraatAiControl_refreshChatContext(true)`）。这条是 2026-09-20 补的：以前只有
  「对象被创建/删除」或用户改选中才会重写，只写文件的空脚本不触发，前端就会拿着
  上一个实例的旧列表去规划。改 `cb_userMessage()` 时别把这行删掉。
- 投递目标优先选对象窗口（`Praat Objects`，类名 `PraatShell…`）：它一直在，
  不会因为用户关掉编辑器或 Info 窗口而消失。
- 窗口类名按前缀匹配 `praat`（`PraatChildWindow1 Praat` / `PraatShell1 Praat`），
  别写死类名里的数字和程序名。
- **自定义脚本里也不许写 Info 命令**：`tools.neutralize_info_commands()` 在
  `render()` 里把每一条会弹 Info 窗口的输出命令都翻译成 `appendFileLine` 写结果文件
  （内容一句不丢）：带值列表的 `appendInfoLine` / `writeInfoLine` / `appendInfo` /
  `writeInfo` 参数原样带过去；`printline` / `print` / `echo` 写的是字面文字，
  整段抄成一个字符串参数；只有 `printtab` / `clearinfo` 没有内容可保留，改成注释。
  `ai/tests/verify_chat_templates.py` 的 `custom_script-info-rewrite` 与
  `custom_script-literal-output` 用例在真 Praat 里守着这条。
- 想退回老路径：`PRAAT_AI_SEND_MODE=argv`（只排障用，会激活 Praat 的子窗口）。
- 脚本执行失败时**不再**弹错误对话框（2026-09-21 改的，见 §8.9）：对话窗口用自己的
  消息投递，Praat 那边的 `cb_userMessage()` 认出是前端发来的消息后把错误原文写进
  `runtime/chat_failure.txt` + 结果文件，并补一句完成标记；前端立刻把这条当失败，
  **一次都不再等 25 秒**，错误原文也显示在对话里。别人的 `--send` 消息保持原样
  （照样弹对话框），免得把第三方脚本的报错吞掉。
- 回归：`ai/tests/test_sendpraat.py`（纯单测）+
  `python ai/tests/verify_chat_no_popup.py`（真机，会先把 Praat 的窗口收进
  任务栏、置前一个 Tk 窗口，再检查窗口状态和前台焦点都没变；
  `--legacy` 是反证，用老路径跑同一条链路，应当看到窗口被拽出来/前台被抢）。

### 8.6 点「启动前端」闪退：Python 运行器里的 std::filesystem 异常

现象（2026-09-20 用户报的）：选中一个日文名字的声音，在编辑器里点
「前端 → 启动前端」，Praat **没有任何提示就消失**（闪退）。

根因链（真机复现 + 转储分析）：

1. `PraatAiControl_startFrontend()` → `runControlCommand()` →
   `praat_runPythonScriptFile()`（`sys/praat_python.cpp`）会先把**选中的对象**
   导出到 `%TEMP%\praat_py_workspace_<pid>\`，文件名是 `<id>_<类名>_<对象名>.wav`；
2. 旧代码是 `std::filesystem::path objPath = tempDir / objFileName8.get();`：
   `std::filesystem::path` 收窄字符串按**系统 ANSI 代码页**解释（中文 Windows 是
   936/GBK）。UTF-8 字节恰好是合法 GBK 序列时只是文件名变乱码
   （实测 `1_Sound_鎬濄亜鍑恒仚.wav`）；不是合法 GBK 序列时（例如 `あなた`、
   `音频`、`ソ`、`能`）libc++ 直接抛 `std::filesystem::filesystem_error`；
3. 菜单回调只 `catch (MelderError)`，而 `runControlCommand()` 的 `catch (...)`
   只是 `throw;`，于是异常穿出窗口过程 → libc++abi `std::terminate` → `abort()`
   （崩溃地址就是 `ucrtbase!abort+0x46` 的 `int 0x29`）→ 进程当场结束，
   连错误对话框都来不及弹。

怎么认这条崩溃（排查下次再遇到时照这个走）：

- `%LOCALAPPDATA%\CrashDumps\Praat.exe.<pid>.dmp` 在，事件日志 `Application Error`
  写的是 `ucrtbase.dll` / `0xc0000409`（WER 里的 BEX64）；
- 用 `.pdata` 展开转储里崩溃线程（主 UI 线程）的栈，会看到
  `ucrtbase!abort` ← libc++abi 的 terminate 帧 ← `__cxa_rethrow`（`runControlCommand`
  的 `catch (...)` 重新抛出）← `PraatAiControl_startFrontend`；
- 栈顶指针指向 `NSt3__14__fs10filesystem16filesystem_errorE`（类型名在
  Praat.exe 的 .rdata 里），也就是「未捕获的 filesystem_error」；
- `%TEMP%\praat_py_workspace_<pid>\praat_context.json` 停在 28 字节
  （只写出 `{ "selected_objects": [`, 导出对象时就断了），目录里没有导出的 wav。

修法（三处，缺一不可）：

- `sys/praat_python.cpp`：导出路径改用现成的 `utf8_to_path()`（按 CP_UTF8 转宽
  字符），非 ASCII 对象名不再抛异常，临时文件名也不再是乱码；
- 同一文件：`praat_runPythonScriptFile()` / `praat_runPythonScriptText()` 拆成
  `*_impl()` + 一层 `guardPythonRunner()`，标准库异常统一转成 `Melder_throw`
  （用户看到对话框，而不是进程消失）；
- `foned/FunctionEditor.cpp`：AI 菜单回调统一走 `runAiMenuAction()`，除了
  `MelderError` 还接住 `std::exception` 和 `...`——**任何异常都不允许穿出窗口过程**。

回归：`python ai/tests/verify_ai_menu_no_crash.py`（真机、不用鼠标：开一个临时
Praat → 建 `Sound あなた` → `View & Edit` → 给编辑窗口发 `WM_COMMAND` 触发
「启动前端」的真实回调 → 检查进程还在、没有新转储、`praat_context.json` 完整、
导出文件名不是乱码）。修这条 bug 之前，同一个流程必崩并留下转储。

### 8.7 原生插件（B2）：不重编 Praat 也能加菜单

`ai/plugin/praat_ai/` 是一个 **Praat 原生插件**（`plugin_praat_ai`）。Praat 启动时
会扫 preferences 目录下的 `plugin_*/setup.praat`（`sys/praat.cpp` 的
`Melder_preferencesFolder7()` 那段），所以把文件夹复制到
`%APPDATA%\Praat\plugin_praat_ai\` 就能在菜单里多出：

| 在哪 | 菜单 | 作用 |
| --- | --- | --- |
| 对象列表（选中 Sound） | 右侧动态菜单底部「AI 声学测量...」 | 对话框选参数（`all` 或 `mean_pitch` 等）+ 时间范围，结果写进 Table「AI 测量结果」 |
| 声音 / TextGrid 编辑器 | `Analyses` →「AI 声学测量（圈选段）...」 | 对编辑器圈选的那一段测全部参数 |
| 对象列表窗口 | `Praat` →「启动 AI 对话窗口」 | 启动 Python 前端 |

约定和坑：

- **脚本由表生成**：`praatAiMeasure.praat` 由 `ai/tools/build_plugin.py` 从
  `ai/praat_ai/measures.tsv` 生成（和对话前端同源，所以两边数一致），改了表要
  `python ai/tools/build_plugin.py` 重新生成；`--check` 在单测里守着这条。
  `@@ dedicated`（H/L、谱强调、Hammarberg、峰值/有效值、强度斜率、基频峰值延迟）
  是多步脚本，插件里不重复实现。
- 装/卸：`powershell -ExecutionPolicy Bypass -File ai\plugin\install.ps1`，
  卸载就是删掉 `%APPDATA%\Praat\plugin_praat_ai`。
- `install.ps1` **必须保持纯 ASCII**：Windows PowerShell 用 ANSI 代码页读没有 BOM
  的 .ps1，中文注释会让解析直接失败（实测 `Missing closing '}'`）。中文说明写在
  `ai/plugin/README.zh-CN.md`。
- **表单字段的标签就是变量名**（空格变下划线），而且默认值必须是**带引号的字符串**：
  `real: "Start (s)", "0"` 对，`real: "Start (s)", 0` 会报
  “Only choice, optionmenu and boolean fields can take a number”。批量模式
  （`--run`）里表单不会自己用默认值，必须把参数按位置传给 `runScript`。
- 编辑器那一条（`praatAiMeasureEditor.praat`）读圈选范围要靠 `editor ... endeditor`，
  批量模式没有编辑器（Praat 直接报 `Cannot edit a Sound from batch`），所以它只能
  在真机上手点验证；其余每条都有自动化用例。
- 回归：`python ai/tests/verify_plugin.py`（4 条：菜单注册语法、33 个参数、
  单参数带范围、无声段）+ `ai/tests/test_plugin_build.py`（生成物和表一致、
  菜单指向的文件存在、表单字段数和 `runScript` 参数个数相等）。

### 8.8 跑现成（社区）.praat 脚本（C3）

用户手里那堆社区脚本（声学测量、标注、画图）默认是「在图形界面里对选中对象运行」。
**不能**把它们直接投给用户开着的 Praat：脚本里的 `form` 会弹模态框、脚本报错会弹
错误框，两种都会把后面排队的消息全挡住（§8.5）；而且批处理里表单不会自己用默认值，
直接 `runScript` 会报 `Found 0 arguments but expected more`。

所以 `run_praat_script` 这个工具走**批处理**（实现在
`ai/praat_ai/external_script.py`）：

1. 先让开着的 Praat 把当前声音（列表里只有一个 TextGrid 时再加上它）另存到
   `ai/runtime/external/<uuid>/`——用户自己的对象一个都不动；
2. `external_script.parse_form()` 从脚本文本里读出表单字段，把**默认值**按顺序传进
   `runScript`（等价于脚本作者点 OK 时那个行为）；
3. 起 `Praat.exe --FULL-TRUST --run 包装脚本`，读回脚本自己 `writeInfoLine` 的输出、
   以及它在自己目录里新增/改动的文件；总之**不碰用户开着的那个 Praat**。

约定和坑：

- **批处理里看不到用户当前的对象列表**：脚本拿到的是导出的副本（读回来时会把名字
  改回原名，脚本按 `select Sound "tone"` 找对象也能找到）。所以「对编辑器圈选段
  做分析」这种脚本不能这样跑，reply 里要写清楚，让用户在 Praat 里自己点；
- 表单字段的默认值必须是带引号的字符串；**数值字段的默认值必须是数字**
  （`real: "Start (s)", "0.0 (= auto)"` 这种带说明的默认值是常见情况，遇到就明确
  拒绝并说明，不能猜一个数传进去）；
- 认不出来的字段类型（社区脚本可能有新字段）也**明确拒绝**，不要按错位的参数传；
- 批处理进程有超时（默认 60 秒），脚本自己弹了对话框也不会把前端挂死；
- `MAX_AGENT_STEPS` 之类护栏照旧：`run_praat_script` 算「会改动对象」的工具，
  用户没说「然后再」时不会在第二轮被执行。

回归：`python ai/tests/verify_external_script.py`（真 Praat 批处理，4 条：带表单的
社区脚本 + 无表单 + 脚本报错 + 认不出的字段类型），单测
`ai/tests/test_external_script.py`（表单解析、参数、包装脚本、工具注册、对话窗口
那条分流）。

### 8.9 脚本报错的模态框会挡住后面所有消息

用户报的现象：某条指令让脚本报错之后，**后面每条消息都要等满 25 秒才超时**，而且
错误原文在哪都看不到。

根因（先复现再改，`ai/tests/verify_error_dialog.py` 就是那个复现）：

1. 前端投递的脚本由 Praat 的 `cb_userMessage()`（`sys/praat.cpp`）执行；
2. 脚本报错时它 catch 里调 `Melder_flushError()`，Windows 上（`gui_error`，
   `sys/Gui_messages.cpp`）开的是 `MessageBox (nullptr, msg, L"Message",
   MB_OK | MB_TOPMOST | MB_ICONWARNING)`——**模态框 + 自带消息循环**；
3. 于是：这一条脚本没写完成标记（脚本半路就停了）→ 前端只能等满 25 秒；错误原文
   在那个人工点掉的框里，前端读不到。
   复现实测：报错那一条 `chat_state.txt` 永远不出现（用例里是 `-1.00 秒`），
   而 Praat 进程里多出一个 `#32770`（标题 `Message`）的模态窗口。

修法（C++，两处）：

- `sys/praat.cpp` 的 `cb_userMessage()`：先读一遍消息文件判断**这条是不是对话前端
  发来的**（前端的消息一定带 `# praat-ai` 或引用 `runtime/commands/chat_command_*`，
  见 `praat_ai/sendpraat.py`）。是前端发来的就**不弹框**：把错误拿进变量、
  `Melder_clearError()`，再交给下一句去写文件；别的程序的 `--send` 消息保持原来的
  弹框行为（否则会把别人的报错吞掉）。
- `sys/PraatAiControl.cpp` 的 `PraatAiControl_reportChatScriptFailure()`：把错误
  压成一行写进 `runtime/chat_result.tsv`（用户看得到），补一句 `done` 到
  `chat_state.txt`（前端不再干等超时），再写一份原文到
  `runtime/chat_failure.txt`。
- 前端 `praat_ai/chat.py`：`failure_path()` / `_read_failure()`；投递完先看这个
  文件，有就按「失败」回灌给模型（不是把错误行当结果），失败行照样显示给用户；
  窗口里那句「对话窗口拿不到那些文字」的旧说明也一起改掉了。

回归：`python ai/tests/verify_error_dialog.py`（真机，4 条：准备对象、报错后没有
模态框、报错 0.x 秒内回到结果文件、报错之后的下一条指令不被挡）。改之前是
2/4（报错那条永远等满 25 秒）。

### 8.10 不再每条消息都刷一次对象列表（C5）

原来每条用户消息都先投一条空脚本「刷一遍」对象列表（投递 + 等完成标记 = 一次完整
往返，Praat 卡住时还要白等 25 秒）。现在：

- Praat 在 `chat_context.tsv` 末尾写自己的进程号（`# praat-pid=<pid>`，
  `sys/PraatAiControl.cpp` 的 `writeChatContext`；解析在 `chat.context_pid()`，
  `praat_ai.tools.parse_object_context` 会忽略这一行）；
- `chat.refresh_object_context()` 看到标记就是正在跑的这个 Praat 就**一条消息都
  不发**；标记对不上（Praat 重启过）、文件缺失、对方的 Praat 不写标记时才真的刷
  一次。`force=True` 强制刷（验证脚本用）；
- 老版本 Praat 还有一条同样管用的捷径：`assume_fresh=True`
  （`ChatWindow.context_ready_pids` 记着「这个进程集合已经投递过脚本」，而 Praat
  每执行完一条 app 消息都会重写对象列表）。

**两个坑**：① `context_pid(text=None)` 的默认参数要读文件——第一版写成
`text if text is not None else object_context()`，传空串时解析的是空字符串，于是
「永远认为没有标记、永远 ping」，是 `verify_context_marker.py` 抓出来的，现在有
单测守着（`test_default_argument_reads_the_context_file`）；
② 对象列表文件**所有 Praat 共用一个**：同时开着第二个 Praat 时它会覆盖标记，这时
前端按「标记对不上」处理（回到刷一次的老行为），只是省不下那一趟。

回归：`python ai/tests/verify_context_marker.py`（2 条：Praat 真的写自己的进程号、
标记对上后不再投 ping）、`verify_chat_live.py`（单实例时顺带验一次）、
`ai/tests/test_context_freshness.py`（13 条单测）。

### 8.11 上下文按 token 预算裁，裁掉什么要看得见（A5）

原来历史只带最近 8 条（`qwen.history_messages` 里的 `history[-8:]`）、对象列表整份
塞进 system prompt。可 `ctx` 只有 8192，**光工具 schema 就占 ~6.6k token**（实测
`estimate_tokens`：36 个工具的 JSON ≈ 18k 字符），所以长对话/长对象列表时会被服务端
静默截掉，表现为模型突然「忘了」前面说过什么。

现在 `chat.run_turn()` 先算预算：

```
预算 = ctx − 工具 schema − 系统提示 − 用户这句话 − 回答预留(plan_max_tokens) − 安全余量(200)
对象列表 ≤ 预算 / 3（它必须让模型看到「当前选中」）；剩下的给历史
```

- `qwen.estimate_tokens()` 只求够准：CJK 1 字 ≈ 1 token，其余 ≈ 4 字符 1 token；
- `qwen.trim_history()` 从最近往回留，只留「从某句 user 开始」的完整后段；
- `qwen.trim_object_context()` 一定留表头和「当前选中」那一行，省掉的行数写在文本里
  （`（对象列表一共 N 个…还有 M 个没列出。当前选中是 …）`）；
- 省掉的东西写进 `TurnOutcome.notes`（对话窗口显示成提示行），例如
  「对话太长：这一轮只带了最近 2 条历史（省掉更早的 6 条）」，**不静默**。

本机的现实：8192 的窗口里工具说明占了大头，所以历史预算很小（实测约 80 token）。
想多带历史就调大预设里的 `context_tokens`（`ai_config.json` 的 `server.presets`），
或者精简工具说明。

回归：`ai/tests/test_token_budget.py`（14 条：估算、预算扣减、按轮裁剪、对象列表
裁剪、`run_turn` 的提示行）。

### 8.12 等 Praat、等批处理都可以取消（C7）

以前点了「发送」就只能等：Praat 卡住要等满 25 秒，跑社区脚本时更久。现在对话窗口
输入框旁边多一个「停止」按钮：

- `ChatWindow.cancel_event`（`threading.Event`）→ `chat._send_script(cancel=…)` →
  `_wait_for_result()` 每 0.15 秒看一次，置上就立刻返回「已取消」，并把排队中的
  `WM_APP` 换成空脚本（`sendpraat.cancel_pending()`），免得它以后醒来执行**下一条**
  指令的脚本；
- 多轮循环（`_run_agent_turn`）每一轮、每一步之前也看这个标记，取消后不再规划、
  不再执行，reply 直接说「已取消」；
- 本地工具（跑社区脚本的 `run_praat_script`）把 `environment.cancelled` 传给
  `external_script.run_batch()`：批处理进程每 0.2 秒问一次，取消就 `terminate` 它
  ——一个自己循环很久的脚本不必等到超时。

注意语义：取消是「不再等」，**不是**把 Praat 里已经在跑的脚本停下来（Praat 没有
提供这种能力给外部程序）；脚本可能已经跑完、也可能根本还没被 Praat 取走（消息已经
被换成空脚本）。所以结果文件里可能还有它的输出。

回归：`ai/tests/test_cancel.py`（9 条单测）、`python ai/tests/verify_cancel_live.py`
（3 条真机：取消等结果、取消之后还能继续投递、取消一个自己循环很久的批处理）、
`verify_chat_window_ui.py`（顺带验「停止」按钮接上了事件）。

### 8.13 API 配置：填 key 就能接更大的云端模型

本机跑得动的模型有限（8G 显存上 2B 就到顶）。「前端 → API 配置…」让用户改接一个
**云端大模型**（任何 OpenAI 兼容的 ``/v1`` 接口：DeepSeek、OpenAI、百炼、
智谱、Kimi、硅基流动，或者本机 Ollama/vLLM 这类网关）：

- 窗口是 Python + Tk（`ai/praat_ai/api_settings.py`）：服务商下拉 + Base URL +
  模型名 + API key（默认打码，可点「显示」）+ 超时/上下文/回复上限，
  「测试连接」按钮、保存/取消。**测试连接**发一条极小的对话请求
  （`qwen.probe_api`）——比只查 ``/models`` 靠得住，很多网关的 ``/models`` 是假的；
- 保存写进 `ai_config.json` 的 **`api` 节**（这个文件在 .gitignore 里，key 不会进
  仓库）；也可以用环境变量 `PRAAT_AI_API_KEY`（还有 `PRAAT_AI_API_BASE_URL` /
  `PRAAT_AI_API_MODEL`）覆盖，界面里留空即可；
- 勾上「使用云端 API 模型」之后，`config.load_config()` 会把 api 节的地址/模型/key/
  上下文搬进 `config.qwen` 并把 `provider` 设成 `api`（`apply_api_to_qwen`）——
  对话链路到处用的都是 `config.qwen`，所以**别的地方一行都不用改**；本地
  llama-server 的配置原样留着，取消勾选就回到本地；
- API 模式下：`server.auto_start` 被强制关掉（不许悄悄拉起 llama-server），
  `control.start_frontend/stop_frontend` 都不碰本地服务（但「停止前端」仍会收掉
  之前启动过的本机服务，腾显存），状态栏/菜单显示 `模型: <云端模型>` +
  `状态: 运行中（API 模式）`；**key 一个字都不进 `runtime/status.json`**；
- 请求形状随 `provider` 变：`llama.cpp` 带 `chat_template_kwargs`（多轮回灌靠它，
  见 §8.4），`api` 不带——云端不认这个字段；遇到只认 `max_completion_tokens` 的
  新模型会自动换字段重试一次（`QwenClient._post`）；
- 对话窗口里也有同一个入口（「API 配置…」按钮）；点「应用预设」= 回到本地模型
  （会顺手关掉 API 模式），这样两边都走得通。

回归：`ai/tests/test_api_settings.py`（17 条：配置解析/环境变量/请求形状/key 不泄漏/
校验/保存/探测）、`python ai/tests/verify_api_mode.py`（5 条：自己起一个**假的
OpenAI 兼容服务**，真走 HTTP 跑完一轮 `run_turn`——工具 schema 78 个字段都在、
没有 llama.cpp 专有字段、Authorization 头正确、工具调用被真的执行）、
`python ai/tests/verify_api_menu_live.py`（真机：在编辑器菜单里找到
「前端 / API 配置...」并触发它的回调，小窗口弹出、关掉之后 Praat 还活着）。

### 8.14 加载/停止模型的进度小窗口

加载一个 2B 模型要十几秒，以前这段时间界面什么都不说。现在两条入口都有**一个小窗口
带一根进度条**：

- **Praat 菜单那一路**（「启动前端 / 停止前端 / 添加模型路径…」）：控制脚本把进度打到
  标准输出（`PRAAT_PROGRESS\t<0-1>\t<说明>`），Praat 侧由
  `sys/praat_python.cpp` 的 `handlePythonOutputLine` 接住 → `Melder_progress` →
  Praat 自己的进度窗口（标题「正在处理中」，一根进度条 + 一个「中断」按钮，
  `waitWhileProgress` 会抽消息队列，所以窗口能刷新、Praat 也不僵）；
  进度点是 `control._progress`：查显卡/运行参数 0.05 → 准备启动 0.08 → 查端口 0.10
  → 启动进程 0.15 → `QwenServerManager._wait_for_endpoint` 里按等待时间从 0.2 爬到
  0.95 → 就绪 1.0；停止是 0.1 停服务 → 0.6 等端口 → 1.0；
- **对话窗口那一路**（点「应用预设」，以及切到 API 模式后自动停本地服务）：
  `praat_ai/progress_popup.py` 的 `MiniProgress`——一个只有一句话 + 一根进度条的
  迷你窗（不可缩放、置顶、不给中途关），数据走同一个进度回调
  （`control.*(progress=...)`），窗口线程只通过 `messages` 队列更新，不跨线程碰 Tk。

回归：`ai/tests/test_model_progress.py`（8 条：`PRAAT_PROGRESS` 行与回调、
加载/停止真的会发进度、顺序单调、API 模式不动本地服务）、
`python ai/tests/verify_model_progress_live.py`（真机：从菜单点「启动前端」，
**加载过程中确实出现了进度窗口「正在处理中」、加载完自己关掉**；再点「停止前端」
同样看到进度窗口、端口释放）、`verify_chat_window_ui.py`（进度消息 → 迷你窗出现/
更新/关闭，以及「API 配置…」按钮能开出窗口）。

#### 8.14.1 「窗口打开时没有进度条、闪一下就没了」是怎么来的（2026-09-21）

用户实测：点「启动前端」后窗口先是没有进度条，随后进度条闪一下，窗口跟着就关了。
这是三个独立原因叠出来的，每一个单独都能造成那个观感：

1. **C++ 里「先显示、后填内容」**（`sys/Gui_messages.cpp` 的 `gui_progress`）：
   原来是 `GuiThing_show (dia)` 之后才设标签和进度条，设完只做一次 `GdiFlush ()`
   ——它只把 GDI 调用刷出去，**不抽消息队列**，所以第一帧画的是空窗口；进度到
   1.0 又直接 `GuiThing_hide`，用户就只看到「闪一下」。现在：先把标签/进度条设好
   再 `show`；满格时先画满格那一帧再隐藏；显示之后抽一次消息队列，再用
   `RedrawWindow`（父窗口）+ `UpdateWindow`（进度条控件）强制重画两遍。
   - **坑**：`GuiObject->d_widget` 不是 HWND，HWND 在 `structGuiObject::window`
     字段里（见 `sys/GuiP.h`）；窗口还没真正显示就先 `UpdateWindow`，会把重画请求
     消费掉，第一帧依旧是空的。
2. **进度根本没送到 Praat**（`ai/praat_ai/control.py`）：`QwenServerManager` 的进度
   只回调给了对话窗口，没走 `_progress` → `PRAAT_PROGRESS` 那条路，于是 8 秒加载
   期间 Praat 那边停在 0.05，最后一下跳到 1.0。现在 manager 的 `progress` 传的是
   `lambda fraction, message: _progress(fraction, message, progress)`，两个界面同时涨。
3. **启动前两次 HTTP 探测各卡满 2 秒超时**（`ai/praat_ai/server.py`）：
   `ensure_started` 上来先问 `server_model_state` / `endpoint_available`，而**本机端口
   是静默丢包**（不是立刻拒绝），一次探测要等满 2 秒，两次就是 4 秒，进度条就定在
   原地。现在先花 0.25 秒做一次纯 socket 的 `_endpoint_port_is_open`（按 `base_url`
   解析 host/port；取不出地址时返回 `True`＝「当它开着」，保持原来的 HTTP 探测行为），
   端口没开就跳过那两次 HTTP 探测；`_wait_for_endpoint` 也改成「**先报进度** → 再快速
   探端口 → 端口开了才用 0.8 秒短超时问一句」，`expected` 从 30 秒改成 15 秒。
   - 顺手修的：`_spawn` 里 `Popen` 失败（llama-server 路径不对、那个文件不是可执行
     文件……）时，原来会漏出原始 `OSError`，还会把 `qwen-server.log` 的句柄留在手里
     （Windows 上这个文件之后连删都删不掉）；现在先关句柄，再报
     `无法启动 llama-server：…`。
4. **太快结束也像「闪一下」**：加载完那一下补了 `finishProgressWindow ()`
   （`sys/praat_python.cpp`：先 `Melder_progress (0.999)` + 停 250 毫秒 + `1.0`，
   让满格那一帧真的画出来）；对话窗口那一路的迷你窗（`progress_popup.MiniProgress`）
   有 `MINIMUM_VISIBLE_SEC = 0.8`，打开不足 0.8 秒时 `hide_progress` 用
   `root.after` 延后关，不在弹出的同一瞬间消失。

实测数据（2026-09-21，0.8B 预设）：冷启动从 7.9 秒降到 4.1 秒，进度每 0.25 秒前进
一格；逐帧数绿色像素：第一帧 0 px（只有轨道和文字）→ 0.2 秒后 14 px → 3.2 秒 73 px
→ 4.2 秒 119 px。也就是说窗口**第一帧就有进度条（轨道 + 文字标签）**，绿色填充在
0.2 秒内跟上——Win32 进度条在被映射的那一帧仍按旧位置画，这个滞后在控件内部，
C++ 已经重画两遍，剩下的属于截图工具会放大的观感。

回归：`ai/tests/test_frontend_model.py`（新增「端口上没东西在听时跳过两次慢探测、
而且一开始就报进度」和「llama-server 路径不对时报中文错误、不泄漏日志句柄」）、
`ai/tests/progress_window_utils.py` + `verify_model_progress_live.py`
（真机抓两张 PNG 数像素：第一帧必须有进度条，0.5 秒后填充必须变多）。
