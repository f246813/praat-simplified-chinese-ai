# 已归档会话入口

设置 → 已归档会话显示独立归档列表，可打开历史、取消归档及管理记录。归档操作即时保存，其他未保存设置仍使用页面离开确认。取消归档后留在设置页面，恢复原分区成员关系；旧会话恢复后仍不能续写。

列表分组、筛选和删除范围见 [归档页面](ARCHIVED-SETTINGS-COMPLETION.zh-CN.md)。实现入口为 `src/codex/ArchivedSessions.tsx`、`archived-groups.ts`、`Settings.tsx` 与宿主组织服务。检查入口为 `ai/tests/verify_archived_settings_desktop.py`。
