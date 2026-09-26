from __future__ import annotations

import csv
import json
import math
import tempfile
from pathlib import Path
from typing import Any

from .bridge import PraatBridge, PraatBridgeError
from .vot import (
    VOTAcousticResult,
    VOTAlignedPhone,
    VOTAnalysisRequest,
    VOTStatus,
)


def _decode_tsv_field(value: str) -> str:
    decoded: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character == "\\" and index + 1 < len(value):
            escaped = value[index + 1]
            if escaped == "t":
                decoded.append("\t")
            elif escaped == "n":
                decoded.append("\n")
            elif escaped == "r":
                decoded.append("\r")
            elif escaped == "\\":
                decoded.append("\\")
            else:
                decoded.extend((character, escaped))
            index += 2
        else:
            decoded.append(character)
            index += 1
    return "".join(decoded)


def _parse_parameters(value: str) -> dict[str, str]:
    parameters: dict[str, str] = {}
    for item in _decode_tsv_field(value).split("; "):
        name, separator, parameter_value = item.partition("=")
        if separator:
            name = name.strip()
            if name:
                parameters[name] = parameter_value.strip()
        elif parameters:
            # Parameter values are human-readable provenance and may contain
            # semicolons. Preserve continuation text instead of truncating it.
            last_name = next(reversed(parameters))
            parameters[last_name] += "; " + item.strip()
    return parameters


def _metric_rows(result_path: Path) -> dict[str, dict[str, str]]:
    try:
        with result_path.open("r", encoding="utf-8", newline="") as stream:
            rows = csv.DictReader(stream, delimiter="\t")
            if rows.fieldnames is None or "metric_id" not in rows.fieldnames:
                raise PraatBridgeError("C++ VOT result is missing its metric columns.")
            return {
                _decode_tsv_field(row.get("metric_id", "")): row
                for row in rows
                if row.get("metric_id")
            }
    except (OSError, UnicodeError, csv.Error) as error:
        raise PraatBridgeError(f"Could not read the C++ VOT result: {error}") from error


def _finite_metric(rows: dict[str, dict[str, str]], metric_id: str) -> float | None:
    value = rows.get(metric_id, {}).get("value", "")
    if not value:
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _metric_status(rows: dict[str, dict[str, str]], metric_id: str) -> str:
    row = rows.get(metric_id)
    return _decode_tsv_field(row.get("status", "unavailable")) if row else "unavailable"


def parse_vot_acoustic_result(
    request: VOTAnalysisRequest,
    aligned_phone: VOTAlignedPhone | None,
    result_path: Path,
) -> VOTAcousticResult:
    rows = _metric_rows(result_path)
    snapshot = request.audio_snapshot
    vot_row = rows.get("vot_candidate_ms", {})
    native_status = _metric_status(rows, "vot_candidate_ms")
    if native_status == "ambiguous":
        status = VOTStatus.AMBIGUOUS
    elif native_status == "target_incomplete":
        status = VOTStatus.TARGET_INCOMPLETE
    elif native_status == "warning":
        status = VOTStatus.CANDIDATE
    else:
        status = VOTStatus.FAILED

    def boundary_sample(metric_id: str) -> int | None:
        value = _finite_metric(rows, metric_id)
        if value is None:
            return None
        try:
            return snapshot.seconds_to_absolute_sample(value)
        except (TypeError, ValueError):
            return None

    burst_sample = boundary_sample("burst_time_candidate")
    onset_sample = boundary_sample("voicing_time_candidate")
    if status == VOTStatus.CANDIDATE and (burst_sample is None or onset_sample is None):
        status = VOTStatus.FAILED
    parameters_found = _parse_parameters(vot_row.get("parameters", ""))
    path = parameters_found.get("burstDetectionPath", "")
    band = parameters_found.get("burstDetectionBand", "")
    fallback_reason = parameters_found.get("burstDetectionFallbackReason", "")
    algorithm_version = parameters_found.get("algorithmVersion", "")
    reason = _decode_tsv_field(vot_row.get("reason", ""))
    if status in {VOTStatus.AMBIGUOUS, VOTStatus.TARGET_INCOMPLETE, VOTStatus.FAILED}:
        reason = reason or parameters_found.get("candidateFailureReason", "")
    negative_evidence = _finite_metric(rows, "negative_vot_prevoicing_evidence")
    metric_parameters: dict[str, Any] = dict(parameters_found)
    metric_parameters["native_metric_status"] = native_status
    return VOTAcousticResult(
        status=status,
        burst_sample_index=burst_sample if status == VOTStatus.CANDIDATE else None,
        onset_sample_index=onset_sample if status == VOTStatus.CANDIDATE else None,
        reason=reason,
        burst_source=f"cpp:{band or path}:release-envelope" if burst_sample is not None else "",
        onset_source="cpp:pitch-stability-and-hnr" if onset_sample is not None else "",
        detector_path=path,
        fallback_reason=fallback_reason,
        negative_vot_evidence=bool(negative_evidence and negative_evidence > 0.0),
        parameters=metric_parameters,
        algorithm_version=algorithm_version,
    )


class PraatVOTAcousticAnalyzer:
    """Run the native contextual VOT analyzer against the immutable PCM snapshot."""

    def __init__(self, bridge: PraatBridge):
        self.bridge = bridge

    def analyze(
        self,
        request: VOTAnalysisRequest,
        aligned_phone: VOTAlignedPhone | None,
    ) -> VOTAcousticResult:
        snapshot = request.audio_snapshot
        if snapshot.pcm_path is None or snapshot.manifest_path is None:
            raise PraatBridgeError("The VOT audio snapshot is missing its native PCM or manifest file.")
        for path in (snapshot.pcm_path, snapshot.manifest_path, snapshot.path):
            if not path.is_file():
                raise PraatBridgeError(f"The VOT audio snapshot artifact is missing: {path}")

        if aligned_phone is None:
            aligned_start = aligned_end = -1
        else:
            aligned_start = aligned_phone.start_sample
            aligned_end = aligned_phone.end_sample
        parameters = json.dumps(
            {
                **request.to_dict()["parameters"],
                "mode": request.mode.value,
                "manual_boundaries": (
                    list(request.manual_boundaries)
                    if request.manual_boundaries is not None
                    else None
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        old_selection = [item.id for item in self.bridge.selected_objects()]
        with tempfile.TemporaryDirectory(
            prefix="praat-vot-result-", dir=str(self.bridge.output_dir())
        ) as temporary:
            result_path = Path(temporary) / "analysis.tsv"
            try:
                self.bridge.select(int(snapshot.object_id))
                self.bridge.call(
                    "Analyse VOT audio snapshot...",
                    str(snapshot.manifest_path),
                    str(snapshot.pcm_path),
                    request.target_range[0],
                    request.target_range[1],
                    request.acoustic_context_range[0],
                    request.acoustic_context_range[1],
                    aligned_start,
                    aligned_end,
                    parameters,
                    str(result_path),
                )
            finally:
                self.bridge._restore_selection(old_selection)
            if not result_path.is_file():
                raise PraatBridgeError("Praat did not write a structured VOT acoustic result.")
            return parse_vot_acoustic_result(request, aligned_phone, result_path)


class TSVVOTAcousticAnalyzer:
    """Adapt an already produced native TSV into the shared acoustic result type."""

    def __init__(self, result_path: Path):
        self.result_path = result_path

    def analyze(
        self,
        request: VOTAnalysisRequest,
        aligned_phone: VOTAlignedPhone | None,
    ) -> VOTAcousticResult:
        return parse_vot_acoustic_result(request, aligned_phone, self.result_path)
