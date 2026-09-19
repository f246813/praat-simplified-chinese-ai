# Praat 本地 AI 纠音前端设计

## 目标

在保留 Praat 7.0.02 中文界面、内置手册和原生算法的前提下，增加一个可离线运行的本地纠音前端：

1. 使用 Praat 自带 Python 桥接操作对象、调用原生算法并回写结果。
2. 给定额外语言音位序列和标准音范本后，把学习者的声学特征与范本对齐。
3. 在语图和音高、强度、共振峰轨迹上标出偏差区间与音素。
4. 使用 Qwen3.5-0.8B 解析用户意图、选择工具和生成解释，不用它替代声学评分。
5. 按显存和任务需求懒加载模型，只保留当前功能需要的运行时组件。

## 模型边界

Qwen3.5-0.8B 是 `image-text-to-text` 视觉语言模型，不是音频模型。它可以：

- 阅读用户用自然语言写的纠音要求。
- 生成受 JSON Schema 约束的工具调用。
- 查看语图、波形、特征曲线截图并生成解释。

它不能可靠地：

- 直接听 WAV 或读取原始采样点。
- 单独完成音素强制对齐。
- 对 F1、F2、VOT、CPP 等数值做可信的逐音素判断。
- 承担完全自由形式的 Agent 循环。

因此，发音错误检测必须由确定性的声学流水线完成；Qwen 只负责前端交互和结果解释。

## 总体架构

```text
中文 Praat 7.0.02
  |
  |  选中 Sound / TextGrid
  v
自带 Python 桥
  |  praat.get_selected()
  |  praat.call()
  |  praat.run_praat_script()
  v
本地 AI 纠音前端
  |
  +--> 请求解析：Qwen3.5-0.8B，受限 JSON
  |
  +--> 声学分析流水线
  |      Praat / Parselmouth / NumPy
  |      音素分段
  |      特征提取
  |      DTW 对齐
  |      范本偏差评分
  |
  +--> 结果写回
         错误 TextGrid
         对比图 PNG
         JSON 报告
         可选 Qwen 解释
```

## 模块划分

### `praat_ai.bridge`

封装 Praat 操作接口：

- 在 Praat Python 环境中使用自动生成的 `praat` 模块。
- 通过 `praat.get_selected()` 获取选中 Sound、TextGrid 和导出文件。
- 通过 `praat.call()` 调用 Praat 原生算法。
- 通过 `praat.run_praat_script()` 生成对象、绘制结果和回写 TextGrid。
- 支持 `sendpraat` 模式，供独立 GUI 控制已运行的 Praat。

### `praat_ai.audio`

读取学习者录音和标准音范本：

- 优先使用 `parselmouth` 调用 Praat 算法提取 Pitch、Formant、Intensity 和 Harmonicity。
- 没有 Parselmouth 时，使用标准库和 NumPy 提取 RMS、过零率、频谱质心、时长和能量包络。
- 输出与采样率无关的时间序列，供后续比较。

### `praat_ai.alignment`

负责音素区间和轨迹对齐：

- 若已有 TextGrid，直接读取目标音位边界。
- 后续可接 MFA、WhisperX 或 wav2vec2 强制对齐器。
- 没有对齐器时，可按给定音位时长和能量/谱变化做基线分段。
- 对参考和学习者的每条特征轨迹做时间规整 DTW。

### `praat_ai.pronunciation`

对每个音素计算偏差：

- 元音：F1、F2、F3、时长、音高轮廓。
- 塞音：VOT、闭音段、爆破谱、后接元音起始共振峰。
- 擦音：频谱质心、高频能量、过零率、摩擦时长。
- 鼻音和近音：共振峰轨迹、强度、时长。
- CPP/HNR：可选的嗓音质量辅助指标。

评分方式：

1. 特征轨迹按 DTW 对齐。
2. 用范本内标准差、音位容差和全局阈值计算标准化距离。
3. 超过阈值的连续片段合并为一个错误区间。
4. 每个错误包含音素、区间、特征、方向、严重程度和证据数值。

Qwen 不参与分数计算。

### `praat_ai.visualization`

生成：

- `ai_errors.TextGrid`：错误区间层和错误点层。
- `ai_overlay.png`：参考与学习者的语图或特征曲线对比，错误区间用矩形框标出。
- `ai_report.json`：完整数值、阈值和错误说明。

### `praat_ai.qwen`

封装本地 OpenAI 兼容服务：

