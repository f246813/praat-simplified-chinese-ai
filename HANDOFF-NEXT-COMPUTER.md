# VOT 统一分析开发交接

交接日期：2026-09-26
源码目录：`D:\Praat-work\praat-simplified-chinese`
快速恢复包：`G:\praat2 for move\working-tree-handoff`
完整原始源码仍在 D: 盘；G: 盘中同名全量复制目录只是被中止的部分副本，不要当作完整仓库使用。

## 当前状态

SoundEditor 的 VOT 窗口和 AI `vot` 工具已经接入同一份规范请求、异步模型对齐服务、C++ 声学检测入口和结果结构。音频快照以 PCM 内容哈希和对象版本识别；目标搜索范围、声学上下文和固定对齐上下文均使用原音频采样点索引。编辑器只在用户点击应用后更新对象。

模型辅助 VOT 不再接收比例分配的近似区间。MFA 和 wav2vec2 现在需要声明支持的语言；MFA 会识别常见预训练模型名称中的语言。语言不匹配或语言未配置时返回失败原因且不产生 VOT 数值。最新定向回归和真实 AI 工具入口均覆盖了这项拦截。

## 已有验收证据

最终汇总在验收目录的 `acceptance-report-final.json`。关键结论：

- 相同合成音频和规范输入下，AI 工具与真实目标 `Praat.exe` 的编辑器入口在纯声学模式得到同一请求哈希、音频版本、边界、VOT 和状态。
- AI 入口进行了 5 次独立新计算、共 15 次 Praat 脚本调用，结果一致；编辑器另做了独立重复计算，结果一致。将选区移动 5 ms 后边界漂移为 0 ms。选区裁掉目标时两边均失败且没有 VOT 数值。
- 正、零、负三种人工边界的采样点、请求哈希、状态和 VOT 在两个入口逐项一致。人工模式采用 `(onset_sample - burst_sample) * 1000 / sample_rate`。
- MFA 语言保护通过真实 AI `vot` 工具入口验证：本机英文 MFA 配置面对日语请求时返回 `language_mismatch`；wav2vec2 因语言支持未配置而不运行；最终结果没有数值。
- 准确性仍未验证。当前回归音频是合成音频；没有可用的日语真实录音人工标注和裁定边界。先前观察到的 `+14 ms` 不能作为正确答案。

快速恢复包的 `acceptance-evidence` 保留了目标可执行文件、入口结果、编辑器案例、AI 完整结果、手工边界结果、模型诊断和合并报告。详细文件列表见汇总 JSON 的 `source_artifacts`。

## 模型环境限制

本机 `ai/ai_config.json` 指向 English US ARPA MFA 词典/模型，但请求样本语言是日语。新保护会正确拒绝这个组合。当前 wav2vec2 配置没有声明支持语言；先前离线探测还发现缓存的模型目录缺少 `pytorch_model.bin` 和 `model.safetensors`。因此当前机器没有能接受的日语 MFA/wav2vec2 对齐模型，不要把旧探测产生的 MFA 音素区间或置信度 `0.85` 当作可信边界。

配置示例在 `ai/ai_config.example.json`，说明在 `ai/README.zh-CN.md`：MFA 填 `alignment.mfa.language`（例如 `ja`）；wav2vec2 填 `alignment.wav2vec2.languages`（例如 `["ja"]`，只在模型确实支持多语言时填 `["*"]`）。更换到真实日语模型后，再做模型辅助模式的双入口对齐验收。

## 恢复与继续步骤

1. 阅读 `G:\praat2 for move\working-tree-handoff\HANDOFF-RESTORE.md`。从你现有的 Git 远端克隆/拉取仓库，检出基线提交 `50863f04140fec96f8fe08142d64159eebce27f1`，应用 `tracked-changes.patch`，再按相对路径复制 `untracked-files`。
2. 恢复后查看 `git status --short`；不要丢弃现有修改。交接时分支为 `modern`、HEAD 为上述提交，有大量未提交变更；没有暂存内容，也没有为本次工作创建提交。旧二进制快照和快捷方式没有放入快速包，可从 Git 或原 D: 盘找回。
3. 先读本文件、`docs/superpowers/specs/2026-09-26-unified-vot-analysis-design.md` 和 `docs/superpowers/plans/2026-09-26-unified-vot-analysis.md`。
4. 新电脑需要重新检查编译器、Python、Praat AI 依赖和 MFA/wav2vec2 模型路径。Python 虚拟环境和模型缓存没有包含在快速包中；按项目依赖重新安装即可。
5. 先补齐真实日语模型与人工裁定的真实录音，再通过实际 `Praat.exe` 编辑器和 AI 工具入口比较模型辅助结果。覆盖正、零、负 VOT、多个爆破候选和持续有声片段，并分别报告边界误差、漏检、错误配对和歧义。
6. 高优先级验收完成后，再集中运行计划中剩余的低优先级测试，避免重复跑全套测试。

本次开发已按要求暂停；不要在未恢复任务前继续实现或改动验收范围。D: 盘源目录没有删除或清理。

## 参考实现

- [AutoVOT](https://github.com/mlml/autovot)：其分类器面向正 VOT，不能直接充当负 VOT 检测器。
- [VOT-CP](https://github.com/llcit/vot-cp)：展示了先使用对齐区间缩小目标范围、再做声学 VOT 检测的拆分方式。
- [JUCE Windows 消息队列](https://github.com/juce-framework/JUCE/blob/master/modules/juce_events/native/juce_Messaging_windows.cpp) 和 [进度对话框示例](https://github.com/juce-framework/JUCE/blob/master/examples/GUI/DialogsDemo.h)：用于检查后台工作完成后回到界面线程的模式。
