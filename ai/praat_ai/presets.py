"""模型预设：把「用哪个模型、配哪个 mmproj、用多大上下文」固化成一键切换。

维护要点：

- 预设只是配置模板，真正的切换仍然走
  :func:`praat_ai.control.set_frontend_model` 那套「端口上的模型和配置不一致就
  重启」的逻辑，所以预设不会绕过模型一致性检查。
- 预设里的 ``model_path`` 和 ``mmproj_path`` 必须成对；切换时会把这一对写进
  ``server.mmproj_by_model``，避免把 0.8B 的投影文件带给 2B 模型。
- 启动参数（上下文长度、GPU 层数）以预设为准，写入 ``server.active_preset``
  后由 :func:`apply_preset_to_profile` 覆盖显存档位。
- 找不到预设、模型文件不存在时给出中文提示，而不是静默失败。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from .config import AppConfig, ServerPreset
from .server import model_name_matches
from .vram import RuntimeProfile


class PresetError(ValueError):
    pass


def preset_model_name(preset: ServerPreset) -> str:
    return Path(preset.model_path).name if preset.model_path else ""


def preset_missing_files(preset: ServerPreset) -> list[str]:
    """预设里不存在的文件（model_path 是硬性要求，mmproj 缺失只影响视觉）。"""

    missing: list[str] = []
    if not preset.model_path:
        missing.append("model_path")
    elif not Path(preset.model_path).is_file():
        missing.append(preset.model_path)
    if preset.mmproj_path and not Path(preset.mmproj_path).is_file():
        missing.append(preset.mmproj_path)
    return missing


def preset_available(preset: ServerPreset) -> bool:
    return bool(preset.model_path) and Path(preset.model_path).is_file()


def find_preset(config: AppConfig, key: str | Path | None) -> ServerPreset | None:
    """按 id、显示名、模型路径或文件名查找预设（不区分大小写）。"""

    if key is None:
        return None
    text = str(key).strip()
    if not text:
        return None
    lowered = text.casefold()
    candidates = config.server.presets or []
    for preset in candidates:
        if lowered == preset.id.casefold():
            return preset
    for preset in candidates:
        if lowered in {
            preset.label.casefold(),
            preset_model_name(preset).casefold(),
        }:
            return preset
    for preset in candidates:
        if preset.model_path and model_name_matches(preset.model_path, text):
            return preset
    return None


def active_preset(config: AppConfig) -> ServerPreset | None:
    """当前配置对应的预设：先看 ``server.active_preset``，再按模型路径匹配。"""

    preset = find_preset(config, config.server.active_preset)
    if preset is not None:
        return preset
    for candidate in config.server.presets or []:
        if candidate.model_path and model_name_matches(
            candidate.model_path, config.server.model_path
        ):
            return candidate
    return None


def preset_view(config: AppConfig, preset: ServerPreset) -> dict[str, Any]:
    current = active_preset(config)
    # 预设声明要视觉、但没有配套 mmproj 时，实际只能纯文本运行。
    vision = bool(preset.vision and preset.mmproj_path)
    return {
        "id": preset.id,
        "label": preset.display_name,
        "model": preset_model_name(preset),
        "model_path": preset.model_path,
        "mmproj": Path(preset.mmproj_path).name if preset.mmproj_path else "",
        "mmproj_path": preset.mmproj_path,
        "vision": vision,
        "vision_requested": bool(preset.vision),
        "context_tokens": int(preset.context_tokens or 0),
        "available": preset_available(preset),
        "missing": preset_missing_files(preset),
        "active": current is not None and current.id == preset.id,
    }


def list_presets(config: AppConfig) -> list[dict[str, Any]]:
    return [preset_view(config, preset) for preset in config.server.presets or []]


def preset_config_values(
    preset: ServerPreset,
    existing_mmproj: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """把预设展开成可以合并进 ``ai_config.json`` 的键值。"""

    if not preset.model_path:
        raise PresetError(f"预设「{preset.display_name}」没有配置 model_path。")
    model = Path(preset.model_path)
    if not model.is_file():
        raise PresetError(f"预设「{preset.display_name}」的模型文件不存在：{model}")

    server: dict[str, Any] = {
        "model_path": str(model),
        "active_preset": preset.id,
    }
    if preset.mmproj_path:
        mmproj = Path(preset.mmproj_path)
        if not mmproj.is_file():
            raise PresetError(
                f"预设「{preset.display_name}」的投影文件不存在：{mmproj}"
            )
        # 记住「这个模型用哪个 mmproj」，切回旧模型时不会带错投影文件。
        mapping = dict(existing_mmproj or {})
        mapping[str(model)] = str(mmproj)
        server["mmproj_path"] = str(mmproj)
        server["mmproj_by_model"] = mapping

    qwen: dict[str, Any] = {"model": model.name}
    qwen.update(preset.qwen or {})
    return {"server": server, "qwen": qwen}


def apply_preset_to_profile(
    profile: RuntimeProfile,
    preset: ServerPreset | None,
) -> RuntimeProfile:
    """用预设覆盖显存档位的上下文长度/GPU 层数。

    视觉以预设为准：预设声明视觉而且配了 mmproj 就打开（llama-server 在 CPU
    上也能带投影文件跑），预设没配 mmproj 就只能纯文本，和
    :func:`preset_view` 报给界面的结论保持一致。
    """

    if preset is None:
        return profile
    values: dict[str, Any] = {
        "vision_enabled": bool(preset.vision and preset.mmproj_path),
    }
    if preset.context_tokens > 0:
        values["context_tokens"] = int(preset.context_tokens)
    if preset.n_gpu_layers is not None:
        values["n_gpu_layers"] = int(preset.n_gpu_layers)
    return replace(profile, **values)
