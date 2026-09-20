import unittest

from praat_ai.qwen import extract_json_object


class QwenTests(unittest.TestCase):
    def test_json_object_is_extracted_from_markdown(self) -> None:
        value = extract_json_object('```json\n{"language": "cmn"}\n```')
        self.assertEqual(value["language"], "cmn")

    def test_json_object_is_extracted_from_explanation(self) -> None:
        value = extract_json_object('Here is the result: {"ok": true} done')
        self.assertTrue(value["ok"])


if __name__ == "__main__":
    unittest.main()
