# 安装器实现参考

安装器使用 Windows .NET Framework WinForms。`build.ps1` 生成单文件安装器，
`AIPraat.exe` 启动入口关联本机路径，路径窗口维护 Python、模型和对齐器设置。

安装说明见 [README.zh-CN.md](README.zh-CN.md)。资源与有效载荷由构建脚本决定，
当前根目录 EXE 是否匹配当前源码必须通过实际载荷清单核对。

检查入口为 `tests/Run-Tests.ps1`；`verification/` 的说明给出检查主题和边界，
不将旧测试通过数或旧包哈希作为当前状态。云端供应商兼容性、UAC 交互和目标机器
的程序权限需按实际运行环境核对。
