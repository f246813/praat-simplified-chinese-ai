# 取消与执行状态参考

GUI Praat 结果等待和批处理脚本使用取消标记。`chat._wait_for_result` 轮询完成标记，默认等待上限为 25 秒；取消时停止等待并用 `sendpraat.cancel_pending()` 将消息文件替换为空操作。规划循环在后续请求和动作之前检查取消。

停止等待不能终止 GUI Praat 中已运行的脚本。已投递但结果未确认时必须保留执行状态不明，不能宣称操作没有发生；现代调度器会阻止继续投递。

`external_script.run_batch` 在独立 Praat 子进程中执行，通过可取消轮询获取输出；取消或超时使用 terminate / kill / wait 收尾。该批处理进程与用户打开的 GUI Praat 不同。

现代任务服务还记录 queued、running、cancelling 等状态，取消后保留已经显示和取得的证据。窗口与任务取消的范围由对应服务管理。

相关实现：`chat.py`、`external_script.py`、`modern_app.py`、`modern_execution.py`、`cloud_runtime.py`。
