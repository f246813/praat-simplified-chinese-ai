"""自己投递 Praat 脚本（不激活窗口）的关键行为。

老路子 ``Praat.exe --send`` 会对 ``FindWindow("PraatChildWindow…")`` 找到的
窗口做 ``ShowWindow(SW_RESTORE) + SetForegroundWindow``，所以每发一条指令都会
弹出 Praat Info / 把声音编辑器顶到前面。回归用例守着新的投递方式：
消息文件内容、目标窗口选择、超时取消、以及 ``argv`` 兜底开关。
"""

import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from praat_ai import chat, sendpraat


class FakeUser32:
    def __init__(self, post_result: int = 1) -> None:
        self.post_result = post_result
        self.posted: list[tuple[int, int]] = []

    def PostMessageW(self, handle, message, wparam, lparam) -> int:   # noqa: N802
        self.posted.append((int(handle), int(message)))
        return self.post_result


def make_window(handle: int, pid: int, title: str, class_name: str = "PraatChildWindow1 Praat"):
    return sendpraat.WindowInfo(
        handle=handle,
        process_id=pid,
        class_name=class_name,
        title=title,
        visible=True,
        minimized=True,
    )


class MessageTests(unittest.TestCase):
    def test_message_matches_what_send_writes(self) -> None:
        message = sendpraat.build_message(
            Path("D:/Praat-work/praat-simplified-chinese/ai"),
            Path("D:/Praat-work/praat-simplified-chinese/ai/runtime/chat_command.praat"),
        )
        # praat_executeScript_noGUI() 靠这一行给完全信任（脚本要写 runtime/ 之外的路径）。
        self.assertTrue(message.startswith("\n# --FULL-TRUST\n"))
        self.assertIn(
            'setWorkingDirectory: "D:/Praat-work/praat-simplified-chinese/ai"', message
        )
        self.assertIn(
            'runScript: "D:/Praat-work/praat-simplified-chinese/ai/runtime/chat_command.praat"',
            message,
        )

    def test_backslashes_and_quotes_are_escaped(self) -> None:
        message = sendpraat.build_message(Path(r"C:\a\b"), Path(r'C:\a"b\c.praat'))
        self.assertIn('setWorkingDirectory: "C:/a/b"', message)
        self.assertIn('runScript: "C:/a""b/c.praat"', message)

    def test_noop_message_has_trust_marker_and_does_nothing(self) -> None:
        message = sendpraat.noop_message()
        self.assertTrue(message.startswith("\n# --FULL-TRUST\n"))
        self.assertNotIn("runScript", message)
        for line in message.splitlines():
            self.assertTrue(line == "" or line.startswith("#"))


