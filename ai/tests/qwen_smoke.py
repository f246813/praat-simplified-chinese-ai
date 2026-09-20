from __future__ import annotations

import argparse

from praat_ai.config import load_config
from praat_ai.qwen import QwenClient
from praat_ai.server import QwenServerManager
from praat_ai.vram import detect_gpu, select_runtime_profile


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llama-server", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--mmproj")
    parser.add_argument("--port", type=int, default=18082)
    parser.add_argument("--vision", action="store_true")
    parser.add_argument("--image")
    arguments = parser.parse_args()

    config = load_config()
    config.server.auto_start = True
    config.server.llama_server = arguments.llama_server
    config.server.model_path = arguments.model
    config.server.mmproj_path = arguments.mmproj or ""
    config.server.port = arguments.port
    config.qwen.base_url = f"http://127.0.0.1:{arguments.port}/v1"
    config.qwen.model = "Qwen3.5-0.8B"

    profile = select_runtime_profile(7100, arguments.vision)
    manager = QwenServerManager(config, profile)
    try:
        started = manager.ensure_started()
        client = QwenClient(config.qwen)
        reply = client.chat(
            [
                {
                    "role": "user",
                    "content": "只输出 JSON 对象：{\"ok\": true, \"message\": \"本地模型正常\"}",
                }
            ],
            max_tokens=128,
            temperature=0.1,
            json_mode=True,
        )
        gpu_during_run = detect_gpu()
        print(f"started={started}")
        print(f"available={client.available()}")
        print(f"reply={reply!r}")
        if arguments.image:
            description = client.vision_explain(
                arguments.image,
                {"task": "describe image"},
                {"errors": []},
            )
            print(f"vision={description!r}")
        print(f"gpu={gpu_during_run.to_dict() if gpu_during_run else None}")
        return 0
    finally:
        manager.stop()


if __name__ == "__main__":
    raise SystemExit(main())
