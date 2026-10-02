import io
import unittest
import wave
from praat_ai.audio_probe import generate_probe, validate_probe


class ProbeTests(unittest.TestCase):
    def test_synthetic_wav_and_feature_validation(self):
        data, expected = generate_probe()
        with wave.open(io.BytesIO(data)) as audio:
            self.assertEqual(audio.getnchannels(),1)
            self.assertEqual(audio.getframerate(),16000)
            self.assertGreater(audio.getnframes(),16000)
        self.assertTrue(validate_probe(expected, expected))
        self.assertFalse(validate_probe({'count':0,'direction':'unknown'}, expected))


if __name__ == '__main__':
    unittest.main()
