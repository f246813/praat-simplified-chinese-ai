# 已归档会话分组、筛选与删除

归档设置页提供搜索、聊天来源与项目分类，按保留的分区、实际项目来源或“无项目”显示分组。正文搜索使用紧凑宿主搜索 RPC；来源分类当前为全部聊天、桌面聊天 appServer 和旧版聊天 unknown。

单条、当前显示的组内会话与全部归档会话均可删除或取消归档。全部删除覆盖全部归档会话，搜索筛选不缩小范围；确认框说明范围。批量操作串行调用宿主，失败显示已完成数量。

现代删除移除本地记录及关联数据。已归档旧会话删除仅在现代侧旁元数据中标记入口移除，旧库仍只读，原始记录保留；未归档旧会话不能执行此移除。恢复保留分区关系。

Codex `ThreadDeleteParams.ts`、`ThreadSourceKind.ts`、`ThreadListParams.ts`、`ThreadUnarchiveParams.ts` 固定于 `ab45264919aaeb8a421cc156f1a5459ef9d60b72`，原文件与来源校验信息保存在 `ai/third_party/codex/upstream/archived-settings/`。React 页面使用本项目组件，公开协议不代表复制了未公开桌面渲染源码。许可见 [来源说明](FRONTEND-SOURCES.md)。检查入口为 `ai/tests/verify_archived_settings_desktop.py` 与来源检查脚本。
