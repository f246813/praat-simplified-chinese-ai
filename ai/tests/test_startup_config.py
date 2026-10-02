"""启动配置缺失时给出可操作的提示，保留环境变量配置方式。"""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from praat_ai import control
from praat_ai.config import AppConfig, load_config
from praat_ai.server import QwenServerError, QwenServerManager
from praat_ai.vram import select_runtime_profile


class StartupConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.config_path = self.directory / "ai_config.json"
        self.server = self.directory / "llama-server.exe"
        self.server.write_bytes(b"stub")
        self.model = self.directory / "model.gguf"
        self.model.write_bytes(b"stub")

    def manager(self, config: AppConfig) -> QwenServerManager:
        config.server.auto_start = True
        return QwenServerManager(config, select_runtime_profile(None, False))

    def test_missing_config_identifies_the_file_and_setup_step(self) -> None:
        stderr = io.StringIO()
        with (
            patch.dict(os.environ, {"PRAAT_AI_CONFIG_PATH": str(self.config_path)}, clear=True),
            patch("praat_ai.control.endpoint_available", return_value=False),
            patch("praat_ai.server._endpoint_port_is_open", return_value=False),
            patch("praat_ai.control.detect_gpu", return_value=None),
            patch("praat_ai.control._write_status"),
            contextlib.redirect_stderr(stderr),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            exit_code = control.main(["start"])
        error = json.loads(stderr.getvalue())["error"]
        self.assertEqual(exit_code, 1)
        self.assertIn(str(self.config_path), error)
        self.assertIn("ai_config.example.json", error)
        self.assertNotIn("not found: .", error)

    def test_blank_server_path_identifies_the_setting(self) -> None:
        for value in ("", " \t"):
            with self.subTest(value=value):
                config = AppConfig()
                config.server.llama_server = value
                config.server.model_path = str(self.model)
                with patch("praat_ai.server._endpoint_port_is_open", return_value=False):
                    with self.assertRaisesRegex(QwenServerError, "server.llama_server"):
                        self.manager(config).ensure_started()

    def test_blank_model_path_identifies_the_setting(self) -> None:
        for value in ("", " \t"):
            with self.subTest(value=value):
                config = AppConfig()
                config.server.llama_server = str(self.server)
                config.server.model_path = value
                with patch("praat_ai.server._endpoint_port_is_open", return_value=False):
                    with self.assertRaisesRegex(QwenServerError, "server.model_path"):
                        self.manager(config).ensure_started()

    def test_environment_paths_allow_start_without_a_config_file(self) -> None:
        with (
            patch.dict(os.environ, {
                "PRAAT_AI_LLAMA_SERVER": str(self.server),
                "PRAAT_AI_QWEN_MODEL_PATH": str(self.model),
            }, clear=True),
            patch("praat_ai.server._endpoint_port_is_open", return_value=False),
            patch("praat_ai.control.detect_gpu", return_value=None),
            patch.object(QwenServerManager, "_spawn"),
            patch.object(QwenServerManager, "_wait_for_endpoint"),
            patch("praat_ai.control.collect_status", return_value={"success": True}),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = control._launch_server(load_config(self.config_path), self.config_path)
        self.assertTrue(result["success"])


if __name__ == "__main__":
    unittest.main()
