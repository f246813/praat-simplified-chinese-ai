import tempfile
import unittest
from pathlib import Path

import parselmouth
from parselmouth.praat import call

from praat_ai.models import AnalysisResult, PronunciationError
from praat_ai.report import write_overlay_png, write_textgrid


class ReportTests(unittest.TestCase):
    def test_textgrid_and_overlay(self) -> None:
        result = AnalysisResult(
            language="cmn",
            reference_name="reference",
            learner_name="learner",
            reference_path="reference.wav",
            learner_path="learner.wav",
            duration=0.2,
            errors=[
                PronunciationError(
                    phone_index=1,
                    ipa="a",
                    start=0.0,
                    end=0.1,
                    feature="f1",
                    score=1.5,
                    severity=1.2,
                    direction="偏高",
                    message="/a/ 的 f1 偏高",
                    reference_value=700.0,
                    learner_value=900.0,
                    unit="Hz",
                ),
                PronunciationError(
                    phone_index=1,
                    ipa="a",
                    start=0.0,
                    end=0.1,
                    feature="f2",
                    score=1.5,
                    severity=1.2,
                    direction="偏低",
                    message="/a/ 的 f2 偏低",
                    reference_value=1200.0,
                    learner_value=900.0,
                    unit="Hz",
                ),
            ],
            reference_phones=[],
            learner_phones=[],
        )
        with tempfile.TemporaryDirectory() as directory:
            textgrid = Path(directory) / "errors.TextGrid"
            overlay = Path(directory) / "overlay.png"
            write_textgrid(result, textgrid)
            self.assertIn("AI_Errors", textgrid.read_text(encoding="utf-8"))
            self.assertTrue(write_overlay_png(result, overlay))
            self.assertGreater(overlay.stat().st_size, 0)

    def test_generated_textgrid_can_be_read_by_praat(self) -> None:
        result = AnalysisResult(
            language="cmn",
            reference_name="reference",
            learner_name="learner",
            reference_path="reference.wav",
            learner_path="learner.wav",
            duration=0.2,
            errors=[
                PronunciationError(
                    phone_index=1,
                    ipa="a",
                    start=0.0,
                    end=0.1,
                    feature="f1",
                    score=1.5,
                    severity=1.2,
                    direction="偏高",
                    message="/a/ 的 f1 偏高",
                    reference_value=700.0,
                    learner_value=900.0,
                    unit="Hz",
                ),
                PronunciationError(
                    phone_index=1,
                    ipa="a",
                    start=0.0,
                    end=0.1,
                    feature="f2",
                    score=1.5,
                    severity=1.2,
                    direction="偏低",
                    message="/a/ 的 f2 偏低",
                    reference_value=1200.0,
                    learner_value=900.0,
                    unit="Hz",
                ),
            ],
            reference_phones=[],
            learner_phones=[],
        )
        with tempfile.TemporaryDirectory() as directory:
            textgrid = Path(directory) / "errors.TextGrid"
            write_textgrid(result, textgrid)
            grid = parselmouth.read(str(textgrid))
            self.assertEqual(call(grid, "Get number of tiers"), 2)
            self.assertEqual(call(grid, "Get number of points", 2), 1)
            label = call(grid, "Get label of point", 2, 1)
            self.assertIn("f1 偏高", label)
            self.assertIn("f2 偏低", label)


if __name__ == "__main__":
    unittest.main()
