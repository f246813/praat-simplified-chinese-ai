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

GRID_CONTEXT = "id\tclass\tname\tselected\n1\tTextGrid\tTextGrid grid\t1\n"

# 打开了编辑器、并在波形上拖选了 0.25–0.5 秒时的上下文（多出两列）。
SELECTED_CONTEXT = (
    "id\tclass\tname\tselected\tsel_start\tsel_end\n"
    "1\tSound\tSound tone\t1\t0.250000\t0.500000\n"
    "2\tSound\tSound tone2\t0\t\t\n"
)

# Sound 编辑器保留圈选，但 Praat 对象列表当前选中的是 Harmonicity。
SOUND_SELECTION_HARMONICITY_SELECTED = (
    "id\tclass\tname\tselected\tsel_start\tsel_end\n"
    "1\tSound\tSound tone\t0\t0.250000\t0.500000\n"
    "2\tHarmonicity\tHarmonicity tone\t1\t\t\n"
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

    def test_editor_selection_columns_are_parsed(self) -> None:
        # Praat 打开编辑器后会多写 sel_start/sel_end 两列；旧的四列写法也要照旧能读。
        rows = tools.parse_object_context(SELECTED_CONTEXT)
        self.assertEqual(rows[0].selection, (0.25, 0.5))
        self.assertIsNone(rows[1].selection)
        legacy = tools.parse_object_context(CONTEXT)
        self.assertIsNone(legacy[0].selection)

    def test_cursor_without_a_dragged_range_is_not_a_selection(self) -> None:
        rows = tools.parse_object_context(
            "id\tclass\tname\tselected\tsel_start\tsel_end\n"
            "1\tSound\tSound tone\t1\t0.300000\t0.300000\n"
        )
        self.assertIsNone(rows[0].selection)


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
                "3\tTextGrid\tTextGrid grid\t0\n"
            ),
            base / "chat_result.tsv",
            base / "chat_state.txt",
        )
        extra: dict[str, dict[str, object]] = {
            "rename_object": {"new_name": "测试"},
            "extract_part": {"start": 0.1, "end": 0.4},
            "save_sound": {"path": str(base / "ai-chat.wav")},
            "read_file": {"path": str(base / "ai-chat.wav")},
            "concatenate_sounds": {"object": 1, "object2": 2},
            "textgrid_info": {"object": 3},
            "textgrid_set_interval": {
                "object": 3,
                "start": 0.1,
                "end": 0.2,
                "label": "a",
            },
            "textgrid_insert_boundary": {"object": 3, "time": 0.5},
            "vot": {"object": 3, "burst": 0.3, "voicing": 0.42},
            "measure": {"parameter": "rms,mean_intensity"},
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

    def test_object_creating_tools_report_the_new_id(self) -> None:
        """新建对象的结果行里要带 id：多步请求的下一步要靠它认出这个新对象。"""

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
        cases = {
            "create_sound": {"duration": 0.2, "frequency": 220},
            "extract_part": {"start": 0.1, "end": 0.4},
            "duplicate_object": {},
            "resample_sound": {"rate": 16000},
            "concatenate_sounds": {"object": 1, "object2": 2},
            "spectrogram": {},
        }
        for tool_name, arguments in cases.items():
            with self.subTest(tool=tool_name):
                script = tools.render(tool_name, arguments, context)
                self.assertIn("newId = ", script, tool_name)
                self.assertIn("fixed$ (newId, 0)", script, tool_name)


class BorrowedMeasurementTests(unittest.TestCase):
    """B3：借用 chengafni 的测量脚本（公式照抄，真机验证在 verify_chat_templates）。"""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        base = Path(self.directory.name)
        self.result = base / "chat_result.tsv"
        self.context = tools.ToolContext(
            tools.parse_object_context(
                "id\tclass\tname\tselected\n"
                "1\tSound\tSound tone\t1\n"
                "2\tTextGrid\tTextGrid grid\t0\n"
                "3\tIntensity\tIntensity tone\t0\n"
                "4\tPitch\tPitch tone\t0\n"
            ),
            self.result,
            base / "chat_state.txt",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def render(self, name: str, **arguments: object) -> str:
        return tools.render(name, arguments, self.context)

    def test_spectral_emphasis_follows_the_source_script(self) -> None:
        script = self.render("spectral_emphasis", object=1)
        self.assertIn("intensity = Get intensity (dB)", script)
        self.assertIn("To Pitch: 0, 75.000000, 600.000000", script)
        self.assertIn("Filter (pass Hann band): 0, cutoff, 20.000000", script)
        # 中间对象要删掉，最后回到用户原来选中的对象。
        self.assertIn("Remove", script)
        self.assertIn("selectObject: 1", script)

    def test_spectral_emphasis_falls_back_to_the_only_sound(self) -> None:
        """指错类型但列表里只有一个 Sound 时按它算（guide §8.4 的按类型兜底）。"""

        script = self.render("spectral_emphasis", object=2)
        self.assertIn("selectObject: 1", script)

    def test_hl_ratio_rejects_overlapping_bands(self) -> None:
        with self.assertRaises(tools.ToolError):
            self.render("hl_ratio", object=1, low_to=5000, high_from=4000)
        script = self.render("hl_ratio", object=1)
        self.assertIn("To Spectrum", script)
        self.assertIn("lowBand = Get band energy: 0.000000, 4000.000000", script)

    def test_hammarberg_index_needs_sound_or_ltas(self) -> None:
        script = self.render("hammarberg_index", object=1)
        self.assertIn("To Ltas: 100.000000", script)
        self.assertIn('lowBand = Get maximum: 0.000000, 2000.000000, "Parabolic"', script)
        with self.assertRaises(tools.ToolError):
            self.render("hammarberg_index", object=2)

    def test_pitch_peak_latency_rejects_objects_without_pitch(self) -> None:
        script = self.render("pitch_peak_latency", object=1)
        self.assertIn('peakTime = Get time of maximum: tmin, tmax, "Hertz", "Parabolic"', script)
        self.assertIn("latency = (peakTime - tmin) / (tmax - tmin)", script)
        # TextGrid 有时长但没有 To Pitch：要在这里拦住，而不是让 Praat 弹英文错误框。
        with self.assertRaises(tools.ToolError):
            self.render("pitch_peak_latency", object=2)
        # 已经是 Pitch 的直接用，不再做一次 To Pitch。
        self.assertNotIn("To Pitch", self.render("pitch_peak_latency", object=4))

    def test_peak_to_average_uses_rms_not_the_signed_mean(self) -> None:
        script = self.render("peak_to_average_ratio", object=1)
        self.assertIn('peak = Get maximum: tmin, tmax, "Sinc70"', script)
        self.assertIn("rms = Get root-mean-square: tmin, tmax", script)
        self.assertNotIn("Get mean: 1", script)

    def test_intensity_slope_local_and_global(self) -> None:
        local = self.render("intensity_slope", object=1)
        self.assertIn('Formula: "abs(self[col+1]-self[col])/dx"', local)
        self.assertIn("Down to Matrix", local)
        global_ = self.render("intensity_slope", object=1, method="global")
        self.assertIn("slope = (lastEl - firstEl) / (lastTime - firstTime)", global_)
        self.assertNotIn("Formula:", global_)

    def test_intensity_slope_rejects_bad_method_and_range(self) -> None:
        with self.assertRaises(tools.ToolError):
            self.render("intensity_slope", object=1, method="whatever")
        # Intensity 对象没有「取片段」命令：别假装能按范围算。
        with self.assertRaises(tools.ToolError):
            self.render("intensity_slope", object=3, **{"from": 0.1, "to": 0.5})
        with self.assertRaises(tools.ToolError):
            self.render("intensity_slope", object=2)

    def test_intensity_slope_extracts_a_part_for_sound_ranges(self) -> None:
        script = self.render("intensity_slope", object=1, **{"from": 0.2, "to": 0.8})
        self.assertIn("extractedId = Extract part:", script)
        self.assertIn("if extractedId <> 0", script)

    def test_intensity_slope_whole_object_does_not_delete_anything(self) -> None:
        """整段分析时 extractedId = 0，收尾的删除要跳过（不能删错对象）。"""

        script = self.render("intensity_slope", object=1)
        self.assertIn("extractedId = 0", script)
        self.assertIn("if extractedId <> 0", script)


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

    def test_custom_script_must_not_open_the_info_window(self) -> None:
        """模型写 writeInfoLine / print 会弹出「Praat Info」，脚本层要兜住，内容不丢。"""

        directory = tempfile.TemporaryDirectory()
        base = Path(directory.name)
        result = base / "chat_result.tsv"
        context = tools.ToolContext(
            tools.parse_object_context(CONTEXT), result, base / "chat_state.txt"
        )
        script = tools.render(
            tools.CUSTOM_SCRIPT_TOOL,
            {},
            context,
            custom_script=(
                'selectObject: 1\n'
                'writeInfoLine: "共振峰：", 500\n'
                "clearinfo\n"
                'printline 这行也要留着\n'
                'Rename: "新名字"\n'
            ),
        )
        directory.cleanup()
        # 可执行的行里不许再有会弹 Info 窗口的命令（被注释掉的 printtab/clearinfo 不算）。
        for line in script.splitlines():
            if line.strip().startswith("#"):
                continue
            self.assertIsNone(tools.INFO_LINE_PATTERN.match(line), line)
            self.assertIsNone(tools.INFO_OTHER_PATTERN.match(line), line)
        # 行式的输出改成写结果文件，模型想回给用户的那句话还在。
        self.assertIn('appendFileLine: "', script)
        self.assertIn('"共振峰：", 500', script)
        self.assertIn('Rename: "新名字"', script)
        # printline 的字面文字也要带过去，不再被注释掉。
        self.assertIn('appendFileLine: "', script)
        self.assertNotIn("这行也要留着", "\n".join(
            line for line in script.splitlines() if line.strip().startswith("#")
        ))
        self.assertIn("这行也要留着", script)
        # 只有「没有内容可保留」的命令才留注释，方便排查。
        self.assertIn("已省略只影响 Info 窗口的命令", script)

    def test_literal_output_commands_become_result_lines(self) -> None:
        """printline / print / echo 在 Praat 里写的是字面文字，整段抄进结果文件。"""

        script = tools.neutralize_info_commands(
            'printline 第一行\nprint 接着写\necho 说一句"带引号"的话\n',
            Path("D:/x/result.tsv"),
        )
        self.assertEqual(
            script,
            'appendFileLine: "D:/x/result.tsv", "第一行"\n'
            'appendFileLine: "D:/x/result.tsv", "接着写"\n'
            'appendFileLine: "D:/x/result.tsv", "说一句""带引号""的话"\n',
        )

    def test_value_output_commands_become_result_lines(self) -> None:
        """appendInfo / writeInfo 带的是值列表，原样换成 appendFileLine。"""

        script = tools.neutralize_info_commands(
            'appendInfo: "F1 = ", f1, " Hz"\nwriteInfo: 1, 2, 3\n',
            Path("D:/x/result.tsv"),
        )
        self.assertEqual(
            script,
            'appendFileLine: "D:/x/result.tsv", "F1 = ", f1, " Hz"\n'
            'appendFileLine: "D:/x/result.tsv", 1, 2, 3\n',
        )

    def test_meaningless_info_commands_are_commented_out(self) -> None:
        """printtab 只写制表符、clearinfo 只清空 Info 窗口：没有内容可保留。"""

        script = tools.neutralize_info_commands(
            "printtab\nclearinfo\n", Path("D:/x/result.tsv")
        )
        self.assertNotIn("appendFileLine", script)
        self.assertEqual(len(script.strip().splitlines()), 2)
        for line in script.strip().splitlines():
            self.assertTrue(line.startswith("# praat-ai:"), line)

    def test_write_info_line_without_arguments_stays_valid(self) -> None:
        script = tools.neutralize_info_commands(
            "writeInfoLine:\n", Path("D:/x/result.tsv")
        )
        self.assertEqual(script.strip(), 'appendFileLine: "D:/x/result.tsv", ""')

    def test_append_file_line_lines_are_untouched(self) -> None:
        original = 'appendFileLine: "D:/x/result.tsv", "ok"\n'
        self.assertEqual(
            tools.neutralize_info_commands(original, Path("D:/x/result.tsv")), original
        )


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


class FormantSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        base = Path(self.directory.name)
        self.context = tools.ToolContext(
            tools.parse_object_context(SOUND_SELECTION_HARMONICITY_SELECTED),
            base / "chat_result.tsv",
            base / "chat_state.txt",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_selected_harmonicity_falls_back_to_the_only_sound_and_keeps_its_selection(self) -> None:
        for name, arguments, expected_time in (
            ("formant_statistics", {"formant": 1}, "tmin = 0.250000"),
            ("formant_frequency", {"formant": 1}, "time = 0.375000"),
        ):
            with self.subTest(tool=name):
                script = tools.render(name, arguments, self.context)
                self.assertIn("selectObject: 1", script)
                self.assertIn("To Formant (burg):", script)
                self.assertIn(expected_time, script)
                if name == "formant_statistics":
                    self.assertIn("tmax = 0.500000", script)

    def test_explicit_harmonicity_id_is_rejected_instead_of_replaced_by_sound(self) -> None:
        for name in ("formant_statistics", "formant_frequency", "formant_bandwidth"):
            with self.subTest(tool=name):
                with self.assertRaises(tools.ToolError) as caught:
                    tools.render(name, {"object": 2, "formant": 1}, self.context)
                self.assertIn("对象 2 是 Harmonicity", str(caught.exception))
                self.assertIn("Sound 或 Formant", str(caught.exception))

    def test_selected_harmonicity_with_multiple_candidates_requires_an_object_id(self) -> None:
        text = SOUND_SELECTION_HARMONICITY_SELECTED.replace(
            "2\tHarmonicity\tHarmonicity tone\t1\t\t\n",
            "2\tSound\tSound second\t0\t\t\n"
            "3\tHarmonicity\tHarmonicity tone\t1\t\t\n",
        )
        context = tools.ToolContext(
            tools.parse_object_context(text),
            self.context.result_path,
            self.context.state_path,
        )
        with self.assertRaises(tools.ToolError) as caught:
            tools.render("formant_statistics", {}, context)
        self.assertIn("请用对象 id 指定", str(caught.exception))
        self.assertIn("1: Sound tone", str(caught.exception))
        self.assertIn("2: Sound second", str(caught.exception))

    def test_existing_formant_is_used_without_burg_conversion(self) -> None:
        text = (
            "id\tclass\tname\tselected\n"
            "1\tSound\tSound tone\t0\n"
            "2\tFormant\tFormant tone\t0\n"
            "3\tHarmonicity\tHarmonicity tone\t1\n"
        )
        context = tools.ToolContext(
            tools.parse_object_context(text),
            self.context.result_path,
            self.context.state_path,
        )
        script = tools.render("formant_statistics", {"object": 2}, context)
        self.assertIn("selectObject: 2", script)
        self.assertNotIn("To Formant (burg):", script)


class TextGridToolTests(unittest.TestCase):
    """TextGrid 的查看与标注（真机命令在 verify_chat_templates.py 里跑过）。"""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        base = Path(self.directory.name)
        self.context = tools.ToolContext(
            tools.parse_object_context(GRID_CONTEXT),
            base / "chat_result.tsv",
            base / "chat_state.txt",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_info_lists_tiers_and_intervals(self) -> None:
        script = tools.render("textgrid_info", {}, self.context)
        self.assertIn("Get number of tiers", script)
        # if 条件里不能直接调用命令，必须先赋值。
        self.assertIn("isInterval = Is interval tier: tier", script)
        self.assertIn("if isInterval = 1", script)
        self.assertIn("Get label of interval: tier, part", script)
        self.assertIn("Get number of points: tier", script)
        self.assertIn("Get label of point: tier, part", script)

    def test_info_limits_the_listing(self) -> None:
        script = tools.render("textgrid_info", {"maximum_intervals": 5}, self.context)
        self.assertIn("if shown < 5", script)
        self.assertIn("未列出", script)

    def test_set_interval_inserts_boundaries_and_writes_label(self) -> None:
        script = tools.render(
            "textgrid_set_interval",
            {"start": 0.2, "end": 0.5, "label": "a"},
            self.context,
        )
        self.assertIn("t1 = 0.200000", script)
        self.assertIn("t2 = 0.500000", script)
        self.assertIn("Insert boundary: 1, t1", script)
        self.assertIn("Insert boundary: 1, t2", script)
        self.assertIn('Set interval text: 1, part, "a"', script)
        # 已经有边界时不能再插入，否则 Praat 会直接报错。
        self.assertIn("needBoundary1 = 1", script)
        self.assertIn("needBoundary2 = 1", script)
        self.assertIn("boundaryTime", script)
        self.assertIn("tier = 1", script)

    def test_set_interval_requires_label_and_range(self) -> None:
        with self.assertRaises(tools.ToolError):
            tools.render("textgrid_set_interval", {"start": 0.2, "end": 0.5}, self.context)
        with self.assertRaises(tools.ToolError):
            tools.render("textgrid_set_interval", {"label": "a"}, self.context)
        with self.assertRaises(tools.ToolError):
            tools.render(
                "textgrid_set_interval",
                {"start": 0.5, "end": 0.2, "label": "a"},
                self.context,
            )

    def test_insert_boundary_reports_existing_boundary(self) -> None:
        script = tools.render("textgrid_insert_boundary", {"time": 0.5}, self.context)
        self.assertIn("Insert boundary: 1, t1", script)
        self.assertIn("已经有边界", script)
        with self.assertRaises(tools.ToolError):
            tools.render("textgrid_insert_boundary", {}, self.context)

    def test_textgrid_tools_reject_other_objects(self) -> None:
        sound_context = tools.ToolContext(
            tools.parse_object_context(MIXED_CONTEXT),
            self.context.result_path,
            self.context.state_path,
        )
        for name, arguments in (
            ("textgrid_info", {"object": 1}),
            ("textgrid_set_interval", {"object": 1, "start": 0.1, "end": 0.2, "label": "a"}),
            ("textgrid_insert_boundary", {"object": 1, "time": 0.5}),
        ):
            # 这个上下文里有两个 Sound、一个 TextGrid：模型把 object 填成 Sound 时
            # 应该自动改用那个唯一的 TextGrid，而不是报错。
            script = tools.render(name, arguments, sound_context)
            self.assertIn("selectObject: 3", script, name)

    def test_class_fallback_needs_a_unique_candidate(self) -> None:
        two_grids = tools.ToolContext(
            tools.parse_object_context(
                "id\tclass\tname\tselected\n"
                "1\tSound\tSound tone\t1\n"
                "2\tTextGrid\tTextGrid a\t0\n"
                "3\tTextGrid\tTextGrid b\t0\n"
            ),
            self.context.result_path,
            self.context.state_path,
        )
        with self.assertRaises(tools.ToolError) as caught:
            tools.render("textgrid_info", {"object": 1}, two_grids)
        self.assertIn("TextGrid", str(caught.exception))

    def test_tier_number_is_validated(self) -> None:
        with self.assertRaises(tools.ToolError) as caught:
            tools.render("textgrid_insert_boundary", {"time": 0.5, "tier": 0}, self.context)
        self.assertIn("层号", str(caught.exception))
        with self.assertRaises(tools.ToolError):
            tools.render("textgrid_set_interval", {"tier": "第一层"}, self.context)


class VotToolTests(unittest.TestCase):
    """VOT is dispatched through the shared local request service."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        base = Path(self.directory.name)
        self.grid_context = tools.ToolContext(
            tools.parse_object_context(GRID_CONTEXT),
            base / "chat_result.tsv",
            base / "chat_state.txt",
        )
        self.sound_context = tools.ToolContext(
            tools.parse_object_context("id\tclass\tname\tselected\n1\tSound\tSound tone\t1\n"),
            base / "chat_result.tsv",
            base / "chat_state.txt",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_sample_index_accepts_roundoff_at_audio_domain_boundary(self) -> None:
        first_sample_time = 1.1337868480731927e-05
        sample_period = 2.2675736961451248e-05

        sample = tools._vot_sample_index(
            0.0,
            first_sample_time=first_sample_time,
            sample_period_sec=sample_period,
            sample_count=44100,
        )

        self.assertEqual(sample, 0)

    def test_sample_index_rounds_half_sample_ties_up_despite_float_error(self) -> None:
        sample_rate = 44100
        requested_sample = 220
        time_seconds = requested_sample / sample_rate

        sample = tools._vot_sample_index(
            time_seconds,
            first_sample_time=0.5 / sample_rate,
            sample_period_sec=1.0 / sample_rate,
            sample_count=28549,
        )

        self.assertEqual(sample, requested_sample)

    def test_vot_audio_query_preserves_half_sample_boundary_precision(self) -> None:
        environment = _CapturingPraatEnvironment(Path(self.directory.name))

        ok, _, _ = tools.LOCAL_TOOLS["vot"].run(
            {"object": 1, "mode": "acoustic_only", "from": 0.25, "to": 0.5},
            self.sound_context,
            environment,
        )

        self.assertFalse(ok)
        self.assertTrue(environment.scripts)
        self.assertIn("fixed$ (firstSampleTime, 20)", environment.scripts[0])
        self.assertNotIn("secondSampleTime", environment.scripts[0])

    def test_zero_times_are_passed_as_explicit_boundaries(self) -> None:
        schema = tools.tool_parameters("vot")
        self.assertIn("vot", tools.LOCAL_TOOLS)
        self.assertEqual(
            schema["properties"]["mode"]["enum"],
            ["model_assisted", "acoustic_only", "manual"],
        )

    def test_only_one_time_is_still_an_error(self) -> None:
        with self.assertRaises(tools.ToolError):
            tools.LOCAL_TOOLS["vot"].run(
                {"burst": 0.3, "object": 1},
                self.sound_context,
                _UnusedPraatEnvironment(Path(self.directory.name)),
            )

    def test_non_numeric_time_is_rejected_in_chinese(self) -> None:
        with self.assertRaises(tools.ToolError) as raised:
            tools.LOCAL_TOOLS["vot"].run(
                {"burst": "爆破", "voicing": 0.4, "object": 1},
                self.sound_context,
                _UnusedPraatEnvironment(Path(self.directory.name)),
            )
        self.assertIn("必须是数字", str(raised.exception))

    def test_textgrid_path_adds_boundaries_and_reports_ms(self) -> None:
        environment = _UnusedPraatEnvironment(Path(self.directory.name))
        ok, rows, _ = tools.LOCAL_TOOLS["vot"].run(
            {"burst": 0.30, "voicing": 0.42}, self.grid_context, environment
        )
        script = rows[0]
        self.assertTrue(ok)
        self.assertIn("t1 = 0.300000", script)
        self.assertIn("t2 = 0.420000", script)
        self.assertIn("vot = t2 - t1", script)
        self.assertIn("Insert boundary: 1, t1", script)
        self.assertIn("Insert boundary: 1, t2", script)
        self.assertIn("fixed$ (vot * 1000, 1)", script)
        self.assertIn("秒（爆破）", script)
        self.assertIn("并在该层补上了边界", script)

    def test_sound_path_uses_shared_cpp_analysis_action(self) -> None:
        self.assertNotIn("vot", tools.TOOL_MAP)
        vot_schema = next(
            item for item in tools.tool_schemas()
            if item["function"]["name"] == "vot"
        )
        self.assertIn("model_assisted", vot_schema["function"]["parameters"]["properties"]["mode"]["enum"])
        self.assertEqual(tools.LOCAL_TOOLS["vot"].parameters, tools.tool_parameters("vot"))

    def test_missing_or_bad_times_are_rejected(self) -> None:
        with self.assertRaisesRegex(tools.ToolError, "不会退回整段音频"):
            tools.LOCAL_TOOLS["vot"].run(
                {"object": 1},
                tools.ToolContext(
                    tools.parse_object_context("id\tclass\tname\tselected\n1\tSound\ttone\t1\n"),
                    self.sound_context.result_path,
                    self.sound_context.state_path,
                ),
                _UnusedPraatEnvironment(Path(self.directory.name)),
            )
        with self.assertRaises(tools.ToolError) as caught:
            tools.LOCAL_TOOLS["vot"].run(
                {"burst": 0.3}, self.grid_context,
                _UnusedPraatEnvironment(Path(self.directory.name)),
            )
        self.assertIn("voicing", str(caught.exception))
        self.assertIn("voicing", str(caught.exception))

    def test_auto_mode_needs_a_sound_not_a_textgrid(self) -> None:
        with self.assertRaises(tools.ToolError) as caught:
            tools.LOCAL_TOOLS["vot"].run(
                {"from": 0.1, "to": 0.3}, self.grid_context,
                _UnusedPraatEnvironment(Path(self.directory.name)),
            )
        self.assertIn("人工提供", str(caught.exception))


class _UnusedPraatEnvironment:
    def __init__(self, runtime: Path):
        self.runtime_directory = runtime
        self.praat_executable = "Praat.exe"
        self.cancelled = None

    def execute(self, script: str) -> tuple[bool, list[str], str]:
        return True, [script], ""


class _CapturingPraatEnvironment(_UnusedPraatEnvironment):
    def __init__(self, runtime: Path):
        super().__init__(runtime)
        self.scripts: list[str] = []

    def execute(self, script: str) -> tuple[bool, list[str], str]:
        self.scripts.append(script)
        return True, [], ""


class EditorSelectionRangeTests(unittest.TestCase):
    """拖出来的选区要能接到所有"按一段时间统计"的工具上，而不是只有 VOT。"""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        base = Path(self.directory.name)
        self.selected = tools.ToolContext(
            tools.parse_object_context(SELECTED_CONTEXT),
            base / "chat_result.tsv",
            base / "chat_state.txt",
        )
        self.plain = tools.ToolContext(
            tools.parse_object_context(CONTEXT),
            base / "chat_result.tsv",
            base / "chat_state.txt",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_statistics_tools_use_the_editor_selection(self) -> None:
        for name in (
            "pitch_statistics",
            "intensity_statistics",
            "formant_statistics",
            "harmonicity_statistics",
        ):
            script = tools.render(name, {}, self.selected)
            self.assertIn("tmin = 0.250000", script, name)
            self.assertIn("tmax = 0.500000", script, name)
            self.assertIn("按编辑器圈选 0.250–0.500 秒", script, name)
            self.assertIn("appendFileLine:", script, name)
            # 回话的最后一句就是范围出处，不能只写数字。
            written = [
                line for line in script.splitlines() if "chat_result.tsv" in line
            ]
            self.assertTrue(written[-1].endswith("rangeNote$"), name)

    def test_statistics_note_survives_the_model_echoing_the_selection(self) -> None:
        # 模型把 sel_start/sel_end 抄成 from/to 时，回话里仍要写清范围出处。
        script = tools.render(
            "formant_statistics",
            {"formant": 1, "from": 0.25, "to": 0.5},
            self.selected,
        )
        self.assertIn("tmin = 0.250000", script)
        self.assertIn("按编辑器圈选 0.250–0.500 秒", script)

    def test_explicit_range_beats_the_editor_selection(self) -> None:
        script = tools.render(
            "intensity_statistics",
            {"from": 0.6, "to": 0.8},
            self.selected,
        )
        self.assertIn("tmin = 0.600000", script)
        self.assertIn("tmax = 0.800000", script)
        self.assertNotIn("按编辑器圈选", script)

    def test_without_a_selection_the_whole_object_is_still_the_default(self) -> None:
        script = tools.render("pitch_statistics", {}, self.plain)
        self.assertIn("tmin = 0", script)
        self.assertIn("tmax = duration", script)
        self.assertNotIn("按编辑器圈选", script)
        self.assertIn('rangeNote$ = ""', script)

    def test_point_query_falls_back_to_the_selection_middle(self) -> None:
        # 圈了 0.25–0.5 再问「这一刻的基频」：问的应该是圈里那一段，不是整个对象的中点。
        for name in ("pitch", "intensity", "formant_frequency"):
            script = tools.render(name, {}, self.selected)
            self.assertIn("time = 0.375000", script, name)
        explicit = tools.render("pitch", {"time": 0.9}, self.selected)
        self.assertIn("time = 0.900000", explicit)
        self.assertNotIn("time = 0.375000", explicit)

    def test_extract_part_uses_the_editor_selection(self) -> None:
        script = tools.render("extract_part", {}, self.selected)
        self.assertIn("t1 = 0.250000", script)
        self.assertIn("t2 = 0.500000", script)
        self.assertIn("按编辑器圈选 0.250–0.500 秒", script)
        # 没圈选也没有 end 时仍然报错，不能猜一个范围。
        with self.assertRaises(tools.ToolError):
            tools.render("extract_part", {}, self.plain)

    def test_extract_part_honours_the_finish_alias(self) -> None:
        # finish 是 end 的别名；以前取值漏了别名，会误报「开始时间必须小于结束时间」。
        script = tools.render(
            "extract_part",
            {"object": 1, "start": 0.1, "finish": 0.4},
            self.plain,
        )
        self.assertIn("t2 = 0.400000", script)

    def test_textgrid_label_uses_the_editor_selection(self) -> None:
        # 在 TextGrid 编辑器里拖一段再让 AI 标注：范围就用拖出来的那一段。
        context = tools.ToolContext(
            tools.parse_object_context(
                "id\tclass\tname\tselected\tsel_start\tsel_end\n"
                "1\tTextGrid\tTextGrid grid\t1\t0.250000\t0.500000\n"
            ),
            self.plain.result_path,
            self.plain.state_path,
        )
        script = tools.render("textgrid_set_interval", {"label": "a"}, context)
        self.assertIn("t1 = 0.250000", script)
        self.assertIn("t2 = 0.500000", script)
        self.assertIn("按编辑器圈选 0.250–0.500 秒", script)
        # 没圈选时照旧报错，不能自己编一个区间。
        with self.assertRaises(tools.ToolError):
            tools.render("textgrid_set_interval", {"label": "a"}, self.plain)


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
