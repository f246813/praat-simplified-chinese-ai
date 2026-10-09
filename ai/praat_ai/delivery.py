"""脚本投递事实。NOT_DELIVERED 表示未交给 Praat；DELIVERED 表示已交付，仍需判定执行结果；EXECUTION_UNKNOWN 表示交付后未确认完成；EXECUTION_BLOCKED 表示因先前结果不明而阻止本次投递。调用方必须区分这些状态，不能仅凭错误文字推断。"""

#: 脚本已经交给 Praat。结果可能是成功、脚本内报错或超时，由调用方继续判断。
DELIVERED = 'delivered'

#: 脚本没有交给 Praat（确定什么都没跑）。
NOT_DELIVERED = 'not_delivered'

#: 脚本交出去了，但没有等到完成标记；执行结果不明。
EXECUTION_UNKNOWN = 'unknown'

#: 本轮已停止投递（上一条指令结果不明），这次调用没有投出去。
EXECUTION_BLOCKED = 'blocked'
