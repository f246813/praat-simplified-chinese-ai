# 上下文、技能与缓存检查方法

当前模块职责见 [阶段历史、技能与缓存](../CURRENT-IMPLEMENTATION.zh-CN.md#阶段历史技能与缓存)。检查需区分协议正确性、请求形状、供应商用量和性能；旧样本的通过数与耗时不能代替当前结果。

## 离线协议检查

在项目根目录、已安装项目依赖的 Python 环境中执行：

```powershell
$env:PYTHONPATH = 'ai'
python -m unittest discover -s ai/tests -p 'test_phase_context.py'
python -m unittest discover -s ai/tests -p 'test_cloud_protocol.py'
python -m unittest discover -s ai/tests -p 'test_token_budget.py'
```

核对阶段消息追加、配置身份变化、压缩边界、工具调用/返回配对、非文本内容的持久化边界和预算口径。失败时先比较当前源码与测试期待，不直接把旧断言升级为业务规则。

## 请求与用量检查

`cloud_metrics.py` 记录最终请求静态指纹、消息指纹、消息数与字节数，归一化输入、输出、推理及缓存读写用量。未返回的缓存字段为未知；不能按零命中或已命中解释。

同阶段比较固定规则、工具及输出协议，并检查动态目标、技能和新证据的位置。检查压缩或配置更新后的上下文版本，避免把不同上下文当成同一稳定前缀。任务状态与权限不会因为消息压缩而重置。

## 实际端点测量

`ai/tests/benchmark_context_cache.py` 只有显式 `--send` 才发送请求，使用 `ai/ai_config.json` 的 API 并生成隔离材料。运行前需核实当前模型、端点、依赖和数据输出位置。脚本的 baseline 路径固定依赖 `backups/pi-context-cache-20261006`；该备份缺失时不能直接用于当前 A/B 比较。

`ai/tests/summarize_context_cache.py` 面向固定二十条历史样本布局，并包含固定价格估算。它不是通用当前账单工具；使用其他样本或当前价格前需调整相应假设。

测量应记录源码版本、配置、重复次数、样本与阶段、缓存可观测性、请求数、首字时间、总耗时和报告接受状态。控制冷暖连接与缓存条件；无法控制时如实记录。分别判断对话、测量、失败收尾和压缩，不能将单个样本推广为全场景加速。

本页提供检查方法，不声明当前环境或实际 API 已通过。
