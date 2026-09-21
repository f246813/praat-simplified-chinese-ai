"""C5：对象列表已经对应这个 Praat 进程时，不要再送那条 ping 往返。

以前每条用户消息都先投一条空脚本刷新 ``chat_context.tsv``（投递 + 等待 = 一次完整
往返，出错还可能白等 25 秒）。现在 Praat 在对象列表文件末尾写上自己的进程号
（``# praat-pid=…``），前端一看标记就是当前这个 Praat，就直接用文件，不再往返。
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from praat_ai import chat


CONTEXT_WITH_PID = (
    "id\tclass\tname\tselected\n"
    "1\tSound\tSound tone\t1\n"
    "# praat-pid=4242\n"
)
CONTEXT_OTHER_PID = (
    "id\tclass\tname\tselected\n"
    "1\tSound\tSound tone\t1\n"
    "# praat-pid=1111\n"
)
CONTEXT_WITHOUT_PID = "id\tclass\tname\tselected\n1\tSound\tSound tone\t1\n"


class PidMarkerTests(unittest.TestCase):
    def test_marker_is_parsed(self) -> None:
        self.assertEqual(chat.context_pid(CONTEXT_WITH_PID), 4242)
        self.assertEqual(chat.context_pid(CONTEXT_WITHOUT_PID), 0)
        self.assertEqual(chat.context_pid(""), 0)

    def test_marker_does_not_break_object_parsing(self) -> None:
        from praat_ai import tools

        rows = tools.parse_object_context(CONTEXT_WITH_PID)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].name, "Sound tone")

    def test_default_argument_reads_the_context_file(self) -> None:
        """不给参数时要读 chat_context.tsv（真机回归抓到的 bug：默认参数走了空字符串）。"""

        with patch.object(chat, "object_context", return_value=CONTEXT_WITH_PID) as read:
            self.assertEqual(chat.context_pid(), 4242)
        read.assert_called_once()
        with patch.object(
            chat, "object_context", return_value=CONTEXT_WITHOUT_PID
        ):
            self.assertEqual(chat.context_pid(), 0)
        with patch.object(chat, "object_context", return_value=""):
            self.assertEqual(chat.context_pid(), 0)


class RefreshDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "chat_context.tsv"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def refresh(
        self,
        *,
        process_ids=None,
        force=False,
        assume_fresh=False,
        text=CONTEXT_WITH_PID,
    ):
        if text is not None:
            self.path.write_text(text, encoding="utf-8")
        with patch.object(chat, "context_path", return_value=self.path), patch.object(
            chat, "_send_script", return_value=(True, "")
        ) as send:
            result = chat.refresh_object_context(
                "Praat.exe",
                process_ids,
                force=force,
                assume_fresh=assume_fresh,
            )
        return result, send

    def test_fresh_context_does_not_deliver_anything(self) -> None:
        """列表就是当前这个 Praat 写的：一次往返都不该有。"""

        (ok, note), send = self.refresh(process_ids=[4242])
        self.assertTrue(ok)
        self.assertEqual(note, "")
        send.assert_not_called()

    def test_another_praat_instance_triggers_one_refresh(self) -> None:
        (ok, _note), send = self.refresh(process_ids=[9999])
        self.assertTrue(ok)
        send.assert_called_once()

    def test_context_without_a_marker_still_refreshes(self) -> None:
        """老版本 / 别人的 Praat 不写标记：保持原来的行为（刷一次）。"""

        (ok, _note), send = self.refresh(
            process_ids=[4242], text=CONTEXT_WITHOUT_PID
        )
        self.assertTrue(ok)
        send.assert_called_once()

    def test_missing_context_file_refreshes(self) -> None:
        (ok, _note), send = self.refresh(process_ids=[4242], text=None)
        self.assertTrue(ok)
        send.assert_called_once()

    def test_force_refreshes_even_when_fresh(self) -> None:
        (ok, _note), send = self.refresh(process_ids=[4242], force=True)
        self.assertTrue(ok)
        send.assert_called_once()

    def test_assume_fresh_skips_the_ping_for_older_praat_builds(self) -> None:
        """老版本 Praat 不写标记，但「这一轮之前投递过脚本」同样说明列表是新的。"""

        (ok, note), send = self.refresh(
            process_ids=[4242], assume_fresh=True, text=CONTEXT_WITHOUT_PID
        )
        self.assertTrue(ok)
        self.assertEqual(note, "")
        send.assert_not_called()

    def test_assume_fresh_still_refreshes_when_the_file_is_gone(self) -> None:
        (ok, _note), send = self.refresh(
            process_ids=[4242], assume_fresh=True, text=None
        )
        self.assertTrue(ok)
        send.assert_called_once()

    def test_no_praat_running_is_not_an_error(self) -> None:
        (ok, note), send = self.refresh(process_ids=[])
        self.assertFalse(ok)
        self.assertEqual(note, "")
        send.assert_not_called()

    def test_failed_refresh_reports_in_chinese(self) -> None:
        self.path.write_text(CONTEXT_OTHER_PID, encoding="utf-8")
        with patch.object(chat, "context_path", return_value=self.path), patch.object(
            chat, "_send_script", return_value=(False, "")
        ):
            ok, note = chat.refresh_object_context("Praat.exe", [4242])
        self.assertFalse(ok)
        self.assertIn("没有响应", note)

    def test_marker_from_a_second_praat_counts(self) -> None:
        """同时开着两个 Praat 时，只要标记是其中之一就不用刷。"""

        (ok, _note), send = self.refresh(process_ids=[4242, 777])
        self.assertTrue(ok)
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
