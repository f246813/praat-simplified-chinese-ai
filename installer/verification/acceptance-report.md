# AIPraat-install.exe 验收记录

日期：2026-09-29。用户确认三步向导，并授权自行审阅、直接构建，测试集中在最后阶段运行。

## 发行产物

- 文件：D:\Praat-work\稳定早期版\AIPraat-install.exe
- 大小：55,911,936 字节（53.3 MiB）
- SHA-256：0D6A0723BE2750F3C2068767D6E708B8C9A79F672A3A0DFE3BCDB3F25DF63FB6
- 内嵌资源：59 项，包含 58 个程序/说明文件和一份哈希清单。
- 原 Praat.exe SHA-256 保持为 6D6020954EAB4AD4D08C4A24FD589B72FE5530AD79CCE0DD67D5580EF1818EEC。
- 原 Praat 版本：7.0.02（August 26 2026）。核心算法和原可执行文件未改动。
- Python、llama.cpp、模型及视觉投影由用户另行准备；云端 API 配置在 AI 窗口进行。

## 需求与证据

| 要求 | 验收证据 | 结果 |
|---|---|---|
| 默认 C:\AIPraat | default_exact_C_drive_folder；发行安装器实际首页显示 C:\AIPraat | 通过 |
| 已有文件夹原地复用，无嵌套目录 | 已有中文/空格目录实际安装；用户文件保留.txt 内容未变；reuse 契约 | 通过 |
| 输入目录与系统浏览器 | 手工输入中文/空格路径；实际打开 FolderBrowserDialog 并确认所选目录 | 通过 |
| 前置路径可输入与浏览 | 四项输入框及浏览按钮实际展示；Python OpenFileDialog 确认 python.exe | 通过 |
| 可选择暂不配置 | 新目录实际完成 skip 安装；Python 路径为空，默认模型/API 均为空 | 通过 |
| 配置时有效 Python 必需 | 真实 Python 3.12.14 检查；无依赖虚拟环境被拒绝，显示 numpy/PIL 缺失 | 通过 |
| llama/model/mmproj 可留空 | 三项为空时实际完成 configured 安装；非空有效/缺失/错误扩展名契约 | 通过 |
| 下一步边框和文字灰转黑 | 真实控件渲染；事件记录 ARGB -5592406（灰）→ -16777216（黑）；OutlineButton 统一绘制边框与文字 | 通过 |
| 异步旧检查不能解除禁用 | 检查编号随路径/选项变化递增；等待状态及失效编号契约 | 通过 |
| 实际安装进度 | configured 安装记录 20/47/77/88/95/100；skip 安装记录中间值及 100；按解压/复制字节计量 | 通过 |
| 安装结束显示安装已完成 | 两个实际安装场景的 UI 文本、ProgressBar.Value=100 及完成页渲染 | 通过 |
| 保留用户配置及模型预设 | API/未知字段、其他预设、模型绑定、同模型自定义参数保留契约；skip 保留原配置 | 通过 |
| 占用/路径错误明确失败并回滚 | locked_file_rolls_back_prior_changes、archive_traversal_cannot_escape 等契约 | 通过 |
| 管理员恢复保留原选择和用户目录 | redirected AppData/Desktop/UNC Programs 验证；resume 恢复 Python/模型/视觉/llama 选择契约 | 通过代码和契约验证 |
| 单文件发行与程序完整性 | 实际启动根目录发行 exe；两次安装后的 58 个应用哈希均符合清单 | 通过 |
| 快捷方式正确 | COM 读取测试开始菜单快捷方式；TargetPath/WorkingDirectory 对应安装入口和目录 | 通过 |
| 安装后 Praat/AI 可启动 | 安装后的 AIPraat.exe 启动 Praat Objects 与 Praat AI 对话窗口；进程命令行指向安装目录 | 通过 |
| 排除开发机配置与凭据 | ZIP 项目审计；未含 ai_config.json/runtime/logs/tests/cache；未含开发配置中的实际 API key | 通过 |

## 最终批量测试

- 安装器：21 项通过，0 失败，日志 installer-contracts.log。
- AI：555 项通过，耗时 80.967 秒，日志 ai-unit-tests.log。
- 启动检查使用 --no-pref-files --no-plugins，安装测试首选项/快捷方式均写入独立 fixture，未改动现有 Praat 用户配置。
- 独立审阅覆盖 11/11 个生产文件，发现的四项问题（重定向目录、恢复后重试、预设保留、异步旧检查）已修复并补充契约。

## 图像及验证范围

UI 图像位于 ui-fixture；它们由相同 WinForms 实际控件的 DrawToBitmap 产生。原生截图工具两次超时，未将这些图像冒称为系统截图。step-2-completed-settled.png 在原生进度条动画结束后捕获。

UAC 安全桌面未自动操作；权限恢复逻辑和选择保留已直接验证，实际 UAC 交互尚需在目标机器检查。未配置本地模型或云端 API 的场景验证了窗口启动，未声称完成真实模型推理。发行文件未签名，CPU/系统范围保持当前 Praat 的 Windows 10/11 x64-v3（AVX2/FMA/F16C）。
