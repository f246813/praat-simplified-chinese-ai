# AIPraat 安装与路径说明

双击 AIPraat-install.exe，依次选择目录、决定是否配置前置软件、完成安装。

默认使用 C:\AIPraat；已有同名文件夹直接复用。浏览按钮选择的是最终安装文件夹，不会再在其里面套一层 AIPraat。可输入其他驱动器或包含中文、空格的完整路径。默认不要求管理员权限；如果目标目录不可写，安装失败页可选择其他位置，或以管理员权限重试。

## 前置软件路径

| 向导字段 | 要选择的文件 | 是否必需 |
|---|---|---|
| Python 环境 | Python 3.10+ 环境内的 python.exe | 选择“现在配置”时必需 |
| llama.cpp | llama-server.exe，与其原有 DLL 放在一起 | 可留空 |
| 前端模型 | 语言模型 .gguf | 可留空 |
| 视觉投影 | 和语言模型配套的 mmproj .gguf | 可留空，只在使用图像能力时需要 |
| wav2vec2 模型 | 本地模型目录，使用文件夹浏览按钮选择 | 可留空 |
| MFA 程序 | mfa.exe，也支持已有 .bat / .cmd 启动器 | 可留空 |
| MFA 声学模型 | 声学模型 .zip | 可留空 |
| MFA 发音词典 | 发音词典 .dict / .txt / .zip | 可留空 |

wav2vec2 和 MFA 路径行依次追加在已有路径行下方，输入框与浏览按钮沿用相同样式；字段较多时可滚动查看。保存只更新这些路径，保留对齐后端、启用状态、CPU/CUDA、Conda 和其他运行参数。已有 wav2vec2 模型 ID、MFA 声学模型名称以及 `mfa` 命令也会回填并保留。使用 Conda 启动 MFA 时，原有 Conda 配置继续生效。

Python 环境需含 Tk、NumPy >= 2、Pillow >= 10，以及云端编排依赖 pydantic-ai-slim[openai] 2.52.0、pydantic-graph 2.52.0、jsonschema 4.26.0。安装器和路径配置窗口检测到依赖缺失时，会同步显示 **“运行Powershell命令一键配置 →”**。点击后打开 PowerShell，为所选 python.exe 配置 pip、Pillow、NumPy 和上述云端编排依赖；已有满足版本的依赖会保留。Tk 属于 Tcl/Tk 组件：Conda 环境通过其管理器安装 tk；唯一匹配的官方 Python 安装通过对应版本、架构和用户范围的安装器补装或修复 Tcl/Tk。若环境未注册、安装目录存在歧义或不支持自动修复，命令窗口会提示具体原因及下一步。完成后按 Enter 返回，界面自动复检，通过后可保存或继续安装。下载依赖需要网络；系统级 Python 修复可能需要管理员权限。

基础依赖清单在 ai\requirements.txt，其中 praat-parselmouth 可增强纠音声学分析。仅在点击一键配置时才修改所选 Python 的依赖；模型仍需自行准备。torch、transformers、MFA 等仅在启用相应强制对齐后端时需要，不是基础 AI 对话的必需项。

如果选择“暂不配置”，可以安装并使用基础 Praat；随后在语图窗口上方选择“前端 → 路径配置…”配置 Python、llama.cpp、视觉投影、wav2vec2 和 MFA 路径。模型文件仍通过“前端 → 添加模型路径…”选择。路径配置窗口可在尚未配置 Python 时打开；保存时检查环境、保留现有模型和 API 设置，并备份原配置。正在运行的服务或对话窗口需重新启动后使用新的路径。也可以再次运行同一安装器，选择原有目录并配置路径。云端 API 可在 AI 窗口配置，不要求本地 llama.cpp 和模型文件。

## 路径保存位置

| 文件 | 保存内容 |
|---|---|
| 安装目录\install-settings.json | 选择的 Python 路径与安装信息 |
| 安装目录\ai\ai_config.json | 前端路径、模型预设，以及 alignment.wav2vec2.model、alignment.mfa.executable / acoustic_model / dictionary_path；用户自己的 API 设置也在此 |
| %APPDATA%\Praat\Preferences.txt | Python.executablePath 和 AI.projectDirectory；保留其他首选项 |
| %APPDATA%\Praat\plugin_praat_ai | 原生测量插件、指向安装目录的 AI 启动命令 |
| 安装目录\.aipraat-backups\时间和编号 | 更新前的原文件及对应路径清单 |

从桌面或开始菜单的 **AIPraat** 快捷方式启动。该入口负责关联本机路径，然后运行当前 Praat.exe。请先关闭其他正在运行的 Praat，以免不同目录的实例共用首选项和消息文件。

安装器重新配置时会保存新的选择；选“暂不配置”重新安装时保留原来的 Python 和模型配置。用户自己的音频、标注和其他文件不会被删除。

本包保留当前 Windows x64-v3 Praat，因此需要 Windows 10/11 64 位及支持 x64-v3（AVX2、FMA、F16C 等）的 Intel/AMD CPU。安装器本身使用 Windows 自带的 .NET Framework，不需要 Python 才能运行。发行文件尚未签名。

## 开发构建

在仓库根目录运行：

    pwsh -NoProfile -File installer\build.ps1

使用本机已有的 .NET Framework C# 编译器。输出为根目录 AIPraat-install.exe，无需 .NET SDK、Inno Setup 或外部压缩工具。包内没有开发机配置、API key、日志、缓存或临时运行文件。

构建完成后，批量验证：

    pwsh -NoProfile -File installer\tests\Run-Tests.ps1 -Python D:\Praat-work\venv-ai\Scripts\python.exe

验证产物和日志位于 installer\verification。UI 验证用相同向导和安装资源，但首选项、快捷方式均写入独立测试目录。
