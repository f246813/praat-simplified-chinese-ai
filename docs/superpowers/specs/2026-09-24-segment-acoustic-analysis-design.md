# 语音段声学分析更新方案

状态：设计基线；已根据后续明确请求编写分模块实施计划，计划待评审。本文是产品与技术基线；开始编写功能代码前，先评审实施计划并选择执行方式。

## 目标

为 Praat 增加可复核、可比较的语音段分析入口，覆盖 VOT、元音鼻化、鼻辅音和 R 音声学特征。界面菜单、Praat 对象动作和 AI 工具必须调用同一套 C++ 测量核心，避免三条路径逐渐得到不同的结果。所有结果保留原始单位、来源、边界、参数和质量状态；不把声学特征冒充为发音器官动作或未经验证的评分。

本文中的“鼻化”分为**元音鼻化**与**鼻辅音特征**两类。“卷舌度”统一改名为**R 音声学分析**。分析类别由用户选择，不从整句自动识别音素，也不根据未验证的普通话阈值自动判定正误。

## 现状与阻塞点

| 现状 | 相关代码 | 为什么功能还没有落地 |
|---|---|---|
| 现有声学指标清单包含通用共振峰和频谱重心，但没有鼻化、鼻辅音或 R 音的类别化流程。 | `ai/measures.tsv`、`ai/praat_ai/tools.py` | 通用 F1/F2/COG 查询没有目标/参照选择、片段边界、参数同一性、质量标记或可复现导出，不能直接作为完整功能。 |
| AI 对话工具能生成 Praat 脚本；声音编辑器另有原生菜单系统。 | `ai/praat_ai/tools.py`；`foned/FunctionEditor.cpp` 的 `createAiMenus()`；`foned/SoundAnalysisArea.cpp` 的 `v_createMenus()` | 目前没有连接两类入口的领域测量 API。若分别加算法，会出现结果定义与修 bug 的分叉。 |
| Sound 编辑器已有按区间提取音频和检查选区的内部辅助函数。 | `foned/SoundAnalysisArea.cpp` 的 `extractSoundOrNull()`、`makeQueriable()` | 这些函数是编辑器内部实现，不是能被对象动作、脚本和 AI 共同调用的测量核心。 |
| 当前 AI VOT 显式路径将两个时刻限制为非负，并拒绝 `voicing <= burst`；调度器又将 `burst=0, voicing=0` 当成“未提供”并转入自动估计。 | `ai/praat_ai/tools.py` 的 `_build_vot_explicit()`、`_build_vot()`；`ai/tests/test_chat_tools.py` 的零值回归用例 | 负 VOT、恰为零的 VOT、显式时间 0 与缺省参数无法可靠区分。自动估计目前还是 AI 脚本链路，与菜单和未来共享核心脱节。 |
| 交接文档把“真机复核 VOT”列为近期工作，但未定义鼻化/R 音的实现或验收。 | `ai/HANDOFF.md` §3、§6 | 合成音的 VOT 复核不能替代真实录音验证；缺少普通话鼻化、塞擦音和 R 音人工边界样本。 |

