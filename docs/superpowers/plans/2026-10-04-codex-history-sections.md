# Codex History Sections Implementation Plan

> Implement inline using superpowers:executing-plans. User has directly authorized the described change.

**Goal:** 接入稳定历史分区与独立会话分叉。

**Architecture:** 新增现代库元数据服务，移植公开 Codex 分区类型／规则；既有 ChatStore 接口和 Pi ContextMenu 承载本地渲染，不引入 Codex／Pi Agent 内核。

**Tech Stack:** Python SQLite、React、assistant-ui、pywebview/WebView2。

- [x] 保存固定上游来源与备份；先编写分区／归档／分叉宿主失败检查。
- [x] `modern_organization.py` 管理分区与事务，`modern_store.py` 添加表与元数据投影，`modern_app.py` 增加显式 RPC 和任务保护。
- [x] `src/codex/protocol/` 保留原类型；扩展 types/bridge/store 与独立测试，处理权威元数据和本地阅读状态隔离。
- [x] 会话菜单接入移动选择与分叉，新增 `HistoryOrganization.tsx` 管理分区菜单与编辑／移动对话框，侧栏添加分区、归档入口及拖放。
- [x] 更新显式 demo 适配与浏览器行为回归，覆盖恢复、移除不删除和新建归属。
- [x] 进行独立代码复核，修复发现的问题；运行相关回归、生产构建、WebView2 与来源分发检查，记录验收。
