import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from praat_ai.config import (
    MfaAlignmentConfig,
    Wav2Vec2AlignmentConfig,
)
from praat_ai.forced_alignment import (
    AlignmentBackend,
    AlignmentError,
    AlignmentResult,
    CompositeAligner,
    MfaAligner,
    Wav2Vec2Aligner,
    _ctc_forced_align,
    parse_mfa_textgrid,
)
from praat_ai.models import AlignedPhone, PhoneSpec


class FixedAligner(AlignmentBackend):
    def __init__(self, name: str, offsets: list[float], confidence: float):
        self.name = name
        self.offsets = offsets
        self.confidence = confidence

    def available(self) -> bool:
        return True

    def align(self, audio_path, phones, language, transcript=""):
        del audio_path, language, transcript
        return AlignmentResult(
            [
                AlignedPhone(
                    index,
                    phone.ipa,
                    offset,
                    offset + 0.1,
                    self.confidence,
                    self.name,
                )
                for index, (phone, offset) in enumerate(
                    zip(phones, self.offsets),
                    start=1,
                )
            ],
            self.name,
            self.confidence,
        )


class UnavailableAligner(AlignmentBackend):
    name = "mfa"

    def available(self) -> bool:
        return False

    def align(self, audio_path, phones, language, transcript=""):
        raise AssertionError("an unavailable backend must not be invoked")


class FailingAligner(FixedAligner):
    def align(self, audio_path, phones, language, transcript=""):
        raise AlignmentError("backend fixture failure")


