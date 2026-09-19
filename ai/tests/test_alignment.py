import unittest

from praat_ai.alignment import dtw_align


class AlignmentTests(unittest.TestCase):
    def test_identical_tracks_have_zero_cost(self) -> None:
        reference, learner, cost = dtw_align([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
        self.assertEqual(reference, learner)
        self.assertAlmostEqual(cost, 0.0)

    def test_shifted_track_has_positive_cost(self) -> None:
        _, _, cost = dtw_align([1.0, 2.0, 3.0], [2.0, 3.0, 4.0])
        self.assertGreater(cost, 0.0)


if __name__ == "__main__":
    unittest.main()
