# Praat 本地 AI 纠音前端

本目录在 `praat-simplified-chinese` 的 Python 桥接之上实现 Qwen3.5-0.8B 本地纠音前端。

## 快速开始

1. 安装 Python 3.10 或更高版本，并在 Praat 的 `Python settings...` 中设置解释器路径。
   本机已经创建好独立环境，可直接填写：

   ```text
   D:\Praat-work\venv-ai\Scripts\python.exe
   ```

2. 安装基础依赖：

   ```powershell
   python -m pip install -r ai/requirements.txt
   ```

3. 下载 Qwen3.5-0.8B 与视觉投影：

   ```powershell
   pwsh -NoProfile -File ai/Download-Qwen35.ps1 -OutputDirectory D:\models
   ```

4. 将 `ai/ai_config.example.json` 复制为 `ai/ai_config.json`，修改模型路径。
5. 将 `ai/run_ai_tutor.py` 作为 Python 脚本打开或在 Praat Python 编辑器中运行。
6. 选中标准 Sound 和学习者 Sound。
7. 填写目标语言音位、范本对象、学习者对象和阈值。
8. 运行后查看自动导回的 `ai_errors.TextGrid`、`ai_overlay.png` 和 `ai_report.json`。

## Qwen 服务

默认连接本地 OpenAI 兼容接口：

```text
http://127.0.0.1:8000/v1
```

也可以通过环境变量配置：

```powershell
$env:PRAAT_AI_QWEN_BASE_URL = 'http://127.0.0.1:8000/v1'
$env:PRAAT_AI_QWEN_MODEL = 'Qwen/Qwen3.5-0.8B'
```

本地 llama.cpp 可执行文件和模型路径写在 `ai/ai_config.example.json` 中。

## 音素强制对齐

对齐器是可插拔的：

- `mfa`：配置 `alignment.mfa.enabled`、MFA 可执行文件、发音词典和声学模型。
- `wav2vec2`：配置 `alignment.wav2vec2.model`，安装可选依赖：

  ```powershell
  python -m pip install -r ai/requirements-wav2vec2.txt
  ```

- `auto`：同时启用可用后端，合并边界；不一致时降低置信度。
- 没有任何强制对齐后端时，自动回退为比例分段，并在报告中给出警告。

本机可以使用以下脚本复现环境：

```powershell
pwsh -NoProfile -File ai/Install-MFA.ps1
pwsh -NoProfile -File ai/Download-MFA-Models.ps1
```

当前实现为每次学习者录音动态创建 MFA 词典条目，因此可以直接使用给定的
IPA 音素序列，不要求先准备整段文本的词典。实际语言仍需要对应的 MFA 声学
模型，wav2vec2 模型也需要包含目标音素的 tokenizer。

## 说明

- Qwen 只负责自然语言前端、工具选择和解释。
- 音素对比和错误区间由确定性的声学算法生成。
- 没有 Qwen 服务时，基础纠音仍然可用。
