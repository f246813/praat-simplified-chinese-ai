# Praat 原生插件（plugin_praat_ai）

这个文件夹是一个 **Praat 原生插件**：装进 Praat 的 preferences 目录后，Praat
启动时会自己扫到它（`sys/praat.cpp` 里扫 `%APPDATA%\Praat\plugin_*`），菜单里就
多出「AI 声学测量」和「启动 AI 对话窗口」。**不需要重新编译 Praat.exe**，所以
没装我们这个 fork 的人也能用这条分发路径。

做法参考 [chengafni/praat](https://github.com/chengafni/praat)：每个插件是
`plugin_*/setup.praat` + 若干 `.praat` 脚本，菜单用 `Add menu command` /
`Add action command` 注册。和他们的差别：脚本是**从参数表生成的**（见下），而不是
在 Praat 里拼字符串再动态求值。

## 装 / 卸

```powershell
# 装（仓库根目录，默认用仓库旁边 venv-ai 里的 Python）
powershell -ExecutionPolicy Bypass -File ai\plugin\install.ps1

# 指定 Python（例如没建 venv 时）
powershell -ExecutionPolicy Bypass -File ai\plugin\install.ps1 -Python C:\Python312\pythonw.exe
```

装完目录是 `%APPDATA%\Praat\plugin_praat_ai\`。**卸载就是删掉这个目录**；Praat
下次启动就没有这两条菜单了。

手工安装也行：把 `ai/plugin/praat_ai/` 整个复制成
`%APPDATA%\Praat\plugin_praat_ai\`，再按 `praatAiChat.praat.in` 的样子手写一份
`praatAiChat.praat`（里面是本机的 Python 和项目路径）。

## 装完有什么

| 在哪 | 菜单 | 作用 |
| --- | --- | --- |
| 对象列表（选中一个 Sound） | 右侧动态菜单底部「AI 声学测量...」 | 弹出对话框，可填 `all` 或参数名（`mean_pitch` 等）+ 时间范围，结果写进 Table「AI 测量结果」 |
| 声音 / TextGrid 编辑器 | `Analyses` →「AI 声学测量（圈选段）...」 | 对**编辑器里圈选的那一段**测全部参数 |
| 对象列表窗口 | `Praat` →「启动 AI 对话窗口」 | 启动 Python 前端（自然语言操作 Praat） |

结果表每行一个参数：`参数 / 说明 / 起点 / 终点 / 数值 / 单位`。算不出来的（例如
整段是无声）数值留空、单位里写「（这一段没法算）」，不会写个 0 骗人，也不会弹
英文错误框。

## 参数从哪来（和前端同源）

`praatAiMeasure.praat` 由 `ai/tools/build_plugin.py` 从 **`ai/praat_ai/measures.tsv`**
生成（对话前端用的也是这张表），所以：

```powershell
python ai\tools\build_plugin.py            # 改了 measures.tsv 之后重新生成
python ai\tools\build_plugin.py --check    # 只检查生成物和表是否一致（测试里用）
```

表里 `@@ dedicated` 的那些参数（H/L、谱强调、Hammarberg、峰值/有效值、强度斜率、
基频峰值延迟）是**多步脚本**，只在对话前端里实现，插件里不重复写一遍。

## 已知边界（都是实测的）

- 插件脚本在**对象列表**上工作：批处理（`Praat.exe --run`）和菜单点一下都行。
  编辑器那一条（`praatAiMeasureEditor.praat`）要读圈选范围，只能在真的开着编辑器
  时用——批处理里 Praat 会直接说 `Cannot edit a Sound from batch`，所以这一段
  只能在真机上手点验证（见下）。
- 插件和对话前端**共用一套命令字面量和默认设置**，所以同一个声音两边结果一致
  （`ai/tests/verify_plugin.py` 用 220 Hz 纯音核对：平均基频 220 Hz、RMS 0.3536 Pa、
  F1 191.9 Hz、CPPS 20.62 dB）。
- 插件只对 **Sound** 生效（`LongSound` 没有 `To Pitch` 这些命令，菜单里没给它挂）。

## 验证

```powershell
python ai\tests\verify_plugin.py      # 4/4：菜单注册 + 33 个参数 + 单参数带范围 + 无声段
python -m unittest discover -s ai\tests   # 里面 test_plugin_build.py 守着生成物和表一致
```
