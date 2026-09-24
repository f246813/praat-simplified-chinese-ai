"""VOT adapters must hand boundaries and result serialization to Praat's C++ core."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from praat_ai import tools


class SegmentAnalysisToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.context = tools.ToolContext(
            tools.parse_object_context(
                "id\tclass\tname\tselected\tsel_start\tsel_end\n"
                "1\tSound\ttone\t1\t0.250000\t0.500000\n"
            ),
            root / "chat_result.tsv",
            root / "chat_state.txt",
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_zero_boundaries_are_explicit_manual_values(self) -> None:
        script = tools._build_vot(
            {"object": "Sound tone", "burst": 0.0, "voicing": 0.0}, self.context
        )

        self.assertIn("Write VOT analysis to file", script)
        self.assertIn("0.000000, 0.000000", script)
        self.assertIn("readFile$", script)
        self.assertNotIn("Filter (pass Hann band)", script)

    def test_negative_vot_boundaries_are_passed_without_reordering(self) -> None:
        script = tools._build_vot(
            {"object": "Sound tone", "burst": 0.30, "voicing": 0.28}, self.context
        )

        self.assertIn("0.300000, 0.280000", script)
        self.assertIn("Write VOT analysis to file", script)
        self.assertNotIn("必须晚于", script)

    def test_omitted_boundaries_select_candidate_estimation(self) -> None:
        script = tools._build_vot({"object": "Sound tone"}, self.context)

        self.assertIn("Write VOT analysis to file", script)
        self.assertIn("undefined, undefined", script)
        self.assertIn("按编辑器圈选 0.250–0.500 秒", script)
        self.assertIn("readFile$", script)

    def test_one_sided_boundary_fails_before_script_dispatch(self) -> None:
        with self.assertRaises(tools.ToolError):
            tools._build_vot(
                {"object": "Sound tone", "burst": 0.30}, self.context
            )

    def test_longsound_uses_the_same_vot_action(self) -> None:
        long_context = tools.ToolContext(
            tools.parse_object_context("id\tclass\tname\tselected\n1\tLongSound\tlong\t1\n"),
            self.context.result_path,
            self.context.state_path,
        )

        script = tools._build_vot(
            {"object": "LongSound long", "burst": 0.30, "voicing": 0.32},
            long_context,
        )

        self.assertIn("Write VOT analysis to file", script)
        self.assertNotIn("Filter (pass Hann band)", script)


if __name__ == "__main__":
    unittest.main()
