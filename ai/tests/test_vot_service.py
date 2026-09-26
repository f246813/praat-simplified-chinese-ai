from __future__ import annotations

import importlib
import json
import unittest
from pathlib import Path

from praat_ai.forced_alignment import (
    AlignmentBackend,
    AlignmentError,
    AlignmentResult,
    CompositeAligner,
)
from praat_ai.models import AlignedPhone


def load_vot_api():
    try:
        return importlib.import_module("praat_ai.vot")
    except ModuleNotFoundError as error:
        if error.name == "praat_ai.vot":
            raise AssertionError("the shared VOT service module is missing") from error
        raise


class FixedAligner(AlignmentBackend):
    name = "fixed"

    def __init__(self, start: float = 0.5, end: float = 1.0):
        self.start = start
        self.end = end
        self.calls = 0

    def available(self) -> bool:
        return True

    def align(self, audio_path, phones, language, transcript=""):
        del audio_path, language, transcript
        self.calls += 1
        return AlignmentResult(
            [
                AlignedPhone(
                    index,
                    phone.ipa,
                    self.start,
                    self.end,
                    0.85,
                    self.name,
                )
                for index, phone in enumerate(phones, start=1)
            ],
            self.name,
            0.85,
        )


class UnavailableAligner(AlignmentBackend):
    name = "mfa"

    def available(self) -> bool:
        return False

    def align(self, audio_path, phones, language, transcript=""):
        raise AssertionError("an unavailable model must not be invoked")


class LanguageMismatchAligner(FixedAligner):
    name = "wav2vec2"

    def align(self, audio_path, phones, language, transcript=""):
        raise AlignmentError(f"language mismatch: {language} is unsupported")


class FixedAcousticAnalyzer:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def analyze(self, request, aligned_phone):
        del request, aligned_phone
        self.calls += 1
        return self.result


