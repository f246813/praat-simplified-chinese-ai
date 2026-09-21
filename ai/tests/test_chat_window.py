"""对话窗口的状态栏、Praat 存活判断、投递编号和输出过滤。"""

import os
import tempfile
import time
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from praat_ai import chat
from praat_ai.config import AppConfig
from praat_ai.qwen import selected_object_hint


class SelectedObjectHintTests(unittest.TestCase):
    """规划提示里要单独写清「当前选中哪个对象」，否则模型爱挑 1 号。"""

    def test_hint_names_the_selected_object(self) -> None:
        context = (
            "id\tclass\tname\tselected\n"
            "1\tTextGrid\tTextGrid grid\t0\n"
            "2\tSound\tSound tone\t1\n"
        )
        self.assertEqual(selected_object_hint(context), "当前选中：id 2（Sound Sound tone）")

    def test_hint_when_nothing_is_selected(self) -> None:
        context = "id\tclass\tname\tselected\n1\tSound\tSound tone\t0\n"
        self.assertIn("没有选中", selected_object_hint(context))
        self.assertIn("没有选中", selected_object_hint(""))


class PresetLabelTests(unittest.TestCase):
    """下拉框的值是文本，切换后列表会重建，所以要能稳定换回预设 id。"""

    def setUp(self) -> None:
        self.presets = [
            {
                "id": "big",
                "label": "Qwen3.5-2B（视觉）",
                "model": "Qwen3.5-2B-UD-Q5_K_XL.gguf",
                "vision": True,
                "available": True,
                "active": True,
            },
            {
                "id": "small",
                "label": "Qwen3.5-0.8B（快速）",
                "model": "Qwen3.5-0.8B-Q4_K_M.gguf",
                "vision": False,
                "available": False,
                "active": False,
            },
        ]

    def test_full_label_resolves(self) -> None:
        label = chat.preset_label_text(self.presets[0])
        self.assertNotIn("当前", label)
        self.assertEqual(chat.resolve_preset_id(self.presets, label), "big")
        self.assertEqual(
            chat.resolve_preset_id(self.presets, chat.preset_label_text(self.presets[1])),
            "small",
        )

    def test_id_model_and_prefix_also_resolve(self) -> None:
        self.assertEqual(chat.resolve_preset_id(self.presets, "small"), "small")
        self.assertEqual(
            chat.resolve_preset_id(self.presets, "Qwen3.5-2B-UD-Q5_K_XL.gguf"), "big"
        )
        self.assertEqual(chat.resolve_preset_id(self.presets, "Qwen3.5-2B（视觉）"), "big")
        self.assertEqual(chat.resolve_preset_id(self.presets, ""), "")
        self.assertEqual(chat.resolve_preset_id(self.presets, "别的模型"), "")

    def test_missing_file_is_shown_in_the_label(self) -> None:
        self.assertIn("文件缺失", chat.preset_label_text(self.presets[1]))
        self.assertIn("纯文本", chat.preset_label_text(self.presets[1]))


