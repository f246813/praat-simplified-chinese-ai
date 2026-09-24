# ADR-005: 声学测量做成「表驱动」，加一个参数 = 加一行

**日期：** 2026-09-21
**状态：** Accepted

## 背景

B3 把 Chen Gafni 的几条测量收进来时，每一条都要在 `tools.py` 里手写一个 Python
函数生成 Praat 脚本。等要覆盖「jitter / shimmer / 共振峰带宽 / 频谱重心 / CPPS /
基频强度的各种统计量」这一批（他 `queries.txt` 里 35 行、我们原本只有 26 个手写
工具）时，问题很清楚：

1. **一条参数 = 一段 Python**：加参数要改模板、改 schema、改 catalog、改真机用例
   四处，容易漏；
2. 参考实现（[chengafni/praat](https://github.com/chengafni/praat) 的
   `plugin_CompleteAnalysis`）用的是**表**：`objects.txt`（生成哪些对象）、
   `queries.txt`（每个参数怎么查）、`settings.txt`（分析设置），加参数只加一行；
3. 但他们的表是**编辑器视角**，而且在 Praat 端把命令拼成字符串再
   `'queryCommand$'` 动态求值 —— 那套在 Praat 7 上很脆，我们的脚本是 Python
   生成的，命令字面量直接进脚本更稳。

## 决策

新增参数表 `ai/praat_ai/measures.tsv`（加载器 `ai/praat_ai/measures.py`）和通用工具
`measure`（渲染 `tools._build_measure`）。表分五节：

| 小节 | 一行是什么 |
| --- | --- |
| `@@ settings` | 分析设置（`pitch_floor` 75、`formant_max` 5500…），命令里的 `{key}` 占位符用它取值，模型可以用同名工具参数覆盖 |
| `@@ derivations` | 从 Sound 生成中间对象（`To Pitch` / `To Formant (burg)` / `To PowerCepstrogram`…），按依赖顺序排 |
| `@@ queries` | **一行一个参数**：`source`（`sound` / 派生 key / `pointProcess+sound` 这种双对象）+ `command` + 单位 + 小数位 |
| `@@ dedicated` | 要好几步才能算的参数（H/L、谱强调、Hammarberg…）指向已有的专用工具，**不在这里重写一遍** |
| `@@ editor_only` | 只能由编辑器算的（Voice report 的平均自相关）：reply 里用中文说明，而不是让 Praat 弹英文错误框 |

从这张表生成的东西：`measure` 的 JSON Schema enum 与说明、`catalog_text()`、
`measure` 的脚本、**Praat 原生插件的脚本**（`ai/tools/build_plugin.py`）、
真机用例（`verify_chat_templates.py` 的 `_measure_cases()`）。

三条实现约定（都是实测逼出来的）：

1. `To Pitch` / `To Formant` 这类命令**会把新建对象选中**——每建一个派生对象前
   都要重新 `selectObject:` 基础对象，否则第二个派生对象做在了中间对象上；
2. 只有命令里出现 `tmin`/`tmax` 的参数才算「按时间段查」，`from`/`to`（含编辑器
   圈选）只对这些参数生效；频谱/倒谱这类没有时间段的参数不谎称有范围；
3. 命令名以 **FORM 之外的那份菜单名**为准：`Get shimmer (local_dB)`（标题写的是
   `local, dB`）、`Get CPPS (hillenbrand)`（默认的 `Get CPPS:` 有 12 个参数）。

## 备选方案

| 方案 | 为什么不选 |
| --- | --- |
| 继续一条参数一个 Python 函数 | 加参数要改四处；真机用例靠手写，容易漏测新增参数 |
| 照抄 chengafni：在 Praat 端把命令拼成字符串再动态求值 | Praat 7 上 `'queryCommand$'` + `extractNumber` + `goto` 很脆；我们已经有「Python 生成脚本」这条更稳的路 |
| 参数表只放手写模板里已有的参数 | 表要能长出参数才有价值；`@@ dedicated` 一节让「多步参数」也能进表而不重写实现 |

## 后果

**好处**

- 加一个参数 = 加一行 TSV（表一致性、schema 覆盖、真机用例都有单测守着）；
- 参数从 26 个长到 41 个，其中 33 个是「一行查询」就能表达的；
- 对话前端和 Praat 原生插件**同源**：同一个声音两边数值一致（220 Hz 纯音：
  平均基频 220 Hz、RMS 0.3536 Pa、F1 191.9 Hz、CPPS 20.62 dB）。

**代价与风险**

- `measure` 的 `parameter` 是 enum，参数多起来以后 schema 变大（约 500 token）；
  宁可多这些 token 也不让模型自己拼参数名；
- 表里的命令字面量必须是真的能跑的命令，所以**每个参数都要有一条真机用例**
  （`verify_chat_templates.py` 98/98）；表写错不会静默通过；
- 「多步参数」和「一行参数」混在一次 `measure` 里会被拒绝，要求分开调用——
  这类参数有专用工具，混在一起会变成两套脚本拼接，得不偿失。

## 相关

- 代码：`ai/praat_ai/measures.tsv`、`ai/praat_ai/measures.py`、
  `ai/praat_ai/tools.py`（`_build_measure` / `measure_signature` / `_measure_schema`）、
  `ai/tools/build_plugin.py`
- 单测／真机验证：`ai/tests/test_measures.py`（25 条）、
  `ai/tests/verify_chat_templates.py`（41 条新用例）、`ai/tests/verify_plugin.py`
- guide.md 对应章节：§8.4（测量参数是表驱动的）、§8.7（原生插件）
