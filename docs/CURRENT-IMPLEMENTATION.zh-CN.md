# 当前实现与检查入口

本文按仓库源码说明当前模块职责、用户入口与实现限制。源码是判断实现行为的依据；检查脚本是复现方法，不代表已在当前环境通过。安装包、配置、供应商服务和运行中的窗口需分别核实，不能由旧构建记录推断。

## 桌面工作台

默认入口为 `ai/start_ai_chat.py`、`ai/run_ai_chat.py` 与 `ai/praat_ai/modern_host.py`，界面使用 `ai/frontend` 的 React 资源和 WebView2 宿主。显式 `--legacy` 路径使用 Tk。现代后端仍通过 `modern_execution.py` 适配 `chat.py` 中的部分工具和投递逻辑。

`modern_app.py` 提供白名单 RPC、后台任务和按游标读取事件；每个会话同时一个任务，全局最多八个任务。Praat 投递由执行器共享锁串行管理，本地推理资源也串行租用。切换会话保留后台任务，关闭后不会自动重放工具。

`modern_store.py` 保存现代会话；`modern_organization.py` 管理分区、置顶、归档和分叉；`modern_search.py` 提供搜索。现代数据库在运行目录的 `modern/sessions.sqlite3`，旧 `conversations.sqlite3` 作为只读历史来源。分叉复制记录和证据，创建独立会话，不重放操作。归档、移除分区和删除会话是不同操作。

前端交互与第三方来源见 [前端架构](ai-frontend/CHAT-UI-ARCHITECTURE.zh-CN.md)、[宿主协议](ai-frontend/HOST-CONTRACT.md) 与 [来源说明](ai-frontend/FRONTEND-SOURCES.md)。布局像素值和菜单文案以当前组件、样式与原生菜单实现为准。

检查入口：`ai/tests/verify_modern_desktop.py`、`test_modern_app.py` 及 `ai/frontend` 的测试配置。桌面检查应使用隔离配置和数据库；真实云端、模型加载及用户音频需要独立验证。

## 云端对话与分析

`dialogue_policy.py` 用本地保守匹配区分明确寒暄、概念问题和分析请求。涉及材料、对象、范围、操作、指代或继续任务时保留分析路径。分流不增加模型分类请求；它不能理解全部自然语言意图。

`api.force_deep_thinking` 默认关闭，仅对最高思考档位生效。明确普通对话在最高档且开关关闭时使用关闭额外思考的请求；概念解释与分析保留相应强度。供应商是否接受思考字段由实际 API 路径决定。

`cloud_agent.py` 承担模型与图执行；`escape_policy.py` 的 `AnalysisState` 保留原始目标、交付项、证据、失败和总预算。L0 为工具执行，L1 为有区别的纠正，L2 为证据解释，L3 为直接音频分析，L4 为一般讨论。默认单轮模型请求限额为 12，工具尝试限额为 20；连续两轮无新增证据退出当前执行分支。执行前参数提案被拒与实际执行失败分别处理，不能把一切参数错误当成已运行工具失败。

继续动作携带原目标、已有证据、上一份报告和覆盖信息，建立新轮次预算。成功证据不会因失败分支而被抹去。材料身份、当前能力与预算仍需在执行时重新检查；保存过报告不代表源材料仍可取得。

检查入口：`ai/tests/test_dialogue_fastpath.py`、`test_dialogue_measurement.py`、`test_cloud_escape.py`、`test_staircase.py`、`test_staircase_review_fixes.py`。这些检查的既有期待可能与实现存在差异，差异需要判断后处理，不能直接变成产品规则。

## 输出与上下文预算

`Budget` 区分可见正文额度和推理预留。思考预留为 off=0、low=1024、medium=4096、high=8192、auto=4096；这是应用估算，不是服务端实际消耗的保证。上下文检查同时预留输出、误差和新增结果空间。

`api.dialogue_max_tokens` 默认 2048，对话正文额度还受本轮回复预算约束。未开启用户 token 限制时，应用仍有上下文和输出保护值；其中 131072 是应用上下文保护值，不能宣称为所选模型的真实窗口。

