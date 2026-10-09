# 会话菜单与持久置顶

会话省略号及右键打开共用 Pi ContextMenu，提供当前宿主支持的重命名、置顶／取消置顶、分区、归档、分叉和删除等动作。菜单处理键盘导航、边缘定位、外部关闭和焦点恢复。

现代置顶由 `sessions.pin` 返回权威状态并落盘；置顶与自定义分区互斥，取消置顶回到普通历史。活动任务禁止会话删除，删除需要确认。旧记录不能重命名／置顶／续写，可通过现代侧旁元数据组织、归档及移除归档入口。

ContextMenu 与滚动显示逻辑来自 Pi 固定提交 `0d47d26769ecbeca1c3ab56fa83b58a91de8190e`；许可及重建材料见 [来源说明](FRONTEND-SOURCES.md)。当前侧栏样式见 [滚动条](HISTORY-SCROLLBAR-RESULTS.zh-CN.md)，持久组织检查入口为 `ai/tests/verify_history_organization_desktop.py`。
