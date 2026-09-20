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

切换模型（菜单「前端 → 添加模型路径…」或配置里的 `server.model_path`）会真正重启
llama-server：只要端口上运行的不是配置里的模型，前端会先停掉旧服务再用新配置启动。
状态里的「前端模型」来自服务实际加载的模型，配置值单独放在
`frontend_model_configured`，两者不一致时 `frontend_model_mismatch` 为 true。

`server.mmproj_path` 只对匹配的模型有效：如果它和所选模型不匹配（例如 0.8B 的
mmproj 配 2B），前端会自动按纯文本模式启动并在 `ai/logs/qwen-server.log` 记录原因，
此时状态里的 `frontend_vision` 为 false。需要视觉能力就要给对应模型配自己的 mmproj。

同时使用多个模型时，用 `server.mmproj_by_model` 给每个模型各配一个投影文件，
键可以是模型的完整路径或文件名（不区分大小写），例如：

```json
"server": {
  "mmproj_path": "D:/models/mmproj-F16.gguf",
  "mmproj_by_model": {
    "D:\\models\\Qwen3.5-0.8B-Q4_K_M.gguf": "D:/models/mmproj-F16.gguf",
    "D:\\llama.cpp-Qwen\\Qwen3.5-2B-UD-Q5_K_XL.gguf": "D:/models/mmproj-2B-F16.gguf"
  }
}
```

启动时会先查这张表，命中就用该模型自己的投影文件，没有命中才退回 `mmproj_path`；
用菜单给某个模型设置过 mmproj 后，这条映射会自动写入配置。挑选投影文件时要确认
`clip.vision.projection_dim` 等于模型的 `qwen35.embedding_length`
（Qwen3.5-0.8B 是 1024，Qwen3.5-2B 是 2048），否则 llama-server 会以
`mtmd_init_from_file: mismatch between text model … and mmproj` 退出。

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

## 对话窗口（自然语言操作 Praat）

在 Praat 菜单「前端 → 启动前端」成功启动模型后，会自动弹出独立的
「Praat AI 对话」窗口。它的执行链路是：

1. Praat 把当前对象列表写到 `ai/runtime/chat_context.tsv`（id、类、名称、是否选中）。
2. 对话窗口把用户请求交给本地 Qwen3.5-0.8B；模型只负责选择工具并填写参数。
3. Praat 脚本由 `ai/praat_ai/tools.py` 的固定模板渲染，不直接执行模型自由文本。
4. 脚本通过 `Praat.exe --FULL-TRUST --send` 送到正在运行的 Praat 里执行。
5. 脚本把数值结果写入 `ai/runtime/chat_result.tsv`，最后写完成标记
   `ai/runtime/chat_state.txt`；窗口轮询到标记后把结果显示在对话里。

已内置的工具：时长、第 n 共振峰带宽、第 n 共振峰频率、基频、强度、选中对象、
打开编辑器、播放、重命名、删除。模板覆盖不到的请求会退回 `custom_script`，
此时脚本必须通过安全检查（单引号自动改成双引号、禁止 `runSystem`、
`deleteFile`、`exit` 等命令）。

注意事项：

- 查询类工具默认取声音的中间时刻，可以在请求里直接写秒数。
- 共振峰查询会临时创建一个 `ai-chat-temp` 对象，脚本结束前自动删除并恢复原选中对象。
- `An instance of Praat that is not me is already running.` 是 `--send` 的常规提示，
  不是错误，窗口会过滤掉。
- 修改 `ai/` 下的 Python 代码后，要重新从菜单启动前端，对话窗口才会加载新代码。
