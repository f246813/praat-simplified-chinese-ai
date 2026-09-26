from __future__ import annotations

import threading
import time
import unittest
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from praat_ai.vot import VOTJobState, VOTStatus
from praat_ai.vot_jobs import VOTEditorJobCoordinator


class CompletionScriptEntryPointTests(unittest.TestCase):
    def test_completion_script_supports_direct_praat_script_execution(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        script = repository / "ai" / "praat_ai" / "complete_vot_editor_job.py"
        environment = os.environ.copy()
        for name in (
            "PRAAT_AI_VOT_PREPARED",
            "PRAAT_AI_VOT_CPP_RESULT",
            "PRAAT_AI_VOT_STATE",
        ):
            environment.pop(name, None)

        completed = subprocess.run(
            [sys.executable, str(script)],
            cwd=repository,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 1)
        self.assertIn("usage:", completed.stderr)
        self.assertNotIn("attempted relative import", completed.stderr)


class BlockingService:
    def __init__(self, *, block: bool = False):
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = block
        self.complete_calls = 0

    def prepare(self, request, use_cache=False):
        self.started.set()
        if self.block:
            self.release.wait(timeout=5)
        return SimpleNamespace(request=request, status=None, reason="")

    def complete(self, prepared, analyzer):
        self.complete_calls += 1
        result = analyzer.analyze(prepared.request, None)
        return result


class RecordingAnalyzer:
    def __init__(self):
        self.calls: list[int] = []

    def analyze(self, request, aligned_phone):
        del aligned_phone
        self.calls.append(threading.get_ident())
        return SimpleNamespace(status=VOTStatus.CANDIDATE, request_id=request.request_id)


class VotEditorJobTests(unittest.TestCase):
    @staticmethod
    def wait_for_state(coordinator, job_id, wanted):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            snapshot = coordinator.poll(job_id)
            if snapshot.state == wanted:
                return snapshot
            time.sleep(0.005)
        raise AssertionError(f"job did not reach {wanted.value}: {coordinator.poll(job_id)!r}")

    def test_background_alignment_stops_before_acoustic_completion(self) -> None:
        service = BlockingService()
        coordinator = VOTEditorJobCoordinator(service)
        try:
            request = SimpleNamespace(request_id="request-current")
            job_id = coordinator.submit(request)
            snapshot = self.wait_for_state(
                coordinator, job_id, VOTJobState.READY_FOR_ACOUSTICS
            )

            self.assertEqual(snapshot.progress, 0.8)
            self.assertEqual(service.complete_calls, 0)
            self.assertIsNone(snapshot.result)
            self.assertEqual(snapshot.prepared_analysis.request, request)
        finally:
            coordinator.close()

    def test_acoustic_completion_runs_on_the_coordinator_thread(self) -> None:
        service = BlockingService()
        coordinator = VOTEditorJobCoordinator(service)
        analyzer = RecordingAnalyzer()
        owner_thread = threading.get_ident()
        try:
            job_id = coordinator.submit(SimpleNamespace(request_id="request-2"))
            self.wait_for_state(coordinator, job_id, VOTJobState.READY_FOR_ACOUSTICS)

            snapshot = coordinator.complete_acoustics(job_id, analyzer)

            self.assertEqual(analyzer.calls, [owner_thread])
            self.assertEqual(snapshot.state, VOTJobState.COMPLETED)
            self.assertEqual(snapshot.progress, 1.0)
            self.assertEqual(snapshot.result.status, VOTStatus.CANDIDATE)
        finally:
            coordinator.close()

    def test_cancelled_alignment_cannot_publish_a_late_ready_result(self) -> None:
        service = BlockingService(block=True)
        coordinator = VOTEditorJobCoordinator(service)
        try:
            job_id = coordinator.submit(SimpleNamespace(request_id="request-stale"))
            self.assertTrue(service.started.wait(timeout=2))
            self.assertTrue(coordinator.cancel(job_id))
            service.release.set()

            time.sleep(0.03)
            snapshot = coordinator.poll(job_id)

            self.assertEqual(snapshot.state, VOTJobState.CANCELLED)
            self.assertIsNone(snapshot.prepared_analysis)
            self.assertIsNone(snapshot.result)
        finally:
            service.release.set()
            coordinator.close()

    def test_acoustic_completion_rejects_a_non_owner_thread(self) -> None:
        service = BlockingService()
        coordinator = VOTEditorJobCoordinator(service)
        try:
            job_id = coordinator.submit(SimpleNamespace(request_id="request-thread"))
            self.wait_for_state(coordinator, job_id, VOTJobState.READY_FOR_ACOUSTICS)
            errors: list[BaseException] = []

            def complete_elsewhere() -> None:
                try:
                    coordinator.complete_acoustics(job_id, RecordingAnalyzer())
                except BaseException as error:
                    errors.append(error)

            worker = threading.Thread(target=complete_elsewhere)
            worker.start()
            worker.join(timeout=2)

            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], RuntimeError)
            self.assertEqual(coordinator.poll(job_id).state, VOTJobState.READY_FOR_ACOUSTICS)
        finally:
            coordinator.close()


if __name__ == "__main__":
    unittest.main()
