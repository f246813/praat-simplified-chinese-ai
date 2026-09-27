from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from .forced_alignment import CompositeAligner
from .models import AlignedPhone, AlignmentResult, PhoneSpec, VOTAlignmentEvidence


class VOTMode(str, Enum):
    MODEL_ASSISTED = "model_assisted"
    ACOUSTIC_ONLY = "acoustic_only"
    MANUAL = "manual"


class VOTStatus(str, Enum):
    CANDIDATE = "candidate"
    AMBIGUOUS = "ambiguous"
    REQUIRES_INPUT = "requires_input"
    TARGET_INCOMPLETE = "target_incomplete"
    FAILED = "failed"
    MANUAL_CONFIRMED = "manual_confirmed"
    STALE = "stale"


class VOTJobState(str, Enum):
    QUEUED = "queued"
    ALIGNING = "aligning"
    READY_FOR_ACOUSTICS = "ready_for_acoustics"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_VOT_STOP_SYMBOLS = frozenset("pbtdʈɖcɟkgɡqɢʔʡɓɗᶑʄɠʛ")
_IPA_PREFIX_MARKS = frozenset("ˈˌːˑ͜͡'")


def _is_vot_stop_phone(ipa: str) -> bool:
    normalized = unicodedata.normalize("NFD", ipa.strip())
    first_segment = next(
        (
            symbol
            for symbol in normalized
            if symbol not in _IPA_PREFIX_MARKS
            and not unicodedata.combining(symbol)
            and not symbol.isspace()
        ),
        "",
    )
    return first_segment in _VOT_STOP_SYMBOLS


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _normalize_parameter_numbers(value: Any) -> Any:
    """Use one JSON representation for equivalent integer and float settings."""

    if isinstance(value, Mapping):
        return {
            str(key): _normalize_parameter_numbers(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return tuple(_normalize_parameter_numbers(item) for item in value)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return value


def _is_sample_index(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_range(value: Any) -> bool:
    return (
        isinstance(value, tuple)
        and len(value) == 2
        and _is_sample_index(value[0])
        and _is_sample_index(value[1])
        and value[0] < value[1]
    )


@dataclass(frozen=True, slots=True)
class VOTAudioSnapshot:
    path: Path
    content_hash: str
    object_id: str
    object_version: str
    source_kind: str
    sample_rate_hz: float
    channels: int
    sample_count: int
    snapshot_start_sample: int
    time_origin_seconds: float
    pcm_path: Path | None = field(default=None, compare=False, repr=False)
    manifest_path: Path | None = field(default=None, compare=False, repr=False)

    @property
    def end_sample_exclusive(self) -> int:
        return self.snapshot_start_sample + self.sample_count

    def absolute_sample_to_seconds(self, sample_index: int) -> float:
        if not _is_sample_index(sample_index):
            raise TypeError("sample index must be an integer")
        if not self.snapshot_start_sample <= sample_index <= self.end_sample_exclusive:
            raise ValueError("sample index is outside the audio snapshot")
        if self.sample_rate_hz <= 0:
            raise ValueError("sample rate must be positive")
        return self.time_origin_seconds + (
            sample_index - self.snapshot_start_sample
        ) / self.sample_rate_hz

    def seconds_to_absolute_sample(self, time_seconds: float) -> int:
        if not math.isfinite(time_seconds):
            raise ValueError("time must be finite")
        if self.sample_rate_hz <= 0:
            raise ValueError("sample rate must be positive")
        sample_offset = (time_seconds - self.time_origin_seconds) * self.sample_rate_hz
        sample_index = self.snapshot_start_sample + math.floor(sample_offset + 0.5)
        if not self.snapshot_start_sample <= sample_index <= self.end_sample_exclusive:
            raise ValueError("time is outside the audio snapshot")
        return sample_index

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_hash": self.content_hash,
            "object_id": self.object_id,
            "object_version": self.object_version,
            "source_kind": self.source_kind,
            "sample_rate_hz": self.sample_rate_hz,
            "channels": self.channels,
            "sample_count": self.sample_count,
            "snapshot_start_sample": self.snapshot_start_sample,
            "time_origin_seconds": self.time_origin_seconds,
        }


@dataclass(frozen=True, slots=True)
class VOTAnalysisRequest:
    request_id: str
    audio_snapshot: VOTAudioSnapshot
    target_range: tuple[int, int]
    acoustic_context_range: tuple[int, int]
    alignment_context_range: tuple[int, int]
    language: str
    transcript: str
    phonemes: tuple[str, ...]
    target_phone_index: int | None
    mode: VOTMode
    parameters: Mapping[str, Any] = field(default_factory=dict)
    model_ids: tuple[str, ...] = ()
    model_versions: Mapping[str, str] = field(default_factory=dict)
    manual_boundaries: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_range", tuple(self.target_range))
        object.__setattr__(
            self,
            "acoustic_context_range",
            tuple(self.acoustic_context_range),
        )
        object.__setattr__(
            self,
            "alignment_context_range",
            tuple(self.alignment_context_range),
        )
        object.__setattr__(self, "phonemes", tuple(str(phone) for phone in self.phonemes))
        object.__setattr__(self, "model_ids", tuple(str(item) for item in self.model_ids))
        object.__setattr__(
            self,
            "parameters",
            _freeze(_normalize_parameter_numbers(self.parameters)),
        )
        object.__setattr__(self, "model_versions", _freeze(self.model_versions))
        if self.manual_boundaries is not None:
            object.__setattr__(self, "manual_boundaries", tuple(self.manual_boundaries))
        if not isinstance(self.mode, VOTMode):
            object.__setattr__(self, "mode", VOTMode(self.mode))

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "audio_snapshot": self.audio_snapshot.to_dict(),
            "target_range": list(self.target_range),
            "acoustic_context_range": list(self.acoustic_context_range),
            "alignment_context_range": list(self.alignment_context_range),
            "language": self.language,
            "transcript": self.transcript,
            "phonemes": list(self.phonemes),
            "target_phone_index": self.target_phone_index,
            "mode": self.mode.value,
            "parameters": _thaw(self.parameters),
            "model_ids": list(self.model_ids),
            "model_versions": _thaw(self.model_versions),
            "manual_boundaries": (
                list(self.manual_boundaries)
                if self.manual_boundaries is not None
                else None
            ),
        }

    @property
    def request_hash(self) -> str:
        # request_id identifies one execution, not its analytical inputs. Keeping
        # it out makes equivalent editor and AI requests compare identically.
        canonical_request = self.to_dict()
        canonical_request.pop("request_id", None)
        encoded = json.dumps(
            canonical_request,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class VOTAlignedPhone:
    phone_index: int
    ipa: str
    start_sample: int
    end_sample: int
    source: str
    confidence: float | None

    @classmethod
    def from_alignment(
        cls,
        phone: AlignedPhone,
        snapshot: VOTAudioSnapshot,
    ) -> VOTAlignedPhone:
        if not math.isfinite(phone.start) or not math.isfinite(phone.end):
            raise ValueError("alignment returned a non-finite phone boundary")
        start = snapshot.snapshot_start_sample + round(
            phone.start * snapshot.sample_rate_hz
        )
        end = snapshot.snapshot_start_sample + round(
            phone.end * snapshot.sample_rate_hz
        )
        if start < snapshot.snapshot_start_sample or end > snapshot.end_sample_exclusive:
            raise ValueError("alignment phone lies outside the audio snapshot")
        if end <= start:
            raise ValueError("alignment phone has an empty sample range")
        return cls(
            phone_index=phone.phone_index,
            ipa=phone.ipa,
            start_sample=start,
            end_sample=end,
            source=phone.source,
            confidence=phone.confidence,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "phone_index": self.phone_index,
            "ipa": self.ipa,
            "start_sample": self.start_sample,
            "end_sample": self.end_sample,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class VOTAcousticResult:
    status: VOTStatus
    burst_sample_index: int | None
    onset_sample_index: int | None
    reason: str
    burst_source: str
    onset_source: str
    detector_path: str
    fallback_reason: str
    negative_vot_evidence: bool = False
    parameters: Mapping[str, Any] = field(default_factory=dict)
    algorithm_version: str = ""
    candidate_pairs: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, VOTStatus):
            object.__setattr__(self, "status", VOTStatus(self.status))
        object.__setattr__(self, "parameters", _freeze(self.parameters))
        object.__setattr__(
            self,
            "candidate_pairs",
            tuple(_freeze(item) for item in self.candidate_pairs),
        )


@dataclass(frozen=True, slots=True)
class VOTPreparedAnalysis:
    request: VOTAnalysisRequest
    alignment_evidence: VOTAlignmentEvidence | None
    target_phone: VOTAlignedPhone | None
    status: VOTStatus | None
    reason: str = ""
    model_disagreement_sec: float | None = None


@dataclass(frozen=True, slots=True)
class VOTAnalysisResult:
    request_id: str
    request_hash: str
    audio_hash: str
    object_id: str
    object_version: str
    source_kind: str
    sample_rate_hz: int
    snapshot_start_sample: int
    target_range: tuple[int, int]
    acoustic_context_range: tuple[int, int]
    alignment_context_range: tuple[int, int]
    mode: VOTMode
    status: VOTStatus
    target_phone: VOTAlignedPhone | None
    burst_sample_index: int | None
    onset_sample_index: int | None
    vot_ms: float | None
    failure_reason: str
    alignment_evidence: VOTAlignmentEvidence | None
    model_disagreement_sec: float | None
    burst_source: str
    onset_source: str
    negative_vot_evidence: bool
    detector_path: str
    fallback_reason: str
    parameters: Mapping[str, Any]
    model_ids: tuple[str, ...]
    model_versions: Mapping[str, str]
    algorithm_version: str
    candidate_pairs: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        evidence = self.alignment_evidence
        return {
            "request_id": self.request_id,
            "request_hash": self.request_hash,
            "audio_hash": self.audio_hash,
            "object_id": self.object_id,
            "object_version": self.object_version,
            "source_kind": self.source_kind,
            "sample_rate_hz": self.sample_rate_hz,
            "snapshot_start_sample": self.snapshot_start_sample,
            "target_range": list(self.target_range),
            "acoustic_context_range": list(self.acoustic_context_range),
            "alignment_context_range": list(self.alignment_context_range),
            "mode": self.mode.value,
            "status": self.status.value,
            "target_phone": self.target_phone.to_dict() if self.target_phone else None,
            "burst_sample_index": self.burst_sample_index,
            "onset_sample_index": self.onset_sample_index,
            "vot_ms": self.vot_ms,
            "failure_reason": self.failure_reason,
            "alignment_evidence": (
                {
                    "results": [result.to_dict() for result in evidence.results],
                    "backend_errors": list(evidence.backend_errors),
                    "disagreement_threshold_sec": evidence.disagreement_threshold_sec,
                }
                if evidence
                else None
            ),
            "model_disagreement_sec": self.model_disagreement_sec,
            "burst_source": self.burst_source,
            "onset_source": self.onset_source,
            "negative_vot_evidence": self.negative_vot_evidence,
            "detector_path": self.detector_path,
            "fallback_reason": self.fallback_reason,
            "parameters": _thaw(self.parameters),
            "model_ids": list(self.model_ids),
            "model_versions": _thaw(self.model_versions),
            "algorithm_version": self.algorithm_version,
            "candidate_pairs": [_thaw(item) for item in self.candidate_pairs],
        }


@dataclass(frozen=True, slots=True)
class VOTJobSnapshot:
    job_id: str
    state: VOTJobState
    stage: str
    progress: float
    prepared_analysis: VOTPreparedAnalysis | None
    result: VOTAnalysisResult | None
    error: str


class VOTAcousticAnalyzer(Protocol):
    def analyze(
        self,
        request: VOTAnalysisRequest,
        aligned_phone: VOTAlignedPhone | None,
    ) -> VOTAcousticResult: ...


class VOTAnalysisService:
    def __init__(self, aligner: CompositeAligner):
        self.aligner = aligner

    def prepare(
        self,
        request: VOTAnalysisRequest,
        use_cache: bool = False,
    ) -> VOTPreparedAnalysis:
        del use_cache  # This service has no result cache; every call recomputes.
        problem = self._request_problem(request)
        if problem:
            return VOTPreparedAnalysis(
                request=request,
                alignment_evidence=None,
                target_phone=None,
                status=VOTStatus.FAILED,
                reason=problem,
            )
        if request.mode == VOTMode.MANUAL:
            return VOTPreparedAnalysis(
                request, None, None, VOTStatus.REQUIRES_INPUT,
                "manual mode requires explicit boundary confirmation",
            )
        if request.mode == VOTMode.ACOUSTIC_ONLY:
            return VOTPreparedAnalysis(request, None, None, None)
        if not request.language.strip():
            return VOTPreparedAnalysis(
                request, None, None, VOTStatus.REQUIRES_INPUT,
                "language is required for model-assisted VOT",
            )
        if not request.phonemes:
            return VOTPreparedAnalysis(
                request, None, None, VOTStatus.REQUIRES_INPUT,
                "phoneme sequence is required for model-assisted VOT",
            )

        try:
            evidence = self.aligner.align_for_vot(
                request.audio_snapshot.path,
                [PhoneSpec(ipa=phone) for phone in request.phonemes],
                request.language,
                request.transcript,
            )
        except Exception as error:
            return VOTPreparedAnalysis(
                request,
                None,
                None,
                VOTStatus.FAILED,
                f"alignment_failed: {error}",
            )

        if not evidence.results:
            return VOTPreparedAnalysis(
                request,
                evidence,
                None,
                VOTStatus.FAILED,
                self._alignment_failure_reason(evidence),
            )

        counts = {len(result.phones) for result in evidence.results}
        if len(counts) > 1:
            return VOTPreparedAnalysis(
                request,
                evidence,
                None,
                VOTStatus.AMBIGUOUS,
                "alignment_phone_count_disagreement: backends returned different phone counts",
            )
        if next(iter(counts)) != len(request.phonemes):
            return VOTPreparedAnalysis(
                request,
                evidence,
                None,
                VOTStatus.FAILED,
                "alignment_phone_count_mismatch: aligned phones do not match the supplied phoneme sequence",
            )

        selected: list[VOTAlignedPhone] = []
        selection_statuses: list[VOTStatus | None] = []
        selection_reasons: list[str] = []
        for alignment in evidence.results:
            phone, status, reason = self._select_target_phone(request, alignment)
            if phone:
                selected.append(phone)
            else:
                selection_statuses.append(status)
                selection_reasons.append(reason)

        if selection_statuses:
            if len(evidence.results) > 1:
                return VOTPreparedAnalysis(
                    request,
                    evidence,
                    None,
                    VOTStatus.AMBIGUOUS,
                    "alignment_target_disagreement: " + "; ".join(selection_reasons),
                )
            return VOTPreparedAnalysis(
                request,
                evidence,
                None,
                selection_statuses[0],
                selection_reasons[0],
            )

        if not _is_vot_stop_phone(selected[0].ipa):
            return VOTPreparedAnalysis(
                request,
                evidence,
                selected[0],
                VOTStatus.FAILED,
                "target_phone_not_stop: model-assisted VOT requires a stop-like "
                f"target, but the aligned phone is /{selected[0].ipa}/",
            )

        disagreement = self._model_disagreement(
            selected,
            request.audio_snapshot.sample_rate_hz,
        )
        if disagreement is not None and disagreement > evidence.disagreement_threshold_sec:
            return VOTPreparedAnalysis(
                request,
                evidence,
                selected[0],
                VOTStatus.AMBIGUOUS,
                "model_disagreement: aligned target boundaries exceed the configured threshold",
                disagreement,
            )
        return VOTPreparedAnalysis(
            request=request,
            alignment_evidence=evidence,
            target_phone=selected[0],
            status=None,
            reason="",
            model_disagreement_sec=disagreement,
        )

    def complete(
        self,
        prepared: VOTPreparedAnalysis,
        acoustic_analyzer: VOTAcousticAnalyzer | None,
    ) -> VOTAnalysisResult:
        request = prepared.request
        if prepared.status is not None:
            return self._result(
                request,
                status=prepared.status,
                reason=prepared.reason,
                alignment_evidence=prepared.alignment_evidence,
                target_phone=prepared.target_phone,
                model_disagreement_sec=prepared.model_disagreement_sec,
            )
        if acoustic_analyzer is None:
            return self._result(
                request,
                status=VOTStatus.FAILED,
                reason="acoustic_analyzer_unavailable",
                alignment_evidence=prepared.alignment_evidence,
                target_phone=prepared.target_phone,
                model_disagreement_sec=prepared.model_disagreement_sec,
            )
        try:
            acoustic = acoustic_analyzer.analyze(request, prepared.target_phone)
        except Exception as error:
            return self._result(
                request,
                status=VOTStatus.FAILED,
                reason=f"acoustic_analysis_failed: {error}",
                alignment_evidence=prepared.alignment_evidence,
                target_phone=prepared.target_phone,
                model_disagreement_sec=prepared.model_disagreement_sec,
            )

        status = acoustic.status
        burst = acoustic.burst_sample_index
        onset = acoustic.onset_sample_index
        vot_ms: float | None = None
        reason = acoustic.reason
        if status == VOTStatus.CANDIDATE:
            if not _is_sample_index(burst) or not _is_sample_index(onset):
                status = VOTStatus.FAILED
                reason = reason or "cpp_result_missing_boundary"
                burst = None
                onset = None
            elif not self._boundaries_inside_context(request, burst, onset):
                status = VOTStatus.FAILED
                reason = "cpp_result_boundary_outside_context"
                burst = None
                onset = None
            elif onset < burst and not acoustic.negative_vot_evidence:
                status = VOTStatus.FAILED
                reason = "negative_vot_without_target_prevoicing_evidence"
            else:
                vot_ms = (
                    (onset - burst)
                    * 1000.0
                    / request.audio_snapshot.sample_rate_hz
                )
        else:
            vot_ms = None

        return self._result(
            request,
            status=status,
            reason=reason,
            alignment_evidence=prepared.alignment_evidence,
            target_phone=prepared.target_phone,
            model_disagreement_sec=prepared.model_disagreement_sec,
            burst_sample_index=burst,
            onset_sample_index=onset,
            vot_ms=vot_ms,
            burst_source=acoustic.burst_source,
            onset_source=acoustic.onset_source,
            negative_vot_evidence=acoustic.negative_vot_evidence,
            detector_path=acoustic.detector_path,
            fallback_reason=acoustic.fallback_reason,
            parameters=acoustic.parameters or request.parameters,
            algorithm_version=acoustic.algorithm_version,
            candidate_pairs=acoustic.candidate_pairs,
        )

    def analyze(
        self,
        request: VOTAnalysisRequest,
        acoustic_analyzer: VOTAcousticAnalyzer,
        use_cache: bool = False,
    ) -> VOTAnalysisResult:
        if request.mode == VOTMode.MANUAL:
            return self.confirm_manual(request)
        prepared = self.prepare(request, use_cache=use_cache)
        return self.complete(prepared, acoustic_analyzer)

    def confirm_manual(self, request: VOTAnalysisRequest) -> VOTAnalysisResult:
        problem = self._request_problem(request)
        if problem:
            return self._result(request, VOTStatus.FAILED, problem)
        if request.mode != VOTMode.MANUAL:
            return self._result(
                request,
                VOTStatus.FAILED,
                "manual_confirmation_requires_manual_mode",
            )
        boundaries = request.manual_boundaries
        if (
            boundaries is None
            or len(boundaries) != 2
            or not all(_is_sample_index(value) for value in boundaries)
        ):
            return self._result(
                request,
                VOTStatus.REQUIRES_INPUT,
                "manual burst and onset sample indices are required",
            )
        burst, onset = boundaries
        if not self._boundaries_inside_context(request, burst, onset):
            return self._result(
                request,
                VOTStatus.FAILED,
                "manual boundaries must lie inside the acoustic context",
            )
        return self._result(
            request,
            status=VOTStatus.MANUAL_CONFIRMED,
            reason="",
            burst_sample_index=burst,
            onset_sample_index=onset,
            vot_ms=(onset - burst) * 1000.0 / request.audio_snapshot.sample_rate_hz,
            burst_source="manual",
            onset_source="manual",
            algorithm_version="manual-v1",
        )

    @staticmethod
    def _request_problem(request: VOTAnalysisRequest) -> str:
        snapshot = request.audio_snapshot
        if not request.request_id.strip():
            return "invalid_request: request id is required"
        if not snapshot.content_hash.strip():
            return "invalid_request: audio content hash is required"
        if snapshot.sample_rate_hz <= 0 or snapshot.channels <= 0 or snapshot.sample_count <= 0:
            return "invalid_request: snapshot sample rate, channels, and sample count must be positive"
        if not _is_sample_index(snapshot.snapshot_start_sample) or snapshot.snapshot_start_sample < 0:
            return "invalid_request: snapshot start sample must be a non-negative integer"
        snapshot_range = (
            snapshot.snapshot_start_sample,
            snapshot.end_sample_exclusive,
        )
        ranges = (
            ("target", request.target_range),
            ("acoustic context", request.acoustic_context_range),
            ("alignment context", request.alignment_context_range),
        )
        for name, sample_range in ranges:
            if not _valid_range(sample_range):
                return f"invalid_request: {name} range must be increasing integer sample indices"
            if (
                sample_range[0] < snapshot_range[0]
                or sample_range[1] > snapshot_range[1]
            ):
                return f"invalid_request: {name} range lies outside the audio snapshot"
        if request.alignment_context_range != snapshot_range:
            return "invalid_request: snapshot must contain exactly the fixed alignment context"
        if not (
            request.acoustic_context_range[0]
            <= request.target_range[0]
            < request.target_range[1]
            <= request.acoustic_context_range[1]
        ):
            return "invalid_request: target range must lie inside acoustic context"
        if not math.isfinite(snapshot.time_origin_seconds):
            return "invalid_request: original time origin must be finite"
        if request.target_phone_index is not None and request.phonemes and (
            not _is_sample_index(request.target_phone_index)
            or request.target_phone_index < 0
            or request.target_phone_index >= len(request.phonemes)
        ):
            return "invalid_request: target phone index must identify a supplied phoneme"
        if request.mode == VOTMode.MANUAL and request.manual_boundaries is not None:
            if len(request.manual_boundaries) != 2 or not all(
                _is_sample_index(value) for value in request.manual_boundaries
            ):
                return "invalid_request: manual boundaries must be two integer sample indices"
        return ""

    @staticmethod
    def _alignment_failure_reason(evidence: VOTAlignmentEvidence) -> str:
        details = "; ".join(evidence.backend_errors)
        lowered = details.lower()
        if not details or all(
            "unavailable" in item.lower() for item in evidence.backend_errors
        ):
            return "model_unavailable: no configured alignment model is available"
        if "language" in lowered and any(
            marker in lowered for marker in ("mismatch", "unsupported", "not support")
        ):
            return f"language_mismatch: {details}"
        if "language metadata is not configured" in lowered:
            return f"language_not_configured: {details}"
        return f"alignment_failed: {details}"

    def _select_target_phone(
        self,
        request: VOTAnalysisRequest,
        alignment: AlignmentResult,
    ) -> tuple[VOTAlignedPhone | None, VOTStatus | None, str]:
        try:
            aligned = [
                VOTAlignedPhone.from_alignment(phone, request.audio_snapshot)
                for phone in alignment.phones
            ]
        except ValueError as error:
            return None, VOTStatus.FAILED, f"invalid_alignment: {error}"

        if request.target_phone_index is not None:
            wanted_index = request.target_phone_index + 1
            matches = [phone for phone in aligned if phone.phone_index == wanted_index]
            if len(matches) != 1:
                return None, VOTStatus.FAILED, "alignment_target_missing: requested phone was not aligned"
            selected = matches[0]
            if not self._selection_contains_phone(request.target_range, selected):
                return None, VOTStatus.TARGET_INCOMPLETE, "target selection clips the aligned phone"
            return selected, None, ""

        fully_selected = [
            phone
            for phone in aligned
            if self._selection_contains_phone(request.target_range, phone)
        ]
        overlapping = [
            phone
            for phone in aligned
            if phone.start_sample < request.target_range[1]
            and phone.end_sample > request.target_range[0]
        ]
        if len(fully_selected) > 1:
            return None, VOTStatus.AMBIGUOUS, "selection contains more than one complete aligned phone"
        if len(fully_selected) == 1:
            if len(overlapping) > 1:
                return None, VOTStatus.AMBIGUOUS, "selection also overlaps a neighboring aligned phone"
            return fully_selected[0], None, ""
        if overlapping:
            return None, VOTStatus.TARGET_INCOMPLETE, "target selection clips the aligned phone"
        return None, VOTStatus.REQUIRES_INPUT, "selection does not identify an aligned phone"

    @staticmethod
    def _selection_contains_phone(
        selection: tuple[int, int],
        phone: VOTAlignedPhone,
    ) -> bool:
        return selection[0] <= phone.start_sample and phone.end_sample <= selection[1]

    @staticmethod
    def _model_disagreement(
        selected: list[VOTAlignedPhone],
        sample_rate_hz: int,
    ) -> float | None:
        if len(selected) < 2:
            return None
        if sample_rate_hz <= 0:
            raise ValueError("sample rate must be positive")
        starts = [phone.start_sample for phone in selected]
        ends = [phone.end_sample for phone in selected]
        max_samples = max(max(starts) - min(starts), max(ends) - min(ends))
        return max_samples / sample_rate_hz

    @staticmethod
    def _boundaries_inside_context(
        request: VOTAnalysisRequest,
        burst: int,
        onset: int,
    ) -> bool:
        start, end = request.acoustic_context_range
        return start <= burst <= end and start <= onset <= end

    @staticmethod
    def _result(
        request: VOTAnalysisRequest,
        status: VOTStatus,
        reason: str = "",
        *,
        alignment_evidence: VOTAlignmentEvidence | None = None,
        target_phone: VOTAlignedPhone | None = None,
        model_disagreement_sec: float | None = None,
        burst_sample_index: int | None = None,
        onset_sample_index: int | None = None,
        vot_ms: float | None = None,
        burst_source: str = "",
        onset_source: str = "",
        negative_vot_evidence: bool = False,
        detector_path: str = "",
        fallback_reason: str = "",
        parameters: Mapping[str, Any] | None = None,
        algorithm_version: str = "",
        candidate_pairs: tuple[Mapping[str, Any], ...] = (),
    ) -> VOTAnalysisResult:
        snapshot = request.audio_snapshot
        used_models: list[str] = []
        if alignment_evidence is not None:
            for alignment in alignment_evidence.results:
                for configured in request.model_ids:
                    if alignment.source == configured or alignment.source.startswith(
                        configured + ":"
                    ):
                        if configured not in used_models:
                            used_models.append(configured)
        used_versions = {
            model: request.model_versions[model]
            for model in used_models
            if model in request.model_versions
        }
        return VOTAnalysisResult(
            request_id=request.request_id,
            request_hash=request.request_hash,
            audio_hash=snapshot.content_hash,
            object_id=snapshot.object_id,
            object_version=snapshot.object_version,
            source_kind=snapshot.source_kind,
            sample_rate_hz=snapshot.sample_rate_hz,
            snapshot_start_sample=snapshot.snapshot_start_sample,
            target_range=request.target_range,
            acoustic_context_range=request.acoustic_context_range,
            alignment_context_range=request.alignment_context_range,
            mode=request.mode,
            status=status,
            target_phone=target_phone,
            burst_sample_index=burst_sample_index,
            onset_sample_index=onset_sample_index,
            vot_ms=vot_ms,
            failure_reason=reason,
            alignment_evidence=alignment_evidence,
            model_disagreement_sec=model_disagreement_sec,
            burst_source=burst_source,
            onset_source=onset_source,
            negative_vot_evidence=negative_vot_evidence,
            detector_path=detector_path,
            fallback_reason=fallback_reason,
            parameters=_freeze(parameters or request.parameters),
            model_ids=tuple(used_models),
            model_versions=used_versions,
            algorithm_version=algorithm_version,
            candidate_pairs=tuple(_freeze(item) for item in candidate_pairs),
        )
