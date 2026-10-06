# 按当前 Codex 截图补齐归档页 · 2026-10-04

参考用户提供的《批注 2026-10-04 204054.png》，补齐上次迁移遗漏的功能。

- 标题“已归档的聊天”右侧提供“全部删除”；每条会话右侧提供删除图标和“取消归档”。删除需确认，取消不改变记录。
- 按保留的原分区分组；没有分区时使用真实项目来源；没有分区或项目来源的会话归入“无项目”。分组标题、数量、省略号菜单和同组行分隔线对应截图。分组菜单可取消归档或删除当前显示的组内会话，恢复保留原成员关系。
- 顶部提供搜索、聊天分类和项目分类。搜索覆盖标题和正文，继续调用既有 Codex 搜索适配器的单次紧凑结果 RPC，沿用 100ms 防抖、过期响应检查和稳定历史修订依赖；搜索框使用现有 Pi 的普通文本/原生输入法和无绿色焦点边框规则。
- 项目分类包含所有原分区、项目及“无项目”。聊天分类按公开来源类型模式接入本项目实际来源：全部聊天、桌面聊天（appServer）、旧版聊天（unknown）。没有增加本项目不存在的云端、CLI 或 Agent 会话来源。
- 全部删除针对全部已归档会话，确认框明确提示筛选不会缩小其范围。整组删除针对当前显示的组内会话。批量操作串行复用现有宿主方法，失败时报告已完成数量，可重试剩余记录。

## 复用及保留边界

公开仓库已有 [`ThreadDeleteParams.ts`](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/schema/typescript/v2/ThreadDeleteParams.ts)、[`ThreadListParams.ts`](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/schema/typescript/v2/ThreadListParams.ts) 的来源分类、归档、项目和分区筛选协议。新增原样搬入 `ThreadDeleteParams.ts`、`ThreadSourceKind.ts`、`ThreadListParams.ts`，与原 `ThreadUnarchiveParams.ts` 一起使用，固定于提交 `ab45264919aaeb8a421cc156f1a5459ef9d60b72`。原文件、Git blob 和 SHA-256 均保存在 `ai/third_party/codex/upstream/archived-settings/`。

Codex 公共仓库没有这页的桌面 React 界面及分类菜单组件。界面依据用户截图适配，菜单直接复用已有 Pi ContextMenu 与已安装的 Radix RadioGroup，搜索继续复用已有 Codex 适配器，删除／恢复继续使用既有 ChatStore 和宿主接口。来源说明明确区分原样协议与本项目适配代码。

现代会话沿用已有删除机制，移除本地记录及关联消息、证据。只读旧版会话仅从本应用中移除，原始旧版记录保留；现代侧旁记录增加删除标记，启动及搜索均排除这些已移除入口。只有已归档旧记录可执行此移除，旧库仍以只读连接打开。确认框说明这一区别。未改变未归档旧记录的编辑、执行或删除限制。

assistant-ui、pywebview/WebView2 及 Pi 交互组件继续使用，没有添加新依赖或 Agent 内核。侧栏滑条规则保持原样。删除未选中会话时不再重复加载当前完整历史，避免批量删除造成无关会话刷新。

## 本次验收

- TypeScript 编译及生产构建通过；完整修改源码、原始协议、Apache/LGPL 说明均随生产资源分发。
- **100 项前端单元测试**、**48 项后端测试**通过。包括旧库字节未改变、移除后重启及搜索不可见、旧数据库新增字段兼容、现代删除级联和原分区保留。
- **9 项 Edge 浏览器验收**通过：5 项归档页（正文搜索、来源／项目筛选、单条／整组／全部删除与取消、恢复、未保存设置保护、窄窗口）、3 项原分区交互、1 项原设置回归。
- 两组生产 **WebView2** 验收通过：归档设置页直接使用真实宿主／独立 SQLite 验证正文搜索仅一个紧凑请求、三种删除范围及重载持久化；分区创建、分叉、批量归档／恢复及移除继续通过。隐藏窗口用 DOM 事件，浏览器验收覆盖实际鼠标与键盘；均未使用用户真实记录、模型或 Praat 执行。
- 四份归档协议逐一与固定 Git blob、SHA-256 和生产分发文件比对一致；完整当前前端构建输入与修改宿主源码分发检查通过。

预览：[桌面排版](verification/archived-settings-complete-desktop.png)、[650 像素窄窗口](verification/archived-settings-complete-narrow.png)。预览使用明确标注的浏览器测试夹具。

真实宿主验收：`verification/archived-settings-desktop-result.json`、`verification/codex-history-desktop-result.json`。协议来源验收：`verification/archived-settings-source-result.json`。

修改前备份：`.aipraat-backups/archived-settings-complete-20261004/before/`。生产资源已构建到 `ai/frontend/dist/`，重新打开前端即可加载。
