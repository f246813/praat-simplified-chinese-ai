# Pi 局部模型数据来源（不引入 Agent 内核）

`ai/praat_ai/modern_budget.py` 仅抽取四条 OpenAI 模型窗口/输出元数据，预算与摘要为本项目 Python 薄适配；没有安装、启动或移植 Pi Agent/coding-agent 运行时。

- npm：`@mariozechner/pi-ai@0.73.1`，`gitHead=781152fc24841dc54b22284514604048ebe5e2c9`。
- 实际读取：发布包 `dist/models.generated.js`；包 SHA-1 `79d6e3b1431845ca4c0b469963c3b9d4f2aabdc3`，npm integrity `sha512-Jh4lXawZYuC83HzSIYuVum9NBqJD49i4JOt3H96cGW/924cwJMOyUs1Mv/e4QPzTXnzrqMoGviNQnvGgSu1LSg==`。
- 固定源码入口：<https://github.com/badlogic/pi-mono/tree/781152fc24841dc54b22284514604048ebe5e2c9/packages/ai>。
- 包内许可证元数据为 MIT；发布 tarball 未附 LICENSE。随本项目保留的 [MIT 声明](../../ai/third_party/pi-ai-LICENSE) 取自固定来源提交 `a276dabe57911253350bffb93cb7d7aff6a73261` 的根 LICENSE，未宣称已经下载核对发布 gitHead 的 LICENSE。

| model | contextWindow | maxTokens |
| --- | ---: | ---: |
| gpt-4o / gpt-4o-mini | 128000 | 16384 |
| gpt-4.1 / gpt-4.1-mini | 1047576 | 32768 |

只对 `api.openai.com` 端点启用上述自动预算；网关同名模型不视为已验证。未知窗口要求手动设置；服务商决定模式省略项目输出 cap，但仍需窗口用于压缩。没有复制 Pi 完整请求栈或整套压缩实现，摘要请求、专业证据存储与执行政策仍由本项目维护。

自动模式实际总输出 cap 是 `min(maxTokens, max(128, contextWindow // 8))`；不向所有模型统一添加 `0.1 / 0.8 / 1.5`。源码查阅及元数据抽取不代表真实服务商能力验证。
