# 侧栏组织与排序菜单

历史工具栏省略号提供“整理侧边栏”与“聊天排序方式”两个侧向子菜单。组织模式为按项目、按远程连接、在一个列表中；排序为最近更新、最早创建、按名称、最近创建。偏好由宿主持久化；置顶及自定义分区保留成员关系。

项目与连接分组使用已记录的来源元数据。新会话记录本地工作目录；分叉继承来源。当前宿主只有本地连接，已保存远程元数据可独立分组；模型 API 地址不作为连接身份，界面没有 SSH 管理或远程执行服务。

Codex `ThreadSortKey.ts`、`SortDirection.ts`、`ThreadListParams.ts` 固定于 `ab45264919aaeb8a421cc156f1a5459ef9d60b72`；路径处理来源为 Pi 固定提交，子菜单使用 Radix Dropdown Menu 2.1.24。复制协议与本项目界面的边界见 [来源说明](FRONTEND-SOURCES.md)。检查入口为 `ai/tests/verify_sidebar_options_desktop.py` 与 `verify_sidebar_options_source.py`。
