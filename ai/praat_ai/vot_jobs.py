from __future__ import annotations

import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

from .vot import (
    VOTAcousticAnalyzer,
    VOTAnalysisRequest,
    VOTAnalysisResult,
    VOTAnalysisService,
    VOTJobSnapshot,
    VOTJobState,
    VOTPreparedAnalysis,
    VOTStatus,
)


@dataclass(slots=True)
class _VOTEditorJob:
    job_id: str
    request: VOTAnalysisRequest
    state: VOTJobState = VOTJobState.QUEUED
    stage: str = "queued"
    progress: float = 0.0
    prepared: VOTPreparedAnalysis | None = None
    result: VOTAnalysisResult | None = None
    error: str = ""
    future: Future[None] | None = None


class VOTEditorJobCoordinator:
    """Run forced alignment off-thread and complete C++ analysis on the owner thread."""

    def __init__(self, service: VOTAnalysisService, *, max_workers: int = 1):
        self.service = service
        self._owner_thread = threading.get_ident()
        self._lock = threading.RLock()
        self._jobs: dict[str, _VOTEditorJob] = {}
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="praat-vot-align",
        )

    def submit(self, request: VOTAnalysisRequest, *, job_id: str | None = None) -> str:
        job_id = job_id or uuid.uuid4().hex
        if not job_id.strip():
            raise ValueError("VOT job ID must not be empty")
        job = _VOTEditorJob(job_id=job_id, request=request)
        with self._lock:
            if job_id in self._jobs:
                raise ValueError(f"VOT job ID already exists: {job_id}")
            self._jobs[job_id] = job
            job.future = self._executor.submit(self._prepare, job_id)
        return job_id

    def poll(self, job_id: str) -> VOTJobSnapshot:
        with self._lock:
            job = self._require_job(job_id)
            return self._snapshot(job)

    def complete_acoustics(
        self,
        job_id: str,
        acoustic_analyzer: VOTAcousticAnalyzer,
    ) -> VOTJobSnapshot:
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("VOT acoustic completion must run on the coordinator thread")
        with self._lock:
            job = self._require_job(job_id)
            if job.state != VOTJobState.READY_FOR_ACOUSTICS or job.prepared is None:
                raise RuntimeError(f"VOT job is not ready for acoustic completion: {job.state.value}")
            prepared = job.prepared
            job.stage = "acoustic_analysis"
            job.progress = 0.9

        try:
            result = self.service.complete(prepared, acoustic_analyzer)
        except Exception as error:
            with self._lock:
                job = self._require_job(job_id)
                if job.state != VOTJobState.CANCELLED:
                    job.state = VOTJobState.FAILED
                    job.stage = "failed"
                    job.progress = 1.0
                    job.error = f"acoustic_analysis_failed: {error}"
                return self._snapshot(job)

        with self._lock:
            job = self._require_job(job_id)
            if job.state != VOTJobState.CANCELLED:
                job.result = result
                job.state = (
                    VOTJobState.FAILED
                    if result.status == VOTStatus.FAILED
                    else VOTJobState.COMPLETED
                )
                job.stage = "failed" if job.state == VOTJobState.FAILED else "completed"
                job.progress = 1.0
                job.error = result.failure_reason if job.state == VOTJobState.FAILED else ""
            return self._snapshot(job)

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._require_job(job_id)
            if job.state in {VOTJobState.COMPLETED, VOTJobState.FAILED, VOTJobState.CANCELLED}:
                return False
            job.state = VOTJobState.CANCELLED
            job.stage = "cancelled"
            job.result = None
            job.prepared = None
            if job.future is not None:
                job.future.cancel()
            return True

    def close(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def _prepare(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job.state == VOTJobState.CANCELLED:
                return
            job.state = VOTJobState.ALIGNING
            job.stage = "aligning"
            job.progress = 0.1
            request = job.request

        try:
            prepared = self.service.prepare(request, use_cache=False)
            result = (
                self.service.complete(prepared, None)
                if prepared.status is not None
                else None
            )
        except Exception as error:
            with self._lock:
                job = self._jobs[job_id]
                if job.state != VOTJobState.CANCELLED:
                    job.state = VOTJobState.FAILED
                    job.stage = "failed"
                    job.progress = 1.0
                    job.error = f"alignment_failed: {error}"
            return

        with self._lock:
            job = self._jobs[job_id]
            if job.state == VOTJobState.CANCELLED:
                return
            job.prepared = prepared
            if result is not None:
                job.result = result
                job.state = (
                    VOTJobState.FAILED
                    if result.status == VOTStatus.FAILED
                    else VOTJobState.COMPLETED
                )
                job.stage = "failed" if job.state == VOTJobState.FAILED else "completed"
                job.progress = 1.0
                job.error = result.failure_reason if job.state == VOTJobState.FAILED else ""
            else:
                job.state = VOTJobState.READY_FOR_ACOUSTICS
                job.stage = "ready_for_acoustics"
                job.progress = 0.8

    def _require_job(self, job_id: str) -> _VOTEditorJob:
        try:
            return self._jobs[job_id]
        except KeyError as error:
            raise KeyError(f"unknown VOT job: {job_id}") from error

    @staticmethod
    def _snapshot(job: _VOTEditorJob) -> VOTJobSnapshot:
        return VOTJobSnapshot(
            job_id=job.job_id,
            state=job.state,
            stage=job.stage,
            progress=job.progress,
            prepared_analysis=job.prepared,
            result=job.result,
            error=job.error,
        )
