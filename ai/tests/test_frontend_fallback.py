"""进程身份保护和窗口复用行为。"""

import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import start_ai_chat
from praat_ai import control
from praat_ai.config import AppConfig
from praat_ai.process import process_alive, process_identity


class ProcessAliveTests(unittest.TestCase):
    """`os.kill (pid, 0)` 在本机对任何 PID 都报 winerror=87，必须换实现。"""

    def test_current_process_is_alive(self) -> None:
        self.assertTrue(process_alive(os.getpid()))

    def test_unknown_process_is_not_alive(self) -> None:
        self.assertFalse(process_alive(999999))
        self.assertFalse(process_alive(0))
        self.assertFalse(process_alive(None))

    def test_current_process_has_verifiable_identity(self) -> None:
        identity = process_identity(os.getpid())
        self.assertIsNotNone(identity)
        self.assertTrue(identity["executable"])
        self.assertTrue(identity["started"])


class StopVerificationTests(unittest.TestCase):
    """只有确认服务真的停了才删 pid 文件，避免再次出现「文件没了服务还在」。"""

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.pid_file = Path(self._temp.name) / "qwen.pid"
        self.pid_file.write_text("4242", encoding="utf-8")
        self.config = AppConfig()
        self.config.server.llama_server = r"D:\x\llama-server.exe"
        self.config.server.port = 8000
        self.patch_pid = patch.object(control, "pid_path", return_value=self.pid_file)
        self.patch_pid.start()

    def tearDown(self) -> None:
        self.patch_pid.stop()
        self._temp.cleanup()

    def _record(self, *, executable: str, started: str = "100") -> None:
        self.pid_file.write_text(
            json.dumps({"pid": 4242, "executable": executable, "started": started}),
            encoding="utf-8",
        )

    def test_record_writer_saves_executable_and_creation_token(self) -> None:
        identity = {"executable": self.config.server.llama_server, "started": "100"}
        with patch.object(control, "process_identity", return_value=identity):
            control._write_pid_record(4242)
        self.assertEqual(json.loads(self.pid_file.read_text(encoding="utf-8")), {
            "pid": 4242, **identity
        })

    def test_pid_record_replace_failure_keeps_the_previous_record(self) -> None:
        previous = '{"pid": 1111, "executable": "old", "started": "99"}'
        self.pid_file.write_text(previous, encoding="utf-8")
        identity = {"executable": self.config.server.llama_server, "started": "100"}
        with (
            patch.object(control, "process_identity", return_value=identity),
            patch.object(control.os, "replace", side_effect=OSError("disk full")),
        ):
            with self.assertRaisesRegex(OSError, "disk full"):
                control._write_pid_record(4242)
        self.assertEqual(self.pid_file.read_text(encoding="utf-8"), previous)
        self.assertEqual(list(self.pid_file.parent.glob("qwen.pid.*.tmp")), [])

    def test_legacy_pid_file_is_removed_without_terminating_its_current_owner(self) -> None:
        self.pid_file.write_text("4242", encoding="utf-8")
        with patch.object(control, "_kill_process") as kill:
            self.assertFalse(control._stop_running_service())
        kill.assert_not_called()
        self.assertFalse(self.pid_file.exists())

    def test_malformed_identity_record_fails_closed(self) -> None:
        self.pid_file.write_text('{"pid": null}', encoding="utf-8")
        with patch.object(control, "_kill_process") as kill:
            self.assertFalse(control._stop_running_service())
        kill.assert_not_called()
        self.assertFalse(self.pid_file.exists())

    def test_reused_pid_with_another_executable_is_not_killed(self) -> None:
        self._record(executable=self.config.server.llama_server)
        with (
            patch.object(control, "process_identity", create=True, return_value={
                "executable": r"D:\other\llama-server.exe", "started": "100"
            }),
            patch.object(control, "_kill_process") as kill,
        ):
            self.assertFalse(control._stop_running_service())
        kill.assert_not_called()

    def test_reused_pid_with_same_path_but_new_start_is_not_killed(self) -> None:
        self._record(executable=self.config.server.llama_server)
        with (
            patch.object(control, "process_identity", create=True, return_value={
                "executable": self.config.server.llama_server, "started": "101"
            }),
            patch.object(control, "_kill_process") as kill,
        ):
            self.assertFalse(control._stop_running_service())
        kill.assert_not_called()

    def test_verified_pid_can_stop_without_a_config_argument(self) -> None:
        self._record(executable=self.config.server.llama_server)
        with (
            patch.object(control, "process_identity", create=True, return_value={
                "executable": self.config.server.llama_server, "started": "100"
            }),
            patch.object(control, "_kill_process") as kill,
            patch.object(control, "_wait_for_process_exit", return_value=True),
        ):
            self.assertTrue(control._stop_running_service())
        kill.assert_called_once_with(4242, {
            "pid": 4242,
            "executable": self.config.server.llama_server,
            "started": "100",
        })

    def test_pid_file_is_removed_when_the_process_is_gone(self) -> None:
        self._record(executable=self.config.server.llama_server)
        with (
            patch.object(control, "process_identity", return_value={
                "executable": self.config.server.llama_server, "started": "100"
            }),
            patch.object(control, "_kill_process", return_value=True),
            patch.object(control, "_wait_for_process_exit", return_value=True),
        ):
            self.assertTrue(control._stop_running_service())
        self.assertFalse(self.pid_file.is_file())

    def test_pid_file_is_kept_when_the_process_survives(self) -> None:
        self._record(executable=self.config.server.llama_server)
        with (
            patch.object(control, "process_identity", return_value={
                "executable": self.config.server.llama_server, "started": "100"
            }),
            patch.object(control, "_kill_process", return_value=True),
            patch.object(control, "_wait_for_process_exit", return_value=False),
        ):
            self.assertFalse(control._stop_running_service())
        self.assertTrue(self.pid_file.is_file())

    def test_failed_kill_keeps_record_without_port_fallback(self) -> None:
        self._record(executable=self.config.server.llama_server)
        with (
            patch.object(control, "process_identity", return_value={
                "executable": self.config.server.llama_server, "started": "100"
            }),
            patch.object(control, "_kill_process", return_value=False),
        ):
            self.assertFalse(control._stop_running_service())
        self.assertTrue(self.pid_file.is_file())


