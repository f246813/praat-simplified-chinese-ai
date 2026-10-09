# 语音段分析范围与 VOT 适配

当前原生扩展保留 VOT，支持手动边界、候选估计和 Sound/LongSound 导出。元音鼻化、鼻辅音、R 音及通用比较编辑器的扩展方案已退出当前范围。AI VOT 模板与原生实现存在负值及 LongSound 支持差异；这属于实现限制，不能用作禁止负 VOT 的业务规则。

模块职责、实现边界和检查入口见 [当前实现说明](../../CURRENT-IMPLEMENTATION.zh-CN.md#vot-与语音资源)。
