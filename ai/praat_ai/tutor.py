from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .bridge import PraatBridge, object_payload
from .config import AppConfig, load_config
from .models import AnalysisRequest, AnalysisResult, PhoneSpec
from .pronunciation import analyze_pronunciation
from .qwen import QwenClient, QwenError
from .report import write_json, write_overlay_png, write_textgrid
from .server import QwenServerError, QwenServerManager
from .ui import show_tutor_form
from .vram import detect_gpu, select_runtime_profile


@dataclass(slots=True)
class TutorOutputs:
    json_path: Path
    textgrid_path: Path
    overlay_path: Path | None
    result: AnalysisResult


def request_from_dict(payload: dict[str, Any]) -> AnalysisRequest:
    phonemes = [
        PhoneSpec(
            ipa=str(item["ipa"]),
            label=str(item.get("label", "")),
            reference_start=float(item.get("reference_start", 0.0)),
            reference_end=float(item.get("reference_end", 0.0)),
            learner_start=(
                float(item["learner_start"])
                if item.get("learner_start") is not None
                else None
            ),
            learner_end=(
                float(item["learner_end"])
                if item.get("learner_end") is not None
                else None
            ),
        )
        for item in payload.get("phonemes", [])
    ]
    return AnalysisRequest(
        reference_object=payload["reference_object"],
        learner_object=payload["learner_object"],
        language=str(payload.get("language", "")),
        phonemes=phonemes,
        transcript=str(payload.get("transcript", "")),
        error_threshold=float(payload.get("error_threshold", 1.25)),
        minimum_error_duration_sec=float(
            payload.get("minimum_error_duration_sec", 0.04)
        ),
        maximum_errors_per_phone=int(payload.get("maximum_errors_per_phone", 3)),
        qwen_explain=bool(payload.get("qwen_explain", True)),
        qwen_vision=bool(payload.get("qwen_vision", False)),
        output_prefix=str(payload.get("output_prefix", "ai")),
    )


def _resolve_request(
    bridge: PraatBridge,
    config: AppConfig,
    *,
    request_path: str | Path | None,
    user_text: str | None,
) -> tuple[AnalysisRequest, dict[str, Any]]:
    if request_path:
        payload = json.loads(Path(request_path).read_text(encoding="utf-8"))
    elif user_text:
        selected = bridge.selected_objects()
        client = QwenClient(config.qwen)
        if not client.available():
            raise QwenError(
                "Qwen is not running. Supply a request JSON file or start the local model."
            )
        payload = client.parse_analysis_request(user_text, object_payload(selected))
    else:
        raise ValueError("A request JSON path or user text is required.")

    request = request_from_dict(payload)
    reference = bridge.resolve_sound(request.reference_object)
    learner = bridge.resolve_sound(request.learner_object)
    request.reference_object = str(reference.file)
    request.learner_object = str(learner.file)
    payload["resolved_reference"] = reference.to_dict()
    payload["resolved_learner"] = learner.to_dict()
    return request, payload


def run_tutor(
    *,
    config_path: str | Path | None = None,
    request_path: str | Path | None = None,
    user_text: str | None = None,
    request: AnalysisRequest | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> TutorOutputs:
    def report(fraction: float, message: str) -> None:
        if progress:
            progress(fraction, message)

    report(0.08, "读取请求和 Praat 选中对象")
    config = load_config(config_path)
    bridge = PraatBridge.from_praat()
    if request is None:
        request, request_payload = _resolve_request(
            bridge,
            config,
            request_path=request_path,
            user_text=user_text,
        )
    else:
        reference = bridge.resolve_sound(request.reference_object)
        learner = bridge.resolve_sound(request.learner_object)
        request.reference_object = str(reference.file)
        request.learner_object = str(learner.file)
        request_payload = request.to_dict()
        request_payload["resolved_reference"] = reference.to_dict()
        request_payload["resolved_learner"] = learner.to_dict()

    gpu = detect_gpu()
    profile = select_runtime_profile(
        gpu.free_mb if gpu else None,
        request.qwen_vision and config.qwen.vision_when_requested,
    )
    config.qwen.max_context_tokens = profile.context_tokens

    server = QwenServerManager(config, profile)
    server_started = False
    server_error = ""
    try:
        if request.qwen_explain or request.qwen_vision:
            try:
                report(0.18, "启动前端模型")
                server_started = server.ensure_started()
            except QwenServerError as error:
                server_error = str(error)

        report(0.32, "音素对齐与声学特征提取")
        result = analyze_pronunciation(request, config.alignment)
        report(0.68, "生成偏差评分")
        output_dir = bridge.output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        prefix = request.output_prefix
        json_path = output_dir / f"{prefix}_report.json"
        textgrid_path = output_dir / f"{prefix}_errors.TextGrid"
        overlay_path = output_dir / f"{prefix}_overlay.png"

        if request.qwen_explain:
            client = QwenClient(config.qwen)
            if client.available():
                try:
                    report(0.76, "生成前端解释")
                    result.explanation = client.explain_errors(
                        request_payload,
                        result.to_dict(),
                    )
                except QwenError as error:
                    result.explanation = f"Qwen 解释不可用：{error}"
            elif server_error:
                result.explanation = f"Qwen 解释不可用：{server_error}"

        report(0.86, "生成 TextGrid、JSON 和叠加图")
        write_textgrid(result, textgrid_path)
        write_json(result, json_path)
        rendered = write_overlay_png(result, overlay_path)

        if request.qwen_vision and rendered:
            client = QwenClient(config.qwen)
            if client.available():
                try:
                    report(0.94, "生成视觉解释")
                    vision_explanation = client.vision_explain(
                        overlay_path,
                        request_payload,
                        result.to_dict(),
                    )
                    if vision_explanation:
                        result.explanation = (
                            result.explanation + "\n\n图表解释：\n" + vision_explanation
                        ).strip()
                        write_json(result, json_path)
                except QwenError:
                    pass

        report(1.0, "分析完成")
        return TutorOutputs(
            json_path=json_path,
            textgrid_path=textgrid_path,
            overlay_path=overlay_path if rendered else None,
            result=result,
        )
    finally:
        if server_started and profile.unload_after_sec == 0:
            server.stop()


def run_from_praat(
    *,
    config_path: str | Path | None = None,
    request_path: str | Path | None = None,
    user_text: str | None = None,
    interactive: bool = True,
) -> int:
    request_path = request_path or os.getenv("PRAAT_AI_REQUEST_JSON")
    user_text = user_text or os.getenv("PRAAT_AI_USER_TEXT")
    request = None
    if not request_path and not user_text and interactive:
        bridge = PraatBridge.from_praat()
        sounds = [
            item
            for item in bridge.selected_objects()
            if item.class_name == "Sound"
        ]
        values = show_tutor_form(sounds)
        request = values.request
        if request is None:
            return 0
    outputs = run_tutor(
        config_path=config_path,
        request_path=request_path,
        user_text=user_text,
        request=request,
    )
    print(f"AI 纠音完成，发现 {len(outputs.result.errors)} 个偏差。")
    print(
        f"对齐：{outputs.result.alignment_source or 'unknown'}，"
        f"置信度 {outputs.result.alignment_confidence:.2f}"
    )
    print(f"报告：{outputs.json_path}")
    print(f"标注：{outputs.textgrid_path}")
    if outputs.overlay_path:
        print(f"叠加图：{outputs.overlay_path}")
    if outputs.result.explanation:
        print("")
        print(outputs.result.explanation)
    return 0
