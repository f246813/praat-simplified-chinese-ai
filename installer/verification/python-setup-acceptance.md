# Python 依赖配置

`PythonSetup.cs`、`PythonSetupGuide.cs` 与嵌入 PowerShell 脚本处理所选 Python 的依赖配置和复检。Tk 是解释器组件；Conda 与注册的官方 Python 使用不同修复入口。现代宿主依赖以 `ai/requirements.txt` 为准。

## 检查方法

路径变化与异步旧结果、依赖已有/缺失、解释器架构、注册目录歧义、取消和复检。真实安装需要网络、环境管理器及相应权限。

检查入口见 [安装说明](../README.zh-CN.md)。检查须核对实际源码、运行资源和目标程序；本页不以旧日志、测试数量或包哈希声明当前已验收。
