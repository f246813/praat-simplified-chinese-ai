# SDD ledger — plan: docs/superpowers/plans/2026-10-02-dialogue-fastpath.md

授权：用户明确同意新增高级设置并实施其余优化。执行方式：当前会话顺序实施。

Pre-flight: Task 1 的分类和字段供 Task 2 使用；force_deep_thinking 默认 false、仅 high 生效；测量分类优先于寒暄，continuation 保留原管线。

Ruling: 无 Git 的当前发行目录使用不可覆盖的源码/安装器备份代替 Git worktree；不复制运行资料或用户配置。

Ruling: 最高档新开关关闭只允许明确普通对话降为 off；低/中/关闭/服务端自动沿用手动值，纯概念和复杂分析仍保留所选档位。这与上一轮手动优先说明及用户新增例外一致。

Task 1：已完成。14项初轮RED后实现配置/保守分类/供应商字段，高级展开高度RED1185后改可滚动，保存重开通过。

Task 2：已完成。单次文本流、窗口runtime、首字/请求/总耗时、Tk增量、明确duration直接工具。客户端连接初轮测试受环境代理关闭干扰；隔离localhost代理后，SDK DONE前未消费EOF造成连接关闭也得到复现。限定0.2秒协议尾部消费后，同TCP连续3轮和取消后新请求通过；产品代理选择保留。

独立审查：/root/dialogue_final_review（无会话历史，只读）发现未知操作/指代与概念混合分流、无完成标记EOF、过程hint边界、空key记录污染。每项先保留RED，再修复并GREEN；最终无待修重要问题。审查独立15项非GUI通过。

完整回归首轮：779项，21个原生测量子例失败，原因是Low进程无法写普通TEMP；.NET Framework宿主在中文路径于Main之前失败。将完全相同宿主字节移到ASCII私有路径，21合同通过；测试TEMP改专用LocalLow后784Python通过125.849秒。随后最终审查更改要求重跑，runner还隔离config和runtime供既有GUI测试使用。

真实GUI：完整ChatWindow submit→worker→queue→mainloop，SDK localhost SSE单次、首字先于完成、唯一最终message、过程hint保留、强制开关保存重开且高级选项在屏幕内、thread关闭均通过。未真实云API/用户音频。

Task 3：最终786Python、21合同通过。配置隔离最初替换路径函数影响5项既有环境变量用例，改用PRAAT_AI_CONFIG_PATH后全套通过233.932秒。用户Python3.14.8/Tk9的72项首轮仅新UI布尔断言类型失败(1与'1')，改为getboolean后Tk8.6/Tk9各3项UI补验通过，其余71项及两项实际mainloop检查通过。两种Tk的真实映射高级布局均970高，保存按钮916–956在滚动后的970高视口内。

安装器重建56,220,672字节，SHA256 f79c21296bfb68e8c74636cf88ec9f53630803722349171ee7921f677b744aa9；72文件/71哈希，内嵌ZIP与源码一致；原生hash保留777b54ff...。本轮Python前端改动不需原生重编译。

状态：全部任务完成。验收 docs/2026-10-02-普通对话响应优化验收.md，重启前端加载新代码。
