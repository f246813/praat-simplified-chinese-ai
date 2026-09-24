# ADR-009: 前端可以接云端大模型（API 配置 + API key）

**日期：** 2026-09-21
**状态：** Accepted

## 背景

本机只有 8 GB 显存，能跑的最多是 2B 级别的模型；用户手上有更大的模型（DeepSeek、
通义千问-Max、GPT-4o 之类），希望「填个 API key 就能用」。难点有三个：

1. 对话链路到处都在用 `config.qwen`（客户端、状态栏、token 预算、预设），
   接云端要在**不重写这些地方**的前提下换掉后端；
2. key 是秘密：不能进仓库、不能进状态文件（Praat 菜单会读 `runtime/status.json`）、
   界面上要默认打码；
3. 云端和 llama.cpp 的**请求形状不一样**：llama.cpp 靠 `chat_template_kwargs`
   开模型自带模板（多轮把工具结果作为 `role=tool` 回灌全靠它），云端不认这个字段；
   新一点的云端模型还只认 `max_completion_tokens`。

## 决策

配置里加一个独立的 `api` 节（`ai/praat_ai/config.py` 的 `ApiConfig`），
由 `apply_api_to_qwen()` 在 `enabled` 且地址/模型都填齐时把它的值**搬进**
`config.qwen`（并把 `qwen.provider` 设成 `api`）：

```jsonc
"api": {
  "enabled": false,
  "label": "DeepSeek",                       // 只用于显示
  "base_url": "https://api.deepseek.com/v1",  // 任何 OpenAI 兼容的 /v1
  "model": "deepseek-chat",
  "api_key": "",                              // 也可用环境变量 PRAAT_AI_API_KEY
  "request_timeout_sec": 120,
  "max_context_tokens": 32768,
  "plan_max_tokens": 1500,
  "vision_when_requested": false,
  "verified_at": ""                            // 「测试连接」成功的时间，仅显示
}
```

- **入口**：Praat 菜单「前端 → API 配置…」（`PraatAiControl_configureApi` →
  `run_ai_control.py api-config` → `api_settings.run_standalone`）和对话窗口里的
  「API 配置…」按钮，共用同一个 Tk 对话框；
- **key 的存放**：`ai_config.json`（已在 `.gitignore` 里）或环境变量
  `PRAAT_AI_API_KEY`（界面留空即可）。状态上报里只有 `api_label/api_model`，
  **没有 key**；
- **请求形状**按 `provider` 分叉：`llama.cpp` 带 `chat_template_kwargs`，
  `api` 不带；服务端报错里提到 `max_completion_tokens` 时自动换字段重试一次；
- **API 模式下不碰本地服务**：`server.auto_start` 关掉、`start_frontend` 不再拉起
  llama-server；但「停止前端」仍会收掉之前启动过的本机服务（腾显存）。
  「应用预设」= 回到本地模型（顺手关掉 API 模式），两边都能走通；
- **换后端时界面说实话**：状态栏/菜单显示 `模型: <云端模型>（<label>，API 模式，
  不需要本机服务）`，`frontend_status` 是 `running (API)`（翻译成
  「运行中（API 模式）」）。

## 备选方案

| 方案 | 为什么不选 |
| --- | --- |
| 让用户直接手改 `ai_config.json` 的 `qwen.base_url/model/api_key` | 那是本地 llama-server 的节，改了就丢本地配置；也没地方放「超时/上下文/回复上限」这些云端专属项，更没法一键切回 |
| 只改 `qwen` 节、不做 `api` 节 | 同上；而且「本地预设」和「云端模型」会互相覆盖 |
| 把 key 放进系统密钥环（Windows Credential Manager） | 多一层依赖，跨平台行为不一致；配置文件本来就不进仓库，够用 |
| 云端也带 `chat_template_kwargs` | 不是 OpenAI 标准字段，网关可能 400；而它是 llama.cpp 专有的模板开关 |
| 关掉 API 模式时自动删掉 key | 用户可能只是想临时切回本地；key 留着更方便，且文件本身不公开 |

## 后果

**好处**

- 用户填一次 key 就能用更大的模型，本地那份配置和预设原样保留、随时切回；
- 对话链路（工具 schema、agent 循环、token 预算、可取消等待）**一行都不用改**，
  因为它们本来就只看 `config.qwen`；
- key 不会出现在仓库、状态文件或界面提示里。

**代价与风险**

- 「云端 vs 本地」的差别集中在 `provider` 上，未来接更多非 OpenAI 兼容的服务
  （比如自研协议）需要在 `QwenClient` 里再分叉；
- 云端模型的能力（工具调用质量、中文表达、上下文长度）由服务商决定，前端只能
  通过 token 预算和提示词去适配；`ctx` 变大之后历史能带更多，但每次请求也更贵；
- 「应用预设 = 关掉 API 模式」是个隐含约定，所以界面上（预设提示行、保存后的提示）
  必须写清楚，否则用户会以为预设没生效。

## 相关

- 代码：`ai/praat_ai/config.py`（`ApiConfig` / `api_is_active` / `apply_api_to_qwen`）、
  `ai/praat_ai/api_settings.py`（对话框与校验/保存）、`ai/praat_ai/qwen.py`
  （`provider` / `probe_api` / `_post` 重试）、`ai/praat_ai/control.py`
  （API 模式的分支与 `api-config` 命令）、`sys/PraatAiControl.cpp` +
  `foned/FunctionEditor.cpp` + `sys/praat_translate.cpp`（菜单项）
- 单测／真机验证：`ai/tests/test_api_settings.py`、`ai/tests/verify_api_mode.py`、
  `ai/tests/verify_api_menu_live.py`
- guide.md 对应章节：§8.13；进度窗口那半见 §8.14
