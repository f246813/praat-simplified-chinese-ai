from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from praat_ai.forced_alignment import CompositeAligner
from praat_ai.vot_editor_worker import run_job


class VotEditorWorkerTests(unittest.TestCase):
    def test_terminal_model_failure_persists_structured_result(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = root / "job"
            job.mkdir()
            pcm = job / "snapshot.f64le"
            pcm.write_bytes(b"\0" * 800)
            wav = job / "alignment.wav"
            wav.write_bytes(b"RIFF")
            manifest = job / "snapshot.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "object_id": 17,
                        "source_kind": "Sound",
                        "sample_rate_hz": 16000,
                        "channels": 1,
                        "sample_count": 100,
                        "snapshot_start_sample": 20,
                        "time_origin_seconds": 0.00125,
                    }
                ),
                encoding="utf-8",
            )
            request = job / "request.json"
            request.write_text(
                json.dumps(
                    {
                        "request_id": "worker-terminal-failure",
                        "job_directory": str(job),
                        "snapshot_paths": {
                            "manifest": str(manifest),
                            "pcm": str(pcm),
                            "wav": str(wav),
                        },
                        "target_range": [30, 80],
                        "acoustic_context_range": [20, 120],
                        "alignment_context_range": [20, 120],
                        "language": "ja",
                        "transcript": "か",
                        "phonemes": ["k", "a"],
                        "target_phone_index": 0,
                        "mode": "model_assisted",
                        "parameters": {"burst_threshold_db": 6.0},
                    }
                ),
                encoding="utf-8",
            )

            with patch("praat_ai.vot_editor_worker._configured_models", return_value=((), {})), patch(
                "praat_ai.vot_editor_worker.load_config",
                return_value=SimpleNamespace(alignment=None),
            ), patch(
                "praat_ai.vot_editor_worker.build_aligner", return_value=CompositeAligner([])
            ):
                exit_code = run_job(request)

            state = json.loads((job / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0, state)
            self.assertEqual(state["state"], "failed")
            self.assertEqual(state["result"]["status"], "failed")
            self.assertIn("model_unavailable", state["result"]["failure_reason"])
            self.assertEqual(state["result"]["snapshot_start_sample"], 20)
            self.assertTrue((job / "snapshot.json").exists())


if __name__ == "__main__":
    unittest.main()
