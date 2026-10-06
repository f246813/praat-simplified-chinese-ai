# 语音词典与声学模型管理改动

已更新工作目录中的 `Praat.exe`、`AIPraat-paths.exe` 和前端生产资源。重新打开 Praat，在语图窗口选择“对齐 → 管理语音词典与模型”即可进入。

- 左侧增加“语音词典”“声学模型”两个一级菜单，复用 AI 对话设置页的分类导航，以及原词典的列表、右键菜单、删除对话框和主题。
- 两类资源均支持多文件添加、去重、选用、当前项绿色标记、缺失文件提示和删除确认。删除只移除配置，保留磁盘文件；删除当前项后选用剩余第一项，列表为空则清除当前路径。
- 声学模型保存在 `alignment.mfa.acoustic_models`，当前选择保存在原有 `alignment.mfa.acoustic_model`，MFA 对齐直接使用该值。旧配置无需迁移。
- 路径配置界面移除 MFA 发音词典、MFA 声学模型两项。保存其他路径时保留这两项配置，也保留资源管理窗口同时写入的新值。
- 原生菜单、窗口标题和相关错误提示改为“管理语音词典与模型”。此前路径配置的父进程误判闪退修复继续保留。

## 验证

| 检查 | 结果 |
| --- | --- |
| Python 词典与模型、MFA 调用、配置写锁专项测试 | 19 项通过 |
| 前端全量 Vitest | 19 个文件，110 项通过 |
| 路径配置与安装器 C# 测试 | [12 项通过](dictionary-models-path-green.log) |
| 路径配置父进程回归 | [2 项通过](dictionary-models-path-parent.log)：存活父进程不会误关闭，实际退出后关闭 |
| Edge 浏览器布局与菜单 | [1 项通过](dictionary-models-browser.log)，覆盖 780×480 和 620×360 两种尺寸 |
| 真实 WebView2 交互 | [10 项通过](dictionary-models-webview.log)，覆盖词典、模型、选择器、选用、删除和配置保留 |
| 原生 Praat 菜单启动 | [4 项通过](dictionary-models-menu.log)，覆盖中文菜单、启动、父进程退出联动和配置不变 |
| 前端与原生程序构建 | [前端成功](dictionary-models-frontend-build.log)、[原生成功](dictionary-models-native-build.log) |
| Python 全量回归 | [1006 项，1005 项通过、1 项失败](dictionary-models-python-suite.log)；失败项单独[复跑通过](dictionary-models-redirect-recheck.log) |

界面截图：[正常尺寸](dictionary-models-780.png)、[最小尺寸](dictionary-models-620.png)。已检查两种尺寸下侧栏、当前项和底部添加按钮，无横向溢出。

测试使用临时配置与资源文件；未修改用户的实际词典和模型配置。

全量回归中的 `test_modern_model_request_never_follows_redirect` 首次运行收到 Windows 本地连接中断（WinError 10053），未收到预期 HTTP 302；在不修改相关代码的情况下单独复跑通过。本次未改动该网络请求实现，也未重复运行整套测试。

## 交付与备份

源代码与旧程序已备份到 `backups/dictionary-models-20261005-233211/`。本次更新当前目录中的应用，未重新打包安装器。

| 文件 | SHA-256 |
| --- | --- |
| `Praat.exe` | `62077566FDDA130E89F3C453CDC4D20686C47DAF73F17EEA8DE5E729698509CB` |
| `AIPraat-paths.exe` | `D4AC3B424A2F0CD859F3C506FAC1965987EC7B33810B37EADA10B6A98E5A4ED3` |

已核对最终 `Praat.exe` 与通过菜单检查的构建产物哈希一致，并在复制后恢复该文件的 Medium 完整性级别。
