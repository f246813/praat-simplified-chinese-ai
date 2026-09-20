from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class QwenConfig:
    base_url: str = "http://127.0.0.1:8000/v1"
    model: str = "Qwen/Qwen3.5-0.8B"
    api_key: str = "EMPTY"
    request_timeout_sec: int = 60
    default_mode: str = "text"
    enable_thinking: bool = False
    vision_when_requested: bool = True
    max_context_tokens: int = 8192
    keep_alive_sec: int = 300


@dataclass(slots=True)
class ServerConfig:
    llama_server: str = ""
    model_path: str = ""
    mmproj_path: str = ""
    mmproj_by_model: dict[str, str] = field(default_factory=dict)
    host: str = "127.0.0.1"
    port: int = 8000
    n_gpu_layers: int = -1
    threads: int = 8
    parallel: int = 1
    auto_start: bool = False


@dataclass(slots=True)
class AnalysisConfig:
    default_error_threshold: float = 1.25
    minimum_error_duration_sec: float = 0.04
    maximum_errors_per_phone: int = 3


@dataclass(slots=True)
class MfaAlignmentConfig:
    enabled: bool = False
    executable: str = "mfa"
    conda_executable: str = ""
    conda_environment: str = ""
    dictionary_path: str = ""
    acoustic_model: str = ""
    beam: int = 10
    retry_beam: int = 40


@dataclass(slots=True)
class Wav2Vec2AlignmentConfig:
    enabled: bool = False
    model: str = ""
    device: str = "cuda"
    blank_token_id: int = 0
    sample_rate: int = 16000
    do_phonemize: bool = False
    token_map: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class AlignmentConfig:
    backend: str = "auto"
    agreement_threshold_sec: float = 0.04
    minimum_confidence: float = 0.45
    mfa: MfaAlignmentConfig = field(default_factory=MfaAlignmentConfig)
    wav2vec2: Wav2Vec2AlignmentConfig = field(
        default_factory=Wav2Vec2AlignmentConfig
    )


@dataclass(slots=True)
class AppConfig:
    qwen: QwenConfig = field(default_factory=QwenConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    alignment: AlignmentConfig = field(default_factory=AlignmentConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_config_path() -> Path:
    return Path(__file__).resolve().parents[1] / "ai_config.json"


def _merge_dataclass(instance: Any, values: dict[str, Any]) -> None:
    for key, value in values.items():
        if hasattr(instance, key):
            setattr(instance, key, value)


def load_config(path: str | Path | None = None) -> AppConfig:
    config = AppConfig()
    candidate = Path(path) if path else default_config_path()
    if candidate.is_file():
        raw = json.loads(candidate.read_text(encoding="utf-8"))
        _merge_dataclass(config.qwen, raw.get("qwen", {}))
        _merge_dataclass(config.server, raw.get("server", {}))
        _merge_dataclass(config.analysis, raw.get("analysis", {}))
        alignment_values = raw.get("alignment", {})
        _merge_dataclass(
            config.alignment,
            {
                key: value
                for key, value in alignment_values.items()
                if key not in {"mfa", "wav2vec2"}
            },
        )
        _merge_dataclass(
            config.alignment.mfa,
            alignment_values.get("mfa", {}),
        )
        _merge_dataclass(
            config.alignment.wav2vec2,
            alignment_values.get("wav2vec2", {}),
        )

    config.qwen.base_url = os.getenv("PRAAT_AI_QWEN_BASE_URL", config.qwen.base_url)
    config.qwen.model = os.getenv("PRAAT_AI_QWEN_MODEL", config.qwen.model)
    config.qwen.api_key = os.getenv("PRAAT_AI_QWEN_API_KEY", config.qwen.api_key)
    config.qwen.default_mode = os.getenv("PRAAT_AI_QWEN_MODE", config.qwen.default_mode)

    env_server = os.getenv("PRAAT_AI_LLAMA_SERVER")
    env_model = os.getenv("PRAAT_AI_QWEN_MODEL_PATH")
    env_mmproj = os.getenv("PRAAT_AI_QWEN_MMPROJ_PATH")
    if env_server:
        config.server.llama_server = env_server
    if env_model:
        config.server.model_path = env_model
    if env_mmproj:
        config.server.mmproj_path = env_mmproj

    return config
