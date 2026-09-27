# VOT 统一分析交接

更新日期：2026-09-28
源码目录：`D:\Praat-work\praat-simplified-chinese`
分支：`modern`
原生入口修复提交：`8a37d076a`（与本交接更新一起推送到 `public/modern`）
推送远端：`public`（`https://github.com/f246813/praat-simplified-chinese-ai.git`）

## 当前实现

VOT 编辑器和 AI `vot` 工具已接入同一规范请求、后台模型对齐服务、C++ 声学检测入口和结果结构。目标搜索范围、声学上下文和固定对齐上下文使用原音频采样点；编辑器保留“点击应用后更新”。模型辅助路径拒绝按比例生成的近似对齐区间，并检查模型声明的语言支持。

本次新增准确性评估工具：

- `ai/praat_ai/vot_accuracy.py`：校验日语人工标注清单、音频哈希和 WAV 元数据；比较两入口的请求、边界、状态、模型／算法来源；分别报告爆破、起声、VOT 误差、漏检、错误配对、歧义决策和标注者分歧。
- `ai/tests/verify_vot_accuracy.py`：调用目标 `Praat.exe` 的 SoundEditor `VOT` 命令和注册的 AI `vot` 工具，按人工裁定数据生成 JSON 报告。失败的入口会作为 `entrypoint_harness_failed` 报告，不会计成准确率通过。
- `ai/tests/fixtures/vot/README.md` 和 `gold_manifest.schema.json`：标注协议与清单结构。真实录音应留在 `ai/tests/fixtures/vot/local/`，不要提交含说话者身份的信息。
- `sys/PraatAiControl.cpp` 的项目目录解析每次都优先读取 `PRAAT_AI_PROJECT_DIR`。Praat 启动期间会多次加载偏好；仅在初始化时设置全局目录会被用户偏好覆盖，导致 SoundEditor 从错误位置启动 VOT worker。

## 本次验证与限制

- 已用 clang 在 Windows 原生构建 `D:\Praat-work\vot-unified-acceptance\Praat-vot-diagnostic.exe`，并通过目标程序的 SoundEditor `VOT` 命令及 AI 注册 `vot` 工具完成端到端检查。
- 同一合成 WAV、目标范围和参数：两入口请求哈希均为 `237f17c46cf79880701a3d7fde3bbbbda14f7b94035ff23ce774f3041bbd3c0b`，结果逐字段一致（状态 `candidate`，爆破样本 `13230`，起声样本 `14641`，VOT `31.9954648526 ms`，算法 `context-pair-v3`，检测频带 `high-band`）。
- 在两个独立新鲜运行中分别重算两入口，结果与请求哈希完全一致；运行器为每轮新建 Praat 进程及任务目录，没有依赖结果缓存。
- 同一合成目标的选区移动 10 ms 后，两入口仍一致且检测边界不变。把爆破点裁到目标选区外时，两入口都返回 `failed`，无边界／VOT 数值，并说明能量增幅未达阈值。
- 日语模型辅助请求缺少音素时，两入口一致返回 `requires_input`。提供日语文本及音素后，本机配置一致返回 `language_mismatch`：MFA 配的是英语，wav2vec2 未声明支持语言；没有把近似对齐位置当成有效证据。
- 以上合成样本只能证明接口一致和重复稳定，不是准确性证据。仍缺真实日语录音、两位标注者的独立边界和裁定结果；合成音频及此前观察的 `+14 ms` 都不能作为金标准。本机也没有经核实可用于日语的 MFA／wav2vec2 配置。
- 已按要求只跑高优先级构建和完整入口检查；低优先级测试留到最后集中运行。

完整测试计划见 `docs/superpowers/plans/2026-09-26-unified-vot-analysis.md`。

## 下一步

1. 获取真实日语录音及至少两位标注者的独立边界和裁定结果，覆盖正、零、负 VOT、多爆破候选、持续有声和歧义样本，运行 `ai/tests/verify_vot_accuracy.py`。误差阈值尚未约定，不要自行写整体通过结论。
2. 配置经确认支持日语的 MFA 或 wav2vec2 模型，再测模型辅助路径的定位、失败原因和双入口一致性。不要用按比例近似区间生成 VOT 边界。
3. 准备好金标与语言模型后，完成准确性验收；随后再集中运行低优先级测试。

## 工作区与迁移

- `public/modern` 包含功能、评估工具和原生入口修复。`origin` 指向上游，只推到 `public`。
- 本机还存在多份未跟踪的 `Praat-*.exe` 快照、`PraatZHcn.lnk` 和 `vot-analysis.tsv`；它们没有加入 Git，也没有删除。
- 本次结束前再次检查时 `G:\` 不存在，因此不能把项目复制到 `G:\praat2 for move`。源码仍在 D 盘，未删除或搬移；不要把此前的部分副本当成完整仓库。
- 另一台电脑可从 `public` 克隆 `modern` 分支并检出本次更新后的 HEAD；不需要再套用旧的 `tracked-changes.patch`。

## 参考实现

- [AutoVOT](https://github.com/mlml/autovot)：其分类器针对正 VOT，不能直接充当负 VOT 检测器。
- [VOT-CP](https://github.com/llcit/vot-cp)：先用对齐结果缩小目标范围，再做声学 VOT 检测。
- [JUCE Windows 消息队列](https://github.com/juce-framework/JUCE/blob/master/modules/juce_events/native/juce_Messaging_windows.cpp) 与 [进度对话框示例](https://github.com/juce-framework/JUCE/blob/master/examples/GUI/DialogsDemo.h)：后台任务结束后回到界面线程的参考实现。
