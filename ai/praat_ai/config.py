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
    # 生成参数：小模型和视觉模型对它们的敏感度不同，所以放进配置，
    # 由 server.presets[].qwen 按预设覆盖。
    plan_max_tokens: int = 700
    plan_temperature: float = 0.1
    top_p: float = 0.8
    presence_penalty: float = 1.5


@dataclass(slots=True)
class ServerPreset:
    """一个可以直接切换的本地模型预设。

    ``id`` 是稳定标识（菜单和状态上报都用它）；``label`` 只用于显示。
    ``context_tokens`` / ``n_gpu_layers`` / ``threads`` 为 0 或 ``None`` 时按显存
    自动选择（见 :mod:`praat_ai.vram`），否则覆盖自动值。
    ``qwen`` 里的键会覆盖 ``qwen`` 配置节，用来给不同模型配生成参数
    （例如小模型关闭 thinking、加大 ``max_tokens``）。
    """

    id: str = ""
    label: str = ""
    model_path: str = ""
    mmproj_path: str = ""
    vision: bool = True
    context_tokens: int = 0
    n_gpu_layers: int | None = None
    threads: int | None = None
    qwen: dict[str, Any] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        return self.label or Path(self.model_path).name or self.id


@dataclass(slots=True)
class ServerConfig:
    llama_server: str = ""
    model_path: str = ""
    mmproj_path: str = ""
    mmproj_by_model: dict[str, str] = field(default_factory=dict)
    presets: list[ServerPreset] = field(default_factory=list)
    active_preset: str = ""
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


def preset_from_raw(value: dict[str, Any], index: int = 0) -> ServerPreset:
    """Build a :class:`ServerPreset` from one JSON entry (tolerant to typos)."""

    model_path = str(value.get("model_path", "") or "")
    preset = ServerPreset(
        id=str(value.get("id", "") or "").strip(),
        label=str(value.get("label", "") or value.get("name", "") or "").strip(),
        model_path=model_path,
        mmproj_path=str(value.get("mmproj_path", "") or ""),
    )
    if not preset.id:
        preset.id = Path(model_path).name or f"preset-{index + 1}"
    if "vision" in value:
        preset.vision = bool(value.get("vision"))
    for key in ("context_tokens", "n_gpu_layers", "threads"):
        if value.get(key) not in (None, ""):
            try:
                setattr(preset, key, int(value[key]))
            except (TypeError, ValueError):
                pass
    qwen = value.get("qwen")
    if isinstance(qwen, dict):
        preset.qwen = dict(qwen)
    return preset


def presets_from_raw(value: Any) -> list[ServerPreset]:
    if isinstance(value, dict):
        # 兼容 {id: {...}} 写法：把键当成 id。
        items = []
        for key, entry in value.items():
            if isinstance(entry, dict):
                merged = dict(entry)
                merged.setdefault("id", key)
                items.append(merged)
        return [preset_from_raw(entry, index) for index, entry in enumerate(items)]
    if isinstance(value, list):
        return [
            preset_from_raw(entry, index)
            for index, entry in enumerate(value)
            if isinstance(entry, dict)
        ]
    return []


def load_config(path: str | Path | None = None) -> AppConfig:
    config = AppConfig()
    candidate = Path(path) if path else default_config_path()
    if candidate.is_file():
        raw = json.loads(candidate.read_text(encoding="utf-8"))
        _merge_dataclass(config.qwen, raw.get("qwen", {}))
        server_values = dict(raw.get("server", {}))
        presets_value = server_values.pop("presets", None)
        _merge_dataclass(config.server, server_values)
        if presets_value is not None:
            config.server.presets = presets_from_raw(presets_value)
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
