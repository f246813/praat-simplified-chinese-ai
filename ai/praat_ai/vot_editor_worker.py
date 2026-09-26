from __future__ import annotations

import json
import hashlib
import os
import sys
import time
from pathlib import Path
from typing import Any

from .config import load_config
from .forced_alignment import CompositeAligner, build_aligner
from .vot import (
    VOTAnalysisRequest,
    VOTAudioSnapshot,
    VOTJobState,
    VOTMode,
    VOTPreparedAnalysis,
    VOTAnalysisService,
)
from .vot_jobs import VOTEditorJobCoordinator


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_prepared(path: Path, prepared: VOTPreparedAnalysis) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    request = prepared.request
    audio = request.audio_snapshot
    evidence = prepared.alignment_evidence
    temporary.write_text(
        json.dumps(
            {
                "request": {
                    **request.to_dict(),
                    "audio_snapshot_paths": {
                        "path": str(audio.path),
                        "pcm_path": str(audio.pcm_path) if audio.pcm_path else None,
                        "manifest_path": str(audio.manifest_path) if audio.manifest_path else None,
                    },
                },
                "alignment_evidence": (
                    {
                        "results": [result.to_dict() for result in evidence.results],
                        "backend_errors": evidence.backend_errors,
                        "disagreement_threshold_sec": evidence.disagreement_threshold_sec,
                    }
                    if evidence
                    else None
                ),
                "target_phone": prepared.target_phone.to_dict() if prepared.target_phone else None,
                "status": prepared.status.value if prepared.status else None,
                "reason": prepared.reason,
                "model_disagreement_sec": prepared.model_disagreement_sec,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def _configured_models() -> tuple[tuple[str, ...], dict[str, str]]:
    alignment = load_config().alignment
    backend = alignment.backend.strip().lower()
    models: dict[str, str] = {}
    if backend in {"auto", "mfa"} and alignment.mfa.enabled:
        models["mfa"] = alignment.mfa.acoustic_model
    if backend in {"auto", "wav2vec2", "ctc"} and alignment.wav2vec2.enabled:
        models["wav2vec2"] = alignment.wav2vec2.model
    return tuple(models), models


def _request_from_payload(payload: dict[str, Any]) -> VOTAnalysisRequest:
    paths = payload["snapshot_paths"]
    manifest_path = Path(paths["manifest"])
    pcm_path = Path(paths["pcm"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pcm_bytes = pcm_path.read_bytes()
    pcm_digest = hashlib.sha256(pcm_bytes).hexdigest()
    identity = {
        "schema_version": int(manifest.get("schema_version", 1)),
        "object_id": int(manifest["object_id"]),
        "source_kind": str(manifest["source_kind"]),
        "object_version": f"pcm-sha256:{pcm_digest}",
        "sample_rate_hz": float(manifest["sample_rate_hz"]),
        "channels": int(manifest["channels"]),
        "sample_count": int(manifest["sample_count"]),
        "snapshot_start_sample": int(manifest["snapshot_start_sample"]),
        "time_origin_seconds": float(manifest["time_origin_seconds"]),
    }
    canonical = json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    content_hash = hashlib.sha256(canonical + b"\0" + pcm_bytes).hexdigest()
    manifest_path.write_text(
        json.dumps(
            {**identity, "pcm_sha256": pcm_digest, "content_hash": content_hash},
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    snapshot_values = {**identity, "content_hash": content_hash}
    snapshot = VOTAudioSnapshot(
        path=Path(paths["wav"]),
        content_hash=str(snapshot_values["content_hash"]),
        object_id=str(snapshot_values["object_id"]),
        object_version=str(snapshot_values["object_version"]),
        source_kind=str(snapshot_values["source_kind"]),
        sample_rate_hz=float(snapshot_values["sample_rate_hz"]),
        channels=int(snapshot_values["channels"]),
        sample_count=int(snapshot_values["sample_count"]),
        snapshot_start_sample=int(snapshot_values["snapshot_start_sample"]),
        time_origin_seconds=float(snapshot_values["time_origin_seconds"]),
        pcm_path=Path(paths["pcm"]),
        manifest_path=Path(paths["manifest"]),
    )
    mode = VOTMode(payload["mode"])
    if mode == VOTMode.MODEL_ASSISTED:
        model_ids, model_versions = _configured_models()
    else:
        model_ids, model_versions = (), {}
    return VOTAnalysisRequest(
        request_id=str(payload["request_id"]),
        audio_snapshot=snapshot,
        target_range=tuple(payload["target_range"]),
        acoustic_context_range=tuple(payload["acoustic_context_range"]),
        alignment_context_range=tuple(payload["alignment_context_range"]),
        language=str(payload.get("language", "")),
        transcript=str(payload.get("transcript", "")),
        phonemes=tuple(
            payload.get("phonemes", ())
            if not isinstance(payload.get("phonemes", ()), str)
            else payload["phonemes"].split()
        ),
        target_phone_index=payload.get("target_phone_index"),
        mode=mode,
        parameters=payload.get("parameters", {}),
        model_ids=model_ids,
        model_versions=model_versions,
        manual_boundaries=(
            tuple(payload["manual_boundaries"])
            if payload.get("manual_boundaries") is not None
            else None
        ),
    )


def _snapshot_payload(snapshot) -> dict[str, Any]:
    value: dict[str, Any] = {
        "job_id": snapshot.job_id,
        "state": snapshot.state.value,
        "stage": snapshot.stage,
        "progress": snapshot.progress,
        "error": snapshot.error,
    }
    if snapshot.prepared_analysis is not None:
        phone = snapshot.prepared_analysis.target_phone
        value["aligned_phone"] = phone.to_dict() if phone is not None else None
    if snapshot.result is not None:
        value["result"] = snapshot.result.to_dict()
    return value


def run_job(payload_path: str | Path) -> int:
    config_path = Path(payload_path).resolve()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    job_dir = Path(payload["job_directory"]).resolve()
    job_dir.mkdir(parents=True, exist_ok=True)
    state_path = job_dir / "state.json"
    prepared_path = job_dir / "prepared.json"
    request = _request_from_payload(payload)
    if request.mode == VOTMode.MANUAL:
        service = VOTAnalysisService(CompositeAligner([]))
    else:
        service = VOTAnalysisService(build_aligner(load_config().alignment))
    coordinator = VOTEditorJobCoordinator(service)
    service = coordinator.service
    if request.mode == VOTMode.MANUAL:
        result = service.confirm_manual(request)
        state = VOTJobState.FAILED if result.status.value == "failed" else VOTJobState.COMPLETED
        _write_json(
            state_path,
            {
                "job_id": request.request_id,
                "state": state.value,
                "stage": "failed" if state == VOTJobState.FAILED else "completed",
                "progress": 1.0,
                "error": result.failure_reason if state == VOTJobState.FAILED else "",
                "result": result.to_dict(),
            },
        )
        coordinator.close()
        return 0
    job_id = coordinator.submit(request, job_id=request.request_id)
    _write_json(
        state_path,
        {
            "job_id": job_id,
            "state": VOTJobState.QUEUED.value,
            "stage": "queued",
            "progress": 0.0,
            "error": "",
        },
    )
    cancel_path = job_dir / "cancel"
    try:
        while True:
            snapshot = coordinator.poll(job_id)
            if cancel_path.exists() and snapshot.state not in {
                VOTJobState.CANCELLED,
                VOTJobState.COMPLETED,
                VOTJobState.FAILED,
            }:
                coordinator.cancel(job_id)
                _write_json(
                    state_path,
                    {
                        "job_id": job_id,
                        "state": VOTJobState.CANCELLED.value,
                        "stage": "cancelled",
                        "progress": snapshot.progress,
                        "error": "cancelled by editor because the request became stale",
                    },
                )
                break

            snapshot_data = _snapshot_payload(snapshot)
            if snapshot.prepared_analysis is not None:
                _write_prepared(prepared_path, snapshot.prepared_analysis)
            _write_json(state_path, snapshot_data)
            if snapshot.state in {
                VOTJobState.READY_FOR_ACOUSTICS,
                VOTJobState.COMPLETED,
                VOTJobState.FAILED,
                VOTJobState.CANCELLED,
            }:
                break
            time.sleep(0.1)
    except BaseException as error:
        _write_json(
            state_path,
            {
                "job_id": job_id,
                "state": VOTJobState.FAILED.value,
                "stage": "failed",
                "progress": 1.0,
                "error": f"editor_vot_worker_failed: {type(error).__name__}: {error}",
            },
        )
        return 1
    finally:
        coordinator.close(wait=True)
    return 0


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m praat_ai.vot_editor_worker REQUEST.json")
    return run_job(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