class ForcedAlignmentTests(unittest.TestCase):
    def _align_for_vot(self, aligner: CompositeAligner, *args, **kwargs):
        method = getattr(aligner, "align_for_vot", None)
        self.assertTrue(
            callable(method),
            "CompositeAligner.align_for_vot must preserve raw backend evidence",
        )
        return method(*args, **kwargs)

    def test_textgrid_parser_reads_phone_tier(self) -> None:
        text = """
        item [1]:
            class = "IntervalTier"
            name = "phones"
            intervals: size = 2
            intervals [1]:
                xmin = 0.0
                xmax = 0.1
                text = "m"
            intervals [2]:
                xmin = 0.1
                xmax = 0.2
                text = "a"
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.TextGrid"
            path.write_text(text, encoding="utf-8")
            result = parse_mfa_textgrid(
                path,
                [PhoneSpec("m"), PhoneSpec("a")],
            )
        self.assertEqual(len(result.phones), 2)
        self.assertAlmostEqual(result.phones[1].start, 0.1)

    def test_ctc_alignment_finds_token_spans(self) -> None:
        log_probabilities = np.full((8, 3), -10.0)
        for frame in range(0, 3):
            log_probabilities[frame, 1] = 0.0
        for frame in range(3, 5):
            log_probabilities[frame, 0] = 0.0
        for frame in range(5, 8):
            log_probabilities[frame, 2] = 0.0
        spans, confidence = _ctc_forced_align(
            log_probabilities,
            [1, 2],
            blank_token_id=0,
        )
        self.assertEqual(spans[0], [0, 1, 2])
        self.assertEqual(spans[1], [5, 6, 7])
        self.assertGreater(confidence, 0.9)

    def test_composite_aligner_merges_boundaries(self) -> None:
        aligner = CompositeAligner(
            [
                FixedAligner("mfa", [0.0], 0.9),
                FixedAligner("wav2vec2", [0.02], 0.8),
            ],
            agreement_threshold_sec=0.04,
        )
        result = aligner.align("unused.wav", [PhoneSpec("a")], "test")
        self.assertGreaterEqual(result.phones[0].start, 0.0)
        self.assertLess(result.phones[0].start, 0.02)
        self.assertIn("dual:", result.source)

    def test_mfa_command_uses_configured_model(self) -> None:
        aligner = MfaAligner(
            MfaAlignmentConfig(
                enabled=True,
                executable="mfa",
                acoustic_model="mandarin_mfa",
            )
        )
        command = aligner.build_command(
            Path("corpus"),
            Path("dictionary.txt"),
            Path("output"),
        )
        self.assertIn("mandarin_mfa", command)
        self.assertIn("long_textgrid", command)

    def test_mfa_invocations_use_separate_temporary_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "input.wav"
            import wave

            with wave.open(str(audio), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(16000)
                handle.writeframes(b"\0\0" * 100)

            aligner = MfaAligner(
                MfaAlignmentConfig(
                    enabled=True,
                    conda_executable=sys.executable,
                    conda_environment="aligner",
                    acoustic_model="japanese_mfa.zip",
                    language="ja",
                )
            )
            temporary_roots: list[str | None] = []

            def fake_mfa(command, **kwargs):
                environment = kwargs.get("env") or {}
                temporary_roots.append(environment.get("MFA_ROOT_DIR"))
                output = Path(command[9])
                (output / "learner.TextGrid").write_text(
                    'item [1]:\n class = "IntervalTier"\n name = "phones"\n'
                    ' intervals: size = 1\n intervals [1]:\n'
                    '  xmin = 0.0\n  xmax = 0.01\n  text = "n"\n',
                    encoding="utf-8",
                )
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("praat_ai.forced_alignment.subprocess.run", side_effect=fake_mfa):
                for _ in range(2):
                    aligner.align(audio, [PhoneSpec("n")], "ja")

            self.assertEqual(len(temporary_roots), 2)
            self.assertTrue(all(temporary_roots))
            self.assertNotEqual(temporary_roots[0], temporary_roots[1])

    def test_vot_mfa_evidence_does_not_claim_fixed_confidence(self) -> None:
        backend = MfaAligner(
            MfaAlignmentConfig(
                enabled=True,
                acoustic_model="japanese_mfa.zip",
                language="ja",
            )
        )
        backend.available = lambda: True
        backend_result = AlignmentResult(
            [AlignedPhone(1, "n", 0.08, 0.11, 0.85, "mfa")],
            "mfa",
            0.85,
        )

        with patch.object(backend, "align", return_value=backend_result):
            evidence = self._align_for_vot(
                CompositeAligner([backend]),
                "unused.wav",
                [PhoneSpec("n")],
                "ja",
                "日本",
            )

        self.assertEqual(evidence.results[0].phones[0].start, 0.08)
        self.assertIsNone(evidence.results[0].phones[0].confidence)
        self.assertIsNone(evidence.results[0].confidence)

    def test_vot_alignment_does_not_use_proportional_fallback(self) -> None:
        aligner = CompositeAligner([UnavailableAligner()])

        evidence = self._align_for_vot(
            aligner,
            "unused.wav",
            [PhoneSpec("a")],
            "Japanese",
        )

        self.assertEqual(evidence.results, [])
        self.assertEqual(evidence.backend_errors, ["mfa: unavailable"])

    def test_vot_alignment_retains_dual_results_without_averaging(self) -> None:
        aligner = CompositeAligner(
            [
                FixedAligner("mfa", [0.0], 0.9),
                FixedAligner("wav2vec2", [0.02], 0.8),
            ],
            agreement_threshold_sec=0.04,
        )

        evidence = self._align_for_vot(
            aligner,
            "unused.wav",
            [PhoneSpec("a")],
            "Japanese",
        )

        self.assertEqual(len(evidence.results), 2)
        self.assertEqual(
            [result.phones[0].start for result in evidence.results],
            [0.0, 0.02],
        )
        self.assertEqual(
            [result.phones[0].source for result in evidence.results],
            ["mfa", "wav2vec2"],
        )
        self.assertEqual(
            [result.phones[0].confidence for result in evidence.results],
            [0.9, 0.8],
        )
        self.assertEqual(evidence.disagreement_threshold_sec, 0.04)

    def test_vot_alignment_reports_backend_errors(self) -> None:
        aligner = CompositeAligner(
            [FailingAligner("mfa", [0.0], 0.9)]
        )

        evidence = self._align_for_vot(
            aligner,
            "unused.wav",
            [PhoneSpec("a")],
            "Japanese",
        )

        self.assertEqual(evidence.results, [])
        self.assertEqual(
            evidence.backend_errors,
            ["mfa: backend fixture failure"],
        )

    def test_vot_alignment_preserves_single_backend_boundaries(self) -> None:
        backend = FixedAligner("mfa", [0.123], 0.85)
        result = backend.align("unused.wav", [PhoneSpec("a")], "Japanese")
        aligner = CompositeAligner([backend])

        evidence = self._align_for_vot(
            aligner,
            "unused.wav",
            [PhoneSpec("a")],
            "Japanese",
        )

        self.assertEqual(len(evidence.results), 1)
        self.assertEqual(evidence.results[0].phones[0].start, 0.123)
        self.assertAlmostEqual(evidence.results[0].phones[0].end, 0.223)
        self.assertEqual(evidence.results[0].phones[0].confidence, 0.85)
        self.assertEqual(evidence.results[0].phones[0].source, "mfa")
        self.assertEqual(evidence.results[0].phones, result.phones)

    def test_vot_alignment_rejects_configured_model_language_mismatch(self) -> None:
        cases = [
            (
                MfaAligner(
                    MfaAlignmentConfig(
                        enabled=True,
                        acoustic_model="english_us_arpa.zip",
                        language="en",
                    )
                ),
                "mfa",
            ),
            (
                Wav2Vec2Aligner(
                    Wav2Vec2AlignmentConfig(
                        enabled=True,
                        model="fixture-model",
                        languages=["en"],
                    )
                ),
                "wav2vec2",
            ),
        ]
        for backend, name in cases:
            with self.subTest(backend=name):
                backend.available = lambda: True
                evidence = self._align_for_vot(
                    CompositeAligner([backend]),
                    "unused.wav",
                    [PhoneSpec("a")],
                    "Japanese",
                )
                self.assertEqual(evidence.results, [])
                self.assertEqual(len(evidence.backend_errors), 1)
                self.assertTrue(evidence.backend_errors[0].startswith(f"{name}:"))
                self.assertIn("language mismatch", evidence.backend_errors[0])


if __name__ == "__main__":
    unittest.main()
