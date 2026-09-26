"""AI VOT uses the shared request, native snapshot, and result service."""

from __future__ import annotations

import csv
import json
import re
import struct
import tempfile
import unittest
from pathlib import Path

from praat_ai import tools


class FakePraatEnvironment:
    def __init__(self, runtime: Path):
        self.runtime_directory = runtime
        self.praat_executable = "Praat.exe"
        self.cancelled = None
        self.scripts: list[str] = []

    def execute(self, script: str) -> tuple[bool, list[str], str]:
        self.scripts.append(script)
        if "sampleRate = Get sampling frequency" in script:
            return True, ["1000|1000.000000000000000|0.000500000000000|0.001500000000000"], ""
        if "Write VOT audio snapshot:" in script:
            line = next(item for item in script.splitlines() if "Write VOT audio snapshot:" in item)
            paths = re.findall(r'"([^"]+)"', line)
            manifest, pcm, wav = map(Path, paths[:3])
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "object_id": 1,
                        "source_kind": "Sound",
                        "sample_rate_hz": 1000.0,
                        "channels": 1,
                        "sample_count": 1000,
                        "snapshot_start_sample": 0,
                        "time_origin_seconds": 0.0005,
                    }
                ),
                encoding="utf-8",
            )
            pcm.write_bytes(struct.pack("<1000d", *([0.0] * 1000)))
            wav.write_bytes(b"test wav fixture")
            return True, [], ""
        if "Analyse VOT audio snapshot:" in script:
            line = next(item for item in script.splitlines() if "Analyse VOT audio snapshot:" in item)
            paths = re.findall(r'"([^"]+)"', line)
            result_path = Path(paths[-1])
            result_path.write_text(
                "metric_id\tvalue\tstatus\treason\tparameters\n"
                "vot_candidate_ms\t\tambiguous\tmultiple plausible pairs\t\n",
                encoding="utf-8",
            )
            return True, [], ""
        raise AssertionError(f"unexpected Praat script: {script}")


class SegmentAnalysisToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.context = tools.ToolContext(
            tools.parse_object_context(
                "id\tclass\tname\tselected\tsel_start\tsel_end\n"
                "1\tSound\ttone\t1\t0.250000\t0.500000\n"
            ),
            self.root / "chat_result.tsv",
            self.root / "chat_state.txt",
        )
        self.environment = FakePraatEnvironment(self.root / "runtime")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def run_vot(self, arguments: dict[str, object]) -> tuple[bool, list[str], str]:
        return tools.LOCAL_TOOLS["vot"].run(arguments, self.context, self.environment)

    def test_ai_vot_calls_native_snapshot_and_detector_and_returns_shared_result(self) -> None:
        ok, rows, failure = self.run_vot(
            {"object": "Sound tone", "mode": "acoustic_only", "from": 0.251, "to": 0.501}
        )

        self.assertTrue(ok, failure)
        self.assertEqual(len(self.environment.scripts), 3)
        self.assertIn("Write VOT audio snapshot:", self.environment.scripts[1])
        self.assertIn("Analyse VOT audio snapshot:", self.environment.scripts[2])
        self.assertIn(", 251, 501,", self.environment.scripts[2])
        self.assertNotIn("Write VOT analysis to file", "\n".join(self.environment.scripts))
        result = json.loads(rows[0])
        self.assertEqual(result["target_range"], [251, 501])
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["mode"], "acoustic_only")

    def test_explicit_range_is_never_replaced_by_nearby_editor_selection(self) -> None:
        target, _ = tools._vot_range_arguments(
            {"from": 0.251, "to": 0.501}, self.context.objects[0]
        )

        self.assertEqual(target, (0.251, 0.501))

    def test_missing_target_range_does_not_fall_back_to_whole_audio(self) -> None:
        context = tools.ToolContext(
            tools.parse_object_context("id\tclass\tname\tselected\n1\tSound\ttone\t1\n"),
            self.context.result_path,
            self.context.state_path,
        )

        with self.assertRaisesRegex(tools.ToolError, "不会退回整段音频"):
            tools.LOCAL_TOOLS["vot"].run(
                {"object": 1, "mode": "acoustic_only"}, context, self.environment
            )
        self.assertEqual(self.environment.scripts, [])

    def test_missing_one_endpoint_fails_before_native_execution(self) -> None:
        with self.assertRaisesRegex(tools.ToolError, "必须同时提供"):
            self.run_vot({"object": 1, "from": 0.2, "mode": "acoustic_only"})
        self.assertEqual(self.environment.scripts, [])

    def test_editor_selection_is_used_only_when_no_explicit_range_is_given(self) -> None:
        target, context_range = tools._vot_range_arguments({}, self.context.objects[0])

        self.assertEqual(target, (0.25, 0.5))
        self.assertEqual(context_range, (None, None))

    def test_editor_selection_uses_its_fixed_vot_context_at_full_precision(self) -> None:
        row = tools.parse_object_context(
            "id\tclass\tname\tselected\tsel_start\tsel_end\tcontext_start\tcontext_end\n"
            "1\tSound\ttone\t1\t0.25500000000000000\t0.50500000000000000\t"
            "0.12345678901234566\t0.87654321098765430\n"
        )[0]

        target, context_range = tools._vot_range_arguments({}, row)

        self.assertEqual(target, (0.255, 0.505))
        self.assertEqual(context_range, (0.12345678901234566, 0.8765432109876543))

    def test_explicit_range_uses_editor_fixed_context_only_when_it_contains_target(self) -> None:
        row = tools.parse_object_context(
            "id\tclass\tname\tselected\tsel_start\tsel_end\tcontext_start\tcontext_end\n"
            "1\tSound\ttone\t1\t0.25000000000000000\t0.50000000000000000\t"
            "0.10000000000000001\t0.80000000000000004\n"
        )[0]

        target, context_range = tools._vot_range_arguments(
            {"from": 0.255, "to": 0.505}, row
        )

        self.assertEqual(target, (0.255, 0.505))
        self.assertEqual(context_range, (0.1, 0.8))

    def test_manual_mode_uses_shared_sample_formula_and_skips_alignment(self) -> None:
        ok, rows, failure = self.run_vot(
            {
                "object": 1,
                "mode": "manual",
                "from": 0.25,
                "to": 0.5,
                "burst": 0.31,
                "voicing": 0.30,
            }
        )

        self.assertTrue(ok, failure)
        self.assertEqual(len(self.environment.scripts), 2)
        self.assertNotIn("Analyse VOT audio snapshot:", self.environment.scripts[-1])
        result = json.loads(rows[0])
        self.assertEqual(result["status"], "manual_confirmed")
        self.assertEqual(result["burst_sample_index"], 310)
        self.assertEqual(result["onset_sample_index"], 300)
        self.assertAlmostEqual(result["vot_ms"], -10.0)
        self.assertEqual(result["burst_source"], "manual")

    def test_textgrid_manual_boundary_workflow_remains_available(self) -> None:
        context = tools.ToolContext(
            tools.parse_object_context("id\tclass\tname\tselected\n2\tTextGrid\tgrid\t1\n"),
            self.context.result_path,
            self.context.state_path,
        )
        env = FakePraatEnvironment(self.root / "textgrid-runtime")
        env.execute = lambda script: (True, [script], "")  # type: ignore[method-assign]

        ok, rows, _ = tools.LOCAL_TOOLS["vot"].run(
            {"object": 2, "burst": 0.3, "voicing": 0.32}, context, env
        )

        self.assertTrue(ok)
        self.assertIn("Insert boundary: 1, t1", rows[0])
        self.assertIn("Insert boundary: 1, t2", rows[0])


if __name__ == "__main__":
    unittest.main()
