# Praat 结果文件参考

桥接脚本逐行写入 `ai/runtime/chat_result.tsv`，完成时写 `chat_state.txt`；执行错误写 `chat_failure.txt`。前端核对请求编号并读取结果。可见结果行主要是中文说明，API 证据层进一步解析可识别的数值、单位和来源。

`tools.neutralize_info_commands` 把 `appendInfoLine`、`writeInfoLine`、`appendInfo`、`writeInfo` 改成向结果文件追加。`printline`、`print`、`echo` 的字面内容写入文件；`printtab` 和 `clearinfo` 改成说明注释。这样输出可进入聊天结果，而不依赖 Info 窗口。

实现限制：`writeInfo` 的清空语义在结果文件中变成追加；每个请求开始前重置结果文件。改写后的内容依原命令的字面输出语义处理。独立批处理社区脚本通过 `external_script.py` 获取自己的输出，不使用 GUI 结果通道。

相关实现：`tools.py`、`chat.py`、`external_script.py`。