class VotServiceTests(unittest.TestCase):
    def make_request(self, vot, **overrides):
        values = {
            "request_id": "request-1",
            "audio_snapshot": vot.VOTAudioSnapshot(
                path=Path("snapshot.wav"),
                content_hash="sha256:audio-fixture",
                object_id="object-7",
                object_version="version-3",
                source_kind="LongSound",
                sample_rate_hz=1000,
                channels=1,
                sample_count=2000,
                snapshot_start_sample=10000,
                time_origin_seconds=8.0,
            ),
            "target_range": (10500, 11000),
            "acoustic_context_range": (10400, 11200),
            "alignment_context_range": (10000, 12000),
            "language": "Japanese",
            "transcript": "か",
            "phonemes": ("k",),
            "target_phone_index": 0,
            "mode": vot.VOTMode.MODEL_ASSISTED,
            "parameters": {"burst_band_hz": [1500, 8000]},
            "model_ids": ("mfa-ja",),
            "model_versions": {"mfa-ja": "1.2.3"},
            "manual_boundaries": None,
        }
        values.update(overrides)
        return vot.VOTAnalysisRequest(**values)

    def make_candidate(
        self,
        vot,
        burst=10610,
        onset=10620,
        negative_vot_evidence=False,
    ):
        return vot.VOTAcousticResult(
            status=vot.VOTStatus.CANDIDATE,
            burst_sample_index=burst,
            onset_sample_index=onset,
            reason="",
            burst_source="burst-envelope",
            onset_source="voicing-transition",
            detector_path="high-band",
            fallback_reason="",
            negative_vot_evidence=negative_vot_evidence,
            parameters={"burst_band_hz": [1500, 8000]},
            algorithm_version="vot-candidate-v2",
        )

    def test_sample_index_time_origin_round_trip(self) -> None:
        vot = load_vot_api()
        snapshot = self.make_request(vot).audio_snapshot

        seconds = snapshot.absolute_sample_to_seconds(10010)

        self.assertAlmostEqual(seconds, 8.01)
        self.assertEqual(snapshot.seconds_to_absolute_sample(seconds), 10010)

    def test_missing_alignment_metadata_requires_input(self) -> None:
        vot = load_vot_api()
        request = self.make_request(vot, language="", transcript="", phonemes=())
        aligner = FixedAligner()
        analyzer = FixedAcousticAnalyzer(self.make_candidate(vot))

        result = vot.VOTAnalysisService(CompositeAligner([aligner])).analyze(
            request,
            analyzer,
            use_cache=False,
        )

        self.assertEqual(result.status, vot.VOTStatus.REQUIRES_INPUT)
        self.assertIsNone(result.vot_ms)
        self.assertEqual(aligner.calls, 0)
        self.assertEqual(analyzer.calls, 0)

    def test_language_mismatch_is_failure(self) -> None:
        vot = load_vot_api()
        request = self.make_request(vot)
        analyzer = FixedAcousticAnalyzer(self.make_candidate(vot))

        result = vot.VOTAnalysisService(
            CompositeAligner([LanguageMismatchAligner()])
        ).analyze(request, analyzer, use_cache=False)

        self.assertEqual(result.status, vot.VOTStatus.FAILED)
        self.assertIn("language mismatch", result.failure_reason)
        self.assertIsNone(result.vot_ms)
        self.assertEqual(analyzer.calls, 0)

    def test_transcript_without_phoneme_sequence_requires_input(self) -> None:
        vot = load_vot_api()
        request = self.make_request(vot, phonemes=())
        analyzer = FixedAcousticAnalyzer(self.make_candidate(vot))

        result = vot.VOTAnalysisService(CompositeAligner([FixedAligner()])).analyze(
            request,
            analyzer,
            use_cache=False,
        )

        self.assertEqual(result.status, vot.VOTStatus.REQUIRES_INPUT)
        self.assertIn("phoneme", result.failure_reason.lower())
        self.assertEqual(analyzer.calls, 0)

    def test_partial_target_selection_is_target_incomplete(self) -> None:
        vot = load_vot_api()
        request = self.make_request(vot, target_range=(10500, 10800))
        analyzer = FixedAcousticAnalyzer(self.make_candidate(vot))

        result = vot.VOTAnalysisService(CompositeAligner([FixedAligner()])).analyze(
            request,
            analyzer,
            use_cache=False,
        )

        self.assertEqual(result.status, vot.VOTStatus.TARGET_INCOMPLETE)
        self.assertIsNone(result.vot_ms)
        self.assertEqual(analyzer.calls, 0)

    def test_adjacent_phone_selection_does_not_guess_target(self) -> None:
        vot = load_vot_api()
        request = self.make_request(
            vot,
            target_range=(11000, 11500),
            acoustic_context_range=(10900, 11600),
            target_phone_index=None,
        )
        analyzer = FixedAcousticAnalyzer(self.make_candidate(vot))

        result = vot.VOTAnalysisService(CompositeAligner([FixedAligner()])).analyze(
            request,
            analyzer,
            use_cache=False,
        )

        self.assertEqual(result.status, vot.VOTStatus.REQUIRES_INPUT)
        self.assertIsNone(result.target_phone)
        self.assertIsNone(result.vot_ms)
        self.assertEqual(analyzer.calls, 0)

    def test_invalid_sample_range_returns_failure(self) -> None:
        vot = load_vot_api()
        request = self.make_request(vot, target_range=(12000, 12500))
        analyzer = FixedAcousticAnalyzer(self.make_candidate(vot))

        result = vot.VOTAnalysisService(CompositeAligner([FixedAligner()])).analyze(
            request,
            analyzer,
            use_cache=False,
        )

        self.assertEqual(result.status, vot.VOTStatus.FAILED)
        self.assertIn("range", result.failure_reason.lower())
        self.assertIsNone(result.vot_ms)
        self.assertEqual(analyzer.calls, 0)

    def test_model_unavailable_has_a_specific_failure(self) -> None:
        vot = load_vot_api()
        request = self.make_request(vot)
        analyzer = FixedAcousticAnalyzer(self.make_candidate(vot))

        result = vot.VOTAnalysisService(
            CompositeAligner([UnavailableAligner()])
        ).analyze(request, analyzer, use_cache=False)

        self.assertEqual(result.status, vot.VOTStatus.FAILED)
        self.assertIn("unavailable", result.failure_reason.lower())
        self.assertIsNone(result.vot_ms)
        self.assertEqual(analyzer.calls, 0)

    def test_dual_model_disagreement_does_not_average_boundaries(self) -> None:
        vot = load_vot_api()
        request = self.make_request(
            vot,
            target_phone_index=None,
            target_range=(10400, 11300),
            acoustic_context_range=(10400, 11300),
        )
        analyzer = FixedAcousticAnalyzer(self.make_candidate(vot))
        aligner = CompositeAligner(
            [FixedAligner(0.5, 1.0), FixedAligner(0.7, 1.2)],
            agreement_threshold_sec=0.04,
        )

        result = vot.VOTAnalysisService(aligner).analyze(
            request,
            analyzer,
            use_cache=False,
        )

        self.assertEqual(result.status, vot.VOTStatus.AMBIGUOUS)
        self.assertEqual(len(result.alignment_evidence.results), 2)
        self.assertEqual(
            [item.phones[0].start for item in result.alignment_evidence.results],
            [0.5, 0.7],
        )
        self.assertAlmostEqual(result.model_disagreement_sec, 0.2)
        self.assertIsNone(result.vot_ms)
        self.assertEqual(analyzer.calls, 0)

    def test_acoustic_only_bypasses_alignment(self) -> None:
        vot = load_vot_api()
        request = self.make_request(vot, mode=vot.VOTMode.ACOUSTIC_ONLY)
        aligner = FixedAligner()
        analyzer = FixedAcousticAnalyzer(self.make_candidate(vot))

        result = vot.VOTAnalysisService(CompositeAligner([aligner])).analyze(
            request,
            analyzer,
            use_cache=False,
        )

        self.assertEqual(result.status, vot.VOTStatus.CANDIDATE)
        self.assertEqual(aligner.calls, 0)
        self.assertEqual(analyzer.calls, 1)
        self.assertEqual(result.burst_sample_index, 10610)
        self.assertEqual(result.onset_sample_index, 10620)

    def test_manual_positive_zero_and_negative_vot_use_sample_formula(self) -> None:
        vot = load_vot_api()
        expected = ((10, 20, 10.0), (10, 10, 0.0), (20, 10, -10.0))

        for burst_offset, onset_offset, wanted_vot in expected:
            with self.subTest(wanted_vot=wanted_vot):
                burst = 10600 + burst_offset
                onset = 10600 + onset_offset
                request = self.make_request(
                    vot,
                    mode=vot.VOTMode.MANUAL,
                    manual_boundaries=(burst, onset),
                )
                analyzer = FixedAcousticAnalyzer(self.make_candidate(vot))

                result = vot.VOTAnalysisService(CompositeAligner([])).analyze(
                    request,
                    analyzer,
                    use_cache=False,
                )

                self.assertEqual(result.status, vot.VOTStatus.MANUAL_CONFIRMED)
                self.assertEqual(result.burst_sample_index, burst)
                self.assertEqual(result.onset_sample_index, onset)
                self.assertEqual(result.vot_ms, wanted_vot)
                self.assertEqual(analyzer.calls, 0)

    def test_failed_cpp_result_cannot_become_a_candidate(self) -> None:
        vot = load_vot_api()
        request = self.make_request(vot, mode=vot.VOTMode.ACOUSTIC_ONLY)
        failed = vot.VOTAcousticResult(
            status=vot.VOTStatus.FAILED,
            burst_sample_index=None,
            onset_sample_index=None,
            reason="no paired acoustic boundaries",
            burst_source="",
            onset_source="",
            detector_path="high-band",
            fallback_reason="",
            parameters={},
            algorithm_version="vot-candidate-v2",
        )

        result = vot.VOTAnalysisService(CompositeAligner([])).analyze(
            request,
            FixedAcousticAnalyzer(failed),
            use_cache=False,
        )

        self.assertEqual(result.status, vot.VOTStatus.FAILED)
        self.assertIsNone(result.vot_ms)
        self.assertEqual(result.failure_reason, "no paired acoustic boundaries")

    def test_negative_candidate_requires_prevoicing_evidence(self) -> None:
        vot = load_vot_api()
        request = self.make_request(vot, mode=vot.VOTMode.ACOUSTIC_ONLY)
        unsupported_negative = self.make_candidate(
            vot,
            burst=10620,
            onset=10610,
        )

        result = vot.VOTAnalysisService(CompositeAligner([])).analyze(
            request,
            FixedAcousticAnalyzer(unsupported_negative),
            use_cache=False,
        )

        self.assertEqual(result.status, vot.VOTStatus.FAILED)
        self.assertIn("prevoicing", result.failure_reason.lower())
        self.assertIsNone(result.vot_ms)

    def test_cache_disabled_recomputes_alignment_and_acoustics(self) -> None:
        vot = load_vot_api()
        request = self.make_request(vot)
        aligner = FixedAligner()
        analyzer = FixedAcousticAnalyzer(self.make_candidate(vot))
        service = vot.VOTAnalysisService(CompositeAligner([aligner]))

        service.analyze(request, analyzer, use_cache=False)
        service.analyze(request, analyzer, use_cache=False)

        self.assertEqual(aligner.calls, 2)
        self.assertEqual(analyzer.calls, 2)

    def test_result_serialization_preserves_shared_sample_fields(self) -> None:
        vot = load_vot_api()
        request = self.make_request(vot, mode=vot.VOTMode.ACOUSTIC_ONLY)
        result = vot.VOTAnalysisService(CompositeAligner([])).analyze(
            request,
            FixedAcousticAnalyzer(self.make_candidate(vot)),
            use_cache=False,
        )

        payload = json.loads(json.dumps(result.to_dict()))

        self.assertEqual(payload["request_id"], "request-1")
        self.assertEqual(payload["audio_hash"], "sha256:audio-fixture")
        self.assertEqual(payload["status"], "candidate")
        self.assertEqual(payload["burst_sample_index"], 10610)
        self.assertEqual(payload["onset_sample_index"], 10620)
        self.assertEqual(payload["vot_ms"], 10.0)


if __name__ == "__main__":
    unittest.main()
