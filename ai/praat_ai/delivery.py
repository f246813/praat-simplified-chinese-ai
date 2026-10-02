"""投递事实：一条脚本到底有没有交给正在运行的 Praat。

``chat._send_script()`` 失败时只返回 ``(False, 说明)``，但两种失败的处理方式完全
不同，只看返回值分不出来（2026-10-02 实测的 VOT 故障就是被这条混同放大的）：

- :data:`NOT_DELIVERED`：脚本**根本没送出去**（``Message.txt`` 写不进去、找不到
  Praat 窗口、没有运行中的 Praat…）。Praat 什么都没做，改参数重试是安全的，
  也不该拦住同一轮后面的其它操作。
- :data:`DELIVERED` + 没有完成标记 → :data:`EXECUTION_UNKNOWN`：脚本已经交出去，
  但完成标记没等到（超时、取消、完成标记对不上）。这时**不能**盲目再投一条，
  按设计要暂停这条分支、核实对象状态，再用已有证据收尾。
- :data:`EXECUTION_BLOCKED`：本轮已经因为上一条指令结果不明而停止投递，这次调用
  **没有投出去**——这是「没执行」，不是又一条「状态不明」。
"""

#: 脚本已经交给 Praat。结果可能是成功、脚本内报错或超时，由调用方继续判断。
DELIVERED = 'delivered'

#: 脚本没有交给 Praat（确定什么都没跑）。
NOT_DELIVERED = 'not_delivered'

#: 脚本交出去了，但没有等到完成标记；执行结果不明。
EXECUTION_UNKNOWN = 'unknown'

#: 本轮已停止投递（上一条指令结果不明），这次调用没有投出去。
EXECUTION_BLOCKED = 'blocked'
