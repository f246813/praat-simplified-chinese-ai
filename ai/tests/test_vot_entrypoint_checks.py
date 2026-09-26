from __future__ import annotations

import unittest

from ai.tests.verify_vot_entrypoints import maximum_boundary_drift_ms


class VotEntrypointCheckTests(unittest.TestCase):
    def test_boundary_drift_uses_original_sample_rate(self) -> None:
        reference = {
            "status": "candidate",
            "sample_rate_hz": 44100.0,
            "burst_sample_index": 13230,
            "onset_sample_index": 14641,
        }
        moved = {
            **reference,
            "burst_sample_index": 13245,
            "onset_sample_index": 14656,
        }

        self.assertAlmostEqual(maximum_boundary_drift_ms(reference, moved), 15 / 44.1)

    def test_boundary_drift_rejects_unavailable_boundaries(self) -> None:
        result = {
            "status": "ambiguous",
            "sample_rate_hz": 44100.0,
            "burst_sample_index": None,
            "onset_sample_index": None,
        }

        with self.assertRaisesRegex(ValueError, "complete candidate"):
            maximum_boundary_drift_ms(result, result)


if __name__ == "__main__":
    unittest.main()
