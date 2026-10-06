# 会话历史操作验收 — 2026-10-06

已按用户确认的“今天、昨天等最末级时间分组”实现，并完成前端生产构建；重新打开 AI 对话窗口即可使用。

## 行为

- 只读会话可通过现有会话菜单、多选删除和已归档会话页面删除。原始旧记录数据库保持只读，通过本应用的元数据持久化删除状态，刷新或重启后不会重新出现。
- 右键时间分组标题，显示“删除分区及其内容 / 仅删除分区 / 全部归档”。沿用已有右键菜单、图标、危险操作样式及确认对话框；支持菜单键或 Shift+F10。
- “仅删除分区”保留其中会话及消息，并将会话直接显示在上一级，刷新与重启后仍生效。后续新会话仍按时间正常分组。
- 删除或归档仅作用于该时间分组内的会话，不影响其他来源或自定义分区。运行中的会话沿用已有删除与归档限制。
- 分组操作先验证所有成员；后端在事务内完成删除或分组解除，避免成员不存在时发生部分修改。

## 验证

- Python modern 后端测试：94 项通过，见 `history-group-actions-python-full.log`。
- 浏览器回归：22 项通过，涵盖新增分组菜单、只读删除、组织管理、多选、归档恢复、空会话布局及搜索，见 `history-group-actions-browser-regression.log`。
- 实际 WebView2 桌面窗口使用生产资源验收：5 项通过，覆盖解除分组、全部归档、恢复、只读删除和分组删除；确认原始旧数据库字节不变，且没有执行 Praat 或模型调用，见 `history-group-actions-webview.json`。
- TypeScript 检查与 Vite 生产构建通过，见 `history-group-actions-build.log`。
- Vitest 全量：114 项通过、1 项既有失败。失败为 `tests/speech-dictionaries.test.tsx:95` 仍期待“管理语音词典与模型”，而现有界面标题为“管理语音词典”；与本次历史操作变更无关，见 `history-group-actions-vitest.log`。

生产主资源：`ai/frontend/dist/assets/index-BNwiNTWA.js`。

修改前备份：`backups/history-group-actions-20261006/`。生产源代码差异：`installer/verification/history-group-actions.diff`。

所有验证均使用隔离测试数据，未删除或归档用户的实际会话。