- 默认端点为 `http://127.0.0.1:8000/v1`。
- 负责请求解析、工具选择和可选图片解释。
- 使用 JSON Schema 或确定性解析器，禁止自由文本直接生成 Praat 脚本。
- 服务不可用时，核心纠音功能仍可运行，只是不提供自然语言解释。

### `praat_ai.server`

管理 llama.cpp 服务：

- 按显存选择文本或视觉配置。
- 默认懒加载，空闲后卸载。
- 同一时间只保留一个 GPU 模型，避免与 Whisper 或说话人分离模型争抢显存。

## 显存策略

默认使用 `Qwen3.5-0.8B-Q4_K_M.gguf`。视觉任务另外加载对应的 `mmproj` 文件。

| 可用显存 | Qwen 模式 | 上下文 | 视觉 | 其他模型 |
| --- | --- | --- | --- | --- |
| 小于 2 GB | CPU | 4096 | 关闭 | 只运行 Praat/CPU 分析 |
| 2-4 GB | GPU 文本 | 4096 | 关闭 | Whisper/分离模型按需串行 |
| 4-6 GB | GPU 文本 | 8192 | 按需 | 不与 ASR 同时加载 |
| 6-8 GB | GPU + 视觉 | 8192 | 开启 | 串行加载，空闲卸载 |
| 大于 8 GB | GPU + 视觉 | 16384 | 开启 | 可保留热模型 |

额外规则：

- 默认关闭 thinking 模式，避免 0.8B 模型进入循环。
- 默认单请求，批大小 1。
- 不使用 262,144 上下文，纠音任务通常 8K 足够。
- 生成对比图后，只有用户请求解释时才加载视觉投影文件。
- Praat 的语音识别、说话人分离、Whisper 模型不随纠音模式自动启动。
- 不通过删除编译功能来省显存；所有功能仍保留，只改为懒加载和串行调度。

## Praat 回写方式

1. 学习者 Sound 和标准 Sound 通过对象列表选中。
2. Python 前端读取 `praat.get_selected()` 中的导出 WAV 路径。
3. 分析完成后把结果写入 `praat.get_output_dir()`。
4. Praat Python 桥在子进程结束后自动把输出目录中的文件导回对象列表。
5. `ai_errors.TextGrid` 可作为 Sound 的标注层打开；`ai_overlay.png` 可在 Picture 或对象列表查看。

更进一步的版本将增加专用 C++ 菜单“AI 纠音...”，但第一版先复用现有 Python 编译器，避免破坏稳定构建。

## 安全约束

- Qwen 只输出经过验证的结构化请求，不直接执行任意命令。
- 所有 Praat 操作由固定工具白名单生成。
- 文件路径只允许来自 Praat 选中对象、用户明确输入或配置目录。
- 不启用模型 thinking 循环；设置最大 token 和超时。
- 不使用云端 API；默认只访问本机推理服务。

## 分阶段实施

### 阶段一：本地可运行骨架

- Python 包和请求模型。
- Qwen OpenAI 兼容客户端。
- Praat 桥接适配器。
- 显存配置选择器。
- 基础 WAV 特征和 DTW 比较。
- TextGrid、PNG、JSON 输出。

### 阶段二：音素级纠音

- 接入 Parselmouth 或 Praat 原生 Formant/Pitch/Intensity。
- 增加语言音位清单和音素特定特征权重。
- 接入 MFA/WhisperX 强制对齐。
- 支持多标准音范本和统计阈值。

### 阶段三：Praat 原生 UI

- 新增“AI 纠音...”菜单和对话框。
- 显示参考/学习者对象、音位序列、范本和阈值。
- 一键打开错误 TextGrid 和叠加图。
- 增加模型状态、显存和卸载控制。

## 验收标准

- 不安装 Qwen 服务时，Praat 和基础纠音仍能运行。
- Qwen 不能直接生成或执行未经校验的 Praat 脚本。
- 每个错误区间都能追溯到具体特征和数值。
- TextGrid、PNG 和 JSON 均可自动导回 Praat。
- 在 8 GB 显存下，文本模式默认可同时保留 Praat 和 Whisper；视觉模式按需串行加载。

## 本机验证记录

2026-09-20 在 NVIDIA GeForce RTX 5050 8 GB 上完成：

- `Qwen3.5-0.8B-Q4_K_M.gguf` 文本请求和 JSON 输出成功。
- 加载 `mmproj-F16.gguf` 后可读取 Praat 界面截图并生成中文描述。
- 视觉模式运行期间显卡仍约有 6 GB 空闲显存。
- 模拟 Praat Python 桥后，参考音、学习者录音、错误评分、TextGrid、PNG 和 JSON
  输出链路全部通过。
