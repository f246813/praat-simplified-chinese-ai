"""对话窗口的状态栏、Praat 存活判断和输出过滤。"""

import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from praat_ai import chat
from praat_ai.config import AppConfig
from praat_ai.qwen import _selected_object_hint


class SelectedObjectHintTests(unittest.TestCase):
    """规划提示里要单独写清「当前选中哪个对象」，否则模型爱挑 1 号。"""

    def test_hint_names_the_selected_object(self) -> None:
        context = (
            "id\tclass\tname\tselected\n"
            "1\tTextGrid\tTextGrid grid\t0\n"
            "2\tSound\tSound tone\t1\n"
        )
        self.assertEqual(_selected_object_hint(context), "当前选中：id 2（Sound Sound tone）")

    def test_hint_when_nothing_is_selected(self) -> None:
        context = "id\tclass\tname\tselected\n1\tSound\tSound tone\t0\n"
        self.assertIn("没有选中", _selected_object_hint(context))
        self.assertIn("没有选中", _selected_object_hint(""))


class PraatProcessTests(unittest.TestCase):
    def test_multiple_instances_produce_a_warning(self) -> None:
        completed = CompletedProcess(
            args=["tasklist"],
            returncode=0,
            stdout=(
                '"Praat.exe","1234","Console","1","98,304 K"\n'
                '"Praat.exe","5678","Console","1","98,304 K"\n'
            ),
            stderr="",
        )
        with patch.object(chat.subprocess, "run", return_value=completed):
            self.assertEqual(chat.praat_process_ids("D:/Praat-work/Praat.exe"), [1234, 5678])
            self.assertIn("2 个 Praat", chat.praat_instance_warning("D:/Praat-work/Praat.exe"))

    def test_single_instance_has_no_warning(self) -> None:
        completed = CompletedProcess(
            args=["tasklist"],
            returncode=0,
            stdout='"Praat.exe","1234","Console","1","98,304 K"\n',
            stderr="",
        )
        with patch.object(chat.subprocess, "run", return_value=completed):
            self.assertEqual(chat.praat_instance_warning("Praat.exe"), "")

    def test_missing_tasklist_output_means_not_running(self) -> None:
        completed = CompletedProcess(
            args=["tasklist"],
            returncode=0,
            stdout="INFO: No tasks are running which match the specified criteria.",
            stderr="",
        )
        with patch.object(chat.subprocess, "run", return_value=completed):
            self.assertFalse(chat.praat_process_running("D:/Praat-work/Praat.exe"))

    def test_running_process_is_detected(self) -> None:
        completed = CompletedProcess(
            args=["tasklist"],
            returncode=0,
            stdout='"Praat.exe","1234","Console","1","98,304 K"\n',
            stderr="",
        )
        with patch.object(chat.subprocess, "run", return_value=completed):
            self.assertTrue(chat.praat_process_running("D:/Praat-work/Praat.exe"))

    def test_tasklist_failure_does_not_block_sending(self) -> None:
        with patch.object(chat.subprocess, "run", side_effect=OSError("no tasklist")):
            self.assertTrue(chat.praat_process_running("D:/Praat-work/Praat.exe"))

    def test_missing_executable_is_not_a_blocker(self) -> None:
        self.assertTrue(chat.praat_process_running(""))


class SendOutputTests(unittest.TestCase):
    def test_send_noise_is_filtered_but_real_errors_survive(self) -> None:
        text = (
            "An instance of Praat that is not me is already running.\n"
            "Cannot write message file C:/Users/x/Praat/Message.txt\n"
        )
        cleaned = chat._clean_send_output(text)
        self.assertNotIn("already running", cleaned)
        # 「Cannot write message file」是真的失败，不能再当成噪声丢掉。
        self.assertIn("Cannot write message file", cleaned)


class FakeSendProcess:
    """假的 Praat.exe --send 进程，用来试超时和错误分支。"""

    def __init__(
        self,
        *,
        state_path: Path | None,
        log_text: str = "",
        exit_code: int | None = 0,
        write_state: bool = False,
    ) -> None:
        self.state_path = state_path
        self.log_text = log_text
        self.exit_code = exit_code
        self.write_state = write_state
        self.terminated = False
        self.killed = False

    def __call__(self, command: list[str], **kwargs: object) -> "FakeSendProcess":
        handle = kwargs.get("stdout")
        if handle is not None and self.log_text:
            handle.write(self.log_text.encode("utf-8"))
        if self.write_state and self.state_path is not None:
            self.state_path.write_text("done\n", encoding="utf-8")
        return self

    def poll(self) -> int | None:
        return self.exit_code

    def terminate(self) -> None:
        self.terminated = True
        self.exit_code = 0

    def kill(self) -> None:
        self.killed = True
        self.exit_code = 0

    def wait(self, timeout: float | None = None) -> int:
        return self.exit_code or 0


class SendScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.runtime = Path(self._temp.name)
        self.patch_runtime = patch.object(chat, "runtime_dir", return_value=self.runtime)
        self.patch_runtime.start()

    def tearDown(self) -> None:
        self.patch_runtime.stop()
        self._temp.cleanup()

    def test_state_file_means_success(self) -> None:
        fake = FakeSendProcess(state_path=chat.state_path(), write_state=True)
        with patch.object(chat.subprocess, "Popen", fake):
            ok, output = chat._send_script("Praat.exe", "selectObject: 1\n")
        self.assertTrue(ok)
        self.assertEqual(output, "")

    def test_context_ping_script_marks_state(self) -> None:
        script = chat.context_ping_script()
        self.assertIn(chat.state_path().as_posix(), script)
        self.assertIn('"done"', script)
        # 刷新用的是空脚本，不能碰任何对象。
        self.assertNotIn("selectObject", script)

    def test_praat_that_never_answers_is_reported_in_chinese(self) -> None:
        fake = FakeSendProcess(state_path=chat.state_path(), exit_code=None)
        with patch.object(chat.subprocess, "Popen", fake), patch.object(
            chat, "EXECUTION_TIMEOUT_SEC", 0.2
        ):
            ok, output = chat._send_script("Praat.exe", "selectObject: 1\n")
        self.assertFalse(ok)
        self.assertIn("没有执行这个脚本", output)
        self.assertTrue(fake.terminated)

    def test_praat_error_output_is_kept(self) -> None:
        fake = FakeSendProcess(
            state_path=chat.state_path(),
            log_text="Error: Command “播放” not available for current selection.",
            exit_code=1,
        )
        with patch.object(chat.subprocess, "Popen", fake), patch.object(
            chat, "EXECUTION_TIMEOUT_SEC", 0.2
        ):
            ok, output = chat._send_script("Praat.exe", "selectObject: 1\nPlay\n")
        self.assertFalse(ok)
        self.assertIn("not available for current selection", output)


class StatusTextTests(unittest.TestCase):
    def make_config(self) -> AppConfig:
        config = AppConfig()
        config.server.model_path = r"D:\llama.cpp-Qwen\Qwen3.5-2B-UD-Q5_K_XL.gguf"
        config.qwen.base_url = "http://127.0.0.1:9/v1"
        return config

    def test_status_uses_live_model_and_vision(self) -> None:
        config = self.make_config()
        info = {
            "id": r"D:\llama.cpp-Qwen\Qwen3.5-2B-UD-Q5_K_XL.gguf",
            "capabilities": ["completion", "multimodal"],
        }
        with patch.object(chat, "running_model_info", return_value=info):
            text = chat.model_status_text(config)
        self.assertIn("Qwen3.5-2B-UD-Q5_K_XL.gguf", text)
        self.assertIn("视觉已开", text)

    def test_status_reports_mismatch_and_unreachable_service(self) -> None:
        config = self.make_config()
        info = {"id": r"D:\models\Qwen3.5-0.8B-Q4_K_M.gguf", "capabilities": []}
        with patch.object(chat, "running_model_info", return_value=info):
            text = chat.model_status_text(config)
        self.assertIn("Qwen3.5-0.8B-Q4_K_M.gguf", text)
        self.assertIn("Qwen3.5-2B-UD-Q5_K_XL.gguf", text)   # 配置值也要显示出来
        with patch.object(chat, "running_model_info", return_value={}):
            offline = chat.model_status_text(config)
        self.assertIn("服务未响应", offline)

    def test_status_mentions_active_preset(self) -> None:
        config = self.make_config()
        from praat_ai.config import ServerPreset

        with tempfile.TemporaryDirectory() as raw:
            model = Path(raw) / "Qwen3.5-2B-UD-Q5_K_XL.gguf"
            model.write_bytes(b"stub")
            config.server.model_path = str(model)
            config.server.presets = [
                ServerPreset(
                    id="big",
                    label="Qwen3.5-2B（视觉）",
                    model_path=str(model),
                    vision=True,
                )
            ]
            with patch.object(chat, "running_model_info", return_value={"id": str(model)}):
                text = chat.model_status_text(config)
        self.assertIn("预设：Qwen3.5-2B（视觉）", text)


if __name__ == "__main__":
    unittest.main()
