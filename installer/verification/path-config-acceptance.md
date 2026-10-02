# 路径配置交付记录

日期：2026-10-01（北京时间）

## 已完成

- 语图编辑器“前端”菜单中，在“添加模型路径…”下方加入“路径配置…”。
- 与安装器共用原生输入框、浏览按钮、文件筛选与 Python 能力校验；窗口仅包含 Python、llama.cpp、视觉投影三个字段。
- 保存前回填当前路径，保存后更新 AI 配置、安装信息、Python 首选项及当前 Praat 进程中的 Python 路径。取消不写配置。
- 保留已有模型、API、自动启动选项及其他预设。仅修改视觉投影时更新当前模型绑定和当前预设的视觉设置。
- 如果打开窗口后模型或预设发生切换，阻止旧窗口覆盖新模型的投影配置。与 API 和模型配置写入共用文件锁。
- 保存前备份原配置；多文件保存失败时回滚。

已有前端服务或对话窗口需要重新启动，才会使用新的 llama.cpp、视觉投影或 Python 环境；当前 Praat 的后续 Python 启动立即使用已保存的环境。

## 构建前备份

位置：`backups/path-config-before-build-20261001-153012/`

备份包含旧 Praat.exe、Praat-fixed.exe、AIPraat-install.exe、相关原始源码和 AI 配置。`manifest.json` 的 22 个文件 SHA256 已核对。备份在首次构建之前创建。

## 构建产物

- `Praat.exe`、`Praat-fixed.exe`：均已更新，内容一致。
- `AIPraat-paths.exe`：独立原生配置窗口，不依赖 Python 启动。
- `AIPraat-install.exe`：已重新打包，包含更新后的 Praat 和配置窗口。

本机原 MSYS2 编译器不存在，因此在 `.build-tools/msys/clang64` 准备了与现有对象文件匹配的 Clang 22.1.8 便携工具链。按原 Makefile 的参数重编译四个修改的 C++ 翻译单元、更新暂存的两个静态库并链接；已有无 ABI 变化的对象文件继续复用。过程记录于 `build-path-config.ps1` 和 `path-config-native-build.log`。构建成功；原有 praat.cpp 内的 5 条编译警告仍存在。

## 验证

| 验证 | 结果 | 证据 |
|---|---|---|
| 路径配置 C# 行为回归 | 15 通过 | path-settings-green.log |
| 原安装器契约回归 | 21 通过 | path-config-installer-contracts.log |
| 完整 AI 单元测试 | 641 通过 | ai-path-config-full-tests.log |
| 实际窗口和菜单回归 | 8 通过 | path-config-live-green.log、path-config-live.json |
| 安装包 CRC、资源 SHA256、备份 SHA256 | 通过 | path-config-package-check.log |

实际窗口测试覆盖菜单相邻顺序、无可用 Python 时打开三项配置、取消不修改、有效 Python 允许保存、模型/API/选项保留、当前 Praat 在一秒内使用新 Python、再次打开回填、关闭 Praat 后路径持久保留及配置子窗口退出。测试采用隔离 USERPROFILE 和合成配置。

首次完整 AI 测试遇到本机缺少 praat-parselmouth；随后将其安装到独立的 `.build-tools/python-libs` 测试目录，重跑全部测试通过。未安装到用户原 Python 环境。
