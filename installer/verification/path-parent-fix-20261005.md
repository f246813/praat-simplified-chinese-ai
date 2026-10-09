# 路径窗口父进程跟随

`PathSettingsForm.cs` 用 `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` 和 `GetExitCodeProcess` 查询父进程。确认退出或 PID 不存在时关闭；查询失败不等于退出，句柄在检查后释放。

## 检查方法

存活父进程、真实退出、无效 PID 与查询受限场景。入口为 `installer/tests/Run-PathParentTests.ps1`。

检查入口见 [安装说明](../README.zh-CN.md)。检查须核对实际源码、运行资源和目标程序；本页不以旧日志、测试数量或包哈希声明当前已验收。
