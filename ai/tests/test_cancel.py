"""C7：等待可以取消（等 Praat 的结果、等批处理跑完）。

以前点了「发送」就只能等：Praat 卡住时要等满 25 秒，跑社区脚本时更久。现在对话
窗口多一个「停止」按钮，它置一个 ``threading.Event``；等结果的循环、批处理进程、
多轮循环每一步都看这个标记，能停就立刻停。
"""

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from praat_ai import chat, external_script, qwen, tools


CONTEXT_TSV = "id\tclass\tname\tselected\n1\tSound\tSound tone\t1\n"


def tool_call(name: str, arguments: dict, call_id: str = "call-1") -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }
        ],
    }


class FakeClient:
    def __init__(self, script: list[dict]) -> None:
        self.script = list(script)
        self.config = qwen.QwenConfig()

    def chat_message(self, messages, **_kwargs) -> dict:
        return self.script.pop(0) if self.script else {"role": "assistant", "content": ""}

    def chat(self, messages, **_kwargs) -> str:
        return "（收尾）"


class WaitCancellationTests(unittest.TestCase):
    def test_waiting_for_praat_stops_when_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            cancel = threading.Event()
            cancel.set()   # 用户已经点了「停止」
            with patch.object(chat, "runtime_dir", return_value=directory), patch.object(
                chat.time, "sleep", lambda _seconds: None
            ):
                started = time.monotonic()
                ok, note = chat._wait_for_result(None, request_id="r1", cancel=cancel)
            self.assertFalse(ok)
            self.assertIn("取消", note)
            self.assertLess(time.monotonic() - started, chat.EXECUTION_TIMEOUT_SEC / 5)

    def test_cancelling_a_delivery_neutralises_the_queued_message(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            cancel = threading.Event()
            cancel.set()
            with patch.object(chat, "ai_directory", return_value=directory), patch.object(
                chat, "_clear_result_files"
            ), patch.object(chat.sendpraat, "deliver", return_value=(True, "")), patch.object(
                chat.sendpraat, "cancel_pending"
            ) as cancel_pending, patch.object(
                chat.time, "sleep", lambda _seconds: None
            ), patch.object(
                chat, "runtime_dir", return_value=directory
            ):
                ok, note = chat._send_script("Praat.exe", "selectObject: 1\n", cancel=cancel)
            self.assertFalse(ok)
            self.assertIn("取消", note)
            cancel_pending.assert_called_once()

    def test_result_that_arrived_before_cancelling_still_counts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            (directory / "chat_state.txt").write_text("done\n", encoding="utf-8")
            cancel = threading.Event()
            cancel.set()
            with patch.object(chat, "runtime_dir", return_value=directory):
                ok, _note = chat._wait_for_result(None, request_id="", cancel=cancel)
            self.assertTrue(ok)


class AgentLoopCancellationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        base = Path(self.directory.name)
        self.context = tools.ToolContext(
            tools.parse_object_context(CONTEXT_TSV),
            base / "chat_result.tsv",
            base / "chat_state.txt",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_cancel_stops_the_loop_before_the_next_step(self) -> None:
        cancel = threading.Event()
        executed: list[str] = []

        def execute(script: str) -> tuple[bool, list[str], str]:
            executed.append(script)
            cancel.set()   # 这一步跑完用户就点了停止
            return True, ["ok"], ""

        client = FakeClient(
            [
                tool_call("pitch", {"time": 0.25}),
                tool_call("pitch", {"time": 0.75}, call_id="call-2"),
            ]
        )
        outcome = chat.run_turn(
            client,
            user_text="查两个时刻的基频",
            context_text=CONTEXT_TSV,
            history=[],
            context=self.context,
            execute=execute,
            cancel=cancel,
        )
        self.assertEqual(len(executed), 1)
        self.assertEqual([step.tool for step in outcome.steps], ["pitch"])
        self.assertTrue(any("取消" in note for note in outcome.notes))

    def test_cancel_before_the_first_step_executes_nothing(self) -> None:
        cancel = threading.Event()
        cancel.set()
        executed: list[str] = []
        client = FakeClient([tool_call("pitch", {"time": 0.25})])
        outcome = chat.run_turn(
            client,
            user_text="查 0.25 秒的基频",
            context_text=CONTEXT_TSV,
            history=[],
            context=self.context,
            execute=lambda script: (executed.append(script), True, ["ok"], "")[1:],
            cancel=cancel,
        )
        self.assertEqual(executed, [])
        self.assertEqual(outcome.steps, [])
        self.assertIn("取消", outcome.reply)

    def test_execute_receives_the_cancel_flag_through_the_environment(self) -> None:
        """本地工具（批处理）也要能被打断。"""

        cancel = threading.Event()
        seen: list[object] = []
        base = Path(self.directory.name)
        community = base / "community.praat"
        community.write_text('writeInfoLine: "hi"\n', encoding="utf-8")

        def execute(script: str) -> tuple[bool, list[str], str]:
            if "Save as WAV file" in script:
                target = Path(script.split('"')[1])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"RIFF")
            return True, [], ""

        environment = tools.LocalEnvironment(
            execute=execute,
            praat_executable="Praat.exe",
            runtime_directory=base / "runtime",
            cancelled=cancel.is_set,
        )
        # 环境把「取消了吗」这个回调原样带下去（对话窗口接的是停止按钮那个事件）。
        self.assertFalse(environment.cancelled())
        cancel.set()
        self.assertTrue(environment.cancelled())
        cancel.clear()

        def fake_batch(praat, wrapper, **kwargs):
            seen.append(kwargs.get("cancelled"))
            return True, "ok"

        with patch.object(external_script, "run_batch", fake_batch):
            tools.LOCAL_TOOLS[tools.RUN_SCRIPT_TOOL].run(
                {"path": str(community)}, self.context, environment
            )
        self.assertEqual(len(seen), 1)
        self.assertIsNotNone(seen[0])


class BatchCancellationTests(unittest.TestCase):
    def test_run_batch_terminates_the_process_when_cancelled(self) -> None:
        class FakeProcess:
            def __init__(self) -> None:
                self.terminated = False
                self.killed = False

            def communicate(self, timeout=None):
                raise __import__("subprocess").TimeoutExpired("praat", timeout)

            def terminate(self) -> None:
                self.terminated = True

            def kill(self) -> None:
                self.killed = True

            def wait(self, timeout=None) -> int:
                return 0

        process = FakeProcess()
        # 第一次问「取消了吗」时还没取消（进程已经起来了），之后就取消。
        checked = {"count": 0}

        def cancelled() -> bool:
            checked["count"] += 1
            return checked["count"] > 2

        with patch.object(
            external_script.subprocess, "Popen", return_value=process
        ):
            ok, note = external_script.run_batch(
                "Praat.exe",
                Path("D:/tmp/wrapper.praat"),
                timeout=30.0,
                cancelled=cancelled,
            )
        self.assertFalse(ok)
        self.assertIn("取消", note)
        self.assertTrue(process.terminated or process.killed)

    def test_run_batch_does_not_even_start_when_already_cancelled(self) -> None:
        cancel = threading.Event()
        cancel.set()
        with patch.object(external_script.subprocess, "Popen") as popen:
            ok, note = external_script.run_batch(
                "Praat.exe",
                Path("D:/tmp/wrapper.praat"),
                timeout=30.0,
                cancelled=cancel.is_set,
            )
        self.assertFalse(ok)
        self.assertIn("取消", note)
        popen.assert_not_called()

    def test_run_batch_still_reports_a_timeout(self) -> None:
        class NeverEnding:
            def communicate(self, timeout=None):
                raise __import__("subprocess").TimeoutExpired("praat", timeout)

            def terminate(self) -> None:
                pass

            def kill(self) -> None:
                pass

            def wait(self, timeout=None) -> int:
                return 0

        with patch.object(
            external_script.subprocess, "Popen", return_value=NeverEnding()
        ), patch.object(external_script.time, "monotonic", side_effect=[0.0, 0.0, 100.0]):
            ok, note = external_script.run_batch(
                "Praat.exe", Path("D:/tmp/wrapper.praat"), timeout=5.0
            )
        self.assertFalse(ok)
        self.assertIn("没有跑完", note)


if __name__ == "__main__":
    unittest.main()
