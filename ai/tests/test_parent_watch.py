"""关掉 Praat 之后，前端窗口要跟着退（2026-09-21 用户报的 bug）。"""

import os
import unittest
from unittest.mock import patch

from praat_ai import parent_watch


class ParentPidTests(unittest.TestCase):
    def test_pid_is_read_from_the_environment(self) -> None:
        with patch.dict(os.environ, {"PRAAT_AI_PRAAT_PID": " 1234 "}):
            self.assertEqual(parent_watch.parent_pid(), 1234)

    def test_bad_or_missing_pid_is_ignored(self) -> None:
        for value in ("", "abc", "0", "-5"):
            with patch.dict(os.environ, {"PRAAT_AI_PRAAT_PID": value}):
                self.assertIsNone(parent_watch.parent_pid())
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(parent_watch.parent_pid())

    def test_executable_comes_from_the_environment(self) -> None:
        with patch.dict(os.environ, {"PRAAT_AI_PRAAT_EXECUTABLE": r"D:\x\Praat.exe"}):
            self.assertEqual(parent_watch.praat_executable(), r"D:\x\Praat.exe")
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(parent_watch.praat_executable("default.exe"), "default.exe")


class PraatAliveTests(unittest.TestCase):
    def test_the_launcher_pid_is_authoritative(self) -> None:
        with (
            patch.dict(os.environ, {"PRAAT_AI_PRAAT_PID": "4321"}),
            patch.object(parent_watch, "process_alive", return_value=False) as alive,
        ):
            self.assertFalse(parent_watch.praat_alive())
        alive.assert_called_once_with(4321)

    def test_without_a_pid_the_process_table_is_used(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            for ids, expected in (([7], True), ([], False), (None, None)):
                with patch("praat_ai.chat.praat_process_ids", return_value=ids):
                    self.assertIs(parent_watch.praat_alive(), expected)

    def test_watching_is_skipped_when_no_praat_is_running(self) -> None:
        """手工起对话窗口做开发时没有 Praat，别自己把自己关掉。"""

        with patch.dict(os.environ, {}, clear=True):
            with patch("praat_ai.chat.praat_process_ids", return_value=[]):
                self.assertFalse(parent_watch.should_watch())
            with patch("praat_ai.chat.praat_process_ids", return_value=[9]):
                self.assertTrue(parent_watch.should_watch())
        with patch.dict(os.environ, {"PRAAT_AI_PRAAT_PID": "5"}):
            self.assertTrue(parent_watch.should_watch())


class FakeWindow:
    def __init__(self) -> None:
        self.scheduled: list[int] = []
        self.destroyed = False

    def after(self, milliseconds: int, _callback) -> str:
        self.scheduled.append(milliseconds)
        return "after#1"

    def destroy(self) -> None:
        self.destroyed = True


class ParentWatcherTests(unittest.TestCase):
    def test_window_is_closed_when_praat_is_gone(self) -> None:
        window = FakeWindow()
        with patch.object(parent_watch, "praat_alive", return_value=False):
            watcher = parent_watch.ParentWatcher(window, grace_sec=0.0)
            watcher.start()
            watcher._tick()
        self.assertTrue(window.destroyed)
        self.assertTrue(watcher.stopped)

    def test_window_survives_while_praat_is_running(self) -> None:
        window = FakeWindow()
        with patch.object(parent_watch, "praat_alive", return_value=True):
            watcher = parent_watch.ParentWatcher(window, grace_sec=0.0)
            watcher.start()
            watcher._tick()
        self.assertFalse(window.destroyed)
        self.assertGreaterEqual(len(window.scheduled), 2)   # 还会继续轮询

    def test_unknown_state_never_closes_the_window(self) -> None:
        window = FakeWindow()
        with patch.object(parent_watch, "praat_alive", return_value=None):
            watcher = parent_watch.ParentWatcher(window, grace_sec=0.0)
            watcher.start()
            watcher._tick()
        self.assertFalse(window.destroyed)

    def test_grace_period_delays_the_first_check(self) -> None:
        window = FakeWindow()
        with patch.object(parent_watch, "praat_alive") as probe:
            watcher = parent_watch.ParentWatcher(window, grace_sec=30.0)
            watcher.start()
            watcher._tick()
        probe.assert_not_called()
        self.assertFalse(window.destroyed)

    def test_on_close_callback_takes_over_the_shutdown(self) -> None:
        """对话窗口要先说一句再关，所以给了 on_close 就不由 watcher 来 destroy。"""

        window = FakeWindow()
        called: list[bool] = []
        with patch.object(parent_watch, "praat_alive", return_value=False):
            watcher = parent_watch.ParentWatcher(
                window, grace_sec=0.0, on_close=lambda: called.append(True)
            )
            watcher.start()
            watcher._tick()
        self.assertEqual(called, [True])
        self.assertFalse(window.destroyed)


if __name__ == "__main__":
    unittest.main()
