from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from ai.tests import verify_vot_accuracy as accuracy_harness
from praat_ai.vot_accuracy import compare_entrypoints, score_case, validate_manifest


class VotAccuracyTests(unittest.TestCase):
    def make_case(self, *, burst=100, onset=120, vot_class="positive", **flags):
        return {
            "id": "ja-test",
            "language": "ja",
            "sample_rate_hz": 1000,
            "sample_count": 1000,
            "transcript": "か",
            "phonemes": ["k"],
            "target_phone_index": 0,
            "mode": "acoustic_only",
            "vot_class": vot_class,
            "target_selection_samples": [50, 250],
            "annotators": {
                "annotator_1": {"burst_sample_index": burst, "onset_sample_index": onset},
                "annotator_2": {"burst_sample_index": burst, "onset_sample_index": onset},
            },
            "adjudicated": {
                "burst_sample_index": burst,
                "onset_sample_index": onset,
                "uncertainty_samples": 0,
            },
            "flags": {
                "multiple_burst_candidates": False,
                "sustained_voicing": False,
                "ambiguous_evidence": False,
                **flags,
            },
            "alternative_pairs": [],
        }

    def result(self, status="candidate", burst=101, onset=119):
        return {
            "status": status,
            "sample_rate_hz": 1000,
            "burst_sample_index": burst,
            "onset_sample_index": onset,
            "vot_ms": onset - burst if burst is not None and onset is not None else None,
        }

    def test_score_reports_separate_boundary_and_signed_vot_errors(self):
        scored = score_case(self.make_case(), {"editor": self.result()})

        editor = scored["entrypoints"]["editor"]
        self.assertEqual(editor["status"], "candidate")
        self.assertEqual(editor["burst_error_ms"], 1.0)
        self.assertEqual(editor["onset_error_ms"], -1.0)
        self.assertEqual(editor["signed_vot_error_ms"], -2.0)
        self.assertTrue(editor["sign_agreement"])
        self.assertFalse(editor["candidate_miss"])

    def test_score_flags_miss_and_single_value_on_ambiguous_case(self):
        missed = score_case(self.make_case(), {"ai": self.result("failed", None, None)})
        self.assertTrue(missed["entrypoints"]["ai"]["candidate_miss"])
        self.assertIsNone(missed["entrypoints"]["ai"]["signed_vot_error_ms"])

        ambiguous = score_case(
            self.make_case(ambiguous_evidence=True),
            {"editor": self.result()},
        )
        self.assertTrue(ambiguous["entrypoints"]["editor"]["single_value_on_ambiguous_evidence"])

        declined = score_case(
            self.make_case(ambiguous_evidence=True),
            {"editor": self.result("ambiguous", None, None)},
        )
        self.assertFalse(declined["entrypoints"]["editor"]["candidate_miss"])
        self.assertTrue(declined["entrypoints"]["editor"]["ambiguity_correctly_declined"])

    def test_compare_entrypoints_checks_result_contract_not_only_vot(self):
        editor = {"status": "candidate", "result": self.result()}
        ai = {"status": "candidate", "result": {**self.result(), "burst_sample_index": 102}}

        compared = compare_entrypoints(editor, ai)

        self.assertFalse(compared["consistent"])
        self.assertIn("burst_sample_index", compared["differences"])

    def test_manifest_requires_two_adjudicated_japanese_annotations(self):
        cases = [
            self.make_case(multiple_burst_candidates=True),
            self.make_case(burst=100, onset=100, vot_class="zero", sustained_voicing=True),
            self.make_case(burst=120, onset=100, vot_class="negative"),
        ]
        for index, case in enumerate(cases):
            case["id"] = f"ja-{index}"
            case["audio"] = f"clips/{case['id']}.wav"
            case["audio_sha256"] = "0" * 64
        manifest = {
            "schema_version": 1,
            "language": "ja",
            "annotation_protocol": "two independent annotators; adjudicated by a third",
            "cases": cases,
        }
        errors = validate_manifest(manifest, require_audio=False)
        self.assertEqual(errors, [])

        invalid = {**manifest, "cases": [cases[0], cases[0]]}
        self.assertTrue(any("unique" in error for error in validate_manifest(invalid, require_audio=False)))


class VotAccuracyHarnessTests(unittest.TestCase):
    def test_editor_job_state_reader_retries_a_transient_windows_lock(self):
        with patch.object(
            Path,
            "read_text",
            side_effect=[PermissionError(13, "file is temporarily locked"), '{"state":"completed"}'],
        ) as read_text, patch.object(accuracy_harness.time, "sleep") as sleep:
            state = accuracy_harness._read_vot_job_state(Path("state.json"))

        self.assertEqual(state, {"state": "completed"})
        self.assertEqual(read_text.call_count, 2)
        sleep.assert_called_once()


if __name__ == "__main__":
    unittest.main()