class StopFrontendOwnershipTests(unittest.TestCase):
    def test_stop_frontend_does_not_kill_a_service_without_identity_record(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            runtime = directory / "runtime"
            runtime.mkdir()
            config_path = directory / "ai_config.json"
            config_path.write_text(
                '{"server": {"llama_server": "D:/x/llama-server.exe", "port": 8000}}',
                encoding="utf-8",
            )
            with (
                patch.object(control, "runtime_dir", return_value=runtime),
                patch.object(control, "status_path", return_value=runtime / "status.json"),
                patch.object(control, "pid_path", return_value=runtime / "qwen.pid"),
                patch.object(control, "detect_gpu", return_value=None),
                patch.object(control, "endpoint_available", return_value=False),
                patch.object(control, "_kill_process") as kill,
            ):
                control.stop_frontend(config_path)
        kill.assert_not_called()


class ChatWindowReuseTests(unittest.TestCase):
    def test_existing_window_is_focused_instead_of_silently_returning(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            runtime = Path(raw)
            (runtime / "chat.pid").write_text("4242", encoding="utf-8")
            with (
                patch.object(start_ai_chat, "process_alive", return_value=True),
                patch.object(start_ai_chat, "focus_existing_window") as focus,
                patch.object(start_ai_chat.subprocess, "Popen") as popen,
            ):
                self.assertEqual(start_ai_chat.main(runtime), 0)
            focus.assert_called_once_with(4242)
            popen.assert_not_called()

    def test_stale_pid_file_starts_a_new_window(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            runtime = Path(raw)
            pid_file = runtime / "chat.pid"
            pid_file.write_text("4242", encoding="utf-8")
            fake_process = type("FakeProcess", (), {"pid": 777})()
            with (
                patch.object(start_ai_chat, "process_alive", return_value=False),
                patch.object(start_ai_chat, "focus_existing_window") as focus,
                patch.object(
                    start_ai_chat.subprocess,
                    "Popen",
                    return_value=fake_process,
                ) as popen,
            ):
                self.assertEqual(start_ai_chat.main(runtime), 0)
            popen.assert_called_once()
            focus.assert_not_called()
            self.assertEqual(pid_file.read_text(encoding="utf-8").strip(), "777")

    def test_focus_is_a_no_operation_off_windows(self) -> None:
        with patch.object(start_ai_chat.os, "name", "posix"):
            self.assertFalse(start_ai_chat.focus_existing_window(1234))


if __name__ == "__main__":
    unittest.main()
