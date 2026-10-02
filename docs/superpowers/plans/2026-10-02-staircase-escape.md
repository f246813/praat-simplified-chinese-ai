# AIPraat 阶梯逃逸 Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, as explicitly authorized in the build handoff.

**Goal:** 单 API 下构建有界工具执行、独立报告、原始音频分析、点击继续与可查看记录。

**Architecture:** pydantic-graph 管理入口、专用执行与报告节点；Pydantic AI 管理云端请求与工具消息。Tk 队列和既有 Praat 执行器保留，本地 Qwen 路径不迁移。

**Tech Stack:** Python 3.12 / Tk / pydantic-ai-slim[openai] / pydantic-graph / jsonschema / sqlite3。

**Spec:** docs/2026-10-02-阶梯逃逸设计草案.md，第 1–12 节。

## Global Constraints

- 当前非 Git 目录内实施，修改前备份相关源码；不创建 Git 仓库或 worktree。
- 首版只用当前一个 API；每问题一次有区别修正、连续两轮无有效进展退出。
- 所有阶段共用预算、取消事件；执行状态不明后不再次投递。
- 原目标与材料绑定；音频字节不写入持久记录，关闭后清理核实任务目录的临时片段。
- 不发送用户录音作为能力探针；明确不支持错误才持久纠正当前路径能力。

## Review Focus

- 工具 schema 与现有业务默认值一致，失败行不能被计为可靠证据。
- 重复调用、改参数反复失败、请求上限均能交付原目标的阶段报告。
- 配置处理中改变模型或能力后，旧请求不能覆盖新设置。
- 继续时选区改变或原对象消失，必须沿用快照或明确缺失，不替换材料。
- 关闭或取消发生在模型请求及工具投递中，后续节点不得执行。

### Task 1: 能力与材料边界

**Files:** model_capabilities.py、config.py、api_settings.py、materials.py；test_escape_capabilities.py。
**Interfaces:** audio_preset(base_url, model)、audio_path(config)、correct_audio_setting(path, identity)、TaskMaterials。
- [x] 写测试并验证失败：明确音频模型预设、未知关闭、手动持久、错误分类与并发更新、任务目录清理。
- [x] 实现字段、复选框、可选合成音频验证、材料快照与安全清理。
- [x] 运行新测试及 API 配置现有回归。

### Task 2: 阶梯与云端会话

**Files:** escape_policy.py、cloud_agent.py；test_staircase.py。
**Interfaces:** AnalysisState、run_cloud_turn(config, state, execute_action, cancel, progress) → state。
- [x] 写失败测试：两轮停滞、一次修正、依赖立即退出、成功后独立 L2、取消、低上下文收尾、来源覆盖。
- [x] 实现 GraphBuilder 节点、Agent.iter 逐步驱动、Tool.from_schema + jsonschema、共享 UsageLimits、协议适配与独立报告。
- [x] 验证真实 SDK 序列化、流式音频路径与假供应商 HTTP 兼容测试；冻结已验证版本。

### Task 3: 记录与 Tk 集成

**Files:** conversation_store.py、chat.py；test_escape_integration.py。
**Interfaces:** ConversationStore、继续 prompt、当前窗口 AnalysisState。
- [x] 写失败测试：无 Praat 讨论、继续只提交一次可见 prompt、测量复用、重开仅查看、无音频字节及密钥。
- [x] 云端接入阶梯；按操作检查 Praat；继续按钮与记录查看；关闭取消并安全清理。
- [x] 运行 GUI 验证与完整单元回归。

### Task 4: 打包与交付

**Files:** ai/requirements.txt、安装器依赖流程、构建验收记录。
- [x] 核对安装器实际安装命令与 Python 版本；验证依赖闭包。
- [x] 独立代码复核；修复重要问题并重跑相关检查。
- [x] 写实际证据与限制，完成源码交付。

## Execution ledger

- 2026-10-02：已读取确认设计、guide 相关前端规则和原执行接口。
- Ruling: 用户明确要求在非 Git 本地目录内联实施，省略技能默认的 worktree、提交与再次确认步骤；使用源码备份保存回退点。
- 依赖候选：pydantic-ai-slim / pydantic-graph 2.52.0、jsonschema 4.26.0；安装与 API 接入验证中。

- 实际执行：采用 pydantic-ai-slim[openai] / pydantic-graph 2.52.0、jsonschema 4.26.0；SDK 维护会话协议，应用维护证据、串行副作用和共享总账。
- TDD 已观察首轮缺模块、预算漏算首请求、SQLite Windows 句柄、配置并发、目标绑定、无效 WAV、继续预检与遗留清理等失败，再逐项修复。
- 独立复核报告四项 Important、零 Critical，均已修复并补回归。实际 SDK 的本机 HTTP fixture 验证 Qwen 流式 URI、Gemini/OpenAI 兼容音频编码、明确能力错误降级、reasoning 字段与限流有限重试。
- 最终主环境 Python 3.12.14：706 项 Python 单元/集成/真实 Tk fixture 测试通过；安装契约 21 项、路径 15 项、Python 配置 4 项通过。一键配置在新虚拟环境实际执行：首次安装、重复配置、缺失解释器三场景通过。
- Windows cp310/cp314 的新增依赖闭包均为 31 个 wheel，下载量约 9.8 MiB；这是解析/下载验证，不冒充 Python 3.10 实际执行验证。
- 首版无真实供应商请求、无用户录音上传、无语言学准确度验收；详细证据与限制见 ../../2026-10-02-阶梯逃逸实现验收.md。
- 用户实际 Python 3.14.8 / Tk 9.0.4：已补齐固定依赖，92 项新增及受影响测试通过；最终安装包及 67 内容哈希与当前源码一致。
