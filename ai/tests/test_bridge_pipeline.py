import math
import json
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np

from praat_ai.models import AnalysisRequest, PhoneSpec
from praat_ai.tutor import run_tutor


def write_tone(path: Path, frequency: float) -> None:
    sample_rate = 16000
    times = np.arange(int(sample_rate * 0.2)) / sample_rate
    samples = (12000 * np.sin(2 * math.pi * frequency * times)).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.tobytes())


class BridgePipelineTests(unittest.TestCase):
    def test_tutor_writes_all_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.wav"
            learner = root / "learner.wav"
            output = root / "output"
            output.mkdir()
            config = root / "ai_config.json"
            config.write_text(
                json.dumps(
                    {
                        "alignment": {
                            "backend": "auto",
                            "mfa": {"enabled": False},
                            "wav2vec2": {"enabled": False},
                        },
                        "server": {"auto_start": False},
                    }
                ),
                encoding="utf-8",
            )
            write_tone(reference, 220.0)
            write_tone(learner, 900.0)

            helper = types.SimpleNamespace(
                get_selected=lambda: [
                    {
                        "id": 1,
                        "name": "reference",
                        "class": "Sound",
                        "file": str(reference),
                    },
                    {
                        "id": 2,
                        "name": "learner",
                        "class": "Sound",
                        "file": str(learner),
                    },
                ],
                get_output_dir=lambda: str(output),
                call=lambda *args, **kwargs: None,
                run_praat_script=lambda *args, **kwargs: None,
                select=lambda *args, **kwargs: None,
                plus_select=lambda *args, **kwargs: None,
            )
            with patch.dict(sys.modules, {"praat": helper}):
                progress: list[tuple[float, str]] = []
                outputs = run_tutor(
                    config_path=config,
                    request=AnalysisRequest(
                        reference_object=1,
                        learner_object=2,
                        language="test",
                        phonemes=[
                            PhoneSpec(
                                "a",
                                reference_start=0.0,
                                reference_end=0.2,
                            )
                        ],
                        error_threshold=1.0,
                        qwen_explain=False,
                        qwen_vision=False,
                    ),
                    progress=lambda fraction, message: progress.append(
                        (fraction, message)
                    ),
                )

            self.assertTrue(outputs.json_path.is_file())
            self.assertTrue(outputs.textgrid_path.is_file())
            self.assertIsNotNone(outputs.overlay_path)
            self.assertTrue(outputs.overlay_path.is_file())
            self.assertGreater(len(outputs.result.errors), 0)
            self.assertEqual(progress[0][0], 0.08)
            self.assertEqual(progress[-1], (1.0, "分析完成"))
            self.assertTrue(any("音素对齐" in message for _, message in progress))


if __name__ == "__main__":
    unittest.main()
