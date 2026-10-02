# 主菜单 UI 移植记录

2026-09-29。以本目录的稳定早期版为基础，参考 `D:\Praat-work\praat-simplified-chinese` 当前主窗口 UI。程序已重新编译为本目录的 `Praat.exe`。

## 修改范围

只修改以下 7 个源码文件：

| 文件 | 修改内容 |
| --- | --- |
| `sys/Gui.h` | 主窗口子菜单按钮的绘制标记 |
| `sys/GuiP.h` | 主窗口操作区滚动布局状态 |
| `sys/GuiButton.cpp` | 子菜单图标、居中标题与右侧箭头 |
| `sys/GuiMenu.cpp` | 子菜单标题与按钮边界对齐 |
| `sys/machine.cpp` | Windows 启动时采用正确的 UI 尺寸 |
| `sys/motifEmulator.cpp` | 主窗口操作区滚动、子菜单容器布局与缩放 |
| `sys/praat_actions.cpp` | 将主窗口右侧操作按钮放入独立滚动区 |

移植保留了早期版的命令注册、选择匹配、按钮回调和命令保存代码。AI、VOT、声学分析、编辑器与插件实现均未从新版引入；没有复制新版的目标文件、静态库或可执行程序。

新版滚动布局只对主窗口操作区启用，其他滚动窗口继续使用早期版的原实现。移植时还修正了滚动条显隐后子菜单按钮宽度不随外框变化的问题，避免右侧箭头被裁切。这些修正同样限定在主窗口动态子菜单容器。

## 验证结果

- `make PRAAT_ARCH=x64v3 -j12`：编译、链接成功。见 `build-main-menu-ui.log`。
- 真机 UI 验证通过：100% 缩放（96 DPI）下，普通按钮与子菜单均高 28 像素，间隔为 5 像素；图标与箭头之间的标题居中，按钮填满子菜单外框。
- 增强回归通过：滚动条出现、隐藏、再次出现三次检查，10 个子菜单按钮始终与外框同宽；窗口缩小后能滚动至最后一项，放大后滚动条隐藏并归还宽度。见 `verify-main-menu-ui.log`。
- 独立审查覆盖全部 7 文件，最终未发现剩余高／中风险问题。
- SHA-256 比对覆盖修改前记录的 3535 个源码、配置和测试文件：仅上述 7 个源码变化，其余 3528 个逐字节一致，无缺失。
- 总测试脚本未全部通过：`test/fon/LongSoundEditor_GUI_.praat` 第 17 行要求打开编辑器，无法在批处理运行；跳过 GUI 测试的运行又在 `test/fon/texio.praat` 第 128 行停止，因为中文界面把错误中的 `open` 翻译成了 `打开`，与测试期待的英文不符。两项均使用修改前的原程序复现，未扩展本次范围去修改它们。对应日志为 `verify-core-tests-ui.log`、`verify-core-headless-ui.log`、`verify-core-baseline-gui-batch.log` 和 `verify-core-baseline-translation.log`。

截图：`主菜单UI验证.png`。

当前程序 SHA-256：

```text
6D6020954EAB4AD4D08C4A24FD589B72FE5530AD79CCE0DD67D5580EF1818EEC
```

## 备份与复核

修改前的程序、7 个原始源码和 `BUILD_INFO.txt` 均在：

```text
D:\Praat-work\稳定早期版-主菜单UI备份-20260929
```

该目录保存 `source-sha256-before.json`、`source-sha256-after.json`、`main-menu-ui.patch` 和增强验证脚本 `verify-scrollbar-submenu-resize.py`。增强验证调用新版目录中的外部 UI 测试，只测试本目录编译出的程序；测试代码未移入稳定早期版或参与编译。

原程序 SHA-256：

```text
01D8CB0F81B9C5ABE1C49D22AE48AB806AAB25146D45EA46DD67A86004D91A4A
```
