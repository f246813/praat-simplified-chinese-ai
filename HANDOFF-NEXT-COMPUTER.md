# VOT 统一分析交接

更新日期：2026-09-28
源码目录：`D:\Praat-work\praat-simplified-chinese`
分支：`modern`
此前原生入口修复提交：`8a37d076a`；此前目标入口整合提交：`f6253120d`；本轮采样索引舍入修复：`3736ca6d4`（已推送到 `public/modern`）。
本轮验收器与交接更新代码提交：`220ec5cc2`（已推送到 `public/modern`）。
本轮起声候选回溯修复提交：`babaa4fae`（已推送到 `public/modern`）。
本轮 v5 长预浊音候选配对修复提交：`9c77e6e2b`。
推送远端：`public`（`https://github.com/f246813/praat-simplified-chinese-ai.git`）

## 当前实现

VOT 编辑器和 AI `vot` 工具已接入同一规范请求、后台模型对齐服务、C++ 声学检测入口和结果结构。目标搜索范围、声学上下文和固定对齐上下文使用原音频采样点；编辑器保留“点击应用后更新”。模型辅助路径拒绝按比例生成的近似对齐区间，并检查模型声明的语言支持。

- VOT 专用 MFA 证据保留对齐边界与来源，但不把兼容用的固定 `0.85` 写成可信度。每次 MFA 调用使用独立临时 `MFA_ROOT_DIR`，避免多个入口争用全局语料数据库。
- 编辑器轮询导致状态文件被短暂占用时，后台 worker 对原子替换做有限重试。
- 模型辅助 VOT 只对塞音类目标运行声学边界检测；目标为鼻音等非塞音时返回 `failed / target_phone_not_stop`，不返回边界或数值 VOT。纯声学候选和人工确认模式不受该模型音素类型门控影响。
- 本轮修复了全入口验收器的两处不稳定点：Praat 完成标记脚本不再引用未定义的 `info$`；读取编辑器 `state.json` 时对 Windows 瞬时文件占用进行最多 6 次、20–120 ms 间隔的重试。新增锁重试回归用例；聚焦 `ai.tests.test_vot_accuracy` 5 项通过（本轮文档更新后按用户要求未重跑测试）。

本次新增准确性评估工具：

- `ai/praat_ai/vot_accuracy.py`：校验日语人工标注清单、音频哈希和 WAV 元数据；比较两入口的请求、边界、状态、模型／算法来源；分别报告爆破、起声、VOT 误差、漏检、错误配对、歧义决策和标注者分歧。
- `ai/tests/verify_vot_accuracy.py`：调用目标 `Praat.exe` 的 SoundEditor `VOT` 命令和注册的 AI `vot` 工具，按人工裁定数据生成 JSON 报告。失败的入口会作为 `entrypoint_harness_failed` 报告，不会计成准确率通过。
- `ai/tests/fixtures/vot/README.md` 和 `gold_manifest.schema.json`：标注协议与清单结构。真实录音应留在 `ai/tests/fixtures/vot/local/`，不要提交含说话者身份的信息。
- `sys/PraatAiControl.cpp` 的项目目录解析每次都优先读取 `PRAAT_AI_PROJECT_DIR`。Praat 启动期间会多次加载偏好；仅在初始化时设置全局目录会被用户偏好覆盖，导致 SoundEditor 从错误位置启动 VOT worker。

## 本次验证与限制

