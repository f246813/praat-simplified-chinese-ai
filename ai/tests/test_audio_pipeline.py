import math
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from praat_ai.models import AnalysisRequest, PhoneSpec
from praat_ai.pronunciation import analyze_pronunciation


def write_tone(path: Path, sample_rate: int, frequency: float) -> None:
    times = np.arange(int(sample_rate * 0.2)) / sample_rate
    samples = (12000 * np.sin(2 * math.pi * frequency * times)).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.tobytes())


class AudioPipelineTests(unittest.TestCase):
    def test_different_spectra_produce_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.wav"
            learner = root / "learner.wav"
            write_tone(reference, 16000, 220.0)
            write_tone(learner, 16000, 900.0)

            result = analyze_pronunciation(
                AnalysisRequest(
                    reference_object=str(reference),
                    learner_object=str(learner),
                    language="test",
                    phonemes=[
                        PhoneSpec(
                            "a",
                            reference_start=0.0,
                            reference_end=0.2,
                        )
                    ],
                    error_threshold=1.0,
                )
            )
            self.assertGreater(len(result.errors), 0)
            self.assertIn(
                "spectral_centroid",
                {error.feature for error in result.errors},
            )


if __name__ == "__main__":
    unittest.main()
