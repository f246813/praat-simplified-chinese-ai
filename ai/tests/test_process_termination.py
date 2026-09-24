"""Identity checks must guard every platform's process termination path."""

import os
import signal
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from praat_ai import process


IDENTITY = {"executable": r"C:\models\llama-server.exe", "started": "100"}


class ProcessTerminationTests(unittest.TestCase):
    def test_windows_does_not_terminate_a_reused_pid(self) -> None:
        kernel32 = SimpleNamespace(
            OpenProcess=Mock(return_value=123),
            TerminateProcess=Mock(return_value=True),
            CloseHandle=Mock(),
        )
        fake_os = SimpleNamespace(name="nt", path=os.path)
        with (
            patch.object(process, "os", fake_os),
            patch("ctypes.WinDLL", return_value=kernel32, create=True),
            patch.object(
                process,
                "_windows_identity_from_handle",
                return_value={"executable": IDENTITY["executable"], "started": "101"},
            ),
        ):
            self.assertFalse(process.terminate_process_if_identity_matches(4242, IDENTITY))
        kernel32.TerminateProcess.assert_not_called()
        kernel32.CloseHandle.assert_called_once_with(123)

    def test_windows_terminates_a_verified_process(self) -> None:
        kernel32 = SimpleNamespace(
            OpenProcess=Mock(return_value=123),
            TerminateProcess=Mock(return_value=True),
            CloseHandle=Mock(),
        )
        fake_os = SimpleNamespace(name="nt", path=os.path)
        with (
            patch.object(process, "os", fake_os),
            patch("ctypes.WinDLL", return_value=kernel32, create=True),
            patch.object(process, "_windows_identity_from_handle", return_value=IDENTITY),
        ):
            self.assertTrue(process.terminate_process_if_identity_matches(4242, IDENTITY))
        kernel32.TerminateProcess.assert_called_once_with(123, 1)
        kernel32.CloseHandle.assert_called_once_with(123)

    def test_pidfd_path_checks_identity_before_signalling(self) -> None:
        fake_os = SimpleNamespace(
            name="posix",
            path=os.path,
            pidfd_open=Mock(return_value=7),
            close=Mock(),
        )
        fake_signal = SimpleNamespace(
            SIGTERM=signal.SIGTERM,
            pidfd_send_signal=Mock(),
        )
        observed = {"executable": IDENTITY["executable"], "started": "101"}
        with (
            patch.object(process, "os", fake_os),
            patch.object(process, "signal", fake_signal),
            patch.object(process, "process_identity", return_value=observed),
        ):
            self.assertFalse(process.terminate_process_if_identity_matches(4242, IDENTITY))
        fake_signal.pidfd_send_signal.assert_not_called()
        fake_os.close.assert_called_once_with(7)

    def test_pidfd_path_signals_a_verified_process_once(self) -> None:
        fake_os = SimpleNamespace(
            name="posix",
            path=os.path,
            pidfd_open=Mock(return_value=7),
            close=Mock(),
        )
        fake_signal = SimpleNamespace(
            SIGTERM=signal.SIGTERM,
            pidfd_send_signal=Mock(),
        )
        with (
            patch.object(process, "os", fake_os),
            patch.object(process, "signal", fake_signal),
            patch.object(process, "process_identity", return_value=IDENTITY),
        ):
            self.assertTrue(process.terminate_process_if_identity_matches(4242, IDENTITY))
        fake_signal.pidfd_send_signal.assert_called_once_with(7, signal.SIGTERM)
        fake_os.close.assert_called_once_with(7)

    def test_pidfd_open_failure_falls_back_to_identity_checked_kill(self) -> None:
        fake_os = SimpleNamespace(
            name="posix",
            path=os.path,
            pidfd_open=Mock(side_effect=OSError(38, "Function not implemented")),
            close=Mock(),
            kill=Mock(),
        )
        fake_signal = SimpleNamespace(
            SIGTERM=signal.SIGTERM,
            pidfd_send_signal=Mock(),
        )
        with (
            patch.object(process, "os", fake_os),
            patch.object(process, "signal", fake_signal),
            patch.object(process, "process_identity", return_value=IDENTITY),
        ):
            self.assertTrue(process.terminate_process_if_identity_matches(4242, IDENTITY))
        fake_os.kill.assert_called_once_with(4242, signal.SIGTERM)
        fake_signal.pidfd_send_signal.assert_not_called()

    def test_posix_fallback_does_not_signal_a_reused_pid(self) -> None:
        fake_os = SimpleNamespace(name="posix", path=os.path, kill=Mock())
        fake_signal = SimpleNamespace(SIGTERM=signal.SIGTERM)
        observed = {"executable": IDENTITY["executable"], "started": "101"}
        with (
            patch.object(process, "os", fake_os),
            patch.object(process, "signal", fake_signal),
            patch.object(process, "process_identity", return_value=observed),
        ):
            self.assertFalse(process.terminate_process_if_identity_matches(4242, IDENTITY))
        fake_os.kill.assert_not_called()

    def test_posix_fallback_signals_a_verified_process_once(self) -> None:
        fake_os = SimpleNamespace(name="posix", path=os.path, kill=Mock())
        fake_signal = SimpleNamespace(SIGTERM=signal.SIGTERM)
        with (
            patch.object(process, "os", fake_os),
            patch.object(process, "signal", fake_signal),
            patch.object(process, "process_identity", return_value=IDENTITY),
        ):
            self.assertTrue(process.terminate_process_if_identity_matches(4242, IDENTITY))
        fake_os.kill.assert_called_once_with(4242, signal.SIGTERM)


if __name__ == "__main__":
    unittest.main()
