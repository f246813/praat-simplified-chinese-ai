# VOT 统一分析交接

更新日期：2026-09-28
源码目录：`D:\Praat-work\praat-simplified-chinese`
分支：`modern`
此前原生入口修复提交：`8a37d076a`；本轮代码修复：`f6253120d`（随后推送到 `public/modern`）。
推送远端：`public`（`https://github.com/f246813/praat-simplified-chinese-ai.git`）

## 当前实现

VOT 编辑器和 AI `vot` 工具已接入同一规范请求、后台模型对齐服务、C++ 声学检测入口和结果结构。目标搜索范围、声学上下文和固定对齐上下文使用原音频采样点；编辑器保留“点击应用后更新”。模型辅助路径拒绝按比例生成的近似对齐区间，并检查模型声明的语言支持。

- VOT 专用 MFA 证据保留对齐边界与来源，但不把兼容用的固定 `0.85` 写成可信度。每次 MFA 调用使用独立临时 `MFA_ROOT_DIR`，避免多个入口争用全局语料数据库。
- 编辑器轮询导致状态文件被短暂占用时，后台 worker 对原子替换做有限重试。
- 模型辅助 VOT 只对塞音类目标运行声学边界检测；目标为鼻音等非塞音时返回 `failed / target_phone_not_stop`，不返回边界或数值 VOT。纯声学候选和人工确认模式不受该模型音素类型门控影响。

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
- 日语 MFA 已在本机 MFA 3.4.2 环境安装并直接运行 Japanese MFA v3 模型与词典；模型文件位于用户 MFA 缓存，不在 Git 中。用同一完整日语音频快照、`日本`、`n i h o ɴ` 和目标 `/n/` 顺序运行目标 `Praat-vot-diagnostic.exe` 的编辑器 `VOT` 命令与 AI 注册工具：两边请求哈希均为 `e2045b58123438216816626ca60e77b6df3fab8ec168bb76d822f0b3e8675497`，音频哈希均为 `b96725d1b7e031305ddb912db38b3f512dac9f972c60ee2acf05b96e0f905f20`；MFA 目标区间均为样点 `[3528,4851)`，状态均为 `failed`，原因均为 `target_phone_not_stop`，爆破／起声／VOT 均为空。MFA 证据的模型与音素置信度均为 `null`。
- 加门控前，AI 入口用新 Praat 进程、新任务目录、不依赖结果缓存复算一次，重复得到同一 `/n/` 对齐和约 `+0.499 ms` 候选；这暴露出“重复稳定但目标类别错误”的风险。加门控后，两个完整入口各自重算 MFA 并都返回 `target_phone_not_stop`，无边界／VOT；这是失败路径一致性验证，不是塞音检测准确性证据。
- 每次 MFA 运行独立建立临时根目录。Japanese MFA v3 能正常返回完整音素区间；其固定兼容分数没有被当作可信度。
- 2026-09-28 使用真实日语录音补做了 10 次独立 MFA 全入口计算（每次新 Praat 进程／任务目录、无结果缓存）。`Ja-ka.ogg` 来源为 [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Ja-ka.ogg)，SHA-256 `35487385B10640F54445A0363C664663126B17F481B03FFB42D69B99E4F602AD`；模型辅助完整范围 `[0,8704)` 的 SoundEditor 和 AI 结果逐字段一致：`candidate`，爆破 `1132`、起声 `3293`、VOT `49.0022675737 ms`，请求哈希 `89e508ad3993797606d8da93716248e866931006e9b56a1378644557d2407cfd`，音频哈希 `c9fe57e5457d9d2aa19078e90fc412347f17143e98004812b15cbbd5b0657d44`。另将右边缘内移 `220/44100 s = 4.989 ms`，由 AI 注册工具重新运行 MFA 和 C++ 后，边界、VOT、状态完全相同，数值漂移 `0 ms`；左边缘位于文件首样点，不能在不裁切目标的前提下内移。
- 同日用 [Ja-WaniKaniTofuguMale-raku.ogg](https://commons.wikimedia.org/wiki/File:Ja-WaniKaniTofuguMale-raku.ogg) 做词内目标稳定性检查。音频上下文始终是完整的 `らく`，MFA 把目标 `/k/` 定位到样点 `[23814,29106)`。全音频选区的编辑器和 AI 独立结果一致；再以目标选区 `[23153,29767)` 重算，两入口仍逐字段一致，均为 `ambiguous`、无边界和数值 VOT，请求哈希 `4d77ddaee8927ae5dbc9db327a1a143dd461fb169927b618dacbd12b19d8c8be`。将选区两边各向内移动 220 样点后，AI 入口重新计算仍定位到同一 `/k/`、状态和失败原因完全不变（请求哈希 `d58016c398d761d9984dcbc9908a4599f8e2748483dd82869a0d82589b9c9561`）。此例证明歧义状态稳定，不提供数值边界漂移证据。
- 把该 `/k/` 目标选区改为 `[24100,29547)`，明确裁掉 MFA 音素起点 `23814` 后，AI 完整入口返回 `target_incomplete`（“target selection clips the aligned phone”），目标音素、爆破、起声和 VOT 均为空。音频哈希仍为 `ec59866699d0ff0943067b6c71656982f6415fa7c54d63438a38508d3288da7d`。
- 随后通过同一目标 `Praat-vot-diagnostic.exe` 的 SoundEditor `VOT` 窗口，对完全相同的裁切请求再次独立运行 MFA；AI 与编辑器请求哈希均为 `6ae7a23f9852803953139cf07daedc43d6e0fda5fd5e44470725035c445943cf`，音频哈希一致，状态均为 `target_incomplete`，失败原因相同，目标音素、爆破、起声和 VOT 均为空。AI 返回摘要与编辑器 job state 的这些规范字段一致。
- 上述两段真实日语发音录音仅用于全入口一致性、稳定性和失败路径回归，均没有独立人工 VOT 金标；`Ja-ka` 为公有领域，`らく` 文件为 CC BY-SA 4.0。原始音频和加静音后 WAV 留在本机 `%TEMP%\vot-ja-ka-model-assisted` 与 `%TEMP%\vot-ja-raku-model-assisted`，没有提交到仓库。跨电脑重跑时需按链接重新获取并核对音频哈希。
- 2026-09-28 用同一目标可执行文件补跑了人工确认全入口：SoundEditor `VOT` 命令与 AI 注册 `vot` 工具对正／零／负三例均返回 `manual_confirmed`，边界样点分别为 `[13230,14641]`、`[13230,13230]`、`[13230,12800]`，VOT 分别为 `31.9954648526`、`0`、`-9.7505668934 ms`；请求哈希、边界、状态和数值逐项一致。样本是合成回归，不作准确性金标。
- 同日用目标 `Praat-vot-diagnostic.exe` 重新跑声学模式：两个独立完整运行的请求哈希和结果一致；选区起点向内移动 220/44100 秒（4.989 ms）或终点向内移动同样距离，边界和 VOT 均不变；裁掉爆破点后两个入口一致返回 `failed` 且没有数值。每轮均新建 Praat 进程和请求目录。
- 推送前聚焦检查：`test_vot_jobs.py` 7/7 通过；`verify_segment_analysis_templates.py` 输出 `SEGMENT_ANALYSIS_NATIVE_PASS: VOT contract and AI local-tool bridge`。启动链为原生提交短时调用 `launch_vot_worker.py`，该脚本通过 Windows detached process flag 创建 worker 后立即返回；此前关于窗口同步等待模型阶段的判断已更正。
- 聚焦验证：`tests.test_forced_alignment`、`tests.test_vot_editor_worker`、`tests.test_vot_service` 共 32 项通过；另通过目标程序两个完整 VOT 入口和未缓存 AI 独立复算。没有运行低优先级全套测试。
- 准确性仍未验收：缺少带两位标注者独立标注和裁定结果的真实日语塞音录音，无法计算真实边界误差；鼻音 `/n/` 回归录音不是 VOT 金标。合成样本及此前观察的 `+14 ms` 均不是金标。
- 稳定性部分验收：模型辅助下 `Ja-ka` 的右选区边缘内移 4.989 ms 后数值边界漂移为 0 ms；`らく` 的两边缘各移动 4.989 ms 后仍为同一目标和同一 `ambiguous` 状态；裁切完整目标得到 `target_incomplete`。完整同请求双入口的独立 MFA 运算有一致结果，且累计超过 5 次；但词内多释放例没有数值边界可测，`Ja-ka` 左边缘受文件边界限制，因此“有效且唯一的模型辅助候选在两边缘移动下均保持数值误差阈值”的验收仍未完成。

完整测试计划见 `docs/superpowers/plans/2026-09-26-unified-vot-analysis.md`。

## 下一步

1. 获取真实日语录音及至少两位标注者的独立边界和裁定结果，覆盖正、零、负 VOT、多爆破候选、持续有声和歧义样本，运行 `ai/tests/verify_vot_accuracy.py`。误差阈值尚未约定，不要自行写整体通过结论。
2. 在继续开发的电脑上配置 Japanese MFA v3（或经确认支持日语的 wav2vec2）及相应词典。不要把比例近似区间或固定 MFA 置信度作为有效边界证据。
3. 准备好双人独立标注及裁定后的真实日语塞音录音后，覆盖正／零／负 VOT、多爆破、持续有声与歧义样本，运行准确性评估并预先约定误差阈值；再完成模型辅助塞音目标的多轮新鲜重复和选区稳定验收。

## 工作区与迁移

- `public/modern` 包含功能、评估工具和原生入口修复。`origin` 指向上游，只推到 `public`。
- 本机还存在多份未跟踪的 `Praat-*.exe` 快照、`PraatZHcn.lnk` 和 `vot-analysis.tsv`；它们没有加入 Git，也没有删除。
- 暂停期间源码保留在 D 盘；另一台电脑可从 `public` 克隆 `modern` 分支，不需要再套用旧的 `tracked-changes.patch`。

## 当前状态

用户之后已恢复本会话未完成的开发目标。统一分析服务及两入口接入已实现；当前 Task 7 仍部分验收，Task 8 准确性验收未验证。本轮补充的日语完整入口一致性、模型辅助选区稳定性与目标裁切失败证据如上。接下来需要补齐可移动两边缘且能给出唯一数值边界的模型辅助样本，并取得覆盖日语正／零／负 VOT、多释放候选及持续有声片段的双人独立标注与裁定数据；在完成前不要宣称准确性通过。

## 参考实现

- [AutoVOT](https://github.com/mlml/autovot)：其分类器针对正 VOT，不能直接充当负 VOT 检测器。
- [VOT-CP](https://github.com/llcit/vot-cp)：先用对齐结果缩小目标范围，再做声学 VOT 检测。
- [JUCE Windows 消息队列](https://github.com/juce-framework/JUCE/blob/master/modules/juce_events/native/juce_Messaging_windows.cpp) 与 [进度对话框示例](https://github.com/juce-framework/JUCE/blob/master/examples/GUI/DialogsDemo.h)：后台任务结束后回到界面线程的参考实现。
