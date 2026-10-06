# 现代 AI 前端：构建与验收结果

> **最新历史分区与分叉已接入。** 会话省略号／右键菜单新增分区和分叉；分区右侧菜单提供编辑、归档、新建、移除，支持拖放排序和归档恢复。公开 Codex 源码边界、持久化与生产验收见 [CODEX-HISTORY-SECTIONS-RESULTS.zh-CN.md](CODEX-HISTORY-SECTIONS-RESULTS.zh-CN.md)。

> **最新会话侧栏全部交互已接入，贴边滚动条扩大为 14px 命中通道，生产 dist 已更新。** 分组、预览、菜单、多选、快捷键和拖动的来源与当前验收见 [PI-SESSION-SIDEBAR-RESULTS.zh-CN.md](PI-SESSION-SIDEBAR-RESULTS.zh-CN.md)。前轮菜单移植记录保留在 [SESSION-MENU-RESULTS.zh-CN.md](SESSION-MENU-RESULTS.zh-CN.md)。

> **正常用户菜单路径已修复并真实验收通过。** 双击本项目 Praat → 导入文件 → 查看并编辑 → 前端／启动前端；无需 PowerShell，不自动弹出。根因、解释器备份／回退及本轮5项 met证据见 [MENU-LAUNCH-RESULTS.zh-CN.md](MENU-LAUNCH-RESULTS.zh-CN.md)。以下保留前一轮构建验收，其 mock／历史测试不代替本次真实菜单结果。

## 1. 当前交付

用户已授权实施；现代 assistant-ui／React 前端、pywebview／WebView2 宿主、独立 Python 应用／执行服务和离线生产资产已经完成。本轮没有调用真实云端、发布、推送、重新制作安装包，也没有修改原生源码、`Praat.exe` 或其权限。

- 入口：`ai/run_ai_chat.py` → `praat_ai.modern_host.main`；原 `start_ai_chat.py` 启动／置前入口仍调用它。
- 源码：`ai/frontend/src`；锁文件：`ai/frontend/package-lock.json`；已构建资产：`ai/frontend/dist`。
- 宿主与服务：`modern_host.py`、`modern_app.py`、`modern_store.py`、`modern_settings.py`、`modern_budget.py`、`modern_execution.py`。
- 契约：[HOST-CONTRACT.md](HOST-CONTRACT.md)；来源与许可：[FRONTEND-SOURCES.md](FRONTEND-SOURCES.md)、[PI-MODEL-SOURCES.md](PI-MODEL-SOURCES.md)。没有引入 Pi Agent 内核。

会话侧栏、草稿／阅读位置、设置分类、富文本／IME 防误发送、附件、Markdown／代码／公式／离线 Mermaid、后台任务与独立取消已接通一套 host store 和 assistant-ui external-store runtime。普通浏览器无宿主时拒绝工作；演示适配只允许开发模式、loopback 和显式 `?demo=1`，不是生产执行器。

## 2. 启动与回退

普通用户请使用上方正常 Praat 菜单路径。以下仅为维护者的独立宿主／显式旧界面入口，不是菜单启动的前置步骤：

```powershell
# 本机 Python 已安装所需宿主依赖；新环境先准备依赖与 WebView2
python -m pip install -r ai\requirements.txt
python ai\run_ai_chat.py

# 显式回退旧 Tk 界面，不删除现代记录
python ai\run_ai_chat.py --legacy
```

启动已经构建的前端不需要 Node。Windows 需要 WebView2 Runtime 和 Python/.NET 宿主依赖；实际验收环境为 Python 3.12.14、pywebview 6.2.1、pythonnet 3.2.0、WebView2 154。

2026-10-04 已修正云端 API 启用与桌面启动入口未接通的问题：在设置中填写并启用云端 API 后，可从 Praat 菜单正常打开前端，不再需要命令行参数。启动与保存不发送模型请求；点击发送才执行，云端验证仍使用现有确认弹窗。新任务使用当前配置，运行中任务保留启动时快照。该桌面策略只允许启用的 API 端点，不放行“本地模型”字段里的远程地址；`--allow-cloud` 继续保留为显式覆盖参数，隔离服务／测试默认限制云端。

可选参数：`--config <配置路径>`、`--data-dir <现代数据目录>`。未指定时使用现有配置路径和 `ai/runtime/modern`。不要为验收覆盖用户配置或旧库。

## 3. 数据与执行边界

- 新库默认 `ai/runtime/modern/sessions.sqlite3`，与旧 `ai/runtime/conversations.sqlite3` 分开。旧记录通过 SQLite `mode=ro` 读取，不迁移覆盖，不允许续写或重放；阅读位置仅在前端内存中维护。
- 恢复新会话保留对话／摘要／专业证据，未完成消息标记中断，不恢复执行线程。续聊是新任务，重新捕获目标；不把旧 Praat 操作重投。
- 最多 8 个后台任务；同会话重叠提交拒绝。消息、事件、配置快照、目标和取消按原 `sessionId/taskId` 隔离，不按当前选择归属。
- Praat gate 覆盖完整不可交错操作段，现代与旧直接入口共用跨进程 gate；验证原进程、对象和范围。未参与 gate 的外部工具／进程不在此协调范围内。
- 投递事实独立于 UI 状态；unknown delivery 阻断后续不安全投递；取消不撤销已经执行的操作。专业白名单、有限修正、证据复用和独立报告约束保留。
- 设置按白名单原子保存，保留未知旧字段和本地值；空 Key 表示保留，显式清除另设动作。API Key 不回传；任务已捕获的配置不随设置编辑改变。
- 三种 token 模式共用请求策略；未知模型不猜上下文窗口。近满载通过真实摘要压缩保留原消息／证据，安全容纳不了时拒绝，不静默裁剪。仅官方 OpenAI 端点的四条固定元数据可自动识别。
- 活跃快照含未落盘增量，并在同一锁内带事件游标；前端只回放游标之后的消息事件，避免首个流式正文被较早空消息覆盖或重复追加。

