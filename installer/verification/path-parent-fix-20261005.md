# 路径配置窗口自动关闭修复（2026-10-05）

## 原因

当前 `Praat.exe` 文件具有 Medium 完整性标签，`AIPraat-paths.exe` 继承目录的 Low 标签。
低完整性的 .NET 程序调用 `Process.GetProcessById(17980)` 时抛出 `ArgumentException`，报告该进程未运行；CIM 和窗口检查确认对应的 Praat 实际仍在运行。
`PathSettingsForm` 的 500 毫秒定时器把这个异常当作父进程已退出，因此主动关闭窗口，表现为打开后闪退。

## 修复与交付

`installer/src/PathSettingsForm.cs` 改用 `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` 和 `GetExitCodeProcess` 查询退出状态。
只有确认进程已退出或 PID 不存在时才关闭；查询失败不再被当作退出。
查询句柄在每次检查结束时释放，保留原来的父进程退出跟随行为。

已重新构建根目录 `AIPraat-paths.exe`，SHA-256：
`e1000a9f82ce15e8eabdb0070383bd2e20d9dbe730ce96a1aa721576ede25ae8`。
本次修改针对当前工作目录的路径配置程序，未重新打包安装器。
原源码和原程序备份于 `backups/path-settings-parent-20261005/`。

## 验证

- `path-parent-red.log`：使用备份源码编译的回归程序复现窗口在父进程仍存活时关闭。
- `path-parent-green.log`：2 项通过，覆盖跨完整性级别保持打开、真实父进程退出后关闭。
- `path-parent-path-regressions.log`：原有路径配置回归 15 项通过，覆盖保存、取消、配置保留、文件锁和失败回滚。测试程序以临时目录副本运行，避免 Low 测试进程的 System.Core 加载限制。
- `path-parent-live.json`：直接运行交付的根目录程序，使用隔离配置及当前 Medium Praat 的父进程 PID；有效与无效 Python 两种情况下均持续运行 8 秒，隔离配置内容不变。测试结束仅终止测试创建的配置进程。

新增回归入口：`installer/tests/Run-PathParentTests.ps1`，默认使用启动该脚本的 PowerShell 进程作为存活父进程，也可传入 `-ParentPid`。
