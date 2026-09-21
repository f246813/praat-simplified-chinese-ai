"""加载/停止模型时的进度上报与「简约小窗口」的数据通路。

Praat 那一路（菜单里点「启动前端 / 加载模型」）靠 `PRAAT_PROGRESS\t<进度>\t<说明>`
标准输出，Praat 侧把它变成带进度条的小窗口（`sys/praat_python.cpp` 的
`handlePythonOutputLine` → `Melder_progress`）。对话窗口那一路（点「应用预设」）
自己在 Tk 里弹一个迷你进度条，数据走同一套回调。

这个文件守着：控制层真的会发进度、回调能被调用、API key 不进入状态上报。
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from praat_ai import control
from praat_ai.config import load_config
from praat_ai.vram import RuntimeProfile


LOCAL_ONLY = {
    "qwen": {"base_url": "http://127.0.0.1:8000/v1", "model": "local.gguf"},
    "server": {
        "llama_server": "D:/llama.cpp/llama-server.exe",
        "model_path": "D:/models/local.gguf",
        "host": "127.0.0.1",
        "port": 8000,
    },
}
API_MODE = {
    **LOCAL_ONLY,
    "api": {
        "enabled": True,
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key": "sk-secret-key",
    },
}


def write_config(directory: Path, payload: dict) -> Path:
    path = directory / "ai_config.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def collect(seen: list[tuple[float, str]]):
    """进度回调：把 `(进度, 说明)` 收进列表（回调是两参数形式）。"""

    return lambda fraction, message: seen.append((fraction, message))


def fake_profile() -> RuntimeProfile:
    return RuntimeProfile(
        name="test",
        device="cpu",
        context_tokens=8192,
        n_gpu_layers=-1,
        vision_enabled=False,
        allow_asr_concurrent=False,
        unload_after_sec=0,
    )


class ProgressReportingTests(unittest.TestCase):
    def test_progress_line_and_callback(self) -> None:
        seen: list[tuple[float, str]] = []
        with patch("builtins.print") as printer:
            control._progress(0.42, "正在加载模型", sink=collect(seen))
        printed = printer.call_args[0][0]
        self.assertTrue(printed.startswith("PRAAT_PROGRESS\t"))
        self.assertIn("0.4200", printed)
        self.assertIn("正在加载模型", printed)
        self.assertEqual(seen, [(0.42, "正在加载模型")])

    def test_progress_without_sink_does_not_crash(self) -> None:
        with patch("builtins.print"):
            control._progress(0.1, "步骤")

    def test_launch_server_reports_progress(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = write_config(Path(raw), LOCAL_ONLY)
            seen: list[tuple[float, str]] = []

            class FakeManager:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.process = None

                def ensure_started(self) -> bool:
                    return True

            with patch.object(control, "QwenServerManager", FakeManager), patch.object(
                control, "detect_gpu", return_value=None
            ), patch.object(
                control, "select_runtime_profile", return_value=fake_profile()
            ), patch.object(control, "collect_status", return_value={"success": True}):
                control.start_frontend(path, progress=collect(seen))
        fractions = [fraction for fraction, _ in seen]
        self.assertTrue(fractions, seen)
        self.assertAlmostEqual(fractions[0], 0.05, places=3)
        self.assertAlmostEqual(max(fractions), 1.0, places=3)
        self.assertTrue(any("模型" in message for _, message in seen))
        self.assertEqual(fractions, sorted(fractions))

    def test_stop_reports_progress(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = write_config(Path(raw), LOCAL_ONLY)
            seen: list[tuple[float, str]] = []
            with patch.object(
                control, "_stop_running_service", return_value=True
            ), patch.object(control, "collect_status", return_value={"success": True}):
                control.stop_frontend(path, progress=collect(seen))
        self.assertTrue(seen)
        self.assertAlmostEqual(seen[0][0], 0.1, places=3)
        self.assertAlmostEqual(seen[-1][0], 1.0, places=3)
        self.assertIn("停止", seen[0][1])


class ApiModeControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = write_config(Path(self.directory.name), API_MODE)
        # 状态文件写到临时目录：别把 ai/runtime/status.json 写成测试里的假模型
        # （Praat 菜单的状态就是从那个文件读的）。
        self.runtime = Path(self.directory.name) / "runtime"
        self.runtime.mkdir(exist_ok=True)
        self._runtime_patch = patch.object(control, "runtime_dir", return_value=self.runtime)
        self._runtime_patch.start()

    def tearDown(self) -> None:
        self._runtime_patch.stop()
        self.directory.cleanup()

    def test_status_reports_the_api_model_without_the_key(self) -> None:
        with patch.object(control, "running_model_info", return_value={}) as probe:
            status = control.collect_status(self.path)
        text = json.dumps(status, ensure_ascii=False)
        self.assertTrue(status["api_enabled"])
        self.assertEqual(status["api_model"], "deepseek-chat")
        self.assertEqual(status["frontend_model"], "deepseek-chat")
        self.assertIn("API", status["frontend_status"])
        self.assertNotIn("sk-secret-key", text)
        probe.assert_not_called()

    def test_start_frontend_does_not_launch_llama_server_in_api_mode(self) -> None:
        with patch.object(control, "_launch_server") as launcher, patch.object(
            control, "endpoint_available", return_value=False
        ), patch.object(control, "running_model_info", return_value={}):
            result = control.start_frontend(self.path)
        launcher.assert_not_called()
        self.assertTrue(result["api_enabled"])

    def test_stop_frontend_in_api_mode_does_not_touch_a_local_service(self) -> None:
        with patch.object(control, "_stop_running_service") as stopper, patch.object(
            control, "running_model_info", return_value={}
        ):
            control.stop_frontend(self.path)
        stopper.assert_not_called()

    def test_api_config_command_is_available(self) -> None:
        with patch.object(control, "run_api_settings_dialog", return_value=0) as dialog:
            result = control.execute_command("api-config", "", self.path)
        dialog.assert_called_once()
        self.assertTrue(result["success"])


if __name__ == "__main__":
    unittest.main()
