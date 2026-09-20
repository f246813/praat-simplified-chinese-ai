import tempfile
import unittest
from pathlib import Path

from praat_ai import tools


CONTEXT = (
    "id\tclass\tname\tselected\n"
    "1\tSound\tSound tone\t1\n"
    "2\tFormant\tFormant tone\t0\n"
)

MIXED_CONTEXT = (
    "id\tclass\tname\tselected\n"
    "1\tSound\tSound 思い出す\t1\n"
    "2\tSound\ttone\t0\n"
    "3\tTextGrid\tTextGrid 思い出す\t0\n"
    "4\tTable\tTable words\t0\n"
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
        base = Path(self.directory.name)
        context = tools.ToolContext(
            tools.parse_object_context(
                "id\tclass\tname\tselected\n"
                "1\tSound\tSound tone\t1\n"
                "2\tSound\ttone2\t0\n"
            ),
            base / "chat_result.tsv",
            base / "chat_state.txt",
        )
        extra: dict[str, dict[str, object]] = {
            "rename_object": {"new_name": "测试"},
            "extract_part": {"start": 0.1, "end": 0.4},
            "save_sound": {"path": str(base / "ai-chat.wav")},
            "concatenate_sounds": {"object": 1, "object2": 2},
        }
        for tool in tools.TOOLS:
            arguments: dict[str, object] = dict(extra.get(tool.name, {}))
            script = tools.render(tool.name, arguments, context)
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


class ObjectMatchingTests(unittest.TestCase):
    """模型给的对象写法常常和 Praat 列表里的名字不完全一样。"""

    def setUp(self) -> None:
        self.context = tools.ToolContext(
            tools.parse_object_context(MIXED_CONTEXT),
            Path("r.tsv"),
            Path("s.txt"),
        )

    def test_name_without_class_prefix_matches(self) -> None:
        self.assertEqual(self.context.resolve_object("思い出す").id, 1)

    def test_short_name_matches_full_name(self) -> None:
        self.assertEqual(self.context.resolve_object("tone").id, 2)

    def test_chinese_id_forms_are_accepted(self) -> None:
        for text in ("3", "3 号", "#3", "id 3"):
            self.assertEqual(self.context.resolve_object(text).id, 3, text)

    def test_ambiguous_name_is_rejected_with_candidates(self) -> None:
        with self.assertRaises(tools.ToolError) as caught:
            self.context.resolve_object("Sound")
        self.assertIn("多个对象", str(caught.exception))

    def test_unknown_name_still_fails(self) -> None:
        with self.assertRaises(tools.ToolError):
            self.context.resolve_object("Sound nothing")


class ToolGuardTests(unittest.TestCase):
    """对象类型不匹配时要给出中文原因，而不是让 Praat 抛英文错误。"""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        base = Path(self.directory.name)
        self.context = tools.ToolContext(
            tools.parse_object_context(MIXED_CONTEXT),
            base / "chat_result.tsv",
            base / "chat_state.txt",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_play_requires_sound(self) -> None:
        with self.assertRaises(tools.ToolError) as caught:
            tools.render("play", {"object": 3}, self.context)
        self.assertIn("声音", str(caught.exception))

    def test_duration_rejects_objects_without_time(self) -> None:
        with self.assertRaises(tools.ToolError):
            tools.render("duration", {"object": 4}, self.context)

    def test_object_info_skips_duration_for_tables(self) -> None:
        script = tools.render("object_info", {"object": 4}, self.context)
        self.assertNotIn("Get total duration", script)
        self.assertIn("没有时长", script)

    def test_object_info_reports_sound_properties(self) -> None:
        script = tools.render("object_info", {"object": 2}, self.context)
        self.assertIn("Get total duration", script)
        self.assertIn("Get number of channels", script)
        self.assertIn("Get sampling frequency", script)


class QueryRobustnessTests(unittest.TestCase):
    """越界时间和 --undefined-- 结果都要变成中文说明。"""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        base = Path(self.directory.name)
        self.context = tools.ToolContext(
            tools.parse_object_context(MIXED_CONTEXT),
            base / "chat_result.tsv",
            base / "chat_state.txt",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_pitch_clamps_time_and_explains_undefined(self) -> None:
        script = tools.render("pitch", {"time": 5.0}, self.context)
        self.assertIn("if time > duration", script)
        self.assertIn("已按对象时长截断", script)
        self.assertIn("if value = undefined", script)
        self.assertIn("没有周期性声源", script)

    def test_formant_query_explains_undefined(self) -> None:
        script = tools.render("formant_bandwidth", {"formant": 2}, self.context)
        self.assertIn("if value = undefined", script)
        self.assertIn("没有可用的共振峰数据", script)

    def test_intensity_query_explains_undefined(self) -> None:
        script = tools.render("intensity", {}, self.context)
        self.assertIn("if value = undefined", script)
        self.assertIn("没有强度数据", script)


class NewToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.base = Path(self.directory.name)
        self.context = tools.ToolContext(
            tools.parse_object_context(MIXED_CONTEXT),
            self.base / "chat_result.tsv",
            self.base / "chat_state.txt",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_formant_can_query_several_numbers_at_once(self) -> None:
        script = tools.render(
            "formant_frequency",
            {"formant": "1,2", "time": 0.4},
            self.context,
        )
        self.assertIn('Get value at time: 1, time, "hertz", "linear"', script)
        self.assertIn('Get value at time: 2, time, "hertz", "linear"', script)
        # 「频率和带宽」一次问完，不再需要两个工具。
        self.assertIn('Get bandwidth at time: 2, time, "hertz", "linear"', script)
        self.assertIn("第 2 共振峰（", script)
        self.assertIn("：频率 ", script)

    def test_invalid_formant_number_message_is_chinese(self) -> None:
        with self.assertRaises(tools.ToolError) as caught:
            tools.render("formant_frequency", {"formant": "0,2"}, self.context)
        self.assertIn("共振峰编号", str(caught.exception))

    def test_create_sound_builds_pure_tone_and_silence(self) -> None:
        tone = tools.render(
            "create_sound",
            {"duration": 1.5, "frequency": 220, "amplitude": 0.4},
            self.context,
        )
        self.assertIn("Create Sound as pure tone", tone)
        self.assertIn("220.000000", tone)
        silence = tools.render("create_sound", {"frequency": 0}, self.context)
        self.assertIn("Create Sound from formula", silence)
        self.assertIn("~ 0", silence)

    def test_concatenate_needs_two_different_sounds(self) -> None:
        script = tools.render(
            "concatenate_sounds",
            {"object": 1, "object2": 2},
            self.context,
        )
        self.assertIn("selectObject: 1", script)
        self.assertIn("plusObject: 2", script)
        self.assertIn("Concatenate", script)
        with self.assertRaises(tools.ToolError):
            tools.render("concatenate_sounds", {"object": 1, "object2": 1}, self.context)
        with self.assertRaises(tools.ToolError):
            tools.render("concatenate_sounds", {"object": 1}, self.context)

    def test_concatenate_rejects_non_sound(self) -> None:
        with self.assertRaises(tools.ToolError):
            tools.render(
                "concatenate_sounds",
                {"object": 1, "object2": 3},
                self.context,
            )

    def test_extract_part_clamps_and_validates(self) -> None:
        script = tools.render(
            "extract_part",
            {"object": 1, "start": 0.2, "end": 0.5},
            self.context,
        )
        self.assertIn('Extract part: t1, t2, "rectangular", 1, "no"', script)
        self.assertIn("if t2 > duration", script)
        # Praat 的 from / to / end 都是保留字，模板里不能拿来当变量名。
        for line in script.splitlines():
            name = line.split("=")[0].strip()
            self.assertNotIn(name, {"from", "to", "end"})
        with self.assertRaises(tools.ToolError):
            tools.render("extract_part", {"start": 0.5}, self.context)
        with self.assertRaises(tools.ToolError):
            tools.render("extract_part", {"start": 0.5, "end": 0.2}, self.context)

    def test_save_sound_requires_absolute_wav_path(self) -> None:
        target = self.base / "out" / "a"
        script = tools.render(
            "save_sound",
            {"object": 1, "path": str(target)},
            self.context,
        )
        self.assertIn(f'Save as WAV file: "{target.as_posix()}.wav"', script)
        with self.assertRaises(tools.ToolError):
            tools.render("save_sound", {"object": 1}, self.context)
        with self.assertRaises(tools.ToolError):
            tools.render("save_sound", {"object": 1, "path": "a.wav"}, self.context)
        with self.assertRaises(tools.ToolError):
            tools.render(
                "save_sound",
                {"object": 3, "path": str(self.base / "a.wav")},
                self.context,
            )

    def test_save_sound_creates_missing_folder(self) -> None:
        target = self.base / "新建目录" / "更深" / "out.wav"
        script = tools.render(
            "save_sound",
            {"object": 1, "path": str(target)},
            self.context,
        )
        self.assertTrue(target.parent.is_dir())
        self.assertIn("Save as WAV file", script)

    def test_resample_requires_integer_rate(self) -> None:
        script = tools.render("resample_sound", {"rate": 16000}, self.context)
        self.assertIn("Resample: 16000, 50", script)
        with self.assertRaises(tools.ToolError):
            tools.render("resample_sound", {"rate": 16000.5}, self.context)

    def test_duplicate_object_uses_copy(self) -> None:
        script = tools.render("duplicate_object", {"object": 1}, self.context)
        self.assertIn('Copy: "', script)

    def test_pitch_statistics_uses_mean_min_max(self) -> None:
        script = tools.render(
            "pitch_statistics",
            {"object": 1, "from": 0.1, "to": 0.6},
            self.context,
        )
        self.assertIn('Get mean: tmin, tmax, "Hertz"', script)
        self.assertIn('Get minimum: tmin, tmax, "Hertz", "Parabolic"', script)
        self.assertIn('Get maximum: tmin, tmax, "Hertz", "Parabolic"', script)
        self.assertIn("tmin = 0.100000", script)
        self.assertIn("tmax = 0.600000", script)

    def test_intensity_statistics_uses_energy_mean(self) -> None:
        script = tools.render("intensity_statistics", {"object": 1}, self.context)
        self.assertIn('Get mean: tmin, tmax, "energy"', script)

    def test_point_queries_accept_several_times(self) -> None:
        for name in ("pitch", "intensity", "formant_frequency"):
            script = tools.render(name, {"time": "0.25,0.75"}, self.context)
            self.assertIn("time = 0.250000", script, name)
            self.assertIn("time = 0.750000", script, name)
        with self.assertRaises(tools.ToolError) as caught:
            tools.render("pitch", {"time": "abc"}, self.context)
        self.assertIn("时间只能是", str(caught.exception))
        with self.assertRaises(tools.ToolError):
            tools.render("pitch", {"time": ",".join(str(i / 10) for i in range(12))}, self.context)

    def test_formant_statistics_reports_each_formant_separately(self) -> None:
        script = tools.render("formant_statistics", {"formant": "1,2"}, self.context)
        self.assertIn('Get mean: 1, tmin, tmax, "hertz"', script)
        self.assertIn('Get mean: 2, tmin, tmax, "hertz"', script)
        # 每条共振峰都要有自己的结果行，不能共用被覆盖的变量。
        self.assertEqual(script.count("第 1 共振峰平均"), 1)
        self.assertEqual(script.count("第 2 共振峰平均"), 1)

    def test_harmonicity_statistics_uses_harmonicity_analysis(self) -> None:
        script = tools.render("harmonicity_statistics", {}, self.context)
        self.assertIn("To Harmonicity (cc): 0.01, 75, 0.1, 1", script)
        self.assertIn("Get mean: tmin, tmax", script)
        self.assertIn("谐噪比 HNR", script)

    def test_spectrogram_requires_sound(self) -> None:
        script = tools.render("spectrogram", {}, self.context)
        self.assertIn('To Spectrogram: 0.005000, 5000.000000, 0.002000, 20.000000, "Gaussian"', script)
        self.assertIn("Get number of frames", script)
        with self.assertRaises(tools.ToolError):
            tools.render("spectrogram", {"object": 3}, self.context)

    def test_spectrogram_name_does_not_shadow_the_source_object(self) -> None:
        # 2 号对象的简称是 tone，模型可能把这个名字当成新名字传进来。
        script = tools.render(
            "spectrogram",
            {"object": 2, "name": "tone"},
            self.context,
        )
        self.assertIn('Rename: "tone 频谱图"', script)

    def test_pitch_statistics_reports_time_of_maximum(self) -> None:
        script = tools.render("pitch_statistics", {}, self.context)
        self.assertIn('Get time of maximum: tmin, tmax, "Hertz", "Parabolic"', script)
        self.assertIn("最高点出现在", script)


class PythonScriptRejectionTests(unittest.TestCase):
    """模型把 Python 当 Praat 脚本时会带来莫名其妙的报错，必须提前拦下。"""

    def test_python_scripts_are_rejected(self) -> None:
        samples = (
            'import numpy as np\nsound = 1\n',
            "from praat import *\n",
            "def make_sound():\n    return 1\n",
            'print("hello")\n',
            'os.system("dir")\n',
        )
        for sample in samples:
            with self.assertRaises(tools.ToolError, msg=sample):
                tools.validate_script(sample)

    def test_praat_scripts_are_still_accepted(self) -> None:
        script = tools.validate_script(
            'selectObject: 1\nRename: "测试"\nappendInfoLine: "ok"\n'
        )
        self.assertIn("Rename", script)


if __name__ == "__main__":
    unittest.main()