流式对话因 `length` 截断时有一次续写路径；再次截断可保留已生成正文并标记未完成。输出上限被服务端拒绝、传输失败、结构化报告校验失败各有独立的有限恢复路径，均受总预算和取消控制。工具阶段不能为恢复输出而自动重放已投递操作。恢复不保证所有供应商或所有输出格式都能成功。

检查入口：`ai/tests/test_dialogue_protocol.py`、`test_cloud_protocol.py`、`test_token_budget.py`、`test_report_chain_regressions.py`。

## 阶段历史、技能与缓存

现代执行器通过 `session_runtime(session_id)` 为会话复用 `CloudRuntime`。runtime 按端点、模型、密钥与超时配置身份更新客户端；会话释放和执行器关闭时关闭资源。连接复用不等于服务端提示缓存命中。

`session_context.py` 的 `PhaseContext` 管理 SDK 原生消息、正式历史同步、配置身份和上下文版本。配置或历史前缀变化会重建相应上下文。其持久化协议标识为 `pydantic-ai-2.52.0`；包含非文本用户内容的消息不直接序列化到该持久载荷，音频与附件保持任务范围。

`skill_registry.py` 从 `ai/skills` 按现有任务匹配加载 prosody、placement、failure 指导。技能正文追加到任务阶段消息，不注册工具或执行脚本；代码守卫继续管理权限与证据。技能文件本身不能证明输入更少或缓存更快。

`cloud_metrics.py` 和请求观察逻辑记录阶段用量与请求指标。缓存收益需核对最终序列化请求、供应商返回的缓存用量和等价样本的时序；未知统计保留未知，不能用单个场景推广为全场景提速。来源和许可见 [上下文组件来源](../ai/third_party/pi-context/SOURCES.md)。

可复现检查方法见 [上下文与缓存检查](verification/2026-10-06-pi-context-cache-results.md)。

## 工具、报告守卫与投递事实

`tool_guards.py` 校验工具参数、目标和执行条件；`tools.py` 的参数表及 schema 应保持一致。`measure` 接受受支持的多个参数名，并规范化分隔符；这不表示任意专用工具参数都能并入通用测量。

`report_guards.py` 核对报告中的对象、来源、量纲、数值和部分结论。引用修复、推导标注及覆盖项整理与阻断分别计数。报告守卫可以发现特定不一致，不能证明语言学结论正确；自由标签的同值匹配也不能证明语义对应唯一。

报告拒绝后，`cloud_agent.py` 可保留草稿并遮罩未通过核对的位置；没有可保留草稿时生成阶段记录。救援稿的核对状态不能显示为已验证。`escape_policy.note_guard` 将稳定规则 ID 写入 `metrics.guard_blocks` 和 `metrics.guard_repairs`，方便区分阻断与自动修复。

`delivery.py` 区分 `not_delivered`、`delivered`、`unknown` 和 `blocked`。脚本交出后没等到完成标记属于执行结果不明，不能按未投递处理或盲目再投。测量完成、音频发送、收到音频响应和报告完成也分别记录。

检查入口：`ai/tests/test_tool_guards.py`、`test_report_guards.py`、`test_report_chain_regressions.py`；报告链路检查方法见 [报告与重试检查](verification/2026-10-06-report-chain-fixes.md)。

## API 音频与材料

`model_capabilities.py` 区分启用设置、名称预设、能力事实和当前可用性；名称预设是代码内的登记，不是实时供应商能力查询。未知名称默认关闭，自定义网关按名称推定也不能证明实际协议可用。`api_diagnostics.py` 与 `audio_probe.py` 提供连接诊断和可选音频验证。

明确的模型或端点不支持音频错误可纠正当前路径的启用设置；账号错误、限流、超时、格式问题不能统一归为模型不支持。纠正写回前应核对请求配置身份，避免覆盖用户随后切换的配置。一次探针结果只支持相应测试范围，不能证明供应商内部处理方式。

`materials.py` 管理目标材料与临时快照；持久记录保存来源、范围与相关证据，不把 SDK 音频字节长期嵌入阶段历史。转写、测量、模型听感与一般知识是不同证据来源。缺少原始音频或实际调用证据时，报告不能声称已听取材料。

