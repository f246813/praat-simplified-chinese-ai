from __future__ import annotations

import json
import sys
import os
from pathlib import Path
from typing import Any

if __package__:
    from .forced_alignment import CompositeAligner
    from .models import AlignedPhone, AlignmentResult, VOTAlignmentEvidence
    from .vot import (
        VOTAlignedPhone,
        VOTAnalysisRequest,
        VOTAnalysisService,
        VOTAudioSnapshot,
        VOTJobState,
        VOTMode,
        VOTPreparedAnalysis,
        VOTStatus,
    )
    from .vot_bridge import TSVVOTAcousticAnalyzer
else:
    # Praat's Python bridge invokes script files directly, outside package context.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from praat_ai.forced_alignment import CompositeAligner
    from praat_ai.models import AlignedPhone, AlignmentResult, VOTAlignmentEvidence
    from praat_ai.vot import (
        VOTAlignedPhone,
        VOTAnalysisRequest,
        VOTAnalysisService,
        VOTAudioSnapshot,
        VOTJobState,
        VOTMode,
        VOTPreparedAnalysis,
        VOTStatus,
    )
    from praat_ai.vot_bridge import TSVVOTAcousticAnalyzer


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    temporary.replace(path)


def _read_prepared(path: Path) -> VOTPreparedAnalysis:
    payload = json.loads(path.read_text(encoding="utf-8"))
    request_data = payload["request"]
    audio_data = request_data["audio_snapshot"]
    paths = request_data["audio_snapshot_paths"]
    snapshot = VOTAudioSnapshot(
        path=Path(paths["path"]),
        pcm_path=Path(paths["pcm_path"]) if paths.get("pcm_path") else None,
        manifest_path=Path(paths["manifest_path"]) if paths.get("manifest_path") else None,
        content_hash=str(audio_data["content_hash"]),
        object_id=str(audio_data["object_id"]),
        object_version=str(audio_data["object_version"]),
        source_kind=str(audio_data["source_kind"]),
        sample_rate_hz=float(audio_data["sample_rate_hz"]),
        channels=int(audio_data["channels"]),
        sample_count=int(audio_data["sample_count"]),
        snapshot_start_sample=int(audio_data["snapshot_start_sample"]),
        time_origin_seconds=float(audio_data["time_origin_seconds"]),
    )
    request = VOTAnalysisRequest(
        request_id=str(request_data["request_id"]),
        audio_snapshot=snapshot,
        target_range=tuple(request_data["target_range"]),
        acoustic_context_range=tuple(request_data["acoustic_context_range"]),
        alignment_context_range=tuple(request_data["alignment_context_range"]),
        language=str(request_data["language"]),
        transcript=str(request_data["transcript"]),
        phonemes=tuple(request_data["phonemes"]),
        target_phone_index=request_data["target_phone_index"],
        mode=VOTMode(request_data["mode"]),
        parameters=request_data["parameters"],
        model_ids=tuple(request_data["model_ids"]),
        model_versions=request_data["model_versions"],
        manual_boundaries=(
            tuple(request_data["manual_boundaries"])
            if request_data.get("manual_boundaries") is not None
            else None
        ),
    )
    evidence_data = payload.get("alignment_evidence")
    evidence = None
    if evidence_data is not None:
        results = [
            AlignmentResult(
                phones=[AlignedPhone(**phone) for phone in result["phones"]],
                source=result["source"],
                confidence=result["confidence"],
                warnings=result["warnings"],
            )
            for result in evidence_data["results"]
        ]
        evidence = VOTAlignmentEvidence(
            results=results,
            backend_errors=evidence_data["backend_errors"],
            disagreement_threshold_sec=evidence_data["disagreement_threshold_sec"],
        )
    target_phone_data = payload.get("target_phone")
    return VOTPreparedAnalysis(
        request=request,
        alignment_evidence=evidence,
        target_phone=VOTAlignedPhone(**target_phone_data) if target_phone_data else None,
        status=VOTStatus(payload["status"]) if payload.get("status") else None,
        reason=str(payload.get("reason", "")),
        model_disagreement_sec=payload.get("model_disagreement_sec"),
    )


def main() -> int:
    if len(sys.argv) == 4:
        prepared_path, acoustic_path, state_path = map(Path, sys.argv[1:])
    else:
        try:
            prepared_path = Path(os.environ["PRAAT_AI_VOT_PREPARED"])
            acoustic_path = Path(os.environ["PRAAT_AI_VOT_CPP_RESULT"])
            state_path = Path(os.environ["PRAAT_AI_VOT_STATE"])
        except KeyError as error:
            raise SystemExit(
                "usage: python -m praat_ai.complete_vot_editor_job PREPARED.pkl NATIVE.tsv STATE.json"
            ) from error
    prepared = _read_prepared(prepared_path)
    if not hasattr(prepared, "request") or not hasattr(prepared, "alignment_evidence"):
        raise RuntimeError("prepared VOT job file does not contain VOTAnalysisService evidence")
    service = VOTAnalysisService(CompositeAligner([]))
    result = service.complete(prepared, TSVVOTAcousticAnalyzer(acoustic_path))
    job_state = (
        VOTJobState.FAILED if result.status == VOTStatus.FAILED else VOTJobState.COMPLETED
    )
    _write_json(
        state_path,
        {
            "job_id": result.request_id,
            "state": job_state.value,
            "stage": "failed" if job_state == VOTJobState.FAILED else "completed",
            "progress": 1.0,
            "error": result.failure_reason if job_state == VOTJobState.FAILED else "",
            "result": result.to_dict(),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