class PraatProcessTests(unittest.TestCase):
    def test_refresh_reuses_a_known_process_list(self) -> None:
        """调用方已经查过进程列表时，刷新上下文不该再起一次 tasklist。"""

        with patch.object(chat.subprocess, "run") as run, patch.object(
            chat, "praat_process_running_from", return_value=True
        ), patch.object(chat, "_send_script", return_value=(True, "")) as send:
            chat.refresh_object_context("D:/praat/Praat.exe", [1234])
        run.assert_not_called()
        send.assert_called_once()

    def test_refresh_queries_once_without_a_known_list(self) -> None:
        completed = CompletedProcess(
            args=["tasklist"],
            returncode=0,
            stdout='"Praat.exe","1234","Console","1","98,304 K"\n',
            stderr="",
        )
        with patch.object(chat.subprocess, "run", return_value=completed) as run, patch.object(
            chat, "_send_script", return_value=(True, "")
        ):
            chat.refresh_object_context("D:/praat/Praat.exe")
        self.assertEqual(run.call_count, 1)

    def test_multiple_instances_produce_a_warning(self) -> None:
        completed = CompletedProcess(
            args=["tasklist"],
            returncode=0,
            stdout=(
                '"Praat.exe","1234","Console","1","98,304 K"\n'
                '"Praat.exe","5678","Console","1","98,304 K"\n'
            ),
            stderr="",
        )
        with patch.object(chat.subprocess, "run", return_value=completed):
            self.assertEqual(chat.praat_process_ids("D:/praat/Praat.exe"), [1234, 5678])
            self.assertIn("2 个 Praat", chat.praat_instance_warning("D:/praat/Praat.exe"))

    def test_single_instance_has_no_warning(self) -> None:
        completed = CompletedProcess(
            args=["tasklist"],
            returncode=0,
            stdout='"Praat.exe","1234","Console","1","98,304 K"\n',
            stderr="",
        )
        with patch.object(chat.subprocess, "run", return_value=completed):
            self.assertEqual(chat.praat_instance_warning("Praat.exe"), "")

    def test_missing_tasklist_output_means_not_running(self) -> None:
        completed = CompletedProcess(
            args=["tasklist"],
            returncode=0,
            stdout="INFO: No tasks are running which match the specified criteria.",
            stderr="",
        )
        with patch.object(chat.subprocess, "run", return_value=completed):
            self.assertFalse(chat.praat_process_running("D:/praat/Praat.exe"))

    def test_running_process_is_detected(self) -> None:
        completed = CompletedProcess(
            args=["tasklist"],
            returncode=0,
            stdout='"Praat.exe","1234","Console","1","98,304 K"\n',
            stderr="",
        )
        with patch.object(chat.subprocess, "run", return_value=completed):
            self.assertTrue(chat.praat_process_running("D:/praat/Praat.exe"))

    def test_tasklist_failure_does_not_block_sending(self) -> None:
        with patch.object(chat.subprocess, "run", side_effect=OSError("no tasklist")):
            self.assertTrue(chat.praat_process_running("D:/praat/Praat.exe"))

    def test_missing_executable_is_not_a_blocker(self) -> None:
        self.assertTrue(chat.praat_process_running(""))


class SendOutputTests(unittest.TestCase):
    def test_send_noise_is_filtered_but_real_errors_survive(self) -> None:
        text = (
            "An instance of Praat that is not me is already running.\n"
            "Cannot write message file C:/Users/x/Praat/Message.txt\n"
        )
        cleaned = chat._clean_send_output(text)
        self.assertNotIn("already running", cleaned)
        # 「Cannot write message file」是真的失败，不能再当成噪声丢掉。
        self.assertIn("Cannot write message file", cleaned)


class FakeSendProcess:
    """假的 Praat.exe --send 进程，用来试超时和错误分支。"""

    def __init__(
        self,
        *,
        state_path: Path | None,
        log_text: str = "",
        exit_code: int | None = 0,
        write_state: bool = False,
        started_path: Path | None = None,
    ) -> None:
        self.state_path = state_path
        self.started_path = started_path
        self.log_text = log_text
        self.exit_code = exit_code
        self.write_state = write_state
        self.terminated = False
        self.killed = False

    def __call__(self, command: list[str], **kwargs: object) -> "FakeSendProcess":
        handle = kwargs.get("stdout")
        if handle is not None and self.log_text:
            handle.write(self.log_text.encode("utf-8"))
        if self.write_state and self.state_path is not None:
            # 真 Praat 会先执行脚本开头那句「请求编号」，再写完成标记。
            if self.started_path is not None:
                request_id = chat.request_id_from_path(Path(command[-1]))
                self.started_path.write_text(
                    f"started {request_id}\n", encoding="utf-8"
                )
            self.state_path.write_text("done\n", encoding="utf-8")
        return self

    def poll(self) -> int | None:
        return self.exit_code

    def terminate(self) -> None:
        self.terminated = True
        self.exit_code = 0

    def kill(self) -> None:
        self.killed = True
        self.exit_code = 0

    def wait(self, timeout: float | None = None) -> int:
        return self.exit_code or 0


class SendScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.runtime = Path(self._temp.name)
        self.patch_runtime = patch.object(chat, "runtime_dir", return_value=self.runtime)
        self.patch_runtime.start()
        self.delivered: list[tuple[Path, Path]] = []

    def tearDown(self) -> None:
        self.patch_runtime.stop()
        self._temp.cleanup()

    def _deliver(self, directory, script, **_kwargs) -> tuple[bool, str]:
        """假投递：记下参数，并像 Praat 那样写请求编号 + 完成标记。"""

        self.delivered.append((Path(directory), Path(script)))
        self._emulate_praat(Path(script))
        return True, ""

    def _emulate_praat(self, script: Path, request_id: str = "") -> None:
        """照真 Praat 的顺序落两个文件：先请求编号，再完成标记。"""

        rid = request_id or chat.request_id_from_path(script)
        chat.started_marker_path().write_text(f"started {rid}\n", encoding="utf-8")
        chat.state_path().write_text("done\n", encoding="utf-8")

    def test_window_delivery_means_success(self) -> None:
        with patch.object(chat.sendpraat, "deliver", self._deliver):
            ok, output = chat._send_script("Praat.exe", "selectObject: 1\n")
        self.assertTrue(ok)
        self.assertEqual(output, "")
        # 投出去的是刚写好的脚本文件，工作目录是前端自己的目录。
        directory, delivered = self.delivered[0]
        self.assertEqual(directory, chat.ai_directory())
        self.assertEqual(delivered.parent, chat.runtime_dir() / "commands")
        content = delivered.read_text(encoding="utf-8")
        # 脚本开头是请求编号（完成标记靠它认身份），后面才是模型/模板给的脚本。
        request_id = chat.request_id_from_path(delivered)
        self.assertTrue(content.startswith(f"# praat-ai 请求 {request_id}\n"))
        self.assertTrue(content.endswith("selectObject: 1\n"))

    def test_each_request_gets_its_own_script_file(self) -> None:
        """两个请求不能共用一个文件名：旧消息醒来时执行的会是新脚本。"""

        with patch.object(chat.sendpraat, "deliver", self._deliver):
            chat._send_script("Praat.exe", "selectObject: 1\n")
            chat._send_script("Praat.exe", "selectObject: 2\n")
        first, second = (item[1] for item in self.delivered)
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_file())
        self.assertTrue(second.is_file())

    def test_completion_marker_from_another_request_is_ignored(self) -> None:
        """完成标记是上一条超时指令写的时，不能把它的数值当成本次结果。"""

        def stale_deliver(directory, script, **_kwargs) -> tuple[bool, str]:
            self.delivered.append((Path(directory), Path(script)))
            # 上一条指令刚刚才跑完：编号是别人的，结果文件里是别人的数值。
            chat.started_marker_path().write_text(
                "started 老指令编号\n", encoding="utf-8"
            )
            chat.result_path().write_text("别人的结果\n", encoding="utf-8")
            chat.state_path().write_text("done\n", encoding="utf-8")
            return True, ""

        with patch.object(chat.sendpraat, "deliver", stale_deliver), patch.object(
            chat, "EXECUTION_TIMEOUT_SEC", 0.4
        ):
            ok, output = chat._send_script("Praat.exe", "selectObject: 1\n")
        self.assertFalse(ok)
        self.assertIn("上一条超时指令", output)
        # 别人的结果和标记都要丢掉，不能留在那里当本次结果。
        self.assertFalse(chat.state_path().is_file())
        self.assertFalse(chat.result_path().is_file())

    def test_prune_keeps_the_newest_scripts(self) -> None:
        directory = chat.command_dir()
        old = time.time() - 7200
        for index in range(chat.MAX_COMMAND_SCRIPTS + 5):
            path = directory / f"chat_command_{index:012x}.praat"
            path.write_text("selectObject: 1\n", encoding="utf-8")
            os.utime(path, (old, old))
        removed = chat.prune_command_scripts()
        self.assertEqual(removed, 5)
        self.assertEqual(len(list(directory.glob("chat_command_*.praat"))), chat.MAX_COMMAND_SCRIPTS)

    def test_prune_keeps_recent_scripts_even_when_there_are_many(self) -> None:
        """最近一小时的脚本都要留着：Message.txt 里可能还引用着它们。"""

        directory = chat.command_dir()
        for index in range(chat.MAX_COMMAND_SCRIPTS + 5):
            (directory / f"chat_command_{index:012x}.praat").write_text(
                "selectObject: 1\n", encoding="utf-8"
            )
        self.assertEqual(chat.prune_command_scripts(), 0)

    def test_window_delivery_failure_is_reported(self) -> None:
        with patch.object(
            chat.sendpraat,
            "deliver",
            return_value=(False, "没有找到正在运行的 Praat 窗口，请先打开 Praat。"),
        ):
            ok, output = chat._send_script("Praat.exe", "selectObject: 1\n")
        self.assertFalse(ok)
        self.assertIn("没有找到正在运行的 Praat 窗口", output)

    def test_context_ping_script_marks_state(self) -> None:
        script = chat.context_ping_script()
        self.assertIn(chat.state_path().as_posix(), script)
        self.assertIn('"done"', script)
        # 刷新用的是空脚本，不能碰任何对象。
        self.assertNotIn("selectObject", script)
        # 也不能写 Info 窗口：那就是「发送指令弹出 Praat Info」的根源。
        for command in ("appendInfoLine", "writeInfoLine", "writeInfo", "echo"):
            self.assertNotIn(command, script)

    def test_praat_that_never_answers_is_reported_in_chinese(self) -> None:
        cancelled: list[bool] = []
        with patch.object(chat.sendpraat, "deliver", return_value=(True, "")), patch.object(
            chat.sendpraat, "cancel_pending", lambda *_a, **_k: cancelled.append(True)
        ), patch.object(chat, "EXECUTION_TIMEOUT_SEC", 0.2):
            ok, output = chat._send_script("Praat.exe", "selectObject: 1\n")
        self.assertFalse(ok)
        self.assertIn("没有执行这个脚本", output)
        # 超时后必须把待执行的消息换成空脚本，免得它执行下一条指令。
        self.assertEqual(cancelled, [True])

    def test_argv_mode_keeps_the_send_process_path(self) -> None:
        fake = FakeSendProcess(
            state_path=chat.state_path(),
            started_path=chat.started_marker_path(),
            write_state=True,
        )
        with patch.object(chat.sendpraat, "send_mode", return_value="argv"), patch.object(
            chat.subprocess, "Popen", fake
        ):
            ok, output = chat._send_script("Praat.exe", "selectObject: 1\n")
        self.assertTrue(ok)
        self.assertEqual(output, "")

    def test_argv_timeout_kills_the_send_process(self) -> None:
        fake = FakeSendProcess(state_path=chat.state_path(), exit_code=None)
        with patch.object(chat.sendpraat, "send_mode", return_value="argv"), patch.object(
            chat.subprocess, "Popen", fake
        ), patch.object(chat, "EXECUTION_TIMEOUT_SEC", 0.2):
            ok, output = chat._send_script("Praat.exe", "selectObject: 1\n")
        self.assertFalse(ok)
        self.assertIn("没有执行这个脚本", output)
        self.assertTrue(fake.terminated)

    def test_praat_error_output_is_kept(self) -> None:
        fake = FakeSendProcess(
            state_path=chat.state_path(),
            log_text="Error: Command “播放” not available for current selection.",
            exit_code=1,
        )
        with patch.object(chat.sendpraat, "send_mode", return_value="argv"), patch.object(
            chat.subprocess, "Popen", fake
        ), patch.object(chat, "EXECUTION_TIMEOUT_SEC", 0.2):
            ok, output = chat._send_script("Praat.exe", "selectObject: 1\nPlay\n")
        self.assertFalse(ok)
        self.assertIn("not available for current selection", output)


