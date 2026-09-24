import math
import shutil
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np

from praat_ai.models import AlignedPhone, AlignmentResult, AnalysisRequest, PhoneSpec
from praat_ai.pronunciation import analyze_pronunciation
from praat_ai.tutor import request_from_dict
from praat_ai.ui import _equal_segments


def write_tone(path: Path, sample_rate: int, frequency: float) -> None:
    times = np.arange(int(sample_rate * 0.2)) / sample_rate
    samples = (12000 * np.sin(2 * math.pi * frequency * times)).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(samples.tobytes())


def write_two_tones(path: Path) -> None:
    sample_rate = 16000
    first = np.arange(int(sample_rate * 0.2)) / sample_rate
    second = np.arange(int(sample_rate * 0.8)) / sample_rate
    samples = np.concatenate(
        [np.sin(2 * math.pi * 220.0 * first), np.sin(2 * math.pi * 2500.0 * second)]
    )
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes((samples * 12000).astype("<i2").tobytes())


class FixedBoundaryAligner:
    def align(self, audio_path, phones, language, transcript=""):
        del audio_path, language, transcript
        return AlignmentResult(
            phones=[
                AlignedPhone(1, phones[0].ipa, 0.0, 0.2, 0.9, "verified"),
                AlignedPhone(2, phones[1].ipa, 0.2, 1.0, 0.9, "verified"),
            ],
            source="verified",
            confidence=0.9,
        )


class AudioPipelineTests(unittest.TestCase):
    def test_null_alignment_metadata_uses_defaults(self) -> None:
        request = request_from_dict(
            {
                "reference_object": "reference.wav",
                "learner_object": "learner.wav",
                "phonemes": [
                    {
                        "ipa": "a",
                        "alignment_confidence": None,
                        "alignment_source": None,
                    }
                ],
            }
        )

        self.assertEqual(request.phonemes[0].alignment_confidence, 1.0)
        self.assertEqual(request.phonemes[0].alignment_source, "")

    def test_missing_reference_boundaries_are_aligned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "two_tones.wav"
            write_two_tones(audio)
            request = AnalysisRequest(
                reference_object=str(audio),
                learner_object=str(audio),
                language="test",
                phonemes=[PhoneSpec("a"), PhoneSpec("b")],
            )
            with patch("praat_ai.pronunciation.build_aligner", return_value=FixedBoundaryAligner()):
                result = analyze_pronunciation(request)

        self.assertEqual(len(result.reference_phones), 2)
        self.assertEqual(result.reference_phones[0].end, 0.2)
        self.assertEqual(result.errors, [])

    def test_same_wav_uses_aligned_reference_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "two_tones.wav"
            write_two_tones(audio)
            request = AnalysisRequest(
                reference_object=str(audio),
                learner_object=str(audio),
                language="test",
                phonemes=_equal_segments(["a", "b"], 1.0),
            )
            with patch("praat_ai.pronunciation.build_aligner", return_value=FixedBoundaryAligner()):
                result = analyze_pronunciation(request)

        self.assertEqual(result.errors, [])
        self.assertEqual(result.reference_phones[0].end, 0.2)
        self.assertEqual(result.learner_phones[0].end, 0.2)

    def test_same_wav_uses_supplied_learner_boundaries_when_aligner_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "two_tones.wav"
            write_two_tones(audio)
            phones = _equal_segments(["a", "b"], 1.0)
            phones[0].learner_start, phones[0].learner_end = 0.0, 0.2
            phones[1].learner_start, phones[1].learner_end = 0.2, 1.0
            result = analyze_pronunciation(
                AnalysisRequest(
                    reference_object=str(audio),
                    learner_object=str(audio),
                    language="test",
                    phonemes=phones,
                )
            )

        self.assertEqual(result.errors, [])
        self.assertEqual(result.reference_phones[0].end, 0.2)
        self.assertEqual(result.learner_phones[0].end, 0.2)

    def test_identical_wavs_at_distinct_paths_share_supplied_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.wav"
            learner = Path(directory) / "learner.wav"
            write_two_tones(reference)
            shutil.copyfile(reference, learner)
            phones = _equal_segments(["a", "b"], 1.0)
            phones[0].learner_start, phones[0].learner_end = 0.0, 0.2
            phones[1].learner_start, phones[1].learner_end = 0.2, 1.0
            result = analyze_pronunciation(
                AnalysisRequest(
                    reference_object=str(reference),
                    learner_object=str(learner),
                    language="test",
                    phonemes=phones,
                )
            )

        self.assertEqual(result.errors, [])
        self.assertEqual(result.reference_phones[0].end, 0.2)

    def test_ui_estimates_stay_estimates_after_request_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "two_tones.wav"
            write_two_tones(audio)
            original = AnalysisRequest(
                reference_object=str(audio),
                learner_object=str(audio),
                language="test",
                phonemes=_equal_segments(["a", "b"], 1.0),
            )
            request = request_from_dict(original.to_dict())
            with patch("praat_ai.pronunciation.build_aligner", return_value=FixedBoundaryAligner()):
                result = analyze_pronunciation(request)

        self.assertEqual(result.reference_phones[0].end, 0.2)
        self.assertEqual(result.errors, [])

    def test_supplied_boundaries_are_preserved_on_both_sides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "two_tones.wav"
            write_two_tones(audio)
            request = AnalysisRequest(
                reference_object=str(audio),
                learner_object=str(audio),
                language="test",
                phonemes=[
                    PhoneSpec("a", reference_start=0.0, reference_end=0.3, learner_start=0.0, learner_end=0.3),
                    PhoneSpec("b", reference_start=0.3, reference_end=1.0, learner_start=0.3, learner_end=1.0),
                ],
            )
            with patch("praat_ai.pronunciation.build_aligner", return_value=FixedBoundaryAligner()) as build:
                result = analyze_pronunciation(request)

        self.assertEqual(result.reference_phones[0].end, 0.3)
        self.assertEqual(result.learner_phones[0].end, 0.3)
        self.assertEqual(result.errors, [])
        build.assert_not_called()

    def test_same_audio_reuses_reference_boundaries_when_both_sides_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "two_tones.wav"
            write_two_tones(audio)
            request = AnalysisRequest(
                reference_object=str(audio),
                learner_object=str(audio),
                language="test",
                phonemes=[
                    PhoneSpec("a", reference_start=0.0, reference_end=0.3, learner_start=0.0, learner_end=0.2),
                    PhoneSpec("b", reference_start=0.3, reference_end=1.0, learner_start=0.2, learner_end=1.0),
                ],
            )
            with patch("praat_ai.pronunciation.build_aligner") as build:
                result = analyze_pronunciation(request)

        self.assertEqual(result.errors, [])
        self.assertEqual(result.learner_phones[0].end, result.reference_phones[0].end)
        build.assert_not_called()

    def test_identical_files_reuse_reference_boundaries_when_both_sides_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reference = Path(directory) / "reference.wav"
            learner = Path(directory) / "learner.wav"
            write_two_tones(reference)
            shutil.copyfile(reference, learner)
            request = AnalysisRequest(
                reference_object=str(reference),
                learner_object=str(learner),
                language="test",
                phonemes=[
                    PhoneSpec("a", reference_start=0.0, reference_end=0.3, learner_start=0.0, learner_end=0.2),
                    PhoneSpec("b", reference_start=0.3, reference_end=1.0, learner_start=0.2, learner_end=1.0),
                ],
            )
            result = analyze_pronunciation(request)

        self.assertEqual(result.errors, [])
        self.assertEqual(result.learner_phones[0].end, result.reference_phones[0].end)

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
