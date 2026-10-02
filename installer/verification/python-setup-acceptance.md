# Python 一键配置验收记录

日期：2026-10-01。

## 已交付

- 路径配置和 install 前置软件页面在检测到缺少 Tk、NumPy 或 Pillow 时，同步显示“运行Powershell命令一键配置 →”。已有可用环境不显示此入口。
- 点击后打开可见的 Windows PowerShell，为所选 python.exe 配置 pip、Pillow >= 10、NumPy >= 2。满足版本的依赖保留。命令结束后按 Enter 返回，配置窗口自动复检；通过后启用保存或下一步。
- Tk 检查包含实际创建、销毁 Tk 根窗口。Conda 使用所选 Python 基环境的 prefix 安装 tk；官方 Python 通过精确注册目录、解释器架构和用户范围选择对应安装器，验证签名后补装或修复 Tcl/Tk。同版本注册目录存在歧义时停止自动修复并显示下一步。
- 配置期间禁止切换路径、保存、进入下一步或关闭配置窗口，避免运行结果写入另一环境。PowerShell 中断或失败后会重新检查并保留重试入口。
- 共用脚本嵌入 AIPraat-paths.exe 与 AIPraat-install.exe，无需另行分发脚本。使用说明已同步。

## 备份及构建

构建前已备份到 `backups/python-setup-before-build-20261001-183035`，23 个原文件的 SHA256 已核对。备份含当前 Praat、路径配置程序、安装器、安装器源码、测试和使用说明。

根目录 `AIPraat-paths.exe`、`AIPraat-install.exe` 已更新。此次无需修改 C++，Praat.exe/Praat-fixed.exe 保持上一版已验收程序。安装包 CRC、59 个有效载荷文件哈希及两个程序内嵌脚本与源码一致性均通过。

## 验证

| 项目 | 结果 | 日志 |
| --- | --- | --- |
| 新功能：缺依赖分类、两处箭头入口与隐藏、中文/空格/引号/元字符路径参数 | 4 通过 | python-setup-green.log |
| Windows PowerShell 5.1：全新无 pip 虚拟环境实际安装、重复执行、不存在解释器失败返回 | 3 通过 | python-setup-live-green.log |
| Tk 修复：拒绝用户/系统安装歧义、保存系统范围与目标目录、保存用户范围 | 3 通过 | tk-selection-green.log |
| 路径配置与保存回归 | 15 通过 | python-setup-path-regressions.log |
| 安装器契约回归 | 21 通过 | python-setup-installer-contracts.log |
| 实际 Praat 菜单、打开/取消、保存、回填与退出 | 8 通过 | python-setup-native-live.log |
| 最新脚本实际执行复检 | 通过 | python-setup-final-script.log |
| 构建与有效载荷、备份校验 | 通过 | python-setup-build.log / python-setup-package-check.log |

共 54 项功能/回归检查通过，另外完成最终脚本执行与构建产物校验。独立代码审查发现的 PowerShell 5.1 引号、解释器架构与修复目标问题均已修复并复核。

实际依赖安装仅在独立测试虚拟环境中执行。未在用户现有 Conda 或官方 Python 上实际执行 Tk 安装/修复；这两条分支经过代码审查和注册目标选择测试，其真实安装行为仍取决于环境管理器、官方组件可用性及权限。未注册的便携 Python 等特殊环境会明确提示使用其安装器补齐 Tcl/Tk。

界面截图：`python-setup-paths.png`、`python-setup-installer.png`。
