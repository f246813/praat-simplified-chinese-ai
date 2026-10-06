# 已归档会话迁移至设置 · 2026-10-04

这是首次迁移记录；用户提供当前截图后的删除、分组、顶部搜索和分类补齐，见 [后续验收](ARCHIVED-SETTINGS-COMPLETION.zh-CN.md)。

入口现为 **设置 → 已归档会话**，原侧栏的“已归档”按钮已移除。

按 Codex 公开归档页布局显示独立列表：左侧标题、日期和项目来源，右侧中性的“取消归档”按钮。点击标题可查看历史；取消归档后留在设置页面，会话回到原分区。空列表显示“暂无已归档会话”。归档操作即时保存，无须另点“保存设置”；存在其他未保存的设置时仍可保存，并且离开页面的原确认逻辑保留。

旧会话恢复后仍只读。恢复失败保留列表并提供错误提示，可以重试；恢复中的按钮防止重复请求，键盘焦点接续到下一条记录。原分区的批量恢复功能保留在分区菜单中。侧栏搜索、预览、分组、排序及滑条尺寸不变。

## 复用来源和边界

- [Codex 官方设置说明](https://developers.openai.com/codex/app/settings/)：归档页显示日期和项目，通过 Unarchive 恢复。
- [Codex 公开归档页截图](https://github.com/openai/codex/issues/13018)：边框列表、标题和元信息、右侧 Unarchive。
- 固定开源提交 `ab45264919aaeb8a421cc156f1a5459ef9d60b72` 的 `ThreadUnarchiveParams.ts` 原样搬入并使用；原文件、Git blob 和 SHA-256 保存在 `ai/third_party/codex/upstream/archived-settings/`。
- 项目继续使用现有 Settings、Pi 项目名称与路径处理、会话加载和归档 RPC。没有更换存储，没有新增依赖、远程连接服务或 Agent 内核。

Codex 公开仓库未提供这页的桌面 React 渲染源码。界面是依据上述公开截图和文档，对现有组件的适配；不宣称复制了未公开的桌面源码。Apache/LGPL 来源说明和完整前端构建输入已经同步到生产分发目录。

## 本次验证

- TypeScript 编译、生产构建通过。
- 全部 **98 项单元测试**通过，新增恢复失败重试和请求/焦点测试。
- **11 项 Edge 浏览器检查**通过：3 项归档设置、3 项分区交互、4 项侧栏菜单及 1 项原设置页面回归。窄窗口检查验证无横向溢出；[650 像素窗口截图](verification/archived-settings-narrow.png)使用明确标注的浏览器测试夹具。
- 两组真实 **pywebview / WebView2** 生产资源验收通过：独立 SQLite 数据中验证恢复后保持原分区、消息、草稿、阅读位置，重载仍保留结果；原分区创建、分叉、批量归档/恢复和移除也通过。隐藏窗口使用 DOM 事件，实际鼠标与键盘行为由浏览器测试覆盖。未使用真实用户数据、模型或 Praat 执行。
- 生产来源检查通过：原样协议与 SHA-256 一致，当前前端构建输入和修改源码完整分发，14px 滑条通道及 68px 最短长度对应的样式文件未改动。

验收结果：`verification/archived-settings-desktop-result.json`、`verification/archived-settings-source-result.json`、`verification/codex-history-desktop-result.json`。

修改前备份：`.aipraat-backups/archived-settings-20261004/before/`。生产前端已重新构建到 `ai/frontend/dist/`；重新打开前端即可加载。
