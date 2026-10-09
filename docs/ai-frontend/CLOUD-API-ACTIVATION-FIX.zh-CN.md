# 桌面 API 配置与请求范围

`modern_host.py` 创建桌面应用时启用 configured_cloud 策略。当前启用的 API 端点可从正常 Praat 菜单入口使用；启动和 `settings.save` 不发送模型请求，提交任务使用当前配置快照。连接测试由桌面宿主确认。

该策略适用于启用的 API 配置。本地模型配置中的远程地址仍受端点校验；直接构造应用服务默认限制云端，`--allow-cloud` 是显式覆盖参数。任务运行期间修改配置不改写其快照。

实现入口为 `modern_host.py`、`modern_app.py`、`modern_settings.py` 与端点策略。隔离桌面检查脚本 `ai/tests/verify_modern_desktop.py` 及相关模块测试可检查配置路径与请求边界；模拟端点结果不能证明真实服务商兼容性。
