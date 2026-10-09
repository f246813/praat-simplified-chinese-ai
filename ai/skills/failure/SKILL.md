---
name: failure
description: 真实失败原因与收尾
version: 1
phases: [planner, report]
source: AIPraat analysis guidance
---
blocked_attempts/paused_branches/missing_reason 是实际执行失败的原因（没有运行中的 Praat、消息文件写不进去、脚本报错、超时…）：报告要如实交代失败原因和用户能照做的下一步，不能把投递或环境故障写成模型能力不足，也不能把没跑成的测量说成测量结果。audio_input=false 只表示本轮没把音频交给模型：Praat 测量不依赖它，不能据此说无法测量。
