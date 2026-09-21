"""「前端 → API 配置」：配置节、环境变量覆盖、客户端请求形状、状态上报。

目标：让前端能接一个**更大的模型**（云端 OpenAI 兼容 API），填 API key 就能用；
启用之后不再需要本地 llama-server，而且 key 不许出现在状态文件/日志/界面提示里。
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from praat_ai import api_settings, config as config_module, qwen
from praat_ai.config import load_config


def write_config(directory: Path, payload: dict) -> Path:
    path = directory / "ai_config.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


LOCAL_ONLY = {
    "qwen": {"base_url": "http://127.0.0.1:8000/v1", "model": "Qwen3.5-0.8B-Q4_K_M.gguf"},
    "server": {"model_path": "D:/models/Qwen3.5-0.8B-Q4_K_M.gguf", "host": "127.0.0.1", "port": 8000},
}


class ApiConfigParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def load(self, payload: dict, env: dict[str, str] | None = None):
        path = write_config(Path(self.directory.name), payload)
        keys = [
            "PRAAT_AI_API_KEY",
            "PRAAT_AI_API_BASE_URL",
            "PRAAT_AI_API_MODEL",
            "PRAAT_AI_QWEN_BASE_URL",
            "PRAAT_AI_QWEN_MODEL",
            "PRAAT_AI_QWEN_API_KEY",
        ]
        cleaned = {key: value for key, value in os.environ.items() if key not in keys}
        if env:
            cleaned.update(env)
        with patch.dict(os.environ, cleaned, clear=True):
            return load_config(path)

    def test_defaults_are_off_and_local(self) -> None:
        config = self.load(LOCAL_ONLY)
        self.assertFalse(config.api.enabled)
        self.assertEqual(config.api.base_url, "")
        self.assertFalse(config_module.api_is_active(config))
        self.assertEqual(config.qwen.base_url, "http://127.0.0.1:8000/v1")

    def test_api_section_is_parsed(self) -> None:
        payload = dict(LOCAL_ONLY)
        payload["api"] = {
            "enabled": True,
            "label": "DeepSeek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-test",
            "max_context_tokens": 65536,
            "plan_max_tokens": 2000,
        }
        config = self.load(payload)
        self.assertTrue(config.api.enabled)
        self.assertEqual(config.api.label, "DeepSeek")
        self.assertEqual(config.api.model, "deepseek-chat")
        self.assertTrue(config_module.api_is_active(config))

    def test_api_mode_overrides_the_qwen_client(self) -> None:
        payload = dict(LOCAL_ONLY)
        payload["api"] = {
            "enabled": True,
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-test",
            "max_context_tokens": 65536,
            "plan_max_tokens": 2000,
            "request_timeout_sec": 120,
            "vision_when_requested": False,
        }
        config = self.load(payload)
        self.assertEqual(config.qwen.base_url, "https://api.deepseek.com/v1")
        self.assertEqual(config.qwen.model, "deepseek-chat")
        self.assertEqual(config.qwen.api_key, "sk-test")
        self.assertEqual(config.qwen.max_context_tokens, 65536)
        self.assertEqual(config.qwen.plan_max_tokens, 2000)
        self.assertEqual(config.qwen.provider, "api")
        # API 模式下不许再自动拉起本地服务（但本地配置本身要留着，关掉 API 就能用）。
        self.assertFalse(config.server.auto_start)
        self.assertEqual(
            config.server.model_path, "D:/models/Qwen3.5-0.8B-Q4_K_M.gguf"
        )

    def test_api_mode_needs_both_url_and_model(self) -> None:
        payload = dict(LOCAL_ONLY)
        payload["api"] = {"enabled": True, "base_url": "https://api.example.com/v1"}
        config = self.load(payload)
        self.assertFalse(config_module.api_is_active(config))
        self.assertEqual(config.qwen.base_url, "http://127.0.0.1:8000/v1")

    def test_environment_variables_override_the_api_key(self) -> None:
        payload = dict(LOCAL_ONLY)
        payload["api"] = {
            "enabled": True,
            "base_url": "https://api.example.com/v1",
            "model": "big-model",
            "api_key": "from-file",
        }
        config = self.load(payload, env={"PRAAT_AI_API_KEY": "from-env"})
        self.assertEqual(config.api.api_key, "from-env")
        self.assertEqual(config.qwen.api_key, "from-env")

    def test_environment_can_point_at_another_endpoint(self) -> None:
        payload = dict(LOCAL_ONLY)
        payload["api"] = {
            "enabled": True,
            "base_url": "https://api.example.com/v1",
            "model": "big-model",
        }
        config = self.load(
            payload,
            env={
                "PRAAT_AI_API_BASE_URL": "https://gateway.internal/v1",
                "PRAAT_AI_API_MODEL": "qwen-max",
            },
        )
        self.assertEqual(config.api.base_url, "https://gateway.internal/v1")
        self.assertEqual(config.api.model, "qwen-max")
        self.assertEqual(config.qwen.model, "qwen-max")


class ClientPayloadTests(unittest.TestCase):
    def payload_for(self, provider: str) -> dict:
        client = qwen.QwenClient(
            qwen.QwenConfig(
                base_url="https://api.example.com/v1",
                model="big-model",
                api_key="sk-test",
                provider=provider,
            )
        )
        captured: dict = {}

        class FakeResponse:
            status = 200

            def read(self) -> bytes:
                return json.dumps(
                    {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}
                ).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *_exc) -> bool:
                return False

        def fake_urlopen(request, timeout=None):
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["headers"] = dict(request.headers)
            return FakeResponse()

        with patch.object(qwen.urllib.request, "urlopen", fake_urlopen):
            client.chat_message([{"role": "user", "content": "你好"}])
        return captured

    def test_api_provider_does_not_send_llama_cpp_only_fields(self) -> None:
        captured = self.payload_for("api")
        body = captured["body"]
        self.assertNotIn("chat_template_kwargs", body)
        self.assertEqual(body["model"], "big-model")
        self.assertIn("max_tokens", body)

    def test_local_provider_keeps_chat_template_kwargs(self) -> None:
        captured = self.payload_for("llama.cpp")
        self.assertIn("chat_template_kwargs", captured["body"])

    def test_authorization_header_uses_the_api_key(self) -> None:
        captured = self.payload_for("api")
        headers = {key.casefold(): value for key, value in captured["headers"].items()}
        self.assertEqual(headers.get("authorization"), "Bearer sk-test")


class SettingsValidationTests(unittest.TestCase):
    def test_settings_are_prefilled_from_the_config(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = write_config(
                Path(raw),
                {
                    **LOCAL_ONLY,
                    "api": {
                        "enabled": True,
                        "base_url": "https://api.deepseek.com/v1",
                        "model": "deepseek-chat",
                        "api_key": "sk-x",
                    },
                },
            )
            values = api_settings.settings_from_config(load_config(path))
        self.assertEqual(values["base_url"], "https://api.deepseek.com/v1")
        self.assertEqual(values["model"], "deepseek-chat")
        self.assertTrue(values["enabled"])

    def test_validation_rejects_an_enabled_entry_without_url_or_model(self) -> None:
        clean, errors = api_settings.normalize_settings(
            {"enabled": True, "base_url": "  ", "model": ""}
        )
        self.assertFalse(clean["enabled"])
        self.assertEqual(len(errors), 2)
        self.assertTrue(all("API" in message or "地址" in message or "模型" in message for message in errors))

    def test_validation_trims_and_defaults(self) -> None:
        clean, errors = api_settings.normalize_settings(
            {
                "enabled": True,
                "base_url": "https://api.example.com/v1/",
                "model": " big-model ",
                "api_key": " sk-1 ",
            }
        )
        self.assertEqual(errors, [])
        self.assertEqual(clean["base_url"], "https://api.example.com/v1")
        self.assertEqual(clean["model"], "big-model")
        self.assertEqual(clean["api_key"], "sk-1")
        self.assertGreater(clean["max_context_tokens"], 0)

    def test_saving_writes_the_config_and_marks_when_it_was_verified(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = write_config(Path(raw), LOCAL_ONLY)
            api_settings.save_settings(
                {
                    "enabled": True,
                    "label": "DeepSeek",
                    "base_url": "https://api.deepseek.com/v1",
                    "model": "deepseek-chat",
                    "api_key": "sk-test",
                },
                path,
                verified=True,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(payload["api"]["enabled"])
        self.assertEqual(payload["api"]["model"], "deepseek-chat")
        self.assertTrue(payload["api"]["verified_at"])
        # 本地 llama-server 的配置不许被写坏（关掉 API 还要能回去用）。
        self.assertEqual(payload["server"]["model_path"], LOCAL_ONLY["server"]["model_path"])

    def test_saving_refuses_invalid_values(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = write_config(Path(raw), LOCAL_ONLY)
            with self.assertRaises(ValueError):
                api_settings.save_settings({"enabled": True, "base_url": "", "model": ""}, path)

    def test_provider_list_has_known_entries(self) -> None:
        labels = [item["label"] for item in api_settings.PROVIDERS]
        self.assertIn("DeepSeek", labels)
        self.assertIn("OpenAI", labels)
        self.assertTrue(all(item.get("base_url") for item in api_settings.PROVIDERS))


class ProbeTests(unittest.TestCase):
    def test_probe_reports_success(self) -> None:
        class FakeResponse:
            status = 200

            def read(self) -> bytes:
                return json.dumps(
                    {"choices": [{"message": {"role": "assistant", "content": "pong"}}]}
                ).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *_exc) -> bool:
                return False

        with patch.object(qwen.urllib.request, "urlopen", lambda *a, **k: FakeResponse()):
            ok, detail = qwen.probe_api(
                base_url="https://api.example.com/v1",
                api_key="sk-test",
                model="big-model",
            )
        self.assertTrue(ok)
        self.assertIn("big-model", detail)

    def test_probe_reports_failure_with_the_reason(self) -> None:
        def explode(*_args, **_kwargs):
            raise OSError("connection refused")

        with patch.object(qwen.urllib.request, "urlopen", explode):
            ok, detail = qwen.probe_api(
                base_url="https://api.example.com/v1",
                api_key="sk-test",
                model="big-model",
            )
        self.assertFalse(ok)
        self.assertIn("connection refused", detail)


if __name__ == "__main__":
    unittest.main()
