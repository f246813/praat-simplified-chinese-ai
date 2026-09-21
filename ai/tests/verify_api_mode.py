"""手动回归：API 模式（前端接云端大模型）真的能跑通。

用法（仓库根目录）::

    python ai/tests/verify_api_mode.py

它不需要真的 API key：本脚本自己起一个**假的 OpenAI 兼容服务**
（`/v1/models` + `/v1/chat/completions`），然后把前端配置指向它，验证：

1. 配置里勾上 API 之后，`config.qwen` 真的换成了云端地址/模型（`provider=api`）；
2. 「测试连接」（`qwen.probe_api`）能成功；
3. 真跑一轮 `chat.run_turn`：请求里带上了工具 schema、**没有** llama.cpp 专有的
   `chat_template_kwargs`，模型返回的工具调用被真的执行、结果回灌后给出回答；
4. 状态文案说的是 API 模型（而不是本地 gguf 文件名）。

这里不碰真 Praat：执行那一步用假的执行器（和 `test_agent_loop.py` 一样）。
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praat_ai import chat, qwen, tools   # noqa: E402
from praat_ai.config import api_is_active, load_config   # noqa: E402


CONTEXT_TSV = "id\tclass\tname\tselected\n1\tSound\tSound tone\t1\n"
MODEL = "fake-big-model"
API_KEY = "sk-fake-for-test"


class FakeOpenAIHandler(BaseHTTPRequestHandler):
    """最小可用的 OpenAI 兼容服务：第一次回工具调用，第二次回一句回答。"""

    requests: list[dict] = []

    def log_message(self, *_args) -> None:   # 别把访问日志打到控制台
        pass

    def _json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:   # noqa: N802 - BaseHTTPRequestHandler 的接口
        if self.path.endswith("/models"):
            self._json({"object": "list", "data": [{"id": MODEL, "object": "model"}]})
            return
        self.send_error(404)

    def do_POST(self) -> None:   # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        FakeOpenAIHandler.requests.append(
            {
                "path": self.path,
                "auth": self.headers.get("Authorization", ""),
                "payload": payload,
            }
        )
        has_tool_result = any(
            isinstance(item, dict) and item.get("role") == "tool"
            for item in payload.get("messages", [])
        )
        if has_tool_result:
            message = {"role": "assistant", "content": "0.5 秒处基频 220 Hz。"}
        else:
            message = {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "pitch",
                            "arguments": json.dumps({"time": 0.5}),
                        },
                    }
                ],
            }
        self._json({"id": "chatcmpl-1", "choices": [{"index": 0, "message": message}]})


def start_fake_server() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOpenAIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}/v1"


def main() -> int:
    failures = 0
    server, base_url = start_fake_server()
    try:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            config_path = directory / "ai_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "qwen": {
                            "base_url": "http://127.0.0.1:8000/v1",
                            "model": "local.gguf",
                        },
                        "server": {
                            "llama_server": "D:/llama.cpp/llama-server.exe",
                            "model_path": "D:/models/local.gguf",
                            "host": "127.0.0.1",
                            "port": 8000,
                        },
                        "api": {
                            "enabled": True,
                            "label": "FakeCloud",
                            "base_url": base_url,
                            "model": MODEL,
                            "api_key": API_KEY,
                            "max_context_tokens": 32768,
                            "plan_max_tokens": 800,
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            config = load_config(config_path)
            ok = (
                api_is_active(config)
                and config.qwen.base_url == base_url
                and config.qwen.model == MODEL
                and config.qwen.provider == "api"
                and config.server.auto_start is False
            )
            print(
                f"{'OK  ' if ok else 'FAIL'} 配置切到 API："
                f"{config.qwen.base_url} / {config.qwen.model} / provider={config.qwen.provider}"
            )
            failures += 0 if ok else 1

            ok, detail = qwen.probe_api(
                base_url=base_url, api_key=API_KEY, model=MODEL, timeout=10
            )
            print(f"{'OK  ' if ok else 'FAIL'} 测试连接：{detail}")
            failures += 0 if ok else 1

            # 真跑一轮：规划 → 执行（假执行器）→ 回灌 → 回答
            context = tools.ToolContext(
                tools.parse_object_context(CONTEXT_TSV),
                directory / "chat_result.tsv",
                directory / "chat_state.txt",
            )
            executed: list[str] = []

            def execute(script: str) -> tuple[bool, list[str], str]:
                executed.append(script)
                return True, ["基频（0.500 秒处）= 220.000 Hz"], ""

            client = qwen.QwenClient(config.qwen)
            outcome = chat.run_turn(
                client,
                user_text="查一下 0.5 秒处的基频",
                context_text=CONTEXT_TSV,
                history=[],
                context=context,
                execute=execute,
                native=True,
            )
            # 第 1 条请求是「测试连接」（不带工具），带工具的是规划那一轮：
            # 按内容找，别按下标猜。
            planning = next(
                (
                    item
                    for item in FakeOpenAIHandler.requests
                    if item["payload"].get("tools")
                ),
                None,
            )
            tools_sent = [
                entry["function"]["name"]
                for entry in ((planning or {}).get("payload", {}).get("tools") or [])
            ]
            payload_sent = (planning or {}).get("payload", {})
            auth = (planning or {}).get("auth", "")
            ok = (
                len(executed) == 1
                and outcome.steps
                and outcome.steps[0].tool == "pitch"
                and "220" in outcome.reply
                and payload_sent.get("model") == MODEL
                and "chat_template_kwargs" not in payload_sent
                and "pitch" in tools_sent
                and auth == f"Bearer {API_KEY}"
            )
            print(
                f"{'OK  ' if ok else 'FAIL'} 真跑一轮：工具 {len(tools_sent)} 个、"
                f"执行了 {len(executed)} 步、回答「{outcome.reply[:40]}」、"
                f"Authorization={'有' if auth else '无'}"
            )
            failures += 0 if ok else 1

            status_text = chat.model_status_text(config)
            ok = MODEL in status_text and "API" in status_text
            print(f"{'OK  ' if ok else 'FAIL'} 状态文案：{status_text}")
            failures += 0 if ok else 1

            # 请求次数：一轮里至少两次（规划 + 回灌之后的回答）
            ok = len(FakeOpenAIHandler.requests) >= 2
            print(
                f"{'OK  ' if ok else 'FAIL'} 服务端收到 {len(FakeOpenAIHandler.requests)} 次请求"
            )
            failures += 0 if ok else 1
    finally:
        server.shutdown()
        server.server_close()
        time.sleep(0.2)
    total = 5
    print(f"\n{total - failures}/{total} 个 API 模式用例通过")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
