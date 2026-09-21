"""「前端 → API 配置」：配置节、环境变量覆盖、客户端请求形状、状态上报。

目标：让前端能接一个**更大的模型**（云端 OpenAI 兼容 API），填 API key 就能用；
启用之后不再需要本地 llama-server，而且 key 不许出现在状态文件/日志/界面提示里。
"""

import json
import os
import tempfile
import unittest
import urllib.error
from io import BytesIO
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


    def test_config_path_can_be_overridden_by_the_environment(self) -> None:
        """``PRAAT_AI_CONFIG_PATH`` 整份换配置文件。

        真机回归要跑本地模型时，用户可能已经切到了 API 模式；这条开关让回归自己
        带一份临时配置，不用动用户的 ai_config.json（以前只有菜单那条路认它）。
        """

        with tempfile.TemporaryDirectory() as raw:
            path = write_config(Path(raw), LOCAL_ONLY)
            with patch.dict(os.environ, {"PRAAT_AI_CONFIG_PATH": str(path)}):
                self.assertEqual(config_module.default_config_path(), path)
                config = load_config()
        self.assertEqual(config.qwen.model, "Qwen3.5-0.8B-Q4_K_M.gguf")


class ClientPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        # 「哪个服务端不认哪个字段」是模块级记忆（按 base_url 分），
        # 每条用例自己清一遍，免得互相影响。
        qwen.forget_rejected_thinking_fields()

    def tearDown(self) -> None:
        qwen.forget_rejected_thinking_fields()

    def payload_for(self, provider: str, **overrides) -> dict:
        settings = {
            "base_url": "https://api.example.com/v1",
            "model": "big-model",
            "api_key": "sk-test",
            "provider": provider,
        }
        settings.update(overrides)
        client = qwen.QwenClient(
            qwen.QwenConfig(**settings)
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

    # ---------------------------------------------------- 思考档位（2026-09-21 用户提的）

    def test_api_thinking_level_becomes_reasoning_effort(self) -> None:
        for level in ("low", "medium", "high"):
            captured = self.payload_for("api", thinking_level=level)
            self.assertEqual(captured["body"]["reasoning_effort"], level)

    def test_api_thinking_off_sends_no_reasoning_field(self) -> None:
        for level in ("off", "auto"):
            captured = self.payload_for("api", thinking_level=level)
            self.assertNotIn("reasoning_effort", captured["body"])

    def test_local_thinking_level_toggles_enable_thinking(self) -> None:
        high = self.payload_for("llama.cpp", thinking_level="high")
        self.assertTrue(high["body"]["chat_template_kwargs"]["enable_thinking"])
        off = self.payload_for("llama.cpp", thinking_level="off")
        self.assertFalse(off["body"]["chat_template_kwargs"]["enable_thinking"])
        # auto 沿用老的 enable_thinking 开关（不改变本地已有行为）。
        auto = self.payload_for("llama.cpp", thinking_level="auto", enable_thinking=True)
        self.assertTrue(auto["body"]["chat_template_kwargs"]["enable_thinking"])

    def test_rejected_reasoning_effort_is_retried_without_it(self) -> None:
        """服务端不认 reasoning_effort 时去掉重试，而且之后不再发（别白挨 400）。"""

        calls: list[dict] = []

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
            body = json.loads(request.data.decode("utf-8"))
            calls.append(body)
            if len(calls) == 1:
                raise urllib.error.HTTPError(
                    request.full_url,
                    400,
                    "Bad Request",
                    {},
                    BytesIO(
                        b'{"error":{"message":"unknown field reasoning_effort"}}'
                    ),
                )
            return FakeResponse()

        client = qwen.QwenClient(
            qwen.QwenConfig(
                base_url="https://api.example.com/v1",
                model="big-model",
                api_key="sk-test",
                provider="api",
                thinking_level="high",
            )
        )
        with patch.object(qwen.urllib.request, "urlopen", fake_urlopen):
            client.chat_message([{"role": "user", "content": "你好"}])
            client.chat_message([{"role": "user", "content": "再来一次"}])

        self.assertEqual(calls[0]["reasoning_effort"], "high")
        self.assertNotIn("reasoning_effort", calls[1])
        self.assertIn(
            "reasoning_effort",
            qwen.rejected_thinking_fields("https://api.example.com/v1"),
        )
        self.assertNotIn("reasoning_effort", calls[2])

    def test_a_bare_400_also_drops_the_thinking_field(self) -> None:
        """有的服务端只说 invalid request，不点名 reasoning_effort，也要降级。"""

        calls: list[dict] = []

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
            body = json.loads(request.data.decode("utf-8"))
            calls.append(body)
            if len(calls) == 1:
                raise urllib.error.HTTPError(
                    request.full_url,
                    400,
                    "Bad Request",
                    {},
                    BytesIO(b'{"error":{"message":"invalid request"}}'),
                )
            return FakeResponse()

        client = qwen.QwenClient(
            qwen.QwenConfig(
                base_url="https://api.example.com/v1",
                model="big-model",
                api_key="sk-test",
                provider="api",
                thinking_level="medium",
            )
        )
        with patch.object(qwen.urllib.request, "urlopen", fake_urlopen):
            client.chat_message([{"role": "user", "content": "你好"}])
        self.assertEqual(calls[0]["reasoning_effort"], "medium")
        self.assertNotIn("reasoning_effort", calls[1])

    def test_a_422_also_drops_the_thinking_field(self) -> None:
        """有的网关用 422 报「字段不认」，状态码不能只认 400。"""

        calls: list[dict] = []

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
            body = json.loads(request.data.decode("utf-8"))
            calls.append(body)
            if len(calls) == 1:
                raise urllib.error.HTTPError(
                    request.full_url,
                    422,
                    "Unprocessable Entity",
                    {},
                    BytesIO(b'{"error":{"message":"extra field not allowed"}}'),
                )
            return FakeResponse()

        client = qwen.QwenClient(
            qwen.QwenConfig(
                base_url="https://api.example.com/v1",
                model="big-model",
                api_key="sk-test",
                provider="api",
                thinking_level="low",
            )
        )
        with patch.object(qwen.urllib.request, "urlopen", fake_urlopen):
            client.chat_message([{"role": "user", "content": "你好"}])
        self.assertNotIn("reasoning_effort", calls[1])

    def test_a_server_error_does_not_silently_drop_the_thinking_field(self) -> None:
        """5xx / 401 这类不是「字段不认」，该报错就报错，别偷偷降级。"""

        calls: list[dict] = []

        def fake_urlopen(request, timeout=None):
            calls.append(json.loads(request.data.decode("utf-8")))
            raise urllib.error.HTTPError(
                request.full_url,
                401,
                "Unauthorized",
                {},
                BytesIO(b'{"error":{"message":"invalid api key"}}'),
            )

        client = qwen.QwenClient(
            qwen.QwenConfig(
                base_url="https://api.example.com/v1",
                model="big-model",
                api_key="sk-bad",
                provider="api",
                thinking_level="low",
            )
        )
        with patch.object(qwen.urllib.request, "urlopen", fake_urlopen):
            with self.assertRaises(qwen.QwenError):
                client.chat_message([{"role": "user", "content": "你好"}])
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            qwen.rejected_thinking_fields("https://api.example.com/v1"), set()
        )


