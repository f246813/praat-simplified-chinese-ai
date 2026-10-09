# Windows 安装与路径配置

安装向导、路径设置和 Python 环境配置由 installer/src 实现，构建入口为 installer/build.ps1。依赖要求、路径处理和载荷内容以当前校验源码及实际构建结果为准；旧三步方案或构建哈希不作为当前验收。

模块职责、实现边界和检查入口见 [当前实现说明](../../CURRENT-IMPLEMENTATION.zh-CN.md#windows-启动菜单与安装)。
