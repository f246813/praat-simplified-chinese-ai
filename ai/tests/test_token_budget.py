"""A5：上下文按 token 预算裁剪，而且裁剪要看得见（不静默丢内容）。

以前的规矩是死的：历史只带最近 8 条、对象列表整份塞进 system prompt。``ctx`` 是
8192，而工具 schema 本身就有 18k 字符，所以长对话/长对象列表时是**静默**被服务端
截掉的。现在按「预算 = 上下文 − 工具说明 − 回答预留」算，能带多少带多少，被省掉的
部分在 prompts 和 ``TurnOutcome.notes`` 里都写清楚。
"""

import tempfile
import unittest
from pathlib import Path

from praat_ai import chat, qwen, tools


def context_tsv(count: int) -> str:
    rows = "".join(
        f"{index}\tSound\ttone{index}\t{1 if index == 1 else 0}\n"
        for index in range(1, count + 1)
    )
    return "id\tclass\tname\tselected\n" + rows


class EstimateTests(unittest.TestCase):
    def test_ascii_is_cheaper_than_cjk(self) -> None:
        ascii_tokens = qwen.estimate_tokens("a" * 400)
        cjk_tokens = qwen.estimate_tokens("语" * 400)
        self.assertGreater(cjk_tokens, ascii_tokens)
        self.assertLess(ascii_tokens, 200)
        self.assertGreater(cjk_tokens, 300)

    def test_empty_text_is_free(self) -> None:
        self.assertEqual(qwen.estimate_tokens(""), 0)


class BudgetTests(unittest.TestCase):
    def test_history_budget_subtracts_the_instructions_and_the_answer(self) -> None:
        big = qwen.history_budget(
            8192,
            instructions="x" * 4000,
            tool_schemas=[{"function": {"description": "y" * 2000}}],
            user_text="你好",
            response_tokens=700,
        )
        small = qwen.history_budget(
            8192,
            instructions="x" * 4000,
            tool_schemas=[],
            user_text="你好",
            response_tokens=700,
        )
        self.assertLess(big, small)
        self.assertGreater(big, 0)

    def test_budget_never_goes_negative(self) -> None:
        budget = qwen.history_budget(
            512,
            instructions="x" * 100_000,
            tool_schemas=[],
            user_text="你好",
            response_tokens=700,
        )
        self.assertEqual(budget, 0)


class HistoryTrimTests(unittest.TestCase):
    def test_short_history_is_kept_whole(self) -> None:
        history = [
            {"role": "user", "content": "查基频"},
            {"role": "assistant", "content": "基频是 220 Hz。"},
        ]
        messages, dropped = qwen.trim_history(history, max_tokens=1000)
        self.assertEqual(len(messages), 2)
        self.assertEqual(dropped, 0)

    def test_long_history_is_trimmed_by_tokens_and_reports_the_drop(self) -> None:
        history = []
        for index in range(40):
            history.append({"role": "user", "content": "问" * 40 + str(index)})
            history.append({"role": "assistant", "content": "答" * 40 + str(index)})
        messages, dropped = qwen.trim_history(history, max_tokens=400)
        self.assertGreater(dropped, 0)
        self.assertEqual(dropped, len(history) - len(messages))
        # 留下的是**最近**的几条，不是最早的。
        self.assertIn("39", messages[-1]["content"])
        self.assertNotIn("0", messages[0]["content"])

    def test_history_keeps_valid_prefixes_only(self) -> None:
        """留下的必须从某句用户消息开始：截出来的半截回答（开头是 assistant）要丢掉。"""

        history = [
            {"role": "user", "content": "旧问题"},
            {"role": "assistant", "content": "旧回答"},
            {"role": "user", "content": "新问题"},
        ]
        messages, dropped = qwen.trim_history(history, max_tokens=20)
        self.assertEqual([item["role"] for item in messages], ["user"])
        self.assertIn("新问题", messages[0]["content"])
        self.assertEqual(dropped, 2)

    def test_dropped_zero_when_everything_fits(self) -> None:
        history = [{"role": "user", "content": "hi"}]
        messages, dropped = qwen.trim_history(history, max_tokens=500)
        self.assertEqual(dropped, 0)
        self.assertEqual(messages[0]["content"], "hi")


