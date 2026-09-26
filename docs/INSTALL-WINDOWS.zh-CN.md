# Windows 从零安装指南

这份指南面向第一次接触本项目的 Windows 10/11 x64 用户。它会带你安装本仓库的 Praat 中文版，并按需启用 AI。

> **先看这里：**截至 2026 年 9 月，公开仓库的 [Releases](https://github.com/f246813/praat-simplified-chinese-ai/releases) 没有可下载的 Windows 安装包。之后若页面出现 Windows zip，下载解压即可；目前需要按下面的“从源码构建”步骤生成 `Praat.exe`。Praat 官网的普通版本不能替代本项目构建版，因为它不包含本仓库的中文修改和 Python 桥接功能。

## 1. 准备项目和运行环境

### 必需：Git、MSYS2 和本项目源码

1. 安装 [Git for Windows](https://git-scm.com/install/windows)。不熟悉命令行时，安装选项保持默认即可。
2. 安装 [MSYS2](https://www.msys2.org/)。安装后从开始菜单打开 **MSYS2 CLANG64**，不要用普通的 MSYS2 或 MinGW 终端代替。
3. 在 CLANG64 终端中更新系统并安装本项目构建所需工具：

   ```bash
   pacman -Syu
   ```

   如果它要求关闭终端，关闭后重新打开 **MSYS2 CLANG64**，再运行：

   ```bash
   pacman -Syu
   pacman -S --needed make zip mingw-w64-clang-x86_64-clang mingw-w64-clang-x86_64-pkgconf
   ```

4. 打开 Windows PowerShell，在一个路径简单的目录下载 `modern` 分支：

   ```powershell
   New-Item -ItemType Directory -Force C:\src | Out-Null
   cd C:\src
   git clone --depth 1 --branch modern https://github.com/f246813/praat-simplified-chinese-ai.git
   ```

   这里用 `C:\src` 作例子；如果 Windows 不允许在 C 盘根目录新建文件夹，就把项目放到自己的用户目录下，并在下一步对应修改路径。

5. 回到 **MSYS2 CLANG64** 终端，进入刚下载的项目目录并编译：

   ```bash
   cd /c/src/praat-simplified-chinese-ai
   make PRAAT_ARCH=x64v3 -j2
   ```

   编译成功后，`Praat.exe` 会出现在仓库根目录。首次编译需要一些时间；之后修改源码再运行同一命令即可增量编译。编译时先关闭所有已打开的 Praat 窗口。

   `x64v3` 构建面向较新的 x64 处理器；如果程序启动时报 CPU 指令不支持，在同一目录改用 `make PRAAT_ARCH=x64v1 -j2` 重新编译通用 x64 版本。

> MSYS2 的 CLANG64 环境和包管理方式见[官方文档](https://www.msys2.org/docs/environments/)及[软件包管理说明](https://www.msys2.org/docs/package-management/)。本项目 CI 使用同一套工具和构建命令，详见 [Windows 构建工作流](../.github/workflows/release.yml)。

### 只想使用普通 Praat

如果你不需要本项目的中文版修改和 AI 功能，可以直接从 [Praat 官网下载 Windows 版](https://praat.org/download_win.html)，跳过源码构建。但官网版本不是本项目的构建产物。

## 2. 安装 Python（使用 AI 时需要）

1. 从 [Python 官方 Windows 下载页](https://www.python.org/downloads/windows/)安装 **64 位 Python 3.12**。安装界面勾选添加 Python 到 PATH；安装器若提供 Python Launcher，也一并保留。
2. 在 PowerShell 进入仓库目录，创建独立环境并安装仓库列出的依赖：

   ```powershell
   cd C:\src\praat-simplified-chinese-ai
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install --upgrade pip
   .\.venv\Scripts\python.exe -m pip install -r ai\requirements.txt
   ```

3. 启动本项目编译出的 `Praat.exe`，在 **Praat → Python settings...** 中将解释器设为：

   ```text
   C:\src\praat-simplified-chinese-ai\.venv\Scripts\python.exe
   ```

   要用 AI 就需要这一步。该虚拟环境只供本项目使用；不要把 `python.exe` 误选成 `pythonw.exe`。

## 3. 选择一种 AI 模型连接方式

两种方式选一种即可。第一次配置建议先选云端 API，步骤少；本地方式不需要 API key，但要下载模型文件并占用电脑内存/显存。

### 方式 A：云端 API（不需要 llama.cpp 或本地模型）

1. 在 Praat 菜单打开 **前端 → API 配置...**。
2. 选择服务商，填写服务商提供的 API 地址、模型名和 API key，点击“测试连接”，成功后保存。
3. API key 只保存在本机的 `ai/ai_config.json`（此文件已被 Git 忽略），不要把它发给别人或提交到 GitHub。

### 方式 B：本地模型（llama.cpp + Qwen）

1. 从 [llama.cpp 官方 GitHub](https://github.com/ggml-org/llama.cpp)的 README 阅读 Quick start，并在[官方 Releases](https://github.com/ggml-org/llama.cpp/releases)下载适用于 Windows x64 的预编译包。解压后找到 `llama-server.exe`。需要自行编译时，按其[官方构建指南](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md)操作。
2. 在 PowerShell 运行本仓库的模型下载脚本：

   ```powershell
   .\ai\Download-Qwen35.ps1 -OutputDirectory D:\models
   ```

   脚本会下载 Qwen3.5-0.8B 的 GGUF 模型和视觉投影文件；模型来源与文件名见 [`Download-Qwen35.ps1`](../ai/Download-Qwen35.ps1)。确保 `D:\models` 有足够空间。
3. 把示例配置复制到本机配置，再用记事本编辑：

   ```powershell
   Copy-Item ai\ai_config.example.json ai\ai_config.json
   notepad ai\ai_config.json
   ```

   在 `server` 配置中填写 llama-server 和模型文件的实际路径；在当前启用的 `qwen3.5-0.8b` 预设里也填写对应的两个模型路径。把未下载的 2B 预设路径更新或删除，以免误选。路径示例：

   ```json
   "llama_server": "D:/llama.cpp/llama-server.exe",
   "model_path": "D:/models/Qwen3.5-0.8B-Q4_K_M.gguf",
   "mmproj_path": "D:/models/mmproj-F16.gguf"
   ```

   JSON 里的路径建议使用 `/`。如果 PowerShell 找不到下载脚本，先确认当前目录是仓库根目录。
4. 重启 Praat，在 **前端 → 启动前端** 中启动服务和对话窗口。模型首次加载会比之后慢；如果电脑资源有限，可先用默认的 0.8B 模型，不要同时开多个大模型。

## 4. 验证和可选功能

- 打开 `Praat.exe` 后能看到对象列表窗口，说明 Praat 已能运行。
- 在菜单 **前端 → 启动前端** 后能出现对话窗口，说明 Python、配置和所选模型连接正常。
- 完整 AI 说明、配置项及排障步骤见 [`ai/README.zh-CN.md`](../ai/README.zh-CN.md)。插件单独安装见 [`ai/plugin/README.zh-CN.md`](../ai/plugin/README.zh-CN.md)。
- **强制对齐是可选项**。默认没有 MFA 或 wav2vec2 也能运行；需要更精确的音素时间边界时，再按 AI README 安装 [Miniforge](https://conda-forge.org/download/) 和 [Montreal Forced Aligner](https://montreal-forced-aligner.readthedocs.io/en/latest/installation.html)，仓库提供 `ai/Install-MFA.ps1` 与 `ai/Download-MFA-Models.ps1` 辅助脚本。模型下载脚本需要本机 Git 已保存可用的 GitHub 凭据。wav2vec2 的 Python 依赖见 `ai/requirements-wav2vec2.txt`。

## 所需软件一览

| 目标 | 需要安装 | 不需要时可跳过 |
| --- | --- | --- |
| 编译本项目 Praat | Git、MSYS2 CLANG64 和上面的构建包 | 不编译、直接使用项目提供的 Windows 构建包时 |
| 运行 Praat 中文版 | 编译好的 `Praat.exe` | — |
| 运行 AI 前端 | 64 位 Python 3.12、`ai/requirements.txt` 中的 Python 包 | 只把 Praat 当作普通语音分析工具时 |
| 使用本地 AI | llama.cpp 的 `llama-server.exe`、Qwen GGUF 和 mmproj 文件 | 改用云端 API 时 |
| 使用强制对齐 | Miniforge/MFA 或 wav2vec2 模型与依赖 | 其他 AI 功能和基本测量不依赖它 |
