"""C3：跑现成（社区）.praat 脚本的包装 —— 表单解析、参数、包装脚本、工具注册。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from praat_ai import chat, external_script, tools


COMMUNITY = '''form: "Community helper"
    comment: "这是社区脚本常见的开头"
    positive: "Pitch floor (Hz)", "75"
    word: "Mode", "fast"
    boolean: "Verbose", 1
    realvector: "Bands", "(whitespace-separated)", "1000 2000"
endform
p = To Pitch: 0, pitch_floor, 600
writeInfoLine: "mode=", mode$
'''

NO_FORM = 'writeInfoLine: "no form"\n'

CONTEXT_TSV = (
    "id\tclass\tname\tselected\n"
    "1\tSound\tSound tone\t1\n"
    "2\tTextGrid\tTextGrid grid\t0\n"
)


class FormParsingTests(unittest.TestCase):
    def test_fields_are_parsed_in_order_and_comments_skipped(self) -> None:
        fields = external_script.parse_form(COMMUNITY)
        self.assertEqual(
            [(field.kind, field.default) for field in fields],
            [
                ("positive", "75"),
                ("word", "fast"),
                ("boolean", "1"),
                ("realvector", "1000 2000"),
            ],
        )
        self.assertEqual(fields[0].label, "Pitch floor (Hz)")

    def test_script_without_a_form_has_no_fields(self) -> None:
        self.assertEqual(external_script.parse_form(NO_FORM), ())

    def test_choice_options_are_skipped(self) -> None:
        fields = external_script.parse_form(
            'form: "T"\n'
            '    choice: "Colour", 2\n'
            '        option: "Red"\n'
            '        option: "Blue"\n'
            'endform\n'
        )
        self.assertEqual(len(fields), 1)
        self.assertEqual((fields[0].kind, fields[0].default), ("choice", "2"))

    def test_unknown_field_type_is_reported(self) -> None:
        with self.assertRaises(external_script.ExternalScriptError) as caught:
            external_script.parse_form('form: "T"\n    mystery: "x", "1"\nendform\n')
        self.assertIn("mystery", str(caught.exception))

    def test_commas_inside_quotes_do_not_split(self) -> None:
        parts = external_script.split_arguments('"Band, low", "(formula)", "{ 1, 2 }"')
        self.assertEqual(parts, ['"Band, low"', '"(formula)"', '"{ 1, 2 }"'])


class RunArgumentTests(unittest.TestCase):
    def test_numbers_pass_through_and_strings_are_quoted(self) -> None:
        arguments = external_script.run_arguments(external_script.parse_form(COMMUNITY))
        self.assertEqual(arguments, ["75", '"fast"', "1", '"1000 2000"'])

    def test_non_numeric_default_for_a_number_field_is_reported(self) -> None:
        fields = external_script.parse_form(
            'form: "T"\n    real: "Start (s)", "0.0 (= auto)"\nendform\n'
        )
        with self.assertRaises(external_script.ExternalScriptError) as caught:
            external_script.run_arguments(fields)
        self.assertIn("Start (s)", str(caught.exception))

    def test_quotes_in_a_default_are_escaped(self) -> None:
        fields = external_script.parse_form(
            'form: "T"\n    sentence: "Label", "say ""hi"""\nendform\n'
        )
        self.assertEqual(
            external_script.run_arguments(fields), ['"say ""hi"""']
        )