代码库引用的上游与借用代码来源以 [`CREDITS.zh-CN.md`](https://github.com/f246813/praat-simplified-chinese-ai/blob/modern/CREDITS.zh-CN.md) 为准。它能解释继承来源，不能证明本项目已经具备这里规划的类别化分析功能。

旧的本地 AI 纠音草案 [`docs/ai-frontend/DESIGN.zh-CN.md`](../../ai-frontend/DESIGN.zh-CN.md) 仍描述整句音素对齐、DTW 与阈值评分，但这些是另一条产品路线；文首范围说明已排除它们对本段级工具的约束。交接文档中的 AI 对话 VOT 自动估计属于现存入口，后续应迁移到共用核心并提供人工边界复核，不能据此扩大为自动音素识别。

## 产品边界

### 本次要做

- 建立可被 GUI、Praat 对象动作和 AI 工具复用的 C++ 分析核心。
- 为 VOT 修正显式边界语义，并将已有估计器接入同一结果与质量接口；估计边界始终可见、可编辑。
- 分别实现元音鼻化指标与鼻辅音能量/时长指标。
- 按用户选择的发音类别分析擦音、塞擦音和近音类 R 的声学特征。
- 提供目标音/参照音的双片段选择、试听、对照显示和可复现导出。
- 为未来可能加入的 F0 归一化预留数据扩展位置，但本次不计算或展示 F0 归一化值。

### 明确不做

- 不做整句或整段的自动音素识别，不自动决定鼻音、塞擦音或 R 音的类别。
- 不给“舌头卷了多少”“普通话合格分”或综合百分制分数。
- 不用固定普通话阈值自动判定发音正确/错误。
- 不把跨说话人、跨元音或跨录音条件的差异归一成看似客观的百分比。
- 不依赖在线服务、LLM 或外部模型完成测量。

## 统一数据与调用结构

下面是接口职责，不是要求照抄的最终 C++ 类名。具体类型与文件拆分留给实现计划确认。

```text
SegmentSource
  来源对象身份/显示名、Sound 或 LongSound、绝对起止时间、采样信息

AnalysisRequest
  一侧 SegmentSource、分析类别、测量参数、用户提供的音类/语言/IPA/说话人元数据

ComparisonRequest
  target 与 reference 两份 AnalysisResult；比较操作要求两侧都有有效片段

MetricResult
  指标标识、数值、单位、状态(measured/warning/unavailable)、原因

AnalysisResult
  单侧原始输入与边界、参数快照、各 MetricResult、绘图数据

ComparisonResult
  两侧 AnalysisResult 的兼容性、指标差值或不可比较原因
```

核心职责按 VOT、元音鼻化、鼻辅音、R 音分成可独立测试的分析函数；调用者只负责选择来源和展示结果，不复制 DSP 公式。

建议的 C++ 接口契约如下。这里的结构名是方案名，落地时按 Praat 的 `autoSound`、`Sound`、`LongSound` 和错误处理惯例映射；所有时间使用来源对象的绝对秒值，内部截取后仍携带原始 `tmin/tmax`。

```cpp
struct SourceIdentity {
    optional<integer> objectId;     // 当前 Praat 会话中的对象 ID
    string displayName;
    optional<string> filePath;
    SourceKind kind;                // Sound 或 LongSound
    integer channels;
    double sampleRate;
};

struct UserMetadata {
    optional<string> language, ipa, speakerId, neighboringVowel;
};

struct SegmentMetadata {
    SourceIdentity source;          // 名称/文件名、对象类型、声道、原始采样率
    double startTime, endTime;      // 来源对象时间轴上的绝对秒
    UserMetadata annotation;        // 可选语言、IPA、说话人、相邻元音
};

struct SegmentInput {
    const Sound * samples;          // 借用；LongSound 由适配层先按区间提取成 Sound
    SegmentMetadata metadata;
};

struct SpectralSettings {
    double windowLength, timeStep;  // 秒
    integer fftSize;                // >= 窗内采样点数；实际值写入参数快照
    WindowKind windowKind;
    double minFrequency, maxFrequency;
    bool removeFrameMean;
    double preemphasisFrequency;    // 0 表示关闭
};
struct FormantSettings {
    integer numberOfFormants;
    double maximumFormant, windowLength, timeStep, preemphasis;
};

struct ParameterValue { string name, value, unit; };
struct ParameterSnapshot { vector<ParameterValue> values; };
struct TimeSeries {
    string metricId, unit;
    vector<double> absoluteTimes, values;
};

enum class AnalysisKind { VowelNasality, NasalConsonant, RSegment, VOT };
enum class MetricStatus { measured, warning, unavailable };
struct MetricResult {
    string id, unit;
    optional<double> value;         // unavailable 时必须为空；数值 0 是有效数值
    MetricStatus status;
    string reason;
};

struct MetricComparison {
    string metricId, unit;
    optional<double> targetValue, referenceValue, difference;
    MetricStatus targetStatus, referenceStatus;
    string reason;                  // 空表示可直接比较；否则解释为何无差值
};

struct AnalysisResult {
    int schemaVersion;
    AnalysisKind kind;
    SegmentMetadata source;         // 只保存值，不保留 samples 指针
    ParameterSnapshot parameters;
    vector<MetricResult> metrics;
    vector<TimeSeries> curves;      // 绝对时间；绘图层另生成相对时间坐标
};
struct ComparisonResult {
    SegmentMetadata target, reference;
    vector<MetricComparison> rows;
};

enum class VOTBoundaryMode { manual, estimateCandidates };

AnalysisResult analyseVowelNasality(
    const SegmentInput &, const VowelNasalityParameters &);
AnalysisResult analyseNasalConsonant(
    const SegmentInput &, const NasalConsonantParameters &);
AnalysisResult analyseRSegment(
    const SegmentInput &, RSegmentClass, const RSegmentParameters &);
AnalysisResult analyseVOT(
    const SegmentInput &, optional<double> burstTime,
    optional<double> voicingTime, VOTBoundaryMode);
ComparisonResult compareCompatibleMetrics(
    const AnalysisResult & target, const AnalysisResult & reference);
```

`VowelNasalityParameters` 包含 `SpectralSettings`、P0/P1 搜索带和 Formant 参数；`NasalConsonantParameters` 包含频带边界及窗长、FFT 点数策略、帧移；`RSegmentParameters` 包含所选谱段、频谱窗参数和 Formant 参数。鼻化和鼻辅音的频谱默认关闭预加重，R 擦音允许显式调整；去直流、预加重和滤波设置均需写入参数快照并在两侧一致。不同采样率时窗长/帧移仍按秒一致，实际 FFT 点数至少覆盖该帧样本数并随结果保存，不能靠零填充宣称获得更高真实分辨率。`compareCompatibleMetrics` 只对相同指标定义、单位及匹配参数计算“目标−参照”的原始差值；不生成归一化百分比或综合分。`MetricResult` 的 `optional` 区分缺失与真实 0。`VOTBoundaryMode::manual` 要求两个边界都显式提供；`estimateCandidates` 要求两个边界都缺省并返回两个可编辑候选；只提供一侧属于输入错误。显式提供的 `0` 仍是时间值，不能充当缺省哨兵。结果结构带 `schemaVersion`、通用指标 ID、单位和参数快照，未来可追加 F0 归一化配置/指标而不改写既有导出字段；当前版本不填入 F0 结果。Info 与 TSV/CSV 输出共用同一 `AnalysisResult` 格式化器。

核心在 `fon` 层复用 Praat 已有的 `Sound_to_Spectrum`、`Sound_to_Formant_burg`、`Formant_getBandwidthAtTime` 和 `Spectrum_getCentreOfGravity` 等实现；每个分析窗先按相同设置提取，再由同一段级核心计算类别特征。编辑器和对象动作只负责把 Sound/LongSound 转成有效片段并调用核心，不在 `foned`、`praat_Sound.cpp` 或 Python 中另行复制公式。

- **编辑器菜单**：使用 Praat 原生 C++ 菜单/表单和现有音频对象机制；默认目标为当前 Sound/LongSound 编辑器的选区。编辑器没有有效选区时，要求用户给出范围或明确选择整段，不静默改范围。
- **对象动作与脚本**：在 `fon/praat_Sound.cpp` 注册可供 Sound/LongSound 使用的动作，使 Praat 脚本可以带上范围和参数调用核心。结果支持以文本/TSV 写入指定文件；脚本调用不能擅自弹出 Info 窗口。
- **AI 工具**：`ai/praat_ai/tools.py` 负责参数校验和生成对象动作调用，结果文件路径交给已有工具上下文处理；不在 Python 中另写声学公式。AI 菜单和对话链路都落到同一 C++ 核心。
- **对象来源**：已载入对象列表显示所有可分析的 Sound/LongSound，并允许刷新。文件读取使用 Praat 原生文件选择器和音频读取器；大文件允许使用 LongSound。加载参照音不得替换目标对象、清除对象列表选择或覆盖编辑器选区。

## 界面流程

### VOT

从声音编辑器的“辅音分析”菜单或对象动作打开 VOT 表单。目标默认取当前编辑器选区；用户可切换对象和独立设置范围。自动估计提供初始 burst 与 voicing 候选，显示波形/语图上的候选标记和估计置信/质量说明。用户可以移动两条边界、分别试听边界附近片段，再确认结果。允许正 VOT、负 VOT（预发声）和零 VOT；时间点是否有效由来源对象的时间域判断，不以时间必须非负替代校验。未提供边界与显式输入 `0` 必须是不同状态。AI 调用显式值时原样计算，不把双零改写成自动模式。

自动估计只是可编辑的候选，不等于音位识别或已验证判分。burst 与 voicing 的检测质量不足时标记为 warning/unavailable，仍可手动标注。

### 元音鼻化和鼻辅音

选择“鼻化分析”后，先选择“元音鼻化”或“鼻辅音”。界面有“目标音”和“参照音”两个并列面板。目标单样本测量允许暂不选参照；运行比较时必须先为两侧都选择有效片段。每个面板可以选已加载对象或“从文件夹读取……”，并独立指定绝对起止时间。目标初始使用编辑器选区；参照音的读取、播放或边界调整不应改变目标选择。

每个面板显示波形与语图，允许调整边界，并提供“分别试听”和“依次试听”。元音鼻化可记录元音类别（/a/、/i/、/ə/、其他/未知）、IPA、语言和说话人等可选元数据；这些字段辅助解释结果，不作为自动测量分支的强制档案。鼻辅音可编辑测量频带及时间窗/步长。

### R 音声学分析

入口使用新名称“R 音声学分析”。比较模式下必须分别选择目标音和参照音，再选择“擦音”“塞擦音”或“近音类 r”；任一侧缺失时禁用比较并说明原因。其他类别显示“不支持此分析类别”，不套用最接近的公式。

- 擦音：用户标定噪声段范围，并可预览被纳入频谱统计的区间。
- 塞擦音：单独标出闭塞起点、释放时刻（闭塞终点）、释放瞬态结束/稳定摩擦起点、摩擦终点。结果报告闭塞、释放过渡和摩擦时长；频谱只用用户界定的稳定摩擦段，排除闭塞与释放瞬态。
- 近音类 r：用户标定有声段范围，显示 F2/F3/F3−F2 的时间轨迹；无效或缺失帧不伪造为零。

### 对照结果

结果表按指标并列展示目标、参照、单位、差值和各自质量状态。差值只在指标定义、单位、参数及可用频带兼容时提供。采样率不同但都覆盖共同频带时保留原采样率测量并提示 warning；频谱叠图映射到记录过的共同频率网格，时间窗长仍以秒统一。任一侧有效带宽不足时保留两侧可用的原始值，但不给不可比指标差值。频谱或时间曲线使用不同颜色/图例标出来源和实际时间范围；长度不同的片段可以映射到 0–100% 相对时长用于叠图，但表格始终保留真实起止时间与真实时长。

导出文本/TSV 至少包含：Praat 版本、来源对象/文件标识、目标/参照绝对边界、采样率和声道、分析类别、指标值与单位、差值、质量状态及原因、全部可调参数、可选语言/音类/说话人元数据。导出需可区分“空值/不可用”和数值 0。

## 指标定义

### 元音鼻化

所有指标均是可解释的声学特征，不单独等同于鼻化程度真值。目标/参照应优先来自同一说话人、相似元音和相近录音条件。跨条件对照要明确提示可比性限制。

| 指标 | 定义与单位 | 适用与限制 |
|---|---|---|
| A1−P0 | `20 log10(|H_A1| / |H_P0|)`，单位 dB。A1 为同一分析帧中 F1 带宽内最高谐波的幅度；P0 为低频鼻音极点搜索带内局部峰所对应谐波的幅度。 | 初始 P0 搜索带可设为 250–450 Hz，但它只是可编辑、需随结果记录的先验范围，不是跨元音/说话人的固定生理界限。A1 与 P0 落在同一谐波或无法区分时返回不可用。 |
| A1−P1 | `20 log10(|H_A1| / |H_P1|)`，单位 dB。P1 为 F1 与 F2 之间鼻音极点搜索带内局部峰所对应谐波的幅度；初始搜索带可设为 790–1100 Hz，并与当前 F1/F2 区间取交集。 | 与 A1−P0 分开显示。低 F1/高元音导致 A1−P0 失效时可单独报告 A1−P1；不能把一个指标的值复制到另一个指标。 |
| F1 带宽 B1 | 对同一设置的 Burg 共振峰分析得到第一共振峰带宽，单位 Hz。 | 只在元音段和稳定的 formant 设置下报告；不得直接解释为声道开放或舌位。 |
| A3−P0 | `20 log10(|H_A3| / |H_P0|)`，单位 dB。A3 为 F3 带宽内最高谐波幅度，P0 沿用上述低频鼻音极点幅度；界面标为“频谱倾斜相关特征（A3−P0）”。 | 这是文献中的 spectral-tilt proxy，不是通用全频谱斜率。F3 或 P0 无法可靠定位时不可用；保留说话人、元音与录音条件限制。 |

使用同一可配置分析窗，在元音段 25%、50%、75% 位置及可用的连续帧上取值；初始窗长 50 ms、帧移 5 ms，窗型和参数可编辑，目标/参照必须一致并随结果保存。F1/F2/F3 中心与带宽使用同一份 Praat Formant 设置；A1 取 F1 带宽内谐波幅度最大的谐波，P0/P1 取各自搜索带内局部峰对应的谐波。各谐波幅度先按同一窗和幅度标定转换成 dB，再相减，幅度比按 `20 log10` 计算。结果展示各采样位置/轨迹，并可报告有效帧的中位数作为片段摘要，不把摘要当成分类分数。所有分析参数和有效帧范围随结果保存。参照比较不做归一化百分数和综合鼻化分，后续若要做说话人归一化必须先有独立验证设计。

### 鼻辅音

| 指标 | 定义与单位 | 适用与限制 |
|---|---|---|
| 低/高频能量比 | 每个分析帧计算线性能量比 `sum(power[f_low ≤ f < f_split]) / sum(power[f_split ≤ f ≤ f_high])`，无量纲；`power` 为窗化 FFT 各频点功率，分割频点只计入高频分母侧一次。片段摘要为有效帧比值的中位数，并可显示逐帧曲线。推荐初始频带为 0–320 Hz 与 320–5360 Hz，25 ms Hann 窗、512 点 FFT、2.5 ms 帧移（16 kHz 示例）；其他采样率按帧采样点数调整 FFT 点数并记录。 | 这是描述性谱特征，不叫“鼻化百分比”或分类概率。原始频带来自英语鼻音/半元音区分研究；普通话不同部位鼻辅音的解释必须经本项目标注样本验证。两段使用同一可编辑频带、窗长、帧移及预处理；目标和参照必须一致。若分母为零或有效频带不足则不可用。 |
| 片段时长 | `end − start`，以 ms 显示并保存秒值。 | 起止点由用户确认；自动边界只可作为待确认的初始标记。 |

若采样率/Nyquist 或有效录音带宽不足以覆盖上限，界面提示并标记不可比；用户可以对目标/参照共同选择新频带后重新测量。采样率不同但两侧均覆盖所选频带时保留原始采样率、以同一秒制窗长和频带测量，并显示可比性 warning；绘图只在明确记录的共同频率网格上插值。不得只对一侧静默截断频带。

### R 音声学特征

| 用户选定类别 | 输出 | 定义与约束 |
|---|---|---|
| 擦音 | 谱重心 COG（Hz）、主峰频率（Hz）、谱扩展度（Hz）、谱平坦度（0–1）。 | COG 为所选频带功率加权频率均值 `Σ(f·P)/ΣP`；扩展度为以 COG 为中心的功率加权标准差；谱平坦度为 `exp(mean(ln(P+ε))) / mean(P+ε)`，其中 `ε=max(P)×10⁻¹²`。主峰取同一分析谱与选定频带中的最大功率频点。逐帧分析初始使用 25 ms Hann 窗、5 ms 帧移；显示逐帧曲线与有效帧中位数摘要。目标与参照共用频带、窗、步长和平滑设置。 |
| 塞擦音 | 闭塞时长、释放过渡时长、摩擦时长（ms）及稳定摩擦段的上述谱特征。 | 释放时刻作为闭塞终点；释放过渡从释放时刻计至稳定摩擦起点。闭塞段和释放瞬态不得混入稳态摩擦频谱；边界由用户确认并随结果保存。若稳定摩擦段短于一个分析窗，谱指标不可用但边界时长仍可报告。 |
| 近音类 r | F2、F3、F3−F2（Hz）及各轨迹。 | 目标与参照共用 Burg 阶数、最高共振峰、窗长、预加重和帧移；无声或无可靠共振峰帧报告缺失原因。绘图可按相对片段时间叠加，原始秒数仍保留。 |

这些参数描述声学信号，不直接测量舌头卷曲形态。普通话卷舌/儿化的解释需要对应音类、元音环境和人工标注数据支持；当前版本不将单个数值换算成“卷舌度”。

## 质量与错误处理

每个指标独立返回 `measured`、`warning` 或 `unavailable`。warning 保留可用数值和具体风险；unavailable 不含数值。所有结果行显示状态和人可理解的原因，不把缺失值写成 0 或空白后让用户猜。

至少需要明确处理：对象/选区不存在、起止时间颠倒或越界、片段短于分析窗口、近乎静音、周期性不足、A1/P0/P1 无法分辨、共振峰追踪失败、释放边界不清、用户选择了不支持的发音类别、Nyquist/有效带宽不足、比较参数不一致、格式读取失败，以及核心分析抛出的 Praat 错误。请求字段非法或时间域越界属于输入错误，在对应字段旁显示原因且不运行测量；单项 DSP 指标失败时只将该指标标为 `unavailable`，不丢掉其他已测指标；目标/参照整体不可比时保留两侧原始测量，但不给差值。Praat `MelderError` 和标准 C++ 异常必须在对象动作/GUI/AI 适配边界捕获并转换为可读错误，任何异常都不得穿过窗口过程。预览绘图失败时保留文字测量和错误说明。

参数校验应区分“未提供”和数值 0。任何自动边界都记录为候选值及来源；用户修订后保存最终边界，不覆盖自动候选的来源记录。

## 验收标准

1. GUI、Praat 脚本/对象动作和 AI 工具对相同对象、边界和参数调用同一 C++ 分析函数，产生一致的数值、单位、状态与原因。
2. VOT 能处理显式 `0`、零 VOT、负 VOT/预发声和对象时间域校验；缺参行为明确；自动估计给出可编辑边界，不能静默替代显式输入。
3. 鼻化和 R 音都有目标/参照独立对象、独立边界、波形/语图预览、分别/依次试听、参数快照、对照值与可复现导出。
4. 目标/参照的相同指标只有在定义和参数兼容时才展示差值；不可比较时给出原因。不同片段长度的叠图使用相对时间且不会丢掉真实时长。
5. 缺失值、失败值、零值在表格、图形和导出中含义一致；不产生自动音素标签、合格阈值或未经验证的综合分。
6. 单元/核心测试覆盖公式、边界、频带、缺失/警告和不同采样率；集成测试覆盖三种调用入口的一致性、对象选择不被参照音污染、导出字段与异常安全。
7. 既有 AI 工具与模板回归保持通过；新增 UI 在真实 Praat 构建中验证菜单注册、Sound/LongSound、文件导入、试听、手动边界、结果输出和退出/关闭行为。
8. 科学验收使用带人工边界和音类标注的普通话样本，至少覆盖 `/a i ə/` 鼻化环境、鼻辅音、擦音/塞擦音与近音类 r；TIMIT 等英文现成语料可验证通用边界与工程链路，不能替代普通话指标有效性验证。验证样本、人工标注规则、适用条件和差异报告随实现交付。

## 实施顺序与门槛

1. **固化基线与核心契约**：记录干净 HEAD、当前工作区差异和现有测试结果；在隔离 worktree 中实现。确认来源、绝对边界、指标状态/原因、参数快照和序列化格式。
2. **修复并迁移 VOT**：先补零/负 VOT及缺省区分的测试，再把显式计算和候选估计接入共用 C++ 核心；保留手工复核路径。用单元合成音测试后，以真实人工标注音频验证，不把合成结果当最终科学验证。
3. **实现鼻化核心**：先实现并测试 A1−P0、A1−P1、B1、A3−P0 的单项质量状态，再实现鼻辅音频带比和时长；确认共同参数、带宽不足、元音环境限制的结果表现。
4. **实现 R 音核心**：先做用户指定类别与人工边界，再做擦音、塞擦音和近音类 r 的各自指标及兼容性检查；不增加自动音类分类。
5. **接入原生 UI、对象动作和 AI**：共享双面板选择/试听/编辑组件；分别验证菜单、脚本与 AI 的输入/输出一致性及对象状态保持。
6. **普通话样本验证与交接更新**：完成真实样本复核、局限说明、测试报告和用户文档后，更新 `ai/HANDOFF.md` 的下一步与完成状态。未通过某指标的样本验证时，将该指标保持为实验性描述结果或暂不启用，不增加合格判断。

每阶段只有通过本阶段测试并保存可审查结果后才进入下一阶段。F0 归一化、跨说话人标准化和任何自动分类单独立项。

## 回退准备

- 实现必须在独立 worktree/分支进行。开始前记录当前 HEAD，并留存本轮已有跟踪文件差异清单；不得用 stash、reset 或清理命令处理现有工作区。
- 该工作区当前已有用户改动：`README.md`、`ai/HANDOFF.md`、`ai/praat_ai/chat.py`、`ai/praat_ai/tools.py`、多个 `ai/tests` 文件、`PraatZHcn.lnk` 和 `docs/INSTALL-WINDOWS.zh-CN.md`。这些内容不属于本设计稿，不得随回退覆盖或带入功能提交。
- 每个实现阶段使用独立、可审查提交。核心调用契约与新旧入口之间保持可编译的阶段状态；菜单可先保持隐藏，直到核心与验收用例准备好。
- 回退时关闭 Praat 进程，停用新菜单/动作注册，回退功能提交或丢弃隔离 worktree；不改用户对象文件、录音或 TextGrid。导出的结果文件不自动删除。
- 新增的样本、边界和验证报告进入单独测试目录并记录来源/授权；回退仅删除本分支新增的测试夹具，不触碰用户录音。

## 参考依据

- 项目上游和借用代码记录：[`CREDITS.zh-CN.md`](https://github.com/f246813/praat-simplified-chinese-ai/blob/modern/CREDITS.zh-CN.md)。
- Chen (1997), 元音鼻音化中的 A1−P0/A1−P1 及其适用条件：[PubMed](https://pubmed.ncbi.nlm.nih.gov/9348695/)。
- 普通话鼻韵尾按元音环境分析 A1−P0/P1：[APSIPA 2020 论文](https://www.apsipa.org/proceedings/2020/pdfs/0000584.pdf)。
- Pruthi & Espy-Wilson (2004), 英语鼻音/半元音能量比定义及帧设置：[论文全文 PDF](https://bpb-us-e1.wpmucdn.com/blog.umd.edu/dist/c/619/files/2019/11/journal_pruthi_espy_sc_04.pdf)。该比值在本设计中仅作为原始描述性特征，普通话适用性待验证。
- Styler (2017), 鼻化声学指标的跨说话人/语言差异：[PubMed](https://pubmed.ncbi.nlm.nih.gov/29092545/)。
- Carignan (2021), 鼻化特征测量方法与适用限制：[论文 PDF](https://discovery.ucl.ac.uk/id/eprint/10121435/1/JASA_NAF_R2.pdf)。
- Styler (2015 dissertation), A3−P0 对频谱倾斜的操作定义：[论文 PDF](https://wstyler.ucsd.edu/files/styler_dissertation_final.pdf)。
- A3−P0 作为相关辅助特征的讨论：[JSLHR 2024](https://pubs.asha.org/doi/10.1044/2024_JSLHR-24-00083)。
- 普通话齿擦音频谱重心受说话人及元音环境影响：[Hauser 2023](https://pmc.ncbi.nlm.nih.gov/articles/PMC10666527/)。
- 普通话 R 音及其 F2/F3 声学变异：[PubMed 2024](https://pubmed.ncbi.nlm.nih.gov/39279469/)。
- 普通话塞擦音闭塞/摩擦时长的环境差异：[Zhu & Chen 2016](https://pubmed.ncbi.nlm.nih.gov/27475170/)。
- TIMIT 的时间对齐音素标注可作为工程测试资料：[LDC TIMIT 文档](https://catalog.ldc.upenn.edu/docs/LDC96S32/)。
