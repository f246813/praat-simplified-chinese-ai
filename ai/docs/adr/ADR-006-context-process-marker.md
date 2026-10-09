# 对象上下文与进程身份参考

原生 `writeChatContext()` 在对象快照末尾写 `# praat-pid=<进程号>`。`chat.context_pid` 读取该标记，`parse_object_context` 忽略非对象行。

`refresh_object_context` 根据文件存在性、进程标记、`force` 与 `assume_fresh` 判定是否需要发送空脚本刷新。有效标记属于正在运行的 Praat 时可直接使用；文件缺失、标记不匹配或没有标记时刷新。对象创建、删除、选中变化和消息执行后，原生侧更新上下文。

快照文件由 Praat 实例共享。仅有 PID 标记并不能隔离多个实例；现代执行适配还核对所绑定进程的身份。多实例覆盖快照属于当前桥接限制，应核对实际目标，不能据此承诺始终路由到用户预期的窗口。

相关实现：`sys/PraatAiControl.cpp`、`chat.py`、`tools.py`、`modern_execution.py`、`process.py`。
