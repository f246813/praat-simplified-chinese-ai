# 普通对话响应优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 减少普通对话不必要的推理、规划及报告请求，支持最高档强制深思与文字流式显示。

**Architecture:** 保守本地意图分类；纯文本通道与现有证据分析管线并行；每窗口持有事件循环和客户端。UI 增量不作为正式测量结果，成功后只保存最终消息。

**Tech Stack:** Python、Tk、Pydantic AI/Graph、OpenAI SDK、现有 PowerShell / C# 安装器。

**Spec:** `docs/superpowers/specs/2026-10-02-dialogue-fastpath-design.md`

## Global Constraints

- 工作目录无 Git；使用 `backups/dialogue-fastpath-20261002-d5ed1a31/`，不初始化仓库或复制用户配置。
- `api.force_deep_thinking=false`；仅 high 档生效。其他手动档位和服务端自动保持原含义。
- 测量校验和证据规则保留；不真实调用用户 API、不使用用户音频。
- 保留 Praat.exe 哈希 `777b54ff1ed57484be27aba83f79c22c62b87c3ce8406b2a4f2b0f3b8e7ab37f`。

## Review Focus

- 寒暄加测量、英语操作、文件路径、指代及 continuation 不能误分流。
- 强制高遇到参数拒绝不能静默关闭；网关的兼容学习不能覆盖显式高要求。
- 流开始后异常/取消不能重复输出或发布为完整回答。
- 换模型/凭据后的连接及请求设置不能串用，关闭不能留下线程。
- UI 展开高级选项仍可访问保存按钮；此前能力诊断、自动纠正仍通过。

### Task 1: 设置、分类及供应商参数

Files: config.py、api_settings.py、qwen.py、新 dialogue_policy.py；test_dialogue_fastpath.py。

- [x] 写失败回归：保存开关、默认值、分类/混合输入/指代、强度优先级、Qwen 关闭/低/中/高字段。
- [x] 运行并保留 RED 日志。
- [x] 实现及高级选项可访问布局，运行针对性回归。

### Task 2: 单次纯文本、连接、流式和记录

Files: 新 cloud_runtime.py、cloud_agent.py、cloud_workflow.py、escape_policy.py、chat.py；新增协议、生命周期、UI 回归。

- [x] 写失败回归：一次请求/无工具/无材料，真实 SSE 首字，异常取消，客户端复用/失效/关闭，明确时长快捷工具。
- [x] 运行 RED，实现每窗口 runtime、纯文本请求及 UI 增量，按请求记录耗时。
- [x] 运行针对性与既有分析/能力回归。

### Task 3: 整体交付

- [x] 独立只读审查；修复 Important / Critical 并验证。
- [x] 串行运行完整 Python / 安装器套件及用户所选 Python/Tk。
- [x] 重建安装器、提取并核对内嵌 ZIP / 源码 / 原生哈希。
- [x] 更新 BUILD_INFO、验收和日志；说明需重启前端。
