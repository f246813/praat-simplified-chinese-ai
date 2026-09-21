# 参考、借用与依赖

这个仓库是 **Praat 简体中文版 + 本地 AI 前端**，不是从零写的：主体来自下面的基座
与上游项目，另有一批「借来用」的代码库。这份清单把它们和各自的用途、许可写清楚。

## 基座与上游（必须保留的署名）

| 项目 | 用途 | 许可 |
| --- | --- | --- |
| [KasumiKitsune/praat-simplified-chinese](https://github.com/KasumiKitsune/praat-simplified-chinese) | **本仓库的基座**：Praat 7.0.02 的简体中文汉化（界面/手册/打包），`modern` 分支的现代版界面 | 跟随上游 Praat |
| [praat/praat](https://github.com/praat/praat)（[praat.org](https://praat.org)、[praat.github.io](https://praat.github.io)） | 上游软件本体，作者 **Paul Boersma & David Weenink** | GPL-3.0-or-later（见 [LICENSE](LICENSE)），文档/图片部分另有 CC BY-SA 4.0 等，完整清单在 [`docs/LICENSE.txt`](docs/LICENSE.txt) |

本副本由 `f246813` 发布，**与上游（praat/praat）和基座仓库没有隶属关系**；基座里
原有的署名、许可和链接一律保留。汉化版官方主页仍在
[kasumikitsune.github.io/praat-simplified-chinese](https://kasumikitsune.github.io/praat-simplified-chinese/)。

## 借用了代码或设计的代码库

| 项目 | 借了什么 | 落在哪里 |
| --- | --- | --- |
| [chengafni/praat](https://github.com/chengafni/praat) | 声学测量脚本的公式与做法：`plugin_CompleteAnalysis`（表驱动：`objects.txt`/`queries.txt`/`settings.txt`）、`plugin_SpectralEmphasis`、`plugin_HL`、`plugin_HammarbergIndex`、`plugin_PA`、`plugin_IntensitySlope`、`plugin_PitchPeakLatency` 的原理与原脚本 | `ai/praat_ai/tools.py` 的测量模板、`ai/praat_ai/measures.tsv`（表结构参考）、`ai/plugin/`（原生插件的 `setup.praat` + `Add menu command` 做法），说明见 [ADR-005](ai/docs/adr/ADR-005-table-driven-measurements.md)、guide §8.4/§8.7 |
| [QwenLM/Qwen-Agent](https://github.com/QwenLM/Qwen-Agent) | agent 循环的设计参考：工具自带 JSON Schema → 交给服务端原生 function calling → 把结果作为 function/tool 消息回灌 → 再规划；工具报错当「可恢复的观察」；输入按 token 预算截断 | `ai/praat_ai/qwen.py`、`ai/praat_ai/chat.py`（见 [ADR-003](ai/docs/adr/ADR-003-planning-interface.md)、[ADR-004](ai/docs/adr/ADR-004-agent-loop.md)、[ADR-008](ai/docs/adr/ADR-008-context-token-budget.md)） |
| [Ron-312/PraatPlugin](https://github.com/Ron-312/PraatPlugin) | 调用层的做法参考：Praat 安装位置的定位（对应 `PraatInstallationLocator`）、脚本投递与结果契约的取舍 | `ai/praat_ai/praat_app.py`（找 Praat）、`ai/docs/adr/ADR-001/002`（我们改了结论的地方都写在 ADR 的「备选方案」里） |

## 运行依赖（不是代码借用，但用到了）

| 依赖 | 用途 |
| --- | --- |
| [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp)（`llama-server`） | 本地推理服务，OpenAI 兼容接口 + 原生 tool calling |
| [unsloth/Qwen3.5-0.8B-GGUF](https://huggingface.co/unsloth/Qwen3.5-0.8B-GGUF)、[unsloth/Qwen3.5-2B-GGUF](https://huggingface.co/unsloth/Qwen3.5-2B-GGUF) | 本地模型与 `mmproj` 视觉投影文件 |
| [YannickJadoul/Parselmouth](https://github.com/YannickJadoul/Parselmouth)（praat-parselmouth） | Python 侧读音频、做特征跟踪（可选） |
| [Montreal Forced Aligner](https://montreal-forced-aligner.readthedocs.io/) + [Kalpy](https://github.com/mmcauliffe/kalpy)/Kaldi/OpenFST 等 | 音素强制对齐（可选，见 `ai/Install-MFA.ps1`） |
| [facebook/wav2vec2-lv-60-espeak-cv-ft](https://huggingface.co/facebook/wav2vec2-lv-60-espeak-cv-ft) | 另一种音素对齐后端（可选） |
| Praat `external/` 里的第三方库（espeak-ng、portaudio、whisper.cpp、FLAC、LAME、libvorbis 等） | 随上游 Praat 一起分发，署名与许可见 [`docs/LICENSE.txt`](docs/LICENSE.txt) |

## 测量公式的参考文献

借来的几条嗓音/频谱测量原样照抄了公式，出处写在各工具函数的 docstring 里：

- Traunmüller, H. & Eriksson, A. (2000) — 谱强调（spectral emphasis）
- Hammarberg, B. et al. (1980) — Hammarberg 指数
- Hillenbrand, J. et al. (1994) — 峰值/有效值比、CPPS（Hillenbrand 式）

## 这个副本改了什么

在基座 `modern` 分支之上加的是**本地 AI 前端**（对话窗口、规划循环、表驱动声学测量、
Praat 原生插件、社区脚本包装、token 预算与可取消的等待）。逐条改动看 git 历史，
设计取舍看 [`ai/docs/adr/`](ai/docs/adr/README.md)，踩过的坑看 [`guide.md`](guide.md) §8。
