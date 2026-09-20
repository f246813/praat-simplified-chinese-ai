import tempfile
import unittest
from pathlib import Path

from praat_ai import tools


CONTEXT = (
    "id\tclass\tname\tselected\n"
    "1\tSound\tSound tone\t1\n"
    "2\tFormant\tFormant tone\t0\n"
)


class ObjectContextTests(unittest.TestCase):
    def test_context_is_parsed(self) -> None:
        rows = tools.parse_object_context(CONTEXT)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].name, "Sound tone")
        self.assertTrue(rows[0].selected)

    def test_default_object_prefers_selection(self) -> None:
        rows = tools.parse_object_context(CONTEXT)
        context = tools.ToolContext(rows, Path("r.tsv"), Path("s.txt"))
        self.assertEqual(context.default_object().id, 1)

    def test_object_can_be_resolved_by_id_and_name(self) -> None:
        rows = tools.parse_object_context(CONTEXT)
        context = tools.ToolContext(rows, Path("r.tsv"), Path("s.txt"))
        self.assertEqual(context.resolve_object(2).class_name, "Formant")
        self.assertEqual(context.resolve_object("Sound tone").id, 1)

    def test_unknown_object_is_rejected(self) -> None:
        rows = tools.parse_object_context(CONTEXT)
        context = tools.ToolContext(rows, Path("r.tsv"), Path("s.txt"))
        with self.assertRaises(tools.ToolError):
            context.resolve_object("Sound missing")


class ScriptRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        base = Path(self.directory.name)
        self.context = tools.ToolContext(
            tools.parse_object_context(CONTEXT),
            base / "chat_result.tsv",
            base / "chat_state.txt",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def render(self, name: str, **arguments: object) -> str:
        return tools.render(name, arguments, self.context)

    def test_formant_bandwidth_uses_object_id_and_double_quotes(self) -> None:
        script = self.render("formant_bandwidth", formant=2)
        self.assertIn("selectObject: 1", script)
        self.assertIn("To Formant (burg): 0, 5, 5500, 0.025, 50", script)
        self.assertIn(
            'value = Get bandwidth at time: 2, time, "hertz", "linear"', script
        )
        self.assertNotIn("'", script)

    def test_formant_query_accepts_explicit_time_and_unit(self) -> None:
        script = self.render("formant_frequency", formant=3, time=0.25, unit="Bark")
        self.assertIn("time = 0.250000", script)
        self.assertIn('value = Get value at time: 3, time, "Bark", "linear"', script)

    def test_existing_formant_object_is_not_reanalysed(self) -> None:
        script = self.render("formant_bandwidth", object=2)
        self.assertIn("selectObject: 2", script)
        self.assertNotIn("To Formant (burg)", script)
        self.assertNotIn("Remove", script)

    def test_pitch_and_intensity_templates(self) -> None:
        pitch = self.render("pitch", time=0.3)
        self.assertIn("To Pitch: 0, 75.000000, 600.000000", pitch)
        self.assertIn('value = Get value at time: time, "Hertz", "linear"', pitch)
        intensity = self.render("intensity")
        self.assertIn('To Intensity: 100, 0, "yes"', intensity)
        self.assertIn('value = Get value at time: time, "cubic"', intensity)

    def test_every_script_ends_with_state_marker(self) -> None:
        for tool in tools.TOOLS:
            arguments: dict[str, object] = {}
            if tool.name == "rename_object":
                arguments["new_name"] = "测试"
            script = self.render(tool.name, **arguments)
            last = [line for line in script.splitlines() if line.strip()][-1]
            self.assertIn("chat_state.txt", last, tool.name)
            self.assertIn('"done"', last, tool.name)

    def test_invalid_formant_number_is_rejected(self) -> None:
        with self.assertRaises(tools.ToolError):
            self.render("formant_bandwidth", formant=0)

    def test_invalid_unit_is_rejected(self) -> None:
        with self.assertRaises(tools.ToolError):
            self.render("formant_bandwidth", unit="meters")

    def test_rename_requires_new_name(self) -> None:
        with self.assertRaises(tools.ToolError):
            self.render("rename_object")


class ScriptValidationTests(unittest.TestCase):
    def test_single_quotes_become_double_quotes(self) -> None:
        script = tools.validate_script("selectObject('Sound', 'tone')")
        self.assertEqual(script.strip(), 'selectObject("Sound", "tone")')

    def test_markdown_fence_is_stripped(self) -> None:
        script = tools.validate_script("```praat\nselectObject: 1\n```")
        self.assertEqual(script.strip(), "selectObject: 1")

    def test_dangerous_commands_are_rejected(self) -> None:
        for snippet in (
            'runSystem: "cmd /c dir"',
            'deleteFile: "C:/tmp/a.txt"',
            "exit",
        ):
            with self.assertRaises(tools.ToolError, msg=snippet):
                tools.validate_script(snippet)

    def test_unbalanced_quotes_are_rejected(self) -> None:
        with self.assertRaises(tools.ToolError):
            tools.validate_script('Rename: "abc')

    def test_custom_script_gets_result_marker(self) -> None:
        directory = tempfile.TemporaryDirectory()
        base = Path(directory.name)
        context = tools.ToolContext(
            tools.parse_object_context(CONTEXT),
            base / "chat_result.tsv",
            base / "chat_state.txt",
        )
        script = tools.render(
            tools.CUSTOM_SCRIPT_TOOL,
            {},
            context,
            custom_script="selectObject('Sound', 'tone')",
        )
        directory.cleanup()
        self.assertIn('selectObject("Sound", "tone")', script)
        self.assertIn("chat_state.txt", script)


if __name__ == "__main__":
    unittest.main()
