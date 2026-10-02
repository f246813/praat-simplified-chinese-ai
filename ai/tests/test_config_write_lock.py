"""Configuration updates must serialize with the native path settings writer."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from praat_ai.service_lock import service_transition_lock


class ConfigWriteLockTest(unittest.TestCase):
    def test_api_update_waits_for_foreign_config_writer_and_merges_latest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"server": {"llama_server": "old.exe"}}), encoding="utf-8")
            code = (
                "import sys; from praat_ai.control import update_config; "
                "print('ready', flush=True); "
                "update_config({'api': {'api_key': 'fixture-key'}}, sys.argv[1]); "
                "print('done', flush=True)"
            )
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
            child = None
            try:
                with service_transition_lock(Path(str(path) + ".lock")):
                    child = subprocess.Popen([sys.executable, "-c", code, str(path)], env=environment,
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    self.assertEqual(child.stdout.readline().strip(), "ready")
                    time.sleep(0.3)
                    self.assertIsNone(child.poll(), "API writer ignored path configuration lock")
                    self.assertNotIn("api", json.loads(path.read_text(encoding="utf-8")))
                    path.write_text(json.dumps({"server": {"llama_server": "new.exe"}}), encoding="utf-8")
                output, errors = child.communicate(timeout=15)
                self.assertEqual(child.returncode, 0, errors)
                self.assertIn("done", output)
                saved = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(saved["server"]["llama_server"], "new.exe")
                self.assertEqual(saved["api"]["api_key"], "fixture-key")
            finally:
                if child is not None:
                    if child.poll() is None:
                        child.kill()
                    child.communicate()


if __name__ == "__main__":
    unittest.main()
