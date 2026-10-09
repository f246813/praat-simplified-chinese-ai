# Praat 菜单启动与桌面生命周期

正常入口：本项目 Praat → 导入音频 → 查看并编辑 → 前端／启动前端。`ai/start_ai_chat.py`、`run_ai_chat.py` 与 `modern_host.py` 处理启动、资产／依赖检查和桌面生命周期。

桌面启动检查资源与依赖；首次生产 bootstrap 提供私有就绪记录。重复菜单启动定位已有窗口。绑定的原生父进程关闭时桌面窗口关闭。启动错误由运行记录和可见提示报告，并清理凭据文本。

启动时提供的 Praat 对象快照来自已核对的父进程，不是实时测量。任务提交由执行器重新捕获并核对当前目标。当前启用的 API 不需要额外 CLI 参数，说明见 [API 配置](CLOUD-API-ACTIVATION-FIX.zh-CN.md)。维护启动与依赖见 [构建说明](BUILD-RESULTS.zh-CN.md)。
