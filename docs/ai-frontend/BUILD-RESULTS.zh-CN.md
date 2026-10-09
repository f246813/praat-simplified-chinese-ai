# 现代前端构建与检查

## 启动

正常入口为本项目 Praat → 导入音频 → 查看并编辑 → 前端／启动前端。维护者可运行 `python ai/run_ai_chat.py`，或用 `--legacy` 打开旧 Tk 界面。Windows 需要 WebView2 Runtime 和 `ai/requirements.txt` 中的 Python／.NET 依赖。运行已构建的前端无需 Node。

宿主参数包括 `--config`、`--data-dir` 与 `--allow-cloud`，具体解析见 `modern_host.py`。默认现代数据目录为 `ai/runtime/modern`。桌面启用 API 的行为见 [API 配置](CLOUD-API-ACTIVATION-FIX.zh-CN.md)。

## 构建

在 `ai/frontend` 目录执行：

```powershell
npm ci
npm run build
```

`prebuild` 复制离线 Mermaid 资产、生成依赖通知并分发来源材料；`build` 执行 TypeScript 与 Vite。产物位于 `ai/frontend/dist`。关闭并从 Praat 菜单重开前端以加载资源。当前 Vite 配置采用 `treeshake: false`，构建包体较大，详见 `vite.config.ts`。工具临时目录权限问题应在当前构建进程中处理，不要求改变系统或 Praat 权限。

## 可复现检查

前端命令为 `npm test` 与 `npm run test:ui`；后者通过 Playwright 运行浏览器夹具。`PI_PLAYWRIGHT_CHANNEL=msedge` 可选择安装的 Edge。Python 模块入口包括 `ai/tests/test_modern_app.py`。桌面检查入口为 `ai/tests/verify_modern_desktop.py`，使用临时配置、隔离数据库和 MockExecutor。

专项入口分列在本目录模块文档中。检查时使用隔离数据，按脚本参数指定输出目录。`verification/` 中的 JSON 是保存的检查产物；实际结果应以针对当前代码运行的输出为准，不能将固定计数视为持续通过声明。

浏览器夹具不等于 WebView2，模拟执行器不证明真实模型或 Praat 测量效果。DOM 合成事件不等于所有实体输入法的人工操作。源码与本地构建产物也不证明安装包已包含当前资源。