class WrapperTests(unittest.TestCase):
    def test_wrapper_reads_the_exports_and_calls_the_script(self) -> None:
        script = external_script.wrapper_script(
            sound_path=Path("D:/work/input.wav"),
            grid_path=Path("D:/work/input.TextGrid"),
            target=Path("D:/scripts/community.praat"),
            arguments=["75", '"fast"'],
        )
        self.assertIn('Read from file: "D:/work/input.wav"', script)
        self.assertIn('Read from file: "D:/work/input.TextGrid"', script)
        self.assertIn("plusObject: gridId", script)
        self.assertIn(
            'runScript: "D:/scripts/community.praat", 75, "fast"', script
        )

    def test_wrapper_without_a_grid_does_not_select_one(self) -> None:
        script = external_script.wrapper_script(
            sound_path=Path("D:/work/input.wav"),
            grid_path=None,
            target=Path("D:/scripts/community.praat"),
            arguments=[],
        )
        self.assertNotIn("plusObject", script)
        self.assertIn('runScript: "D:/scripts/community.praat"', script)

    def test_read_script_checks_name_and_size(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            wrong = base / "notes.md"
            wrong.write_text("hi", encoding="utf-8")
            with self.assertRaises(external_script.ExternalScriptError) as caught:
                external_script.read_script(wrong)
            self.assertIn(".praat", str(caught.exception))
            missing = base / "nope.praat"
            with self.assertRaises(external_script.ExternalScriptError) as caught:
                external_script.read_script(missing)
            self.assertIn("找不到", str(caught.exception))

    def test_changed_files_only_reports_new_or_touched(self) -> None:
        self.assertEqual(
            external_script.changed_files({"a.txt": 1.0, "b.txt": 2.0}, {"a.txt": 1.0, "c.txt": 3.0}),
            ["c.txt"],
        )


class LocalToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        base = Path(self.directory.name)
        self.result = base / "chat_result.tsv"
        self.context = tools.ToolContext(
            tools.parse_object_context(CONTEXT_TSV),
            self.result,
            base / "chat_state.txt",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_tool_is_registered_with_a_schema(self) -> None:
        self.assertIn(tools.RUN_SCRIPT_TOOL, tools.LOCAL_TOOLS)
        schema = tools.TOOL_PARAMETERS[tools.RUN_SCRIPT_TOOL]
        self.assertEqual(schema["required"], ["path"])
        self.assertEqual(
            set(schema["properties"]), {"path", "object", "textgrid", "timeout"}
        )
        self.assertIn(tools.RUN_SCRIPT_TOOL, tools.catalog_text())
        names = [item["function"]["name"] for item in tools.tool_schemas()]
        self.assertIn(tools.RUN_SCRIPT_TOOL, names)

    def test_missing_path_is_refused_in_chinese(self) -> None:
        environment = tools.LocalEnvironment(
            execute=lambda script: (True, [], ""),
            praat_executable="Praat.exe",
            runtime_directory=Path(self.directory.name),
        )
        with self.assertRaises(tools.ToolError) as caught:
            tools.LOCAL_TOOLS[tools.RUN_SCRIPT_TOOL].run({}, self.context, environment)
        self.assertIn("path", str(caught.exception))

    def test_whole_flow_exports_then_runs_batch(self) -> None:
        """导出声音 → 跑批处理 → 把脚本输出带回对话（批处理是打桩的）。"""

        base = Path(self.directory.name)
        community = base / "community.praat"
        community.write_text(COMMUNITY, encoding="utf-8")
        delivered: list[str] = []

        def execute(script: str) -> tuple[bool, list[str], str]:
            delivered.append(script)
            # 假装开着的 Praat 真的存了这两个文件。
            if "Save as WAV file" in script:
                target = Path(script.split('"')[1])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"RIFF")
            elif "Save as text file" in script:
                target = Path(script.split('"')[1])
                target.write_text("grid", encoding="utf-8")
            return True, [], ""

        environment = tools.LocalEnvironment(
            execute=execute,
            praat_executable="Praat.exe",
            runtime_directory=base / "runtime",
        )
        with patch.object(
            external_script, "run_batch", return_value=(True, "community mean pitch = 220.0")
        ) as batch:
            ok, lines, failure = tools.LOCAL_TOOLS[tools.RUN_SCRIPT_TOOL].run(
                {"path": str(community)}, self.context, environment
            )
        self.assertTrue(ok, failure)
        self.assertEqual(failure, "")
        self.assertEqual(len(delivered), 2, delivered)
        self.assertIn("Save as WAV file", delivered[0])
        self.assertIn("Save as text file", delivered[1])
        joined = "\n".join(lines)
        self.assertIn("community.praat 跑完了", joined)
        self.assertIn("community mean pitch = 220.0", joined)
        # 表单默认值被如实传进去（批处理里没有表单可点）。
        self.assertIn("Pitch floor (Hz)=75", joined)
        self.assertIn("TextGrid", joined)
        wrapper = Path(batch.call_args[0][1]).read_text(encoding="utf-8")
        self.assertIn("runScript:", wrapper)
        # 数字字段直接写数字，字符串/向量字段加引号（Praat 的 runScript 就是这么吃参数的）。
        self.assertIn('75, "fast", 1, "1000 2000"', wrapper)

    def test_batch_failure_is_reported_with_the_boundary_note(self) -> None:
        base = Path(self.directory.name)
        community = base / "community.praat"
        community.write_text(COMMUNITY, encoding="utf-8")

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
        )
        with patch.object(
            external_script, "run_batch", return_value=(False, "Error: 表单填错了")
        ):
            ok, lines, failure = tools.LOCAL_TOOLS[tools.RUN_SCRIPT_TOOL].run(
                {"path": str(community)}, self.context, environment
            )
        self.assertFalse(ok)
        self.assertEqual(lines, [])
        self.assertIn("表单填错了", failure)
        self.assertIn("批处理里看不到你当前的对象列表", failure)

    def test_chat_reports_missing_environment_instead_of_crashing(self) -> None:
        step = chat._execute_action(
            {"tool": tools.RUN_SCRIPT_TOOL, "arguments": {"path": "x.praat"}},
            self.context,
            lambda script: (True, [], ""),
            1,
            None,
        )
        self.assertFalse(step.ok)
        self.assertIn("没有可用的执行环境", step.observation)

    def test_chat_runs_the_local_tool_through_the_environment(self) -> None:
        base = Path(self.directory.name)
        community = base / "community.praat"
        community.write_text(COMMUNITY, encoding="utf-8")

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
        )
        with patch.object(external_script, "run_batch", return_value=(True, "ok")):
            step = chat._execute_action(
                {"tool": tools.RUN_SCRIPT_TOOL, "arguments": {"path": str(community)}},
                self.context,
                execute,
                1,
                environment,
            )
        self.assertTrue(step.ok)
        self.assertIn("执行成功", step.observation)
        self.assertTrue(step.results)
        self.assertEqual(step.script, "")


if __name__ == "__main__":
    unittest.main()
