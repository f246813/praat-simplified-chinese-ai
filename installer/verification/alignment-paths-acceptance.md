# wav2vec2 / MFA 路径配置验收

日期：2026-10-01。

按最终确认的范围，在现有路径配置窗口和 install 的前置软件页面中，依次追加与 Python、llama.cpp 相同的路径输入框和“浏览…”按钮：

1. wav2vec2 本地模型目录（浏览文件夹）。
2. MFA 程序（mfa.exe / .bat / .cmd）。
3. MFA 声学模型（.zip）。
4. MFA 可选发音词典（.dict / .txt / .zip）。

保持纵向列表，字段较多时滚动查看；没有新增标签页、启用开关、后端或 CPU/CUDA 选项。已有 Python 缺依赖提示和 PowerShell 一键配置入口固定显示在列表下方，不会随新增字段滚出可视范围。

## 保存行为

配置映射为 `alignment.wav2vec2.model`、`alignment.mfa.executable`、`alignment.mfa.acoustic_model`、`alignment.mfa.dictionary_path`。回填已有路径、模型 ID、MFA 模型名称和 PATH 命令。保存只修改编辑过的路径，保留 enabled、backend、device、Conda、音素映射和其他运行参数。未编辑的历史失效路径不会阻断修改其他字段；新无效路径会拒绝保存。

路径配置继续使用已有文件锁、原子写入和备份/回滚流程。安装器 Gather、提权 Resume 和实际 InstallEngine 均携带并保存路径；选择暂不配置时，重装保留原配置文件字节。

这次只提供路径配置，不安装 wav2vec2 / MFA 依赖，不下载模型，不执行对齐任务。现有 Conda 启动配置继续生效。

## 备份与产物

构建前备份：`backups/alignment-paths-before-build-20261001-192137`。30 个原文件的 SHA256 已全部核对。

已更新根目录 `AIPraat-paths.exe`、`AIPraat-install.exe`；Praat.exe 与 Praat-fixed.exe 保持原程序。安装包 CRC、59 个有效载荷文件哈希、文档、默认禁用的可选对齐器和最终构建报告哈希均验证通过。两个程序内嵌 PowerShell 脚本与源码一致。

## 验证结果

| 项目 | 结果 | 日志 |
| --- | --- | --- |
| 新字段顺序与浏览样式、回填、路径校验、参数保留、并发更新、实际安装、跳过重装、旧 MFA 兼容、清空路径及无效新路径拒绝 | 11 通过 | alignment-paths-green.log |
| 路径配置保存、事务与文件锁回归 | 15 通过 | alignment-paths-regressions.log |
| 安装器契约回归 | 21 通过 | alignment-paths-installer-contracts.log |
| Python 缺依赖引导与可见性、PowerShell 参数回归 | 4 通过 | alignment-python-setup-regressions.log |
| 实际 Praat 菜单、7 字段配置窗口、取消、保存、回填与退出 | 8 通过 | alignment-paths-native-live.log |
| 构建与包/备份校验 | 通过 | alignment-paths-build.log / alignment-paths-package-check.log |

共 59 项功能与回归检查通过，另完成构建产物校验。独立代码审查发现的旧 MFA 命令/Conda 兼容问题已修复并复核。

截图：`alignment-paths-dialog.png`、`alignment-paths-installer.png`。
