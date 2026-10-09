# 历史分区、归档与分叉

`modern_organization.py` 管理稳定分区 ID、名称／外观、成员位置和内建置顶分区。删除自定义分区只移除成员关系；对话内容保留。移动通过显式 nullable 目标进行；恢复归档保留原成员关系。

`sessions.fork` 在任务锁下复制当前历史、摘要与证据，生成独立消息／活动 ID；清空草稿与阅读位置，重置置顶和归档，记录来源。活动片段标记中断，不启动任务或重放执行。旧记录作为只读来源可创建现代可写分叉。

会话／分区归档拒绝活动任务；已归档会话仍可查看、移动与分叉，恢复后才能提交。旧库组织元数据保存在现代库。当前批量组动作包括删除、脱离时间组与归档，接口见 [宿主契约](HOST-CONTRACT.md)。

Codex 协议与存储语义固定来源为 `ab45264919aaeb8a421cc156f1a5459ef9d60b72`，公开协议与本项目渲染／宿主适配见 [来源说明](FRONTEND-SOURCES.md)。检查入口为 `ai/tests/verify_history_organization_desktop.py`、`verify_history_group_actions_desktop.py` 与 `verify_history_source.py`。
