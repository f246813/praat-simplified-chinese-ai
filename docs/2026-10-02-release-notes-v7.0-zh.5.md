# v7.0-zh.5：Praat 指令送不出去时的处理修复

- 时间：2026-10-02（北京时间）
- 触发：用户反馈「测量选中这段的 vot」没有完成。
- 这一版包含**重新打包的安装包**；旧的 v7.0-zh.4 及其安装包原样保留、未被改动。

## 下载

| 文件 | 说明 |
| --- | --- |
| `AIPraat-install.exe`（55,732,224 字节） | 完整安装包，已包含本次修复。SHA-256 `ed2e8abc91ada789983e22fc7c0979df2be28cf8c00fcb70c7cd4dc6b88fbdb0` |
| `AIPraat-frontend-fix-20261002.zip`（100,101 字节） | 只给**从源码目录运行**的人：改动的 Python、新增测试与验证脚本、打包/发布脚本、本轮验证记录（不含配置与录音） |


## 这次修了什么

1. **一次「没送出去」不再锁死整轮。**
   脚本没有送进 Praat（消息文件写不进去、找不到窗口…）以前会被当成「执行状态不明」，同一轮后面的所有操作都被拒；现在它是**确定的失败**：允许一次有区别的修正，后面的工具照常执行。
2. **报告会说真话。**
   失败原因（权限、路径、脚本报错、超时）会进报告上下文，报告必须如实交代原因和用户能照做的下一步；**不允许**把投递或环境故障写成「模型能力不足」。同时明确：`audio_input=false` 只表示本轮没有把音频交给模型，**Praat 的测量不依赖它**，不能据此说测不了。
3. **不再为用不上的材料花一次投递。**
   当前模型没有直接音频能力时（例如 `qwen3.7-flash`），以前仍会先导一份「给音频分析用」的片段快照；那份材料永远不会被用到，却要占一次投递——故障现场正是它先把整轮撞停的。现在只在音频能力开启时才导。
4. **真的不确定时，行为不变。**
   脚本交出去了但没等到完成标记（超时、取消、完成标记对不上）：仍然停止继续投递、用已有证据收尾，并把超时原文写进结果。
5. **顺带修掉一个打包问题。**
   `installer/build.ps1` 以前是 UTF-8 **无 BOM**，Windows PowerShell 5.1 会把它当 ANSI 读，于是安装包内「使用说明」的文件名会变成乱码（`AIPraat-浣跨敤璇存槑.md`）。现在该脚本带 BOM，直接 `powershell -File installer\build.ps1` 打出来的包中文名正常。

## 为什么会出问题（供参考）

- 投递函数只返回「成功/失败」，分不出「根本没交给 Praat」和「交给 Praat 但没等到结果」，而这两种情况该怎么处理完全相反（前者可以改参数重试，后者必须停下来核实）。
- 报告上下文里只放了最后一条失败原因，真正的原因（例如 `Message.txt` 权限不足）留在调用记录里没进报告，模型只能自己猜一个理由——现场它就猜成了「模型不支持音频」。
- 另外：如果 Praat 是从带 **Low 完整性标签**的目录启动的，它写不了 `%APPDATA%\Praat\Message.txt`，会**收不到任何指令**。安装版装到普通目录不会有这个问题；从源码目录跑时若遇到，可只对该可执行文件处理：
  `icacls "…\Praat.exe" /setintegritylevel Medium`（回退：把 `Medium` 换成 `Low`）。

## 这一版的校验

- 安装包：`AIPraat-install.exe`，**55,732,224 字节**，SHA-256 `ed2e8abc91ada789983e22fc7c0979df2be28cf8c00fcb70c7cd4dc6b88fbdb0`。
- 包内校验（`installer/verification/verify-delivery-package.py`）：内嵌载荷与构建产物逐字节一致；**73 项内容哈希与当前源码逐项一致**；载荷 74 个文件；不含用户配置、runtime、logs、tests、`__pycache__`、音频或数据库；`Praat.exe` 与重打包前一致（本轮没有重编原生程序）。
- 这次改动到的载荷条目：`ai/praat_ai/chat.py`、`ai/praat_ai/cloud_agent.py`、`ai/praat_ai/cloud_workflow.py`（修改）、`ai/praat_ai/delivery.py`、`ai/tools/launch_praat_medium.py`（新增），以及重新编译的 `AIPraat.exe` / `AIPraat-paths.exe`。
- 回归：完整 Python 套件 **798 项，0 failures**（5 个 error 都是本机环境问题：4 项与本机代理串解析有关、1 项缺少可选依赖 `parselmouth`）。
- 新增回归 10 项：先复现旧行为（7 项红）再修到全绿。
- 真机（真实 Praat）**12 项检查全过**：合成信号（真值 15 毫秒）自动估计 24.0 毫秒、给定两点相减正好 15.0 毫秒；测试录音（选区 0.437403–0.635206 秒）测出 **VOT = 38.0 毫秒**。
- 真云端（阿里云百炼 `qwen3.7-flash`）整轮走通：模型调 `vot` → 投递成功 → 38.0 毫秒 → 报告正确区分「工具测量」与「缺少听感」，不再说「因为 audio_input 为 false 所以测不了」。

## 改动的文件

- 新增：`ai/praat_ai/delivery.py`（投递事实：`DELIVERED` / `NOT_DELIVERED` / `EXECUTION_UNKNOWN` / `EXECUTION_BLOCKED`）
- 修改：`ai/praat_ai/chat.py`、`ai/praat_ai/cloud_workflow.py`、`ai/praat_ai/cloud_agent.py`、`installer/build.ps1`（补 UTF-8 BOM）
- 测试与工具：`ai/tests/test_delivery_state.py`、`ai/tests/verify_delivery_live.py`、`ai/tests/verify_delivery_live_cloud.py`、`ai/tools/launch_praat_medium.py`
- 校验与文档：`installer/verification/verify-delivery-package.py`、`docs/2026-10-02-阶梯逃逸投递事实修复验收.md`、`ai/HANDOFF.md`

## 已知边界（本次未改）

- `vot` 自动估计跑完会在对象列表里留下一个 `Harmonicity` 派生对象（工具只删自己的临时 Sound/Intensity）。
- 若环境变量 `NO_PROXY` 里含带方括号的 IPv6（例如 `[::1]`），本机 Python 网络层在构造请求客户端时会直接抛 `Invalid port`，云端请求发不出去；去掉该条目即可（属于环境/依赖问题，不是本仓库代码）。
