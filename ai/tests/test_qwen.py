import unittest
import urllib.error

from praat_ai.qwen import connection_hint, extract_json_object


class QwenTests(unittest.TestCase):
    def test_json_object_is_extracted_from_markdown(self) -> None:
        value = extract_json_object('```json\n{"language": "cmn"}\n```')
        self.assertEqual(value["language"], "cmn")

    def test_json_object_is_extracted_from_explanation(self) -> None:
        value = extract_json_object('Here is the result: {"ok": true} done')
        self.assertTrue(value["ok"])


class ConnectionHintTests(unittest.TestCase):
    """连不上本机 llama-server 时，报错要能告诉用户下一步点哪里。

    2026-09-22 用户看到的就是裸的 ``[WinError 10061] 由于目标计算机积极拒绝``：
    他知道失败了，但不知道「去菜单点启动前端」。
    """

    def test_refused_local_connection_points_at_the_menu(self) -> None:
        error = ConnectionRefusedError(
            10061, "由于目标计算机积极拒绝，无法连接。"
        )
        hint = connection_hint("http://127.0.0.1:8000/v1", error)
        self.assertIn("启动前端", hint)
        self.assertIn("预设", hint)
        self.assertIn("127.0.0.1:8000", hint)

    def test_url_error_wrapping_a_refusal_is_recognized(self) -> None:
        error = urllib.error.URLError(
            ConnectionRefusedError(10061, "由于目标计算机积极拒绝，无法连接。")
        )
        self.assertTrue(connection_hint("http://localhost:8000/v1", error))

    def test_a_remote_endpoint_gets_no_local_service_hint(self) -> None:
        error = ConnectionRefusedError(10061, "refused")
        self.assertEqual(connection_hint("https://api.deepseek.com/v1", error), "")

    def test_other_transport_errors_are_not_mistaken_for_a_stopped_service(self) -> None:
        self.assertEqual(
            connection_hint("http://127.0.0.1:8000/v1", TimeoutError("timed out")),
            "",
        )
        self.assertEqual(
            connection_hint("http://127.0.0.1:8000/v1", OSError("unknown host")),
            "",
        )


if __name__ == "__main__":
    unittest.main()
