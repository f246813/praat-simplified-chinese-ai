# VOT 统一分析交接

更新日期：2026-09-28
源码目录：`D:\Praat-work\praat-simplified-chinese`
分支：`modern`
已推送提交：`043024c62`（前序功能提交 `50ecb2038`，评估工具提交 `ba57ca225`）
推送远端：`public`（`https://github.com/f246813/praat-simplified-chinese-ai.git`）

## 当前实现

VOT 编辑器和 AI `vot` 工具已接入同一规范请求、后台模型对齐服务、C++ 声学检测入口和结果结构。目标搜索范围、声学上下文和固定对齐上下文使用原音频采样点；编辑器保留“点击应用后更新”。模型辅助路径拒绝按比例生成的近似对齐区间，并检查模型声明的语言支持。

本次新增准确性评估工具：

- `ai/praat_ai/vot_accuracy.py`：校验日语人工标注清单、音频哈希和 WAV 元数据；比较两入口的请求、边界、状态、模型／算法来源；分别报告爆破、起声、VOT 误差、漏检、错误配对、歧义决策和标注者分歧。
- `ai/tests/verify_vot_accuracy.py`：调用目标 `Praat.exe` 的 SoundEditor `VOT` 命令和注册的 AI `vot` 工具，按人工裁定数据生成 JSON 报告。失败的入口会作为 `entrypoint_harness_failed` 报告，不会计成准确率通过。
- `ai/tests/fixtures/vot/README.md` 和 `gold_manifest.schema.json`：标注协议与清单结构。真实录音应留在 `ai/tests/fixtures/vot/local/`，不要提交含说话者身份的信息。

## 最近验证与限制

- Python 语法检查、4 个准确性评估单测和 JSON Schema 解析通过。
- 使用合成回归音频时，AI 工具入口由两次独立目标 `Praat.exe` 执行得到完全相同的请求哈希、边界、状态及算法来源：`candidate`，爆破样本 `13230`，起声样本 `14641`，VOT `31.9954648526 ms`。这是稳定性冒烟，不是准确性证据。
- 新鲜启动的目标 `Praat.exe` 中，编辑器窗口成功打开；向该进程投递完整 VOT 命令后，消息被消费，脚本返回，但没有创建 VOT 后台作业。当前双入口冒烟因此为 `entrypoint_harness_failed`，不能声称两入口一致。`UiForm` 解析代码确认 `CHOICE` 脚本参数必须使用选项字符串；运行器已改用 `纯声学候选` 标签，并分两次投递、结束 editor 上下文。窗口仍出现 VOT／选择表单，`info$` 没读到错误文字；需查清 SoundEditor 回调为何在提交作业前返回。
- 评估报告框架还没有真实人工标注录音可运行。没有真实日语录音及两位独立标注者的边界，准确性仍未验收；合成音频和此前观察的 `+14 ms` 都不能作为金标准。
- 本机 MFA 配置是英文，不适用于日语样本；wav2vec2 模型缺少可确认的日语支持／模型权重。模型辅助日语验收仍需真实模型与语言配置。

本次只运行了高优先级检查；用户要求低优先级测试集中到最后运行。完整测试计划见 `docs/superpowers/plans/2026-09-26-unified-vot-analysis.md`。

## 下一步

1. 先用可读方式取得 SoundEditor VOT 表单的脚本错误／字段状态，修好真实入口命令后，重新运行一次新鲜进程的编辑器＋AI 双入口冒烟，并重复计算确认不是缓存结果。
2. 准备有哈希、采样率及样本数的真实日语 WAV；至少两位标注者独立标注，再裁定边界。覆盖正、零、负 VOT、多爆破候选、持续有声和歧义样本。
3. 配置经确认支持日语的 MFA 或 wav2vec2 模型；对模型辅助、纯声学、人工确认分别报告结果。边界误差阈值尚未约定，不要自行写整体通过结论。
4. 完成高优先级入口一致性、重复稳定性、选区微移及真实音频准确性后，再集中运行低优先级测试。

## 工作区与迁移

- `public/modern` 已包含上述三个提交。`origin` 指向上游只读地址，本次没有向它推送。
- 本机还存在多份未跟踪的 `Praat-*.exe` 快照、`PraatZHcn.lnk` 和 `vot-analysis.tsv`；它们没有加入 Git，也没有删除。
- 当前检查时 `G:\` 不存在，因此没有把项目复制到 `G:\praat2 for move`。旧文档提到的 `G:\praat2 for move\working-tree-handoff` 也不可访问；不要把此前的部分副本当作完整仓库。
- 源码仍在 D 盘。另一台电脑可从 `public` 克隆 `modern` 分支并检出提交 `043024c62`；不需要再套用旧的 `tracked-changes.patch`。

## 参考实现

- [AutoVOT](https://github.com/mlml/autovot)：其分类器针对正 VOT，不能直接充当负 VOT 检测器。
- [VOT-CP](https://github.com/llcit/vot-cp)：先用对齐结果缩小目标范围，再做声学 VOT 检测。
- [JUCE Windows 消息队列](https://github.com/juce-framework/JUCE/blob/master/modules/juce_events/native/juce_Messaging_windows.cpp) 与 [进度对话框示例](https://github.com/juce-framework/JUCE/blob/master/examples/GUI/DialogsDemo.h)：后台任务结束后回到界面线程的参考实现。
