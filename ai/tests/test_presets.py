"""模型预设：解析、状态上报、切换（含真正重启）都要可验证。"""

import json
import socketserver
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch

from praat_ai import control
from praat_ai.config import load_config
from praat_ai.presets import (
    PresetError,
    active_preset,
    apply_preset_to_profile,
    find_preset,
    list_presets,
    preset_config_values,
)
from praat_ai.vram import RuntimeProfile, select_runtime_profile


SMALL_MODEL = r"D:\models\Qwen3.5-0.8B-Q4_K_M.gguf"
BIG_MODEL = r"D:\llama.cpp\Qwen3.5-2B-UD-Q5_K_XL.gguf"


class _ModelsHandler(BaseHTTPRequestHandler):
    model_id = SMALL_MODEL
    capabilities: list[str] = ["completion", "multimodal"]

    def do_GET(self) -> None:   # noqa: N802 - http.server API
        if not self.path.startswith("/v1/models"):
            self.send_error(404)
            return
        payload = json.dumps(
            {
                "object": "list",
                "models": [
                    {
                        "name": self.model_id,
                        "model": self.model_id,
                        "capabilities": list(self.capabilities),
                    }
                ],
                "data": [{"id": self.model_id, "object": "model"}],
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        return


class _FastHTTPServer(HTTPServer):
    """HTTPServer without the slow reverse-DNS lookup in server_bind()."""

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


class FakeService:
    """A real HTTP endpoint that reports the model a server would load."""

    def __init__(self, model_id: str, capabilities: list[str] | None = None) -> None:
        self.model_id = model_id
        self.capabilities = list(capabilities or [])
        self.server = _FastHTTPServer(("127.0.0.1", 0), _ModelsHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/v1"

    def __enter__(self) -> "FakeService":
        _ModelsHandler.model_id = self.model_id
        _ModelsHandler.capabilities = self.capabilities
        self.thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class PresetFixture(unittest.TestCase):
    """建立两个真实存在的模型文件和一个含两个预设的配置。"""

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        directory = Path(self._temp.name)
        self.directory = directory
        self.runtime = directory / "runtime"
        self.runtime.mkdir()
        self.config_path = directory / "ai_config.json"
        self.server_exe = directory / "llama-server.exe"
        self.server_exe.write_bytes(b"stub")
        self.small = directory / "Qwen3.5-0.8B-Q4_K_M.gguf"
        self.big = directory / "Qwen3.5-2B-UD-Q5_K_XL.gguf"
        self.small_mmproj = directory / "mmproj-F16.gguf"
        self.big_mmproj = directory / "mmproj-2B-F16.gguf"
        for path in (self.small, self.big, self.small_mmproj, self.big_mmproj):
            path.write_bytes(b"stub")
        self.patches = [
            patch.object(control, "runtime_dir", return_value=self.runtime),
            patch.object(
                control, "status_path", return_value=self.runtime / "status.json"
            ),
            patch.object(control, "pid_path", return_value=self.runtime / "qwen.pid"),
            patch.object(control, "detect_gpu", return_value=None),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self._temp.cleanup()

    def write_config(self, *, base_url: str, with_presets: bool = True) -> None:
        payload: dict[str, object] = {
            "qwen": {"base_url": base_url, "model": self.big.name},
            "server": {
                "llama_server": str(self.server_exe),
                "model_path": str(self.big),
                "mmproj_path": str(self.big_mmproj),
                "mmproj_by_model": {str(self.big): str(self.big_mmproj)},
                "auto_start": False,
            },
        }
        if with_presets:
            payload["server"]["presets"] = [   # type: ignore[index]
                {
                    "id": "big",
                    "label": "Qwen3.5-2B（视觉）",
                    "model_path": str(self.big),
                    "mmproj_path": str(self.big_mmproj),
                    "vision": True,
                    "context_tokens": 8192,
                    "qwen": {"plan_max_tokens": 900},
                },
                {
                    "id": "small",
                    "label": "Qwen3.5-0.8B（快速）",
                    "model_path": str(self.small),
                    "mmproj_path": str(self.small_mmproj),
                    "vision": True,
                    "qwen": {"enable_thinking": False},
                },
                {
                    "id": "missing",
                    "label": "不存在的模型",
                    "model_path": str(self.directory / "nope.gguf"),
                },
            ]
        self.config_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )


class PresetParsingTests(PresetFixture):
    def test_presets_are_parsed_with_defaults(self) -> None:
        self.write_config(base_url="http://127.0.0.1:9/v1")
        config = load_config(self.config_path)
        self.assertEqual([item.id for item in config.server.presets], ["big", "small", "missing"])
        big = config.server.presets[0]
        self.assertEqual(big.display_name, "Qwen3.5-2B（视觉）")
        self.assertEqual(big.context_tokens, 8192)
        self.assertTrue(big.vision)
        self.assertEqual(big.qwen, {"plan_max_tokens": 900})
        # 缺字段的预设也要能读出来，只是没有投影文件。
        missing = config.server.presets[2]
        self.assertEqual(missing.mmproj_path, "")
        self.assertTrue(missing.vision)

    def test_presets_can_be_written_as_a_mapping(self) -> None:
        self.write_config(base_url="http://127.0.0.1:9/v1", with_presets=False)
        payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        payload["server"]["presets"] = {
            "big": {"label": "大模型", "model_path": str(self.big)},
        }
        self.config_path.write_text(json.dumps(payload), encoding="utf-8")
        config = load_config(self.config_path)
        self.assertEqual([item.id for item in config.server.presets], ["big"])
        self.assertEqual(config.server.presets[0].label, "大模型")

    def test_config_without_presets_still_loads(self) -> None:
        self.write_config(base_url="http://127.0.0.1:9/v1", with_presets=False)
        config = load_config(self.config_path)
        self.assertEqual(config.server.presets, [])
        self.assertEqual(active_preset(config), None)

    def test_preset_view_reports_availability_and_vision(self) -> None:
        self.write_config(base_url="http://127.0.0.1:9/v1")
        config = load_config(self.config_path)
        views = {item["id"]: item for item in list_presets(config)}
        self.assertTrue(views["big"]["available"])
        self.assertTrue(views["big"]["vision"])
        self.assertTrue(views["big"]["active"])
        self.assertFalse(views["missing"]["available"])
        self.assertFalse(views["missing"]["vision"])   # 没有 mmproj 时只能纯文本
        self.assertTrue(views["missing"]["vision_requested"])
        self.assertEqual(views["missing"]["missing"], [
            str(self.directory / "nope.gguf")
        ])

    def test_find_preset_accepts_id_label_and_file_name(self) -> None:
        self.write_config(base_url="http://127.0.0.1:9/v1")
        config = load_config(self.config_path)
        for key in ("small", "Qwen3.5-0.8B（快速）", str(self.small), self.small.name):
            preset = find_preset(config, key)
            self.assertIsNotNone(preset, key)
            self.assertEqual(preset.id, "small")   # type: ignore[union-attr]
        self.assertIsNone(find_preset(config, "unknown"))
        self.assertIsNone(find_preset(config, ""))

    def test_preset_config_values_merge_mmproj_mapping(self) -> None:
        self.write_config(base_url="http://127.0.0.1:9/v1")
        config = load_config(self.config_path)
        small = find_preset(config, "small")
        values = preset_config_values(small, config.server.mmproj_by_model)  # type: ignore[arg-type]
        self.assertEqual(values["server"]["active_preset"], "small")
        self.assertEqual(values["server"]["model_path"], str(self.small))
        self.assertEqual(values["server"]["mmproj_path"], str(self.small_mmproj))
        self.assertEqual(
            values["server"]["mmproj_by_model"],
            {
                str(self.big): str(self.big_mmproj),
                str(self.small): str(self.small_mmproj),
            },
        )
        self.assertEqual(values["qwen"]["model"], self.small.name)
        self.assertFalse(values["qwen"]["enable_thinking"])

    def test_preset_config_values_reject_missing_files(self) -> None:
        self.write_config(base_url="http://127.0.0.1:9/v1")
        config = load_config(self.config_path)
        missing = find_preset(config, "missing")
        with self.assertRaises(PresetError):
            preset_config_values(missing, {})   # type: ignore[arg-type]
        broken_mmproj = config.server.presets[0]
        broken_mmproj = type(broken_mmproj)(
            id="broken",
            label="投影文件缺失",
            model_path=str(self.big),
            mmproj_path=str(self.directory / "nope-mmproj.gguf"),
        )
        with self.assertRaises(PresetError):
            preset_config_values(broken_mmproj, {})

    def test_preset_overrides_runtime_profile(self) -> None:
        self.write_config(base_url="http://127.0.0.1:9/v1")
        config = load_config(self.config_path)
        big = find_preset(config, "big")
        profile = select_runtime_profile(None, True)
        self.assertEqual(profile.context_tokens, 4096)
        tuned = apply_preset_to_profile(profile, big)   # type: ignore[arg-type]
        self.assertEqual(tuned.context_tokens, 8192)
        self.assertTrue(tuned.vision_enabled)
        silent = apply_preset_to_profile(
            RuntimeProfile("t", "cpu", 4096, 0, True, True, 0),
            None,
        )
        self.assertTrue(silent.vision_enabled)


class PresetApplyTests(PresetFixture):
    def test_apply_preset_updates_config_when_service_is_stopped(self) -> None:
        self.write_config(base_url="http://127.0.0.1:9/v1")
        with patch.object(control, "_restart_service") as restart:
            status = control.apply_preset("small", self.config_path)
        self.assertFalse(restart.called)
        config = load_config(self.config_path)
        self.assertEqual(config.server.active_preset, "small")
        self.assertEqual(Path(config.server.model_path), self.small)
        self.assertEqual(Path(config.server.mmproj_path), self.small_mmproj)
        self.assertEqual(config.qwen.model, self.small.name)
        self.assertEqual(config.server.mmproj_by_model[str(self.small)], str(self.small_mmproj))
        self.assertEqual(status["frontend_preset"], "small")
        self.assertTrue(status["frontend_preset_label"])
        self.assertFalse(status["frontend_running"])

    def test_apply_preset_restarts_when_another_model_is_served(self) -> None:
        with FakeService(str(self.small)) as service:
            self.write_config(base_url=service.base_url)
            with patch.object(
                control, "_restart_service", return_value={"success": True}
            ) as restart:
                result = control.apply_preset("big", self.config_path)
        self.assertTrue(restart.called)
        self.assertEqual(result, {"success": True})
        self.assertEqual(load_config(self.config_path).server.active_preset, "big")

    def test_apply_preset_keeps_service_when_model_already_loaded(self) -> None:
        with FakeService(str(self.big)) as service:
            self.write_config(base_url=service.base_url)
            with patch.object(control, "_restart_service") as restart:
                status = control.apply_preset("big", self.config_path)
        self.assertFalse(restart.called)
        self.assertTrue(status["frontend_running"])
        self.assertEqual(
            status["frontend_model"], "Qwen3.5-2B-UD-Q5_K_XL.gguf"
        )
        self.assertTrue(status["frontend_preset_matches_live"])

    def test_apply_preset_rejects_unknown_and_missing(self) -> None:
        self.write_config(base_url="http://127.0.0.1:9/v1")
        with self.assertRaises(PresetError) as caught:
            control.apply_preset("nope", self.config_path)
        self.assertIn("可用预设", str(caught.exception))
        with self.assertRaises(PresetError):
            control.apply_preset("missing", self.config_path)
        # 失败时不能改动配置。
        self.assertEqual(load_config(self.config_path).server.active_preset, "")

    def test_apply_preset_without_presets_is_rejected(self) -> None:
        self.write_config(base_url="http://127.0.0.1:9/v1", with_presets=False)
        with self.assertRaises(PresetError):
            control.apply_preset("big", self.config_path)

    def test_status_lists_presets_for_the_frontend(self) -> None:
        with FakeService(str(self.small), ["completion", "multimodal"]) as service:
            self.write_config(base_url=service.base_url)
            status = control.collect_status(self.config_path)
        ids = [item["id"] for item in status["presets"]]
        self.assertEqual(ids, ["big", "small", "missing"])
        self.assertTrue(status["frontend_vision"])
        # 配置里写的是 2B，但服务实际加载的是 0.8B：状态必须两边都报出来。
        self.assertEqual(status["frontend_model"], "Qwen3.5-0.8B-Q4_K_M.gguf")
        self.assertEqual(status["frontend_model_configured"], "Qwen3.5-2B-UD-Q5_K_XL.gguf")
        self.assertTrue(status["frontend_model_mismatch"])
        self.assertFalse(status["frontend_preset_matches_live"])

    def test_set_model_keeps_preset_flag_in_sync(self) -> None:
        self.write_config(base_url="http://127.0.0.1:9/v1")
        status = control.set_frontend_model(str(self.small), config_path=self.config_path)
        self.assertEqual(status["frontend_preset"], "small")
        # 手动选一个不在预设里的模型时，不能继续显示旧预设。
        other = self.directory / "other.gguf"
        other.write_bytes(b"stub")
        status = control.set_frontend_model(str(other), config_path=self.config_path)
        self.assertEqual(status["frontend_preset"], "")


if __name__ == "__main__":
    unittest.main()