class ModeTests(unittest.TestCase):
    def test_default_mode_is_window(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(sendpraat.send_mode(), sendpraat.WINDOW_MODE)

    def test_env_var_switches_to_argv(self) -> None:
        with patch.dict(os.environ, {sendpraat.SEND_MODE_ENV: "argv"}):
            self.assertEqual(sendpraat.send_mode(), sendpraat.ARGV_MODE)

    def test_message_file_follows_appdata(self) -> None:
        with patch.dict(os.environ, {"APPDATA": r"D:\roaming"}, clear=True):
            self.assertEqual(
                sendpraat.message_file_path(), Path(r"D:\roaming\Praat\Message.txt")
            )

    def test_non_windows_has_no_message_file(self) -> None:
        with patch.object(sendpraat, "os", types.SimpleNamespace(name="posix")):
            self.assertIsNone(sendpraat.message_file_path())

    def test_non_windows_falls_back_to_argv(self) -> None:
        """macOS/Linux 上没有 Message.txt + WM_APP 这套协议，走老的 --send。"""

        fake_os = types.SimpleNamespace(name="posix", getenv=lambda *_a, **_k: "")
        with patch.object(sendpraat, "os", fake_os):
            self.assertEqual(sendpraat.send_mode(), sendpraat.ARGV_MODE)


class WindowChoiceTests(unittest.TestCase):
    def test_objects_window_is_preferred(self) -> None:
        windows = [
            make_window(1, 100, "Praat Info"),
            make_window(2, 100, "1. Sound tone"),
            make_window(3, 100, "Praat Objects", "PraatShell1 Praat"),
        ]
        chosen = sendpraat.choose_window(windows)
        self.assertEqual(chosen.handle, 3)

    def test_newest_praat_wins(self) -> None:
        windows = [make_window(1, 100, "Praat Info"), make_window(2, 200, "Praat Info")]
        self.assertEqual(sendpraat.choose_window(windows).process_id, 200)

    def test_explicit_process_wins(self) -> None:
        windows = [make_window(1, 100, "Praat Info"), make_window(2, 200, "Praat Info")]
        self.assertEqual(sendpraat.choose_window(windows, 100).process_id, 100)

    def test_no_window_returns_none(self) -> None:
        self.assertIsNone(sendpraat.choose_window([]))

    def test_praat_window_class_prefix(self) -> None:
        self.assertTrue(make_window(1, 2, "x").is_praat_window)
        self.assertFalse(
            sendpraat.WindowInfo(1, 2, "Chrome_WidgetWin_1", "x", True, False).is_praat_window
        )


class DeliverTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.message_path = Path(self._temp.name) / "Praat" / "Message.txt"
        self.user32 = FakeUser32()
        self.patches = [
            patch.object(sendpraat, "message_file_path", return_value=self.message_path),
            patch.object(sendpraat, "_user32", return_value=self.user32),
            patch.object(
                sendpraat,
                "praat_windows",
                return_value=[
                    make_window(11, 100, "Praat Info"),
                    make_window(12, 100, "Praat Objects", "PraatShell1 Praat"),
                ],
            ),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self._temp.cleanup()

    def test_deliver_writes_message_and_posts_once(self) -> None:
        script = Path(self._temp.name) / "chat_command.praat"
        ok, note = sendpraat.deliver(Path(self._temp.name), script)
        self.assertTrue(ok)
        self.assertEqual(note, "")
        self.assertEqual(self.user32.posted, [(12, sendpraat.WM_APP)])
        self.assertIn("runScript", self.message_path.read_text(encoding="utf-8"))

    def test_deliver_reports_a_closed_window(self) -> None:
        self.user32.post_result = 0
        ok, note = sendpraat.deliver(Path(self._temp.name), Path("x.praat"))
        self.assertFalse(ok)
        self.assertIn("发消息失败", note)

    def test_deliver_without_praat_is_reported(self) -> None:
        with patch.object(sendpraat, "praat_windows", return_value=[]):
            ok, note = sendpraat.deliver(Path(self._temp.name), Path("x.praat"))
        self.assertFalse(ok)
        self.assertIn("没有找到正在运行的 Praat", note)

    def test_cancel_pending_replaces_the_message(self) -> None:
        script = Path(self._temp.name) / "chat_command.praat"
        sendpraat.deliver(Path(self._temp.name), script)
        self.assertTrue(sendpraat.cancel_pending())
        self.assertEqual(
            self.message_path.read_text(encoding="utf-8"), sendpraat.noop_message()
        )

    def test_cancel_pending_without_message_does_nothing(self) -> None:
        self.assertFalse(sendpraat.cancel_pending())


class ChatIntegrationTests(unittest.TestCase):
    """对话窗口投递时用的是新模块，而且默认不带 --send 的窗口激活副作用。"""

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.runtime = Path(self._temp.name)
        self.patch_runtime = patch.object(chat, "runtime_dir", return_value=self.runtime)
        self.patch_runtime.start()
        # 别让超时分支去动真实的 %APPDATA%\Praat\Message.txt。
        self.patch_cancel = patch.object(chat.sendpraat, "cancel_pending", return_value=True)
        self.cancelled = self.patch_cancel.start()

    def tearDown(self) -> None:
        self.patch_cancel.stop()
        self.patch_runtime.stop()
        self._temp.cleanup()

    def test_chat_delivers_through_sendpraat(self) -> None:
        with patch.object(chat.sendpraat, "deliver", return_value=(True, "")) as fake, patch.object(
            chat, "EXECUTION_TIMEOUT_SEC", 0.2
        ):
            ok, note = chat._send_script("Praat.exe", 'appendFileLine: "x", "y"\n')
        self.assertFalse(ok)   # 没人写状态文件 → 超时
        fake.assert_called_once()
        self.assertEqual(fake.call_args.args[0], chat.ai_directory())
        self.assertEqual(fake.call_args.args[1], chat.script_path())
        # 超时后要把排队中的消息换成空脚本，免得它去执行下一条指令。
        self.cancelled.assert_called_once()


if __name__ == "__main__":
    unittest.main()