检查入口：`ai/tests/test_api_capability_status.py` 及音频能力相关测试。供应商端点的真实可用性、静默忽略音频和 HTTP 状态传播需要按当前配置检查；旧记录不能作为当前通过结论。

## VOT 与语音资源

当前原生语音段扩展为 VOT：`fon/SegmentAcousticAnalysis.cpp`、`fon/SegmentAcousticVOT.h` 和 `fon/praat_Sound.cpp` 提供手动边界、候选估计、Sound/LongSound 适配与 TSV 导出。原生手动值按 `(voicingTime - burstTime) * 1000` 计算，可表达零值和负值；候选结果需人工确认。TSV 保留来源、范围、参数、单位、状态和原因。

AI `vot` 工具在 `ai/praat_ai/tools.py` 使用独立脚本模板。显式边界目前拒绝 `voicing <= burst`；LongSound 需先提取成 Sound。它未统一调用原生 `Write VOT analysis to file` 路径。这是当前适配差异，不能据此规定 VOT 业务上只允许正值。统一行为的产品取舍仍需明确。

此前包含元音鼻化、鼻辅音、R 音及通用目标/参考比较编辑器的扩展方案不属于当前实现范围，不能作为仍待执行的计划。已有 Praat 基础测量工具不等于该扩展已实现。

`speech_dictionaries.py`、`alignment.py`、`forced_alignment.py` 管理语音词典、模型及对齐资源。词典与音频模型不同；资源存在和模型可加载也不保证用户材料的对齐质量。

检查入口：`ai/tests/test_vot_dispatch.py`、`test_segment_analysis_tools.py`、`verify_segment_analysis_templates.py`、语音词典相关检查。原生与 AI 两条 VOT 路径应分别检查，不能沿用另一条路径的通过结论。

## Windows 启动、菜单与安装

`installer/src` 提供安装向导、路径配置、Python 环境设置和启动器；`installer/build.ps1` 构建安装包。安装与依赖要求以当前向导及配置校验源码为准。构建产物是否含最新源码、离线资源和许可证需核对载荷，仓库内旧哈希或版本说明不能证明当前安装器状态。

`modern_app.LocalResources` 在任务租用时，对已配置 llama-server 和模型、端口匹配的回环服务按需启动；等待加载后再发模型请求。外部服务按其配置连接，管理器只停止自有进程。

原生菜单和状态由 `sys/PraatAiControl.cpp` 与相关 Windows GUI 实现维护。API 模式不应把本地模型资源显示成已加载；API 设置入口、模型页跳转和语音资源入口需结合当前宿主和菜单动作核对。

当前 `sys/praat_python.cpp:get_process_workspace` 使用系统临时目录与进程 ID 创建工作目录。源码中没有旧验收文档描述的 `praat_python_workspace.h` 或 LocalLow 选择逻辑；Low 完整性进程写普通 TEMP 可能失败。`Message.txt`、偏好文件或 EXE 的访问状态属于实际环境条件，不能把某台机器的标签修复当成源码已解决。

Tk 的 `ui_windows.py` 提供 DPI 与输入法组合字体同步；旧窗口发送键处理与现代编辑器的组合状态处理应分别检查。第三方输入法、多屏缩放和实际菜单重绘表现不能仅由源码确认。

检查入口：`installer/tests`、`installer/verification`、`ai/tests/test_ime.py`、`test_ime_keys.py` 和菜单/权限相关验证脚本。运行前阅读脚本，使用私有环境，检查是否会启动原生程序、加载模型或调用云端。

## 当前核实边界

检查结果只适用于其源码版本、环境和材料。功能测试、真实云端请求、模型推理、音频分析与安装包构建需要分别记录结果；本页的源码说明不构成这些检查已通过的证明。

需要独立核实的事项包括 VOT 两条路径的产品取舍、API 诊断异常中的 HTTP 状态传播、继续分析的音频完成状态、旧 Tk 交互、真实供应商音频协议，以及当前安装包与源码的一致性。这里只说明可见实现和检查入口，不将未确认偏差转成业务规则。
