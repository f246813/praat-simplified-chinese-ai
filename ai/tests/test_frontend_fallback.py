"""兜底行为：pid 文件丢失时按端口停止服务；对话窗口已存在时置前而不是静默返回。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import start_ai_chat
from praat_ai import control
from praat_ai.config import AppConfig
from praat_ai.process import process_alive


NETSTAT_SAMPLE = """
活动连接

  协议  本地地址          外部地址        状态           PID
  TCP    127.0.0.1:8000         0.0.0.0:0              LISTENING       15068
  TCP    127.0.0.1:8000         127.0.0.1:52100        ESTABLISHED     15068
  TCP    127.0.0.1:5000         0.0.0.0:0              LISTENING       777
  TCP    [::]:8000              [::]:0                 LISTENING       15068
  TCP    127.0.0.1:18000        0.0.0.0:0              LISTENING       888
"""


class NetstatParsingTests(unittest.TestCase):
    def test_finds_listening_pid_for_port(self) -> None:
        self.assertEqual(control._parse_netstat_listening(NETSTAT_SAMPLE, 8000), [15068])

    def test_ignores_other_ports_and_non_listening_rows(self) -> None:
        self.assertEqual(control._parse_netstat_listening(NETSTAT_SAMPLE, 5000), [777])
        self.assertEqual(control._parse_netstat_listening(NETSTAT_SAMPLE, 4321), [])
        self.assertEqual(control._parse_netstat_listening("", 8000), [])
        self.assertEqual(control._parse_netstat_listening(NETSTAT_SAMPLE, 500), [])


class StopByPortTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.pid_file = Path(self._temp.name) / "qwen.pid"   # 故意不存在，模拟 pid 丢失
        self.config = AppConfig()
        self.config.server.llama_server = (
            r"D:\llama.cpp\llama-server.exe"
        )
        self.config.server.port = 8000
        self.patch_pid = patch.object(control, "pid_path", return_value=self.pid_file)
        self.patch_pid.start()

    def tearDown(self) -> None:
        self.patch_pid.stop()
        self._temp.cleanup()

    def test_kills_llama_server_found_by_port(self) -> None:
        with (
            patch.object(control, "_listening_pids", return_value=[15068]),
            patch.object(control, "_process_name", return_value="llama-server.exe"),
            patch.object(control, "_kill_process") as kill,
        ):
            self.assertTrue(control._stop_running_service(self.config))
        kill.assert_called_once_with(15068)

    def test_does_not_kill_another_program_on_the_port(self) -> None:
        with (
            patch.object(control, "_listening_pids", return_value=[4242]),
            patch.object(control, "_process_name", return_value="chrome.exe"),
            patch.object(control, "_kill_process") as kill,
        ):
            self.assertFalse(control._stop_running_service(self.config))
        kill.assert_not_called()

    def test_does_not_kill_when_process_name_is_unknown(self) -> None:
        with (
            patch.object(control, "_listening_pids", return_value=[4242]),
            patch.object(control, "_process_name", return_value=""),
            patch.object(control, "_kill_process") as kill,
        ):
            self.assertFalse(control._stop_running_service(self.config))
        kill.assert_not_called()

    def test_without_config_there_is_no_fallback(self) -> None:
        with patch.object(control, "_listening_pids", return_value=[15068]) as listing:
            self.assertFalse(control._stop_running_service())
        listing.assert_not_called()


class ProcessAliveTests(unittest.TestCase):
    """`os.kill (pid, 0)` 在本机对任何 PID 都报 winerror=87，必须换实现。"""

    def test_current_process_is_alive(self) -> None:
        self.assertTrue(process_alive(os.getpid()))

    def test_unknown_process_is_not_alive(self) -> None:
        self.assertFalse(process_alive(999999))
        self.assertFalse(process_alive(0))
        self.assertFalse(process_alive(None))


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

    def test_pid_file_is_removed_when_the_process_is_gone(self) -> None:
        with (
            patch.object(control, "_kill_process"),
            patch.object(control, "_wait_for_process_exit", return_value=True),
            patch.object(control, "_stop_service_by_port", return_value=False),
        ):
            self.assertTrue(control._stop_running_service(self.config))
        self.assertFalse(self.pid_file.is_file())

    def test_pid_file_is_kept_when_the_process_survives(self) -> None:
        with (
            patch.object(control, "_kill_process"),
            patch.object(control, "_wait_for_process_exit", return_value=False),
            patch.object(control, "_stop_service_by_port", return_value=False),
        ):
            self.assertFalse(control._stop_running_service(self.config))
        self.assertTrue(self.pid_file.is_file())

    def test_port_fallback_runs_when_the_kill_did_not_take_effect(self) -> None:
        with (
            patch.object(control, "_kill_process"),
            patch.object(control, "_wait_for_process_exit", return_value=False),
            patch.object(control, "_stop_service_by_port", return_value=True) as by_port,
        ):
            self.assertTrue(control._stop_running_service(self.config))
        by_port.assert_called_once()
        self.assertFalse(self.pid_file.is_file())


class StopFrontendFallbackTests(unittest.TestCase):
    def test_stop_frontend_passes_config_to_the_fallback(self) -> None:
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
                patch.object(control, "_listening_pids", return_value=[999]),
                patch.object(control, "_process_name", return_value="llama-server.exe"),
                patch.object(control, "_kill_process") as kill,
            ):
                control.stop_frontend(config_path)
        kill.assert_called_once_with(999)


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
