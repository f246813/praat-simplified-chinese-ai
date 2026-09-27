"""Scoring helpers for independently annotated VOT recordings."""

from __future__ import annotations

import hashlib
import itertools
import math
import wave
from pathlib import Path
from typing import Any, Mapping


RESULT_FIELDS = (
    "request_hash",
    "audio_hash",
    "object_id",
    "object_version",
    "source_kind",
    "sample_rate_hz",
    "snapshot_start_sample",
    "target_range",
    "acoustic_context_range",
    "alignment_context_range",
    "mode",
    "status",
    "target_phone",
    "burst_sample_index",
    "onset_sample_index",
    "vot_ms",
    "failure_reason",
    "alignment_evidence",
    "model_disagreement_sec",
    "burst_source",
    "onset_source",
    "negative_vot_evidence",
    "detector_path",
    "fallback_reason",
    "parameters",
    "model_ids",
    "model_versions",
    "algorithm_version",
    "candidate_pairs",
)
SUCCESS_STATUSES = {"candidate", "manual_confirmed"}


def validate_manifest(
    manifest: Any,
    *,
    base_dir: str | Path | None = None,
    require_audio: bool = True,
) -> list[str]:
    """Return structural and coverage errors for the Japanese gold manifest."""

    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"]
    if manifest.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if manifest.get("language") != "ja":
        errors.append("language must be ja")
    if not str(manifest.get("annotation_protocol", "")).strip():
        errors.append("annotation_protocol is required")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        return errors + ["cases must be a non-empty array"]

    seen: set[str] = set()
    classes: set[str] = set()
    multiple_bursts = sustained_voicing = False
    root = Path(base_dir or ".").resolve()
    for index, case in enumerate(cases):
        prefix = f"cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{prefix} must be an object")
            continue
        case_id = str(case.get("id", "")).strip()
        if not case_id:
            errors.append(f"{prefix}.id is required")
        elif case_id in seen:
            errors.append(f"case ids must be unique: {case_id}")
        seen.add(case_id)
        if case.get("language", manifest.get("language")) != "ja":
            errors.append(f"{prefix}.language must be ja")
        rate = case.get("sample_rate_hz")
        count = case.get("sample_count")
        if not isinstance(rate, (int, float)) or isinstance(rate, bool) or not math.isfinite(rate) or rate <= 0:
            errors.append(f"{prefix}.sample_rate_hz must be positive")
            rate = 0
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            errors.append(f"{prefix}.sample_count must be a positive integer")
            count = 0
        selection = case.get("target_selection_samples")
        selection_valid = (
            isinstance(selection, list)
            and len(selection) == 2
            and all(isinstance(value, int) and not isinstance(value, bool) for value in selection)
        )
        if (
            not selection_valid
            or selection[0] < 0
            or selection[0] >= selection[1]
            or selection[1] > count
        ):
            errors.append(f"{prefix}.target_selection_samples must be an in-range half-open sample pair")

        adjudicated = case.get("adjudicated")
        if not isinstance(adjudicated, dict):
            errors.append(f"{prefix}.adjudicated is required")
            adjudicated = {}
        burst = adjudicated.get("burst_sample_index")
        onset = adjudicated.get("onset_sample_index")
        uncertainty = adjudicated.get("uncertainty_samples")
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in (burst, onset, uncertainty)):
            errors.append(f"{prefix}.adjudicated needs integer burst, onset, and uncertainty samples")
        elif not (0 <= burst <= count and 0 <= onset <= count and uncertainty >= 0):
            errors.append(f"{prefix}.adjudicated boundaries or uncertainty are out of range")
        else:
            actual_class = "positive" if onset > burst else "negative" if onset < burst else "zero"
            vot_class = case.get("vot_class")
            if vot_class not in {"positive", "zero", "negative"}:
                errors.append(f"{prefix}.vot_class must be positive, zero, or negative")
            elif vot_class != actual_class:
                errors.append(f"{prefix}.vot_class does not match adjudicated boundary order")
            else:
                classes.add(vot_class)

        annotators = case.get("annotators")
        if not isinstance(annotators, dict) or len(annotators) < 2:
            errors.append(f"{prefix}.annotators must contain at least two independent annotations")
        else:
            for annotator, pair in annotators.items():
                if not isinstance(pair, dict) or not all(
                    isinstance(pair.get(field), int) and not isinstance(pair.get(field), bool)
                    for field in ("burst_sample_index", "onset_sample_index")
                ):
                    errors.append(f"{prefix}.annotators.{annotator} needs integer burst and onset samples")

        flags = case.get("flags")
        if not isinstance(flags, dict):
            errors.append(f"{prefix}.flags is required")
            flags = {}
        for field in ("multiple_burst_candidates", "sustained_voicing", "ambiguous_evidence"):
            if not isinstance(flags.get(field), bool):
                errors.append(f"{prefix}.flags.{field} must be boolean")
        multiple_bursts |= flags.get("multiple_burst_candidates") is True
        sustained_voicing |= flags.get("sustained_voicing") is True
        if not str(case.get("audio", "")).strip():
            errors.append(f"{prefix}.audio is required")
        digest = case.get("audio_sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest.lower()):
            errors.append(f"{prefix}.audio_sha256 must be a SHA-256 hex digest")
        phonemes = case.get("phonemes")
        if not isinstance(phonemes, list) or not phonemes or not all(isinstance(phone, str) and phone.strip() for phone in phonemes):
            errors.append(f"{prefix}.phonemes must be a non-empty phone sequence")
        target_phone_index = case.get("target_phone_index")
        if not isinstance(target_phone_index, int) or isinstance(target_phone_index, bool) or not 0 <= target_phone_index < len(phonemes or []):
            errors.append(f"{prefix}.target_phone_index must select a supplied phoneme")
        if case.get("mode", "acoustic_only") not in {"model_assisted", "acoustic_only"}:
            errors.append(f"{prefix}.mode must be model_assisted or acoustic_only")
        if case.get("mode") == "model_assisted" and not str(case.get("transcript", "")).strip():
            errors.append(f"{prefix}.transcript is required for model-assisted VOT")
        context_start = case.get("context_start_sample", 0)
        context_end = case.get("context_end_sample", count)
        if (
            not isinstance(context_start, int)
            or isinstance(context_start, bool)
            or not isinstance(context_end, int)
            or isinstance(context_end, bool)
            or context_start < 0
            or context_start >= context_end
            or context_end > count
            or not selection_valid
            or (selection_valid and (selection[0] < context_start or selection[1] > context_end))
        ):
            errors.append(f"{prefix} context sample range must contain the target selection")
        alternatives = case.get("alternative_pairs", [])
        if not isinstance(alternatives, list):
            errors.append(f"{prefix}.alternative_pairs must be an array")
        else:
            for pair_index, pair in enumerate(alternatives):
                if not isinstance(pair, dict) or not all(
                    isinstance(pair.get(field), int) and not isinstance(pair.get(field), bool)
                    for field in ("burst_sample_index", "onset_sample_index")
                ):
                    errors.append(f"{prefix}.alternative_pairs[{pair_index}] needs integer boundaries")
        if require_audio and case.get("audio"):
            audio_path = (root / case["audio"]).resolve()
            try:
                audio_path.relative_to(root)
            except ValueError:
                errors.append(f"{prefix}.audio must stay inside the manifest directory")
                continue
            if not audio_path.is_file():
                errors.append(f"{prefix}.audio file does not exist: {case['audio']}")
            else:
                actual_hash = hashlib.sha256(audio_path.read_bytes()).hexdigest()
                if isinstance(digest, str) and actual_hash.casefold() != digest.casefold():
                    errors.append(f"{prefix}.audio_sha256 does not match the file")
                try:
                    with wave.open(str(audio_path), "rb") as stream:
                        if stream.getcomptype() != "NONE":
                            errors.append(f"{prefix}.audio must be uncompressed PCM WAV")
                        if stream.getframerate() != rate or stream.getnframes() != count:
                            errors.append(f"{prefix}.sample_rate_hz/sample_count do not match the WAV")
                except (wave.Error, OSError):
                    errors.append(f"{prefix}.audio must be an uncompressed WAV readable by Python wave")

    for vot_class in ("positive", "zero", "negative"):
        if vot_class not in classes:
            errors.append(f"coverage requires at least one {vot_class} VOT case")
    if not multiple_bursts:
        errors.append("coverage requires a case with multiple_burst_candidates=true")
    if not sustained_voicing:
        errors.append("coverage requires a case with sustained_voicing=true")
    return errors


def _unwrap_result(value: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = value.get("result")
    return nested if isinstance(nested, Mapping) else value


def compare_entrypoints(editor: Mapping[str, Any], ai: Mapping[str, Any]) -> dict[str, Any]:
    """Compare the request/result fields that define cross-entrypoint parity."""

    left, right = _unwrap_result(editor), _unwrap_result(ai)
    differences = {
        field: {"editor": left.get(field), "ai": right.get(field)}
        for field in RESULT_FIELDS
        if left.get(field) != right.get(field)
    }
    return {"consistent": not differences, "differences": differences}


def score_case(case: Mapping[str, Any], entrypoints: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Score both full entrypoint results against the adjudicated sample pair."""

    gold = case["adjudicated"]
    rate = float(case["sample_rate_hz"])
    gold_burst, gold_onset = int(gold["burst_sample_index"]), int(gold["onset_sample_index"])
    gold_vot_ms = (gold_onset - gold_burst) * 1000.0 / rate
    uncertainty_ms = int(gold["uncertainty_samples"]) * 1000.0 / rate
    scores: dict[str, Any] = {}
    for name, wrapped in entrypoints.items():
        result = _unwrap_result(wrapped)
        burst, onset = result.get("burst_sample_index"), result.get("onset_sample_index")
        status = str(result.get("status", "unknown"))
        reported_vot = result.get("vot_ms")
        numeric_vot = (
            isinstance(reported_vot, (int, float))
            and not isinstance(reported_vot, bool)
            and math.isfinite(reported_vot)
        )
        has_numeric_candidate = (
            isinstance(burst, int)
            and not isinstance(burst, bool)
            and isinstance(onset, int)
            and not isinstance(onset, bool)
            and numeric_vot
        )
        ambiguous_case = bool(case.get("flags", {}).get("ambiguous_evidence"))
        ambiguity_correctly_declined = ambiguous_case and status == "ambiguous" and not has_numeric_candidate
        candidate_miss = not has_numeric_candidate and not ambiguity_correctly_declined
        status_value_contract_violation = (status in SUCCESS_STATUSES) != has_numeric_candidate
        burst_error_samples = burst - gold_burst if has_numeric_candidate else None
        onset_error_samples = onset - gold_onset if has_numeric_candidate else None
        boundary_vot = (onset - burst) * 1000.0 / rate if has_numeric_candidate else None
        detected_vot = float(reported_vot) if has_numeric_candidate else None
        vot_error = detected_vot - gold_vot_ms if detected_vot is not None else None
        alternative_pairs = case.get("alternative_pairs", [])
        wrong_pairing: bool | None = None
        if has_numeric_candidate and alternative_pairs:
            matches_alternative = any(
                abs(burst - int(pair["burst_sample_index"])) <= int(pair.get("uncertainty_samples", 0))
                and abs(onset - int(pair["onset_sample_index"])) <= int(pair.get("uncertainty_samples", 0))
                for pair in alternative_pairs
            )
            matches_gold = (
                abs(burst_error_samples) <= int(gold["uncertainty_samples"])
                and abs(onset_error_samples) <= int(gold["uncertainty_samples"])
            )
            wrong_pairing = matches_alternative and not matches_gold
        scores[name] = {
            "status": status,
            "candidate_miss": candidate_miss,
            "has_numeric_candidate": has_numeric_candidate,
            "status_value_contract_violation": status_value_contract_violation,
            "ambiguity_correctly_declined": ambiguity_correctly_declined,
            "burst_error_samples": burst_error_samples,
            "burst_error_ms": burst_error_samples * 1000.0 / rate if burst_error_samples is not None else None,
            "burst_absolute_error_ms": abs(burst_error_samples) * 1000.0 / rate if burst_error_samples is not None else None,
            "onset_error_samples": onset_error_samples,
            "onset_error_ms": onset_error_samples * 1000.0 / rate if onset_error_samples is not None else None,
            "onset_absolute_error_ms": abs(onset_error_samples) * 1000.0 / rate if onset_error_samples is not None else None,
            "gold_vot_ms": gold_vot_ms,
            "detected_vot_ms": detected_vot,
            "boundary_derived_vot_ms": boundary_vot,
            "reported_vot_formula_error_ms": (
                detected_vot - boundary_vot
                if detected_vot is not None and boundary_vot is not None
                else None
            ),
            "signed_vot_error_ms": vot_error,
            "absolute_vot_error_ms": abs(vot_error) if vot_error is not None else None,
            "sign_agreement": (
                (detected_vot > 0) == (gold_vot_ms > 0)
                and (detected_vot < 0) == (gold_vot_ms < 0)
                if detected_vot is not None
                else None
            ),
            "wrong_release_onset_pairing": wrong_pairing,
            "single_value_on_ambiguous_evidence": ambiguous_case and has_numeric_candidate,
            "annotation_uncertainty_ms": uncertainty_ms,
        }
    consistency = None
    if "editor" in entrypoints and "ai" in entrypoints:
        consistency = compare_entrypoints(entrypoints["editor"], entrypoints["ai"])
    annotators = case.get("annotators", {})
    disagreement_ms = None
    pairs = list(annotators.values()) if isinstance(annotators, Mapping) else []
    if len(pairs) >= 2:
        disagreement_samples = max(
            abs(int(left[field]) - int(right[field]))
            for left, right in itertools.combinations(pairs, 2)
            for field in ("burst_sample_index", "onset_sample_index")
        )
        disagreement_ms = disagreement_samples * 1000.0 / rate
    return {
        "case_id": case["id"],
        "language": case.get("language", "ja"),
        "vot_class": case["vot_class"],
        "multiple_burst_candidates": case.get("flags", {}).get("multiple_burst_candidates"),
        "sustained_voicing": case.get("flags", {}).get("sustained_voicing"),
        "ambiguous_evidence": case.get("flags", {}).get("ambiguous_evidence"),
        "gold": {"burst_sample_index": gold_burst, "onset_sample_index": gold_onset, "vot_ms": gold_vot_ms},
        "annotator_disagreement_ms": disagreement_ms,
        "entrypoints": scores,
        "entrypoint_consistency": consistency,
    }


def summarize_cases(scored_cases: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize raw errors without imposing a pass threshold not set by the user."""

    summary: dict[str, Any] = {"case_count": len(scored_cases), "by_class": {}, "entrypoints": {}}
    for vot_class in ("positive", "zero", "negative"):
        summary["by_class"][vot_class] = sum(case.get("vot_class") == vot_class for case in scored_cases)
    names = sorted({name for case in scored_cases for name in case.get("entrypoints", {})})
    for name in names:
        entries = [case["entrypoints"][name] for case in scored_cases if name in case.get("entrypoints", {})]
        valid = [entry for entry in entries if not entry["candidate_miss"]]
        metrics = {}
        for field in ("burst_absolute_error_ms", "onset_absolute_error_ms", "absolute_vot_error_ms"):
            values = [entry[field] for entry in valid if entry[field] is not None]
            metrics[field] = {
                "mean": sum(values) / len(values) if values else None,
                "maximum": max(values) if values else None,
            }
        summary["entrypoints"][name] = {
            "case_count": len(entries),
            "candidate_misses": sum(entry["candidate_miss"] for entry in entries),
            "ambiguity_correctly_declined": sum(entry["ambiguity_correctly_declined"] for entry in entries),
            "status_value_contract_violations": sum(entry["status_value_contract_violation"] for entry in entries),
            "wrong_pairings": sum(entry["wrong_release_onset_pairing"] is True for entry in entries),
            "ambiguous_single_values": sum(entry["single_value_on_ambiguous_evidence"] for entry in entries),
            "sign_agreements": sum(entry["sign_agreement"] is True for entry in valid),
            "errors": metrics,
        }
    comparisons = [case["entrypoint_consistency"] for case in scored_cases if case.get("entrypoint_consistency") is not None]
    summary["entrypoint_consistency"] = {
        "compared_cases": len(comparisons),
        "consistent_cases": sum(item["consistent"] for item in comparisons),
    }
    disagreements = [case["annotator_disagreement_ms"] for case in scored_cases if case.get("annotator_disagreement_ms") is not None]
    summary["annotation_disagreement_ms"] = {
        "mean": sum(disagreements) / len(disagreements) if disagreements else None,
        "maximum": max(disagreements) if disagreements else None,
    }
    return summary
