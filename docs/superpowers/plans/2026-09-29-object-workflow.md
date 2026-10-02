# 对象工作流与 API Prompt 修复计划

> 执行方式：用户要求自主执行。主代理集成，独立任务并行实施；测试先失败再修复，最终独立审查。目录为导出快照，无 Git 仓库，修改前源码已备份。

**Goal:** 修复选择 Sound 后仍操作 Harmonicity 的错误，并让 API 模型完成有依据的多步语音分析。

**Architecture:** 每步使用最新对象状态，向规划模型同步变化；分析模板按可接受的对象类型生成命令。云端 Prompt 独立于本地小模型的保守约束，保留测量真实性和工具参数正确性。

**Tech Stack:** Python unittest、Praat 原生脚本、现有 OpenAI 兼容工具调用接口。

**设计范围:** 现有 chat.py、tools.py、qwen.py 及其测试；不修改用户音频、API 密钥和模型选择。不新增外部依赖。审计确认原生完成标记早于错误和上下文写入，纳入最小 C++ 协议修复并重新编译。

## 全局约束与重点边界

- 选择、创建、重命名、删除对象后，下一步与后续轮次必须获取最新对象。
- 刷新失败时不能继续使用过期对象状态；工具调用与工具结果的消息结构保持合法。
- 明确对象与多个候选须消除歧义；派生对象只能接收其支持的查询。
- 整段分析不得因编辑器旧选区而静默分析局部；明确时间参数仍生效。
- 云端多步分析、知识解释和透明计算应可用；失败结果不能成为实测依据。
- 本地模式、API 严格知识模式、取消行为和现有环境配置兼容。

## Task 1：输入对象与脚本模板

- [x] 构造 Sound / Harmonicity / Pitch / Intensity / Formant 混合对象的失败回归。
- [x] 修复类型解析与命令生成，并检查同类转换工具、时间范围与参数别名。
- [x] 对生成脚本运行单测和真实 Praat 批处理，验证正确对象可执行、错误类型提前拒绝。

## Task 2：多步上下文同步

- [ ] 回归覆盖先选择 Sound 再查询、创建新对象、重命名/删除以及失败状态刷新。
- [x] 为执行循环添加对象刷新接口；同时更新工具上下文与模型可见现场信息。
- [x] 覆盖原生 tool calling 和 JSON 规划方式，保留取消与重复调用语义。

> 2026-09-30 接手补充：加了「用户故障链」端到端回归
> （`test_user_failure_chain_never_analyses_the_harmonicity`：先选 Sound 再连做
> 基频/强度/共振峰，必落到 `selectObject: 1`），以及整段请求清选区的 8 项断言。
> 「重命名/删除/导入后下一步对象状态」仍只有单测级覆盖。

## Task 5：脚本与 Prompt 同类错误排查（2026-09-30 接手新增）

- [x] 用真实 Praat 实测「哪些对象类支持 `Get total duration`」，确认
      `TIME_DOMAIN_CLASSES` 的增删有依据（Manipulation / Spectrum / Ltas /
      Cochleagram 都不支持时长查询，删掉是对的）。
- [x] 逐个体检所有做 `To Pitch` / `To Intensity` / `To Formant` / `To Spectrum`
      转换的模板，确认都收窄到「Sound + 对应派生对象」，没有第二个
      「只查时长、却拿去转换」的口子。
- [x] 发现并修掉同类别名缺陷：`textgrid_set_interval` 不认 `from`/`to`，
      而云端 Prompt 和 `pitch_statistics`/`measure` 的 schema 都在教模型用
      `from`/`to`；同一句话在 `extract_part` 能跑、在标注里直接报「需要 end 参数」。
- [x] 两个工具的 schema 与 `signature` 同步补上 `from`/`to`（`test_planner_tools`
      的 signature 一致性守卫会挡住漏改）。
- [x] 确认 `measure` 的派生对象收窄条件是「所需来源 ⊆ 该对象能提供的一个来源」，
      不是过窄；`PointProcess` 上的 jitter、`PowerCepstrogram` 上的 CPPS 仍然可用。
- [x] `_request_context`：只改列数**正好 6** 且首列为数字的行，列更多时不再截断，
      末尾换行保持原样。

## Task 4：集成与交付

- [x] 运行完整 AI unittest，并检查所有失败。
- [x] 在隔离 Praat 实例/批处理运行用户故障链及同类脚本。
- [x] 使用本地假 API 验证完整接口；必要时对当前云端做一次受控验证，避免发送用户录音。
- [ ] 独立检查全部源码差异，修复实质问题。
- [x] 更新操作说明和验证记录；新版 Praat 与重开前端的步骤已交接。

> 2026-09-30：组合验收做完了。新增 `ai/tests/verify_cloud_live_analysis.py`，
> 用 **Praat 自带测试音频**（不是用户录音）把「真云端 HTTP」和「真 Praat 批处理」
> 接在一起跑用户原话「分析整段语音，指出我的发音有哪些不足」——**8/8 通过**，
> 7/7 脚本在真 Praat 里跑完，5 处派生转换全部作用在 Sound 上。
> 顺带发现并修掉：收尾那轮网络失败会让整轮结果全部作废（现在重试一次后退回实测摘要）。
> 用户同时要求把旧 `Praat.exe` 换成新版，已备份并替换（见 `ai/HANDOFF.md`）。

## 2026-09-29 阶段收尾

用户要求额度将尽时完成当前步骤并交接，当前源码和新版二进制已完成上述实现。
596 个 unittest、5 项隔离原生回调验证通过。尚未替换用户正在运行的旧程序；
完整模板脚本、组合假 API+真 Praat、多对象边界和独立审查留到下次。
具体未完成事项与已发现边界以 `ai/HANDOFF.md` 最新节为准。

## 2026-09-30 接手复查与补充

上一阶段的 `read_file-missing` 模板期望已按交接要求更新（改为断言「脚本中途失败 +
中文错误出现在输出里 + 没写 `chat_state.txt`」，新增 `Case.expect_error`），完整模板验收
从 97/98 变成 **100/100**（另加 `textgrid_set_interval-from-to`、`extract_part-from-to`
两个别名用例）。完整 unittest 从 596 变成 **615/615**。

新发现并修掉的实质缺陷只有一个：`textgrid_set_interval` 的时间参数别名与其余工具不一致
（见 Task 5）。其余复查项（对象类型收窄、`_request_context` 列处理、云端/本地 Prompt
分流、`measure` 派生对象判定）都确认无误，证据记在 `ai/HANDOFF.md` 最新节。

仍未完成：组合假 API + 真 Praat 的多步验收、以及按工具名清除失败状态的边界核查。

