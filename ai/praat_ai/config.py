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
class AppConfig:
    qwen: QwenConfig = field(default_factory=QwenConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)

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