## 4. 本轮实际检查

以下计数来自实际日志／JSON，不引用旧版真机测试来替代新前端检查。

| 层级 | 结果 | 验证范围及边界 |
| --- | --- | --- |
| TypeScript 与生产构建 | 通过；最新 Vite 构建 8.90 秒 | 包含离线 Mermaid 和许可 notices；主 JS 约 3,509.69 kB，gzip 1,007.88 kB；有大 chunk 警告 |
| 前端单元测试 | 合并 29 项通过 | 集中 27 项通过；新增 2 项后仅复测受影响 bridge/store 文件，17 项通过；未重复全量 |
| Playwright 浏览器交互 | 集中 4 项通过；修改后相关流式用例 1 项复测通过 | fail-closed、富文本/IME 防误发/草稿/附件/CRUD、设置、长历史/公式/代码/图表/阅读位置/后台流/取消；仅夹具，不是 WebView2 或真实模型 |
| Python 离线回归 | 合并 60 模块、860 项；0 failure / 0 error / 0 skipped | 按模块独立进程集中执行；失败模块修复后针对性复测；最新 modern_app 的 19 项替换旧 18 项，未再跑全量；网络守卫阻止非 loopback 请求 |
| 真实 React＋WebView2 | 可见窗口 9 组全部通过 | 真正的生产 React 资产与受限 RPC，执行层全部为明确标记的 MOCK；用户代理确认 WebView2 154 |
| 真实云端／真实 Praat 端到端测量 | **本轮未执行** | 不声称新入口的真实模型或真实声学测量已验收；历史记录不是本轮证明 |
| 安装包／发布／推送 | **本轮未执行** | 交付源码与本地离线资产；既有安装包没有合并此次现代前端 |

Python 单进程全量尝试曾被旧 Tk 的 Tcl 跨线程析构 fatal 中断，不能宣称那次全量通过；随后采用模块独立进程完成实际回归。代理环境和临时目录仅在测试子进程规范化，不改全局设置。

真实 WebView2 脚本：`ai/tests/verify_modern_desktop.py`，使用临时配置、新旧数据库和 `MockExecutor`，无用户数据。九组检查：

1. 真实 WebView2、React 启动，API 只有 `rpc`。
2. 离线 Markdown／代码高亮／KaTeX／Mermaid。
3. 后台事件保留原会话归属。
4. 取消隔离，保留独立投递事实。
5. 设置仪表盘与凭据隐藏。
6. 重建应用服务并刷新页面，恢复对话且不重放执行。
7. 恢复后的新轮使用历史和新绑定目标。
8. 旧记录只读，旧库 SHA-256 不变。
9. 页面资源仅来自本机资产来源或 data；刷新后记录 30 项资源。

第 6 项是**同一宿主进程内关闭／重建 Python 应用服务＋真实页面刷新**，不是整个 OS 进程重启。脚本等待新的 `performance.timeOrigin`，避免误把旧 DOM 当作刷新成功。隐藏 WebView2 会节流动画帧，最终验收使用可见窗口；没有为测试扩大生产 RPC 或绕过来源校验。中文输入法测试验证事件防误发送逻辑，不等同于所有实体输入法人工验收。

复测命令（临时结果写会话 scratch）：

```powershell
python ai\tests\verify_modern_desktop.py --output (Join-Path $env:PI_SCRATCH_DIR 'modern-desktop-result.json')
```

本轮日志位于会话 scratch（会话结束可能删除，不是交付资产）：`modern-final-build.log`、`modern-frontend-tests.log`、`modern-watermark-tests.log`、`modern-browser-tests.log`、`modern-stream-browser-retest.log`、`regression-modules.json`、`regression-summary.json`、`modern-live-snapshot-retests.log`、`modern-desktop-result.json`、`modern-desktop-acceptance.log`。PowerShell 会把部分原生 stderr 警告包装成 `NativeCommandError`；上述通过结果均同时检查了实际退出码与结果尾部／JSON。

## 5. 重新构建与已知权衡

一般环境：

```powershell
Set-Location ai\frontend
npm ci
npm run build
npm test
npm run test:ui
```

`prebuild` 自动复制官方 Mermaid 分发并生成许可证通知，不依赖 CDN。当前 Rollup 使用官方 `treeshake: false`，避免本机依赖 barrel 图优化超时，功能保留但包体较大；没有把警告伪装成失败，也没有以删功能减包。本轮 Node 为 v24.19.0（不在默认 PATH）。

本机 Low 目录中的原 esbuild 执行器遇到临时文件 Access denied，构建使用**仅临时工具副本和进程环境变量**，没有修改原工具或 Praat 权限：

```powershell
Copy-Item ai\frontend\node_modules\@esbuild\win32-x64\esbuild.exe (Join-Path $env:PI_SCRATCH_DIR 'esbuild-build-tool.exe')
$env:ESBUILD_BINARY_PATH = Join-Path $env:PI_SCRATCH_DIR 'esbuild-build-tool.exe'
$env:TEMP = $env:PI_SCRATCH_DIR
$env:TMP = $env:PI_SCRATCH_DIR
# 确保 Node/npm 在当前进程 PATH 后再进入 ai/frontend 构建
```

已知限制：本地路径没有 WAV 模型输入能力；旧执行入口未提供原始 thinking 流时界面只显示真实进度，不伪造思考。现代真实远程请求、真实 Praat 综合测量及安装包分发仍需各自授权和验收，**不是本次离线构建的阻塞**。工作目录不是 Git 工作树，没有声称完成 Git diff／提交检查。
