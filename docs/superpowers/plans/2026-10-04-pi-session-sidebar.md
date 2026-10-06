# PI 会话侧栏实施计划

**Goal:** 迁入会话侧栏交互并解决原生滑块难选中。

**Architecture:** 提取固定提交的独立渲染模块，保留完整原文与 LGPL 来源；独立侧栏组件消费现有 ChatStore。宿主仅增加允许保存的排序偏好。

**Spec:** `docs/superpowers/specs/2026-10-04-pi-session-sidebar.md`

- [x] 先增加分组、预览、多选和宽滚动条的行为检查，确认当前界面未提供这些交互。
- [x] 保存原始侧栏和依赖；迁入分组与悬停模块、完整会话列表组件与样式，接入 App。
- [x] 保存并验证排序偏好，更新来源与变更说明。
- [x] 运行前端／相关宿主回归与生产构建，检查滚动条真实指针命中、长度变化、菜单及只读／运行保护。
- [x] 在真实 WebView2 复核最新生产资源，保存截图与验收记录。

验收见 `docs/ai-frontend/PI-SESSION-SIDEBAR-RESULTS.zh-CN.md`。