class WorldKnowledgeTests(unittest.TestCase):
    """云端大模型可以发挥自己的语言学知识；本地小模型仍然只许用工具结果。

    用户 2026-09-21 提的：接上大模型之后限制太严，发挥不出世界知识的优势。
    """

    def load(self, api: dict | None) -> object:
        with tempfile.TemporaryDirectory() as raw:
            payload = dict(LOCAL_ONLY)
            if api is not None:
                payload["api"] = api
            path = write_config(Path(raw), payload)
            return load_config(path)

    def cloud(self, **overrides) -> dict:
        values = {
            "enabled": True,
            "label": "DeepSeek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
            "api_key": "sk-x",
        }
        values.update(overrides)
        return self.load(values)

    def test_local_mode_keeps_the_strict_prompt(self) -> None:
        config = self.load(None)
        self.assertEqual(config.qwen.knowledge_mode, "strict")
        self.assertEqual(
            qwen.planner_instructions(config.qwen),
            qwen.TOOL_PLANNER_INSTRUCTIONS,
        )

    def test_api_mode_allows_world_knowledge_by_default(self) -> None:
        config = self.cloud()
        self.assertTrue(config_module.api_is_active(config))
        self.assertEqual(config.qwen.knowledge_mode, "open")
        prompt = qwen.planner_instructions(config.qwen)
        self.assertIn("语言学", prompt)
        # 放开的是「解释」，不是「编测量数字」。
        self.assertIn("测量数字", prompt)
        self.assertIn("文献里的常见范围", prompt)

    def test_turning_world_knowledge_off_keeps_the_strict_prompt(self) -> None:
        config = self.cloud(use_world_knowledge=False)
        self.assertEqual(config.qwen.knowledge_mode, "strict")
        self.assertEqual(
            qwen.planner_instructions(config.qwen),
            qwen.TOOL_PLANNER_INSTRUCTIONS,
        )

    def test_api_mode_carries_the_thinking_level_into_qwen(self) -> None:
        config = self.cloud(thinking_level="high")
        self.assertEqual(config.qwen.thinking_level, "high")
        self.assertTrue(config.qwen.enable_thinking)
        config = self.cloud(thinking_level="off")
        self.assertEqual(config.qwen.thinking_level, "off")
        self.assertFalse(config.qwen.enable_thinking)

    def test_thinking_level_aliases_are_normalized(self) -> None:
        self.assertEqual(config_module.normalize_thinking_level("高"), "high")
        self.assertEqual(config_module.normalize_thinking_level("2"), "medium")
        self.assertEqual(config_module.normalize_thinking_level("  LOW "), "low")
        self.assertEqual(config_module.normalize_thinking_level(""), "auto")
        self.assertEqual(config_module.normalize_thinking_level("乱写"), "auto")
        self.assertEqual(config_module.normalize_thinking_level(None), "auto")


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

    def test_settings_round_trip_thinking_and_knowledge(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = write_config(
                Path(raw),
                {
                    **LOCAL_ONLY,
                    "api": {
                        "enabled": True,
                        "label": "DeepSeek",
                        "base_url": "https://api.deepseek.com/v1",
                        "model": "deepseek-chat",
                        "api_key": "sk-x",
                        "thinking_level": "high",
                        "use_world_knowledge": False,
                    },
                },
            )
            values = api_settings.settings_from_config(load_config(path))
            clean, errors = api_settings.normalize_settings(values)
        self.assertEqual(errors, [])
        self.assertEqual(values["thinking_level"], "high")
        self.assertFalse(values["use_world_knowledge"])
        self.assertEqual(clean["thinking_level"], "high")
        self.assertFalse(clean["use_world_knowledge"])

    def test_saving_stores_the_thinking_level_for_both_modes(self) -> None:
        """思考档位写进 ``api`` 和 ``qwen`` 两节：本地/云端各自翻成自己的字段。"""

        with tempfile.TemporaryDirectory() as raw:
            path = write_config(Path(raw), LOCAL_ONLY)
            api_settings.save_settings(
                {
                    "enabled": True,
                    "label": "DeepSeek",
                    "base_url": "https://api.deepseek.com/v1",
                    "model": "deepseek-chat",
                    "api_key": "sk-test",
                    "thinking_level": "低",
                    "use_world_knowledge": True,
                },
                path,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["api"]["thinking_level"], "low")
        self.assertEqual(payload["qwen"]["thinking_level"], "low")
        self.assertTrue(payload["api"]["use_world_knowledge"])

    def test_thinking_choice_labels_cover_every_level(self) -> None:
        labels = {value: label for label, value in api_settings.THINKING_CHOICES}
        for level in config_module.THINKING_LEVELS:
            self.assertIn(level, labels)
            self.assertEqual(api_settings.thinking_choice_label(level), labels[level])
        self.assertEqual(
            api_settings.thinking_choice_label("乱写"), labels["auto"]
        )


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
