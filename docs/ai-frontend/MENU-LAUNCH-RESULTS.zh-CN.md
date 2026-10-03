# 正常 Praat 菜单启动现代前端：修复与真实验收

## 用户启动方式

1. 双击本项目 `Praat.exe`。不会自动打开聊天窗口。
2. 用“打开 → 从文件读取…”导入音频，选中声音并点击“查看并编辑”。
3. 在声音编辑器点击现有“前端 → 启动前端”。打开的是 assistant-ui／React＋WebView2 工作台。
4. 再点同一菜单会恢复／置前已有窗口，不新建聊天窗口。关闭启动它的 Praat 后，工作台随之退出。

启动已构建界面无需 PowerShell 或 Node。不添加插件／外部快捷方式，不自动回退旧 Tk，不在启动时请求模型。

## 原因与最小修复

- 本机 Praat 的 Python 路径原指向 WindowsApps Python Manager，实际解释器为 Python 3.14.8，缺少 `webview` 和 `clr`。本机具备完整宿主依赖的是 Python 3.12.14。
- 已备份用户偏好，仅修改 `Python.executablePath` 为 `C:\Users\f2468\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`。这是本机路径；迁移到另一机器必须在 Praat 路径配置选择装有依赖的解释器，不照搬缓存路径。
- 已发布的原生菜单先调用 `run_ai_control.py` 的 `start/quiet` 握手，再读 `status.json`，最后发布真实对象上下文／父 PID并调用聊天启动器。
- 新 `desktop_launch.py` **仅拦截无 CLI 参数的原生 start/quiet 握手**：检查桌面依赖与离线资产，直接进入现代桌面启动，不准备旧模型服务。显式 `run_ai_control.py start` 及其他旧控制命令保持原行为。
- 握手的 `frontend_running` 是既有原生兼容字段，表示“桌面可启动”，不冒称模型已加载；同时写 `frontend_start_phase=ready-to-launch`、`model_service_started=false`。真正 React 连接后才写 `frontend-ready.json`，记录实际执行器类型。
- 启动器采用短启动锁、实际窗口标题／PID身份检查，兼容初始化中的窗口和陈旧／被复用 PID。宿主监视明确父 PID／创建身份；没有父绑定时不猜测别的 Praat。
- `bootstrap.host.praat` 是验证父进程身份及原生 PID标记后的只读启动快照，不是测量结果，也不是后续任务目标。任务仍由原有执行器重新捕获、串行验证。
- 启动失败保持可见：菜单预检通过原生 Message／Info 展示；脱离菜单的启动错误通过 Windows MessageBox 展示，pythonw 没有 stderr 也不静默。运行记录只写脱敏错误，不写配置全文或 traceback。

本轮无需编译或替换 `Praat.exe`，没有修改原生代码、文件／目录安全权限。程序 SHA256 仍为 `777b54ff1ed57484be27aba83f79c22c62b87c3ce8406b2a4f2b0f3b8e7ab37f`。

## 批准合同逐项验收

合同：[通过 Praat 正常菜单启动现代前端](../../.pi/goal/通过-praat-正常菜单启动现代前端-20261003-2243.md)。以下均为本轮真实菜单结果，不以此前 mock／普通浏览器检查替代。

| 标准 | 结果 | 观察证据 |
| --- | --- | --- |
| 可见真实 Praat 导入隔离音频，实际菜单加载现代页面并连接生产宿主 | **met** | 无参数启动本项目程序；通过原生文件选择框导入 1秒／16kHz／220Hz 合成 WAV，点击“查看并编辑”，发送实际菜单项的 `WM_COMMAND`（原生菜单回调，与鼠标选择同一条路径）。普通启动 3.70秒、React观察轮 3.72秒；实际 `ModernExecutor`，不是 MockExecutor／旧 Tk／demo。 |
| 能读取实例和对象上下文；启动不测量、改音频、重放历史 | **met** | 真实 React 唯一 RPC 返回 Praat PID `24288`、对象 `1 / Sound / Sound menu-isolated-synthetic / selected=true`；`taskCount=0`、`cloudAllowed=false`、无 demo banner。源 WAV、配置、旧 SQLite 和现代 SQLite 启动前后 SHA256 完全相同；重复菜单对象快照不变。没有提交模型或工具任务。 |
| 不持续阻塞；再次菜单复用并显示已有窗口 | **met** | 对象窗口和编辑器在初次／重复点击后 `WM_NULL` 1.5秒限时探针全部立即响应（记录按毫秒舍入为0.000秒）。先最小化工作台再点击菜单：同 PID `12252`、仅一个窗口、恢复并成为前台窗口。退出确认后父／聊天进程均退出。 |
| 诊断、修复及可见脱敏失败提示 | **met** | 在已备份情况下临时恢复旧解释器，仅改该字段，从真实菜单复现：可见 Message 提示退出码1，Praat Info 明确显示“当前 Python 缺少依赖：webview, clr”；`status.json` 同样记录原因，不包含两节现有 API Key。未产生聊天窗口，Praat 响应正常。finally 已恢复可用 Python，随后两次正常菜单验收通过。 |
| 针对性检查与交接更新 | **met** | Python 语法检查通过；启动器14、宿主7、应用19、窗口复用3，共 **43项**通过；TypeScript `tsc --noEmit`通过。交付可复用真实菜单脚本、脱敏结果、宿主契约及交接入口。没有重复无关全量测试。 |

正式记录：[普通启动](verification/menu-normal-result.json)、[真实 React／RPC](verification/menu-react-result.json)、[真实缺依赖失败](verification/menu-failure-result.json)。记录只包含进程、合成对象、哈希和诊断，不复制用户消息、配置或 Key。测试 UI 截图／完整观察仅保留于会话 scratch，不作为永久用户数据副本。

## 回退与维护

- 原启动文件、宿主文件和用户 `Preferences.txt` 备份：[backups/modern-menu-launch-20261003](../../backups/modern-menu-launch-20261003/manifest.json)。manifest 还记录原程序、配置和旧库哈希；没有复制或清空用户数据库。
- 回退前关闭相关窗口，确认备份后没有新的用户代码改动；按 manifest 恢复本轮启动器／宿主文件。Python偏好只恢复备份中 `Python.executablePath` 的原值，**不要整份覆盖之后的偏好**。旧路径缺桌面依赖，所以恢复该路径不代表现代前端可运行。
- `ai/runtime/chat-process.json`、`frontend-ready.json` 是 PID身份／就绪诊断，正常退出仅清理本进程拥有的记录；异常终止留下的旧记录不是就绪证据。
- `frontend-startup-error.json` 和 `status.json` 用于启动诊断；旧错误记录可能保留，应结合当前进程／就绪状态判断，不因存在旧错误就认为当前启动失败。
- 维护者可运行 `python ai/tests/verify_modern_menu.py`；需设置当前会话 `PI_SCRATCH_DIR`，会拒绝干扰已有 Praat／聊天窗口。`--observe-react --node <node.exe>` 只在验收子进程启用 CDP并读取真实页面，正常入口不依赖它。测试工具用命令执行不代表用户必须运行命令。

## 仍未验证／未做

本轮没有真实模型请求或声学分析、安装包更新、发布或推送；菜单默认没有远程请求授权。启动上下文快照不替代工具执行验收。跨多 Praat 实例切换、其他旧服务菜单及其他机器部署不属于这次验证。无当前合同阻塞。