class ObjectContextTrimTests(unittest.TestCase):
    def test_short_list_is_untouched(self) -> None:
        text, hidden = qwen.trim_object_context(context_tsv(3), max_tokens=1000)
        self.assertEqual(hidden, 0)
        self.assertIn("tone3", text)

    def test_long_list_keeps_the_selection_and_says_what_was_hidden(self) -> None:
        text, hidden = qwen.trim_object_context(context_tsv(80), max_tokens=200)
        self.assertGreater(hidden, 0)
        self.assertIn("当前选中是", text)      # 选中对象必须留着（规则 6 靠它）
        self.assertIn("tone1", text)
        self.assertIn("这里只列了", text)
        self.assertIn(f"还有 {hidden} 个没列出", text)

    def test_header_stays_even_when_everything_else_is_trimmed(self) -> None:
        text, hidden = qwen.trim_object_context(context_tsv(50), max_tokens=1)
        self.assertIn("id\tclass\tname", text)
        # 预算再小也留一行（否则「当前选中」都没了），其余全都写清楚省掉了。
        self.assertEqual(hidden, 49)
        self.assertIn("还有 49 个没列出", text)


class TurnNoteTests(unittest.TestCase):
    """裁剪要**看得见**：run_turn 要把省掉的东西写进 TurnOutcome.notes。"""

    class FakeClient:
        def __init__(self, max_context_tokens: int) -> None:
            self.config = qwen.QwenConfig(
                max_context_tokens=max_context_tokens, plan_max_tokens=700
            )

        def chat_message(self, messages, **_kwargs):
            return {"role": "assistant", "content": "这个声音 1 秒。"}

        def chat(self, messages, **_kwargs) -> str:
            return "（收尾）"

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        base = Path(self.directory.name)
        self.context = tools.ToolContext(
            tools.parse_object_context(context_tsv(3)),
            base / "chat_result.tsv",
            base / "chat_state.txt",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def turn(self, *, history, max_context_tokens: int) -> chat.TurnOutcome:
        return chat.run_turn(
            self.FakeClient(max_context_tokens),
            user_text="这个声音的总时长是多少",
            context_text=context_tsv(3),
            history=history,
            context=self.context,
            execute=lambda script: (True, ["总时长 = 1 秒"], ""),
            native=True,
        )

    def test_short_conversation_has_no_notes(self) -> None:
        outcome = self.turn(
            history=[
                {"role": "user", "content": "你好"},
                {"role": "assistant", "content": "你好，要我做什么？"},
            ],
            max_context_tokens=32768,
        )
        self.assertEqual(outcome.notes, [])

    def test_trimmed_history_is_announced(self) -> None:
        history = []
        for index in range(6):
            history.append({"role": "user", "content": f"第{index}轮：把前 0.3 秒截出来"})
            history.append({"role": "assistant", "content": f"第{index}轮：已截取片段"})
        outcome = self.turn(history=history, max_context_tokens=1500)
        self.assertTrue(outcome.notes, outcome.notes)
        note = outcome.notes[0]
        self.assertIn("对话太长", note)
        self.assertIn("省掉更早的", note)
        self.assertIn("context_tokens", note)

    def test_trimmed_object_list_is_announced(self) -> None:
        outcome = chat.run_turn(
            self.FakeClient(900),
            user_text="这个声音的总时长是多少",
            context_text=context_tsv(60),
            history=[],
            context=self.context,
            execute=lambda script: (True, ["总时长 = 1 秒"], ""),
            native=True,
        )
        self.assertTrue(any("对象列表太长" in note for note in outcome.notes), outcome.notes)


if __name__ == "__main__":
    unittest.main()
