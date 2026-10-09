# 测试记录

这里保存仓库中的测试运行输出、验收采样与截图。记录反映生成时对应的源码、依赖、环境和夹具，不代表当前版本的测试状态；需要确认当前状态时，应重新运行对应验证脚本。

- `project/`：仓库根目录的构建与验证日志、结果 JSON。
- `frontend/`：React 前端与桌面交互验证结果；`playwright-results/` 保存 Playwright 结果元数据。
- `installer/`：安装器、Python 宿主、Praat 集成的日志、结果 JSON、截图、差异和退出码。

可执行测试和验证脚本仍在 `ai/tests/`、`installer/tests/` 与 `installer/verification/`。验证输入、隔离夹具和构建中间件仍按脚本需要放在其源码目录。脚本生成的日志、结果 JSON 和截图写入本目录相应子目录。