class StatusTextTests(unittest.TestCase):
    def make_config(self) -> AppConfig:
        config = AppConfig()
        config.server.model_path = r"D:\llama.cpp\Qwen3.5-2B-UD-Q5_K_XL.gguf"
        config.qwen.base_url = "http://127.0.0.1:9/v1"
        return config

    def test_status_uses_live_model_and_vision(self) -> None:
        config = self.make_config()
        info = {
            "id": r"D:\llama.cpp\Qwen3.5-2B-UD-Q5_K_XL.gguf",
            "capabilities": ["completion", "multimodal"],
        }
        with patch.object(chat, "running_model_info", return_value=info):
            text = chat.model_status_text(config)
        self.assertIn("Qwen3.5-2B-UD-Q5_K_XL.gguf", text)
        self.assertIn("视觉已开", text)

    def test_status_reports_mismatch_and_unreachable_service(self) -> None:
        config = self.make_config()
        info = {"id": r"D:\models\Qwen3.5-0.8B-Q4_K_M.gguf", "capabilities": []}
        with patch.object(chat, "running_model_info", return_value=info):
            text = chat.model_status_text(config)
        self.assertIn("Qwen3.5-0.8B-Q4_K_M.gguf", text)
        self.assertIn("Qwen3.5-2B-UD-Q5_K_XL.gguf", text)   # 配置值也要显示出来
        with patch.object(chat, "running_model_info", return_value={}):
            offline = chat.model_status_text(config)
        self.assertIn("服务未响应", offline)

    def test_status_mentions_active_preset(self) -> None:
        config = self.make_config()
        from praat_ai.config import ServerPreset

        with tempfile.TemporaryDirectory() as raw:
            model = Path(raw) / "Qwen3.5-2B-UD-Q5_K_XL.gguf"
            model.write_bytes(b"stub")
            config.server.model_path = str(model)
            config.server.presets = [
                ServerPreset(
                    id="big",
                    label="Qwen3.5-2B（视觉）",
                    model_path=str(model),
                    vision=True,
                )
            ]
            with patch.object(chat, "running_model_info", return_value={"id": str(model)}):
                text = chat.model_status_text(config)
        self.assertIn("预设：Qwen3.5-2B（视觉）", text)


class ApiChoiceLabelTests(unittest.TestCase):
    """API 模式下「模型预设」下拉框要显示当前云端模型（2026-09-21 用户报的）。

    以前这一行永远是本地 qwen 预设，接上 API 之后用户看到还是本地模型名。
    """

    def test_cloud_model_is_shown_with_the_provider_name(self) -> None:
        config = AppConfig()
        config.api.enabled = True
        config.api.base_url = "https://api.deepseek.com/v1"
        config.api.model = "deepseek-chat"
        config.api.label = "DeepSeek"
        self.assertEqual(
            chat.api_choice_label(config),
            "云端 API：DeepSeek / deepseek-chat",
        )

    def test_cloud_model_without_a_provider_name_still_names_the_model(self) -> None:
        config = AppConfig()
        config.api.enabled = True
        config.api.base_url = "https://api.example.com/v1"
        config.api.model = "big-model"
        config.api.label = ""
        self.assertEqual(chat.api_choice_label(config), "云端 API：big-model")

    def test_missing_model_is_reported_instead_of_an_empty_row(self) -> None:
        config = AppConfig()
        self.assertEqual(chat.api_choice_label(config), "云端 API：未配置")


if __name__ == "__main__":
    unittest.main()
