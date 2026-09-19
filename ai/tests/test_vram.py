import unittest

from praat_ai.vram import select_runtime_profile


class VramTests(unittest.TestCase):
    def test_small_gpu_selects_cpu_text_mode(self) -> None:
        profile = select_runtime_profile(1024, True)
        self.assertEqual(profile.device, "cpu")
        self.assertFalse(profile.vision_enabled)

    def test_midrange_gpu_disables_vision(self) -> None:
        profile = select_runtime_profile(3072, True)
        self.assertEqual(profile.device, "cuda")
        self.assertFalse(profile.vision_enabled)
        self.assertEqual(profile.context_tokens, 4096)

    def test_large_gpu_can_enable_vision(self) -> None:
        profile = select_runtime_profile(7000, True)
        self.assertTrue(profile.vision_enabled)
        self.assertEqual(profile.context_tokens, 8192)


if __name__ == "__main__":
    unittest.main()