- 已用 clang 在 Windows 原生构建 `D:\Praat-work\vot-unified-acceptance\Praat-vot-diagnostic.exe`，并通过目标程序的 SoundEditor `VOT` 命令及 AI 注册 `vot` 工具完成端到端检查。2026-09-28 又从本次修改源码构建 `Praat-vot-context-v4.exe`；构建成功，未覆盖仓库根目录的 `Praat.exe`。
- 2026-09-28 修复了两端把半采样点边界舍入到前一个样点的问题：`220 / 44100` 相对 `0.5 / 44100` 的偏移曾因浮点误差算成 `219.49999999999997`，AI 返回 `[219,... )`。Python 和 C++ 现只在输入浮点精度范围内将半样点偏移归一到 tie-up 边界。新回归用例先失败（219 != 220），修复后相关两个 Python 用例通过；clang 原生构建成功，更新后的目标 exe 已用于完整入口复核。
- 使用更新后的目标 exe，对同一请求 `[220,22000)`、同一合成 WAV 和参数新建两轮完整运行；每轮都直接调用 SoundEditor `VOT` 命令及注册 AI `vot` 工具。两轮各自的双入口比较均 `consistent=true`，跨轮编辑器与 AI 比较也都 `consistent=true`；四份结果均保留精确目标范围 `[220,22000)`，请求哈希 `067f319c3dc6109f3d8d19b1a09b165a35cdec248d260edbf60b5cc9f34ab02e`，音频哈希 `b580d98bf65217d2a57648add8bdc2e9e062edee0cfb40391a4cf090946c3451`，状态 `candidate`，边界样点 `[13230,14641]`，VOT `31.99546485260771 ms`。这是两轮独立运算，不是缓存命中。
- 同一合成 WAV、目标范围和参数：两入口请求哈希均为 `237f17c46cf79880701a3d7fde3bbbbda14f7b94035ff23ce774f3041bbd3c0b`，结果逐字段一致（状态 `candidate`，爆破样本 `13230`，起声样本 `14641`，VOT `31.9954648526 ms`，算法 `context-pair-v3`，检测频带 `high-band`）。
- 在两个独立新鲜运行中分别重算两入口，结果与请求哈希完全一致；运行器为每轮新建 Praat 进程及任务目录，没有依赖结果缓存。
- 同一合成目标的选区移动 10 ms 后，两入口仍一致且检测边界不变。把爆破点裁到目标选区外时，两入口都返回 `failed`，无边界／VOT 数值，并说明能量增幅未达阈值。
- 日语 MFA 已在本机 MFA 3.4.2 环境安装并直接运行 Japanese MFA v3 模型与词典；模型文件位于用户 MFA 缓存，不在 Git 中。用同一完整日语音频快照、`日本`、`n i h o ɴ` 和目标 `/n/` 顺序运行目标 `Praat-vot-diagnostic.exe` 的编辑器 `VOT` 命令与 AI 注册工具：两边请求哈希均为 `e2045b58123438216816626ca60e77b6df3fab8ec168bb76d822f0b3e8675497`，音频哈希均为 `b96725d1b7e031305ddb912db38b3f512dac9f972c60ee2acf05b96e0f905f20`；MFA 目标区间均为样点 `[3528,4851)`，状态均为 `failed`，原因均为 `target_phone_not_stop`，爆破／起声／VOT 均为空。MFA 证据的模型与音素置信度均为 `null`。
- 加门控前，AI 入口用新 Praat 进程、新任务目录、不依赖结果缓存复算一次，重复得到同一 `/n/` 对齐和约 `+0.499 ms` 候选；这暴露出“重复稳定但目标类别错误”的风险。加门控后，两个完整入口各自重算 MFA 并都返回 `target_phone_not_stop`，无边界／VOT；这是失败路径一致性验证，不是塞音检测准确性证据。
- 每次 MFA 运行独立建立临时根目录。Japanese MFA v3 能正常返回完整音素区间；其固定兼容分数没有被当作可信度。
- 2026-09-28 使用真实日语录音补做了 10 次独立 MFA 全入口计算（每次新 Praat 进程／任务目录、无结果缓存）。`Ja-ka.ogg` 来源为 [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Ja-ka.ogg)，SHA-256 `35487385B10640F54445A0363C664663126B17F481B03FFB42D69B99E4F602AD`；模型辅助完整范围 `[0,8704)` 的 SoundEditor 和 AI 结果逐字段一致：`candidate`，爆破 `1132`、起声 `3293`、VOT `49.0022675737 ms`，请求哈希 `89e508ad3993797606d8da93716248e866931006e9b56a1378644557d2407cfd`，音频哈希 `c9fe57e5457d9d2aa19078e90fc412347f17143e98004812b15cbbd5b0657d44`。另将右边缘内移 `220/44100 s = 4.989 ms`，由 AI 注册工具重新运行 MFA 和 C++ 后，边界、VOT、状态完全相同，数值漂移 `0 ms`；左边缘位于文件首样点，不能在不裁切目标的前提下内移。
- 2026-09-28 为检查左边缘，给相同 `Ja-ka` 录音前后补静音，使用目标 `Praat-vot-diagnostic.exe` 的 AI 注册 `vot` 全入口对同一快照独立运行两次 MFA 和 C++：目标范围从 `[0,28549)` 改为 `[220,28549)`（左边缘内移 `220/44100 s = 4.989 ms`），两个请求哈希不同（范围变化），音频哈希相同 `6e3821fbe89dd41b6f2ac1183bd9ea34fe06dfa442db7113c95967d48f545e0c`，MFA `/k/` 均为 `[12348,14112)`，状态均为 `candidate`，爆破样点 `12554`、起声样点 `14318`、VOT 均为 `40.0 ms`，漂移 `0 ms`。检测来源均为 `high-band`、算法 `context-pair-v3`。这只证明该金标准未知录音的左边缘选区稳定，不把 `40 ms` 作为准确性答案。
- 2026-09-28 随后在**同一补静音 WAV 快照**上完成模型辅助左、右边缘稳定性和双入口一致性复核。音频 SHA-256 始终为 `6e3821fbe89dd41b6f2ac1183bd9ea34fe06dfa442db7113c95967d48f545e0c`，采样率 44.1 kHz，MFA 使用 Japanese MFA v3；目标 `/k/` 始终为 `[12348,14112)`。基线范围 `[0,28549)` 请求哈希 `f391124779b35ba9ce44e295c597deace745655c44faa212745bd625ad07ff01`；左边缘移入 220 样点、范围 `[220,28549)` 的哈希 `9e26e662979b5afd229635632b91896e2e07222249b3f342d75ad4fad194d886`；右边缘移入 220 样点、范围 `[0,28329)` 的哈希 `b0a77f7c07566367af88d7fe87331c62fbb428b3b12568a78ad6a23d491f8724`。三种请求均直接运行目标 `Praat-vot-diagnostic.exe` 的 SoundEditor `VOT` 命令和注册 AI `vot` 工具；每种请求两入口均为 `candidate`，结果逐字段一致：爆破样点 `12554`、起声样点 `14318`、VOT `40.0 ms`、检测频带 `high-band`、算法 `context-pair-v3`。左右边缘变化相对基线的边界漂移均为 0 样点／0 ms。每个入口独立执行模型和声学计算，不依赖缓存。录音仍无人工 VOT 金标，此证据只用于一致性、重复性和稳定性验收。
- 同日用 [Ja-WaniKaniTofuguMale-raku.ogg](https://commons.wikimedia.org/wiki/File:Ja-WaniKaniTofuguMale-raku.ogg) 做词内目标稳定性检查。音频上下文始终是完整的 `らく`，MFA 把目标 `/k/` 定位到样点 `[23814,29106)`。全音频选区的编辑器和 AI 独立结果一致；再以目标选区 `[23153,29767)` 重算，两入口仍逐字段一致，均为 `ambiguous`、无边界和数值 VOT，请求哈希 `4d77ddaee8927ae5dbc9db327a1a143dd461fb169927b618dacbd12b19d8c8be`。将选区两边各向内移动 220 样点后，AI 入口重新计算仍定位到同一 `/k/`、状态和失败原因完全不变（请求哈希 `d58016c398d761d9984dcbc9908a4599f8e2748483dd82869a0d82589b9c9561`）。此例证明歧义状态稳定，不提供数值边界漂移证据。
- 把该 `/k/` 目标选区改为 `[24100,29547)`，明确裁掉 MFA 音素起点 `23814` 后，AI 完整入口返回 `target_incomplete`（“target selection clips the aligned phone”），目标音素、爆破、起声和 VOT 均为空。音频哈希仍为 `ec59866699d0ff0943067b6c71656982f6415fa7c54d63438a38508d3288da7d`。
- 随后通过同一目标 `Praat-vot-diagnostic.exe` 的 SoundEditor `VOT` 窗口，对完全相同的裁切请求再次独立运行 MFA；AI 与编辑器请求哈希均为 `6ae7a23f9852803953139cf07daedc43d6e0fda5fd5e44470725035c445943cf`，音频哈希一致，状态均为 `target_incomplete`，失败原因相同，目标音素、爆破、起声和 VOT 均为空。AI 返回摘要与编辑器 job state 的这些规范字段一致。
- 上述两段真实日语发音录音仅用于全入口一致性、稳定性和失败路径回归，均没有独立人工 VOT 金标；`Ja-ka` 为公有领域，`らく` 文件为 CC BY-SA 4.0。原始音频和加静音后 WAV 留在本机 `%TEMP%\vot-ja-ka-model-assisted` 与 `%TEMP%\vot-ja-raku-model-assisted`，没有提交到仓库。跨电脑重跑时需按链接重新获取并核对音频哈希。
- 2026-09-28 用同一目标可执行文件补跑了人工确认全入口：SoundEditor `VOT` 命令与 AI 注册 `vot` 工具对正／零／负三例均返回 `manual_confirmed`，边界样点分别为 `[13230,14641]`、`[13230,13230]`、`[13230,12800]`，VOT 分别为 `31.9954648526`、`0`、`-9.7505668934 ms`；请求哈希、边界、状态和数值逐项一致。样本是合成回归，不作准确性金标。
- 同日用目标 `Praat-vot-diagnostic.exe` 重新跑声学模式：两个独立完整运行的请求哈希和结果一致；选区起点向内移动 220/44100 秒（4.989 ms）或终点向内移动同样距离，边界和 VOT 均不变；裁掉爆破点后两个入口一致返回 `failed` 且没有数值。每轮均新建 Praat 进程和请求目录。
- 推送前聚焦检查：`test_vot_jobs.py` 7/7 通过；`verify_segment_analysis_templates.py` 输出 `SEGMENT_ANALYSIS_NATIVE_PASS: VOT contract and AI local-tool bridge`。启动链为原生提交短时调用 `launch_vot_worker.py`，该脚本通过 Windows detached process flag 创建 worker 后立即返回；此前关于窗口同步等待模型阶段的判断已更正。
- 聚焦验证：`tests.test_forced_alignment`、`tests.test_vot_editor_worker`、`tests.test_vot_service` 共 32 项通过；另通过目标程序两个完整 VOT 入口和未缓存 AI 独立复算。没有运行低优先级全套测试。
- 准确性仍未验收：缺少带两位标注者独立标注和裁定结果的真实日语塞音录音，无法计算真实边界误差；鼻音 `/n/` 回归录音不是 VOT 金标。合成样本及此前观察的 `+14 ms` 均不是金标。
- 2026-09-28 检索可用日语人工 VOT 资料：[ISCA 的 Tohoku 日语研究](https://www.isca-archive.org/interspeech_2022/noguchi22_interspeech.html)报告了正／负区间 VOT，Julius 对齐后由一位受训语音学家修订、另一位语音学家确认；但 ISCA 页面只提供论文及 PDF，没有可下载的对应音频、逐样本边界和独立标注记录。[NINJAL 官方说明](https://clrd.ninjal.ac.jp/csj/en/)显示 CSJ 有免费在线版和付费离线版；[CSJ-RDB 说明](https://clrd.ninjal.ac.jp/csj/en/rdb-index.html)明确 RDB 不单独发行，只给 CSJ 持有者；[官方样例页](https://clrd.ninjal.ac.jp/csj/sample.html)提供压缩 MP3 示例及仅供购入者研究使用的两讲座 RDB 样例说明，不含可核验的逐条 VOT 金标及独立标注数据。wav2VOT 使用的 CSJ-C 停音边界／爆破标签见[论文](https://arxiv.org/abs/2606.28857)，但该数据本身无法由公开页面下载。本轮未下载或纳入这些材料；Task 8 仍需有合法使用权且能核对标注过程的真实音频及边界。
- 2026-09-28 针对日语 `ta` 起声偏晚修复了 C++ 候选算法：动态路径确认有声后，只在 20 ms 前置窗内回查连续的备选 F0 候选，要求频率与稳定路径相差不超过 20%、强度不低于音高阈值的 75%，且至少连续 `stableVoicedFrames` 帧；允许范围受释放点及最大预浊音时长约束。算法版本为 `context-pair-v4`，结果记录这些回查参数，起声来源标记为 `cpp:pitch-candidate-backtrack-and-hnr`。
- 用 v4 目标程序直接运行真实 SoundEditor VOT 命令和已注册 AI `vot` 工具：二者请求哈希均为 `569120dd9c29385429e4edc8e6f1cf1b13b1fdb429cca38a4eb05eb41993a45c`，音频哈希均为 `1fc1f82035e68cd12f14565b9d9cb805d3eae2ae0cfa4d1f2b16e3379b9b490a`，目标 MFA `/t/` 样点区间均为 `[6615,10584)`，状态均为 `candidate`，爆破与起声样点均为 `[8238,10178]`，VOT 均为 `43.9909297052 ms`。该教育网页为首个 `ta` 给出的手工标注约 `43.283 ms`（爆破约 `0.186712 s`、起声约 `0.229996 s`）；本次边界绝对误差约为爆破 `0.09 ms`、起声 `0.79 ms`。原始录音 SHA-256 为 `559a3560c6d6fcafb2b4d7dbff0180ab1073b44bbe2336c7c39f2bbdf1534e72`，网页保留所有权利，音频只在本机临时目录使用，未提交。该来源只给出一份手工标注，未提供双人独立标注及裁定，因此这是定位 bug 的临时单例回归结果，不构成准确性验收。结果文件在 `D:\Praat-work\vot-unified-acceptance\education-gold\run-ja-ta-v4\entrypoint-result.json`。
- v4 目前完成了一次两个实际入口的同请求一致性复核；没有为 v4 重跑多轮重复性／选区稳定性，也没有可核验的真实日语正／零／负、多爆破及持续有声双人裁定金标。先前 v3 的稳定性数据不能替代 v4 验收。仅按用户要求跳过了低优先级测试套件；原生构建及本条全入口检查已完成。
- Task 7 一致性、稳定性和重复计算验收已完成：声学模式和人工确认模式的真实 `Praat.exe` 双入口测试此前已通过；模型辅助模式现对同一精确音频快照完成基线、左边缘移动、右边缘移动三种请求的 SoundEditor 与 AI 配对计算。模型缺失／目标裁切等失败状态也已确认双入口一致。所有比较都用完整请求与结果字段，并通过新进程和任务目录重新计算，不依赖缓存。
- 2026-09-28 继续真实负 VOT 排查后，发现 v4 会把 Utsugi 教学录音 `ta-da.wav` 中的人声起点压成 `0 ms`：高频释放样点 `44400`，而人工网页参考为爆破 `44351`、起声 `40076`、约 `-96.94 ms`。实际 Pitch 的备选轨迹从 `0.90681 s` 持续到释放前，旧逻辑只看主候选、只回溯 20 ms，并将允许负 VOT 限为 80 ms，因而错过预浊音。
- v5 (`context-pair-v5`) 在原始时间轴上从释放前一帧沿全部 Pitch 候选追踪连续 F0：候选强度至少为音高阈值的 50%，相邻帧频率差不超过 20%，至少连续 `stableVoicedFrames` 帧，最大预浊音窗 120 ms。只有释放后稳定有声起点距释放不超过 10 ms 时，才用这条轨迹与释放配成负 VOT；否则保留正起声路径。轨迹触及目标／搜索边界时按歧义返回，不输出数值。新增原生 `-100 ms` 回归；该回归先在 v4 构建上因起声候选缺失而失败，v5 通过。回溯参数和 `maximumPrevoicingAssociationGapSeconds` 均进入结果参数；AI 桥接起声来源现在标为 `cpp:context-pitch-candidates-and-hnr`。
- v5 用目标 `Praat.exe` 对同一个完整 MFA 请求重新直接运行 SoundEditor `VOT` 命令和注册 AI `vot` 工具，均独立运行 Japanese MFA、未使用缓存。请求哈希为 `569120dd9c29385429e4edc8e6f1cf1b13b1fdb429cca38a4eb05eb41993a45c`，音频 SHA-256 为 `1fc1f82035e68cd12f14565b9d9cb805d3eae2ae0cfa4d1f2b16e3379b9b490a`，MFA `/t/` 为 `[6615,10584)`，模型 id 为 `mfa`、版本来源为本机 Japanese MFA 模型压缩包。两个入口完整规范字段一致：`candidate`，爆破／起声 `[8238,10178]`，VOT `+43.9909297052 ms`。两边 `alignment_evidence` 的模型、区间和空置信度也一致。网页单标记参考约 `+43.283 ms`；与其对比仍是单标记调试证据，不构成裁定金标准。报告：`D:\Praat-work\vot-unified-acceptance\education-gold\run-ja-ta-v5-fixed\entrypoint-result.json`。
- v5 对日语负例使用声学候选模式，直接运行两入口并在不同新任务目录重复两次；另把目标选区左端内移 220 样点、右端内移 220 样点。四种请求的入口比较均 `consistent=true`；同一输入新鲜重算的请求／音频哈希、边界、状态和 VOT 完全相同；所有情况均为 `[burst=44400,onset=39990]`、`candidate`、`-100.0 ms`，选区移动边界漂移为 0 样点。请求范围为 `[39690,45644)`，左右变体仍覆盖同一完整声学目标。网页人工参考 `-96.9388 ms`，边界误差分别约为爆破 49 样点（1.11 ms）、起声 86 样点（1.95 ms）、VOT 3.06 ms；来源只有一份手工标记，不能当作双人裁定准确率。报告：`D:\Praat-work\vot-unified-acceptance\education-gold\run-ja-da-v5-fixed-stability\stability-report.json`。
- 同一正例在加入负 VOT 轨迹后曾错误输出 `-16.01 ms`；两真实入口均复现。增加 10 ms 的“释放后稳定起声与释放关联窗”后，正例回到两个入口完全相同的 `+43.9909 ms`，负例继续稳定输出 `-100.0 ms`。聚焦验证：新鲜 clang 原生构建成功，`verify_segment_analysis_templates.py` 输出 `SEGMENT_ANALYSIS_NATIVE_PASS: VOT contract and AI local-tool bridge`；`ai/tests/test_vot_bridge.py` 6/6 通过；`git diff --check` 通过。没有运行低优先级全套。
- Task 8 仍未验收。现有真实录音网页参考不是两位标注者独立标记后的裁定金标，而且没有正／零／负、多爆破、持续有声、歧义全覆盖；合成样本、模型输出和这个网页的单标注都不能替代它。准确度阈值也尚未约定。

完整测试计划见 `docs/superpowers/plans/2026-09-26-unified-vot-analysis.md`。

## 下一步

1. 获取真实日语录音及至少两位标注者的独立边界和裁定结果，覆盖正、零、负 VOT、多爆破候选、持续有声和歧义样本，运行 `ai/tests/verify_vot_accuracy.py`。误差阈值尚未约定，不要自行写整体通过结论。
2. 在继续开发的电脑上配置 Japanese MFA v3（或经确认支持日语的 wav2vec2）及相应词典。不要把比例近似区间或固定 MFA 置信度作为有效边界证据。
3. 对 `context-pair-v5` 补做模型辅助塞音目标的多轮新鲜重复和选区稳定验收，尤其覆盖移动选区后仍指向同一完整音素的情况。随后准备双人独立标注及裁定后的真实日语塞音录音，覆盖正／零／负 VOT、多爆破、持续有声与歧义样本，预先约定误差阈值后运行准确性评估。

## 工作区与迁移

- `public/modern` 包含功能、评估工具和原生入口修复。`origin` 指向上游，只推到 `public`。
- 本机还存在多份未跟踪的 `Praat-*.exe` 快照、`PraatZHcn.lnk` 和 `vot-analysis.tsv`；它们没有加入 Git，也没有删除。
- `D:\Praat-work\Praat-root-before-vot-rounding-20260928.exe` 是本轮构建前临时保存并随后恢复根目录 `Praat.exe` 时留下的原版副本，没有加入 Git；正式新构建仅复制到上文的 VOT 验收目录。
- 暂停期间源码保留在 D 盘；另一台电脑可从 `public` 克隆 `modern` 分支，不需要再套用旧的 `tracked-changes.patch`。

## 当前状态

统一分析服务及两入口接入已实现。v5 原生回归和 VOT 桥接聚焦检查通过；v5 的 MFA 正例已用两个真实入口新鲜复算并一致，声学负例已完成双入口独立重复和左右边界稳定性复核。v5 模型辅助路径的多轮重复和模型选区移动仍待复验。Task 8 准确性仍未验收：当前只有网页单人参考，没有双人独立标注与裁定，也未覆盖所需样本类别。跨电脑继续时优先按“下一步”完成 v5 模型辅助稳定性，再补齐合法可用的真实日语金标及预先约定的误差阈值；不要把模型自身结果、合成样本或单人参考当成裁定答案。

## 参考实现

- [AutoVOT](https://github.com/mlml/autovot)：其分类器针对正 VOT，不能直接充当负 VOT 检测器。
- [VOT-CP](https://github.com/llcit/vot-cp)：先用对齐结果缩小目标范围，再做声学 VOT 检测。
- [JUCE Windows 消息队列](https://github.com/juce-framework/JUCE/blob/master/modules/juce_events/native/juce_Messaging_windows.cpp) 与 [进度对话框示例](https://github.com/juce-framework/JUCE/blob/master/examples/GUI/DialogsDemo.h)：后台任务结束后回到界面线程的参考实现。
