"""找 Praat 可执行文件：候选顺序、环境变量、缓存与重试。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from praat_ai import chat, praat_app


class LocatorTests(unittest.TestCase):
    def setUp(self) -> None:
        praat_app.reset_cache()
        self._temp = tempfile.TemporaryDirectory()
        self.directory = Path(self._temp.name)
        self.fake = self.directory / "Praat.exe"
        self.fake.write_bytes(b"not really praat")

    def tearDown(self) -> None:
        praat_app.reset_cache()
        self._temp.cleanup()

    def test_repo_build_is_tried_first(self) -> None:
        """这个 fork 自己构建的 Praat.exe 排在最前面。"""

        candidates = praat_app.candidate_paths()
        self.assertEqual(candidates[0], praat_app.project_root() / "Praat.exe")

    def test_explicit_path_wins(self) -> None:
        self.assertEqual(praat_app.find_praat(str(self.fake)), str(self.fake))

    def test_env_override_wins(self) -> None:
        with patch.dict(os.environ, {praat_app.EXECUTABLE_ENV: str(self.fake)}):
            self.assertEqual(praat_app.find_praat(), str(self.fake))

    def test_explicit_path_that_does_not_exist_is_empty(self) -> None:
        """用户指了路径但文件不在：返回空串，别偷偷用别的 Praat。"""

        self.assertEqual(praat_app.find_praat(str(self.directory / "nope.exe")), "")

    def test_first_existing_candidate_is_used(self) -> None:
        missing = self.directory / "missing.exe"
        with patch.object(
            praat_app, "candidate_paths", return_value=[missing, self.fake]
        ):
            self.assertEqual(praat_app.find_praat(), str(self.fake))

    def test_found_result_is_cached(self) -> None:
        with patch.object(
            praat_app, "candidate_paths", return_value=[self.fake]
        ) as candidates:
            self.assertEqual(praat_app.find_praat(), str(self.fake))
            self.assertEqual(praat_app.find_praat(), str(self.fake))
        self.assertEqual(candidates.call_count, 1)

    def test_not_found_is_cached_until_the_retry_interval(self) -> None:
        """没找到也缓存：30 秒内不重复搜盘；reset 之后可以立刻再搜一次。"""

        with patch.object(praat_app, "candidate_paths", return_value=[]) as candidates, patch.object(
            praat_app, "_on_path", return_value=None
        ):
            self.assertEqual(praat_app.find_praat(), "")
            self.assertEqual(praat_app.find_praat(), "")
            self.assertEqual(candidates.call_count, 1)
            praat_app.reset_cache()
            self.assertEqual(praat_app.find_praat(), "")
            self.assertEqual(candidates.call_count, 2)

    def test_not_found_is_retried_after_the_interval(self) -> None:
        with patch.object(praat_app, "candidate_paths", return_value=[]) as candidates, patch.object(
            praat_app, "_on_path", return_value=None
        ), patch.object(praat_app.time, "monotonic", side_effect=[0.0, 0.0, 100.0]):
            praat_app.find_praat()   # 第一次搜盘
            praat_app.find_praat()   # 30 秒内：用缓存
            praat_app.find_praat()   # 过了重试间隔：再搜一次（用户中途装了 Praat）
            self.assertEqual(candidates.call_count, 2)

    def test_path_search_is_the_last_resort(self) -> None:
        with patch.object(praat_app, "candidate_paths", return_value=[]), patch.object(
            praat_app, "_on_path", return_value=self.fake
        ):
            self.assertEqual(praat_app.find_praat(), str(self.fake))

    def test_describe_search_lists_where_it_looked(self) -> None:
        with patch.object(praat_app, "candidate_paths", return_value=[]), patch.object(
            praat_app, "_on_path", return_value=None
        ):
            text = praat_app.describe_search()
        self.assertIn("没有找到 Praat.exe", text)
        self.assertIn(praat_app.EXECUTABLE_ENV, text)


class ChatDelegationTests(unittest.TestCase):
    def test_chat_uses_the_locator(self) -> None:
        with patch.object(praat_app, "find_praat", return_value="D:/fake/Praat.exe") as finder:
            self.assertEqual(chat.praat_executable(), "D:/fake/Praat.exe")
        finder.assert_called_once()


if __name__ == "__main__":
    unittest.main()
