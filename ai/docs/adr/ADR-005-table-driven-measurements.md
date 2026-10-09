# 表驱动声学测量参考

`measures.tsv` 经 `measures.py` 加载，`tools._build_measure` 按表生成 Praat 脚本。参数表也用于工具说明、schema、目录文本和 `ai/tools/build_plugin.py` 的原生插件生成。

| 小节 | 内容 |
| --- | --- |
| `@@ settings` | 分析默认值及命令占位符 |
| `@@ derivations` | Sound 派生对象与依赖 |
| `@@ queries` | 查询源、命令、单位和小数位 |
| `@@ dedicated` | 多步测量所使用的专用工具 |
| `@@ editor_only` | 仅编辑器支持的参数及说明 |

`measure.parameter` 支持 `f1,f2` 等参数列表；schema 的 pattern 与逐项校验均取自参数表。多步专用参数与一般查询的组合受脚本生成器限制，需要按工具支持的形式调用。

创建派生对象会改变选择状态，因此每次派生前重新选中基础对象。只有查询含 `tmin` / `tmax` 时，时间范围才作用于该查询；频谱等查询的范围行为应以生成脚本为准。命令字面量必须对应 Praat 实际菜单命令。

修改参数表后使用 `python ai/tools/build_plugin.py` 更新插件生成物，`--check` 比较生成物与表。表驱动不能替代对新增命令和计算含义的核查。

来源参考：[chengafni/praat](https://github.com/chengafni/praat) 的测量参数组织方式；具体公式和出处见参数表与专用工具。
