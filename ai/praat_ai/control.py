from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import AppConfig, default_config_path, load_config
from .server import QwenServerManager, endpoint_available
from .tutor import run_tutor
from .vram import detect_gpu, select_runtime_profile


def runtime_dir() -> Path:
    path = Path(__file__).resolve().parents[1] / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def status_path() -> Path:
    return runtime_dir() / "status.json"


def pid_path() -> Path:
    return runtime_dir() / "qwen.pid"


def _read_pid() -> int | None:
    path = pid_path()
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def _process_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _write_status(values: dict[str, Any]) -> dict[str, Any]:
    status_path().write_text(
        json.dumps(values, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return values


def collect_status(config_path: str | Path | None = None) -> dict[str, Any]:
    config = load_config(config_path)
    process_id = _read_pid()
    running = endpoint_available(config.qwen.base_url) or _process_alive(process_id)
    gpu = detect_gpu()
    free_gb = round(gpu.free_mb / 1024.0, 2) if gpu else None
    total_gb = round(gpu.total_mb / 1024.0, 2) if gpu else None
    low_vram = free_gb is not None and free_gb < 2.0
    model = Path(config.server.model_path).name if config.server.model_path else ""
    status = {
        "success": True,
        "frontend_model": model,
        "frontend_running": running,
        "frontend_status": "running" if running else "stopped",
        "alignment_mode": config.alignment.backend,
        "vram_total_gb": total_gb,
        "vram_free_gb": free_gb,
        "vram_low": low_vram,
        "error": "",
    }
    return _write_status(status)


def start_frontend(config_path: str | Path | None = None) -> dict[str, Any]:
    config = load_config(config_path)
    if endpoint_available(config.qwen.base_url):
        return collect_status(config_path)
    profile = select_runtime_profile(
        (detect_gpu().free_mb if detect_gpu() else None),
        config.qwen.vision_when_requested,
    )
    config.server.auto_start = True
    manager = QwenServerManager(config, profile)
    manager.ensure_started()
    if manager.process and manager.process.pid:
        pid_path().write_text(str(manager.process.pid), encoding="utf-8")
    return collect_status(config_path)


def stop_frontend(config_path: str | Path | None = None) -> dict[str, Any]:
    process_id = _read_pid()
    if process_id:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process_id), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            os.kill(process_id, signal.SIGTERM)
    try:
        pid_path().unlink()
    except FileNotFoundError:
        pass
    return collect_status(config_path)


def update_config(
    values: dict[str, Any],
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    path = Path(config_path) if config_path else default_config_path()
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = load_config(config_path).to_dict()

    for section, section_values in values.items():
        target = payload.setdefault(section, {})
        target.update(section_values)

    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return collect_status(path)


def set_alignment_mode(
    mode: str,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    normalized = mode.lower()
    if normalized not in {"auto", "mfa", "wav2vec2", "ctc"}:
        raise ValueError(f"Unknown alignment mode: {mode}")
    if normalized == "ctc":
        normalized = "wav2vec2"
    return update_config(
        {"alignment": {"backend": normalized}},
        config_path,
    )


def set_frontend_model(
    model_path: str,
    mmproj_path: str = "",
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    model = Path(model_path)
    if not model.is_file():
        raise FileNotFoundError(f"Model file not found: {model}")
    values: dict[str, Any] = {
        "server": {
            "model_path": str(model),
        },
        "qwen": {
            "model": model.name,
        },
    }
    if mmproj_path:
        mmproj = Path(mmproj_path)
        if not mmproj.is_file():
            raise FileNotFoundError(f"mmproj file not found: {mmproj}")
        values["server"]["mmproj_path"] = str(mmproj)
    return update_config(values, config_path)


def _progress(fraction: float, message: str) -> None:
    print(f"PRAAT_PROGRESS\t{fraction:.4f}\t{message}", flush=True)


def run_analysis(config_path: str | Path | None = None) -> dict[str, Any]:
    request_path = os.getenv("PRAAT_AI_REQUEST_JSON")
    if not request_path:
        candidate = runtime_dir() / "pending_request.json"
        request_path = str(candidate) if candidate.is_file() else None
    if not request_path:
        raise FileNotFoundError("No AI analysis request file was found.")

    _progress(0.05, "读取请求和 Praat 选中对象")
    outputs = run_tutor(
        config_path=config_path,
        request_path=request_path,
        interactive=False,
        progress=_progress,
    )
    return {
        "success": True,
        "report": str(outputs.json_path),
        "textgrid": str(outputs.textgrid_path),
        "overlay": str(outputs.overlay_path) if outputs.overlay_path else "",
        "error_count": len(outputs.result.errors),
    }


def execute_command(
    command: str,
    value: str = "",
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    normalized = command.lower().strip()
    if normalized == "status":
        return collect_status(config_path)
    if normalized == "start":
        return start_frontend(config_path)
    if normalized == "stop":
        return stop_frontend(config_path)
    if normalized == "set-model":
        return set_frontend_model(value, config_path=config_path)
    if normalized == "set-mmproj":
        return set_frontend_model(
            load_config(config_path).server.model_path,
            value,
            config_path,
        )
    if normalized == "set-alignment-mode":
        return set_alignment_mode(value, config_path)
    if normalized == "run":
        return run_analysis(config_path)
    raise ValueError(f"Unknown control command: {command}")


def main(arguments: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    command = (
        arguments[0]
        if arguments
        else os.getenv("PRAAT_AI_CONTROL_COMMAND", "status")
    )
    value = (
        arguments[1]
        if len(arguments) > 1
        else os.getenv("PRAAT_AI_CONTROL_VALUE", "")
    )
    config_path = os.getenv("PRAAT_AI_CONFIG_PATH") or None
    try:
        result = execute_command(command, value, config_path)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as error:
        result = {
            "success": False,
            "error": str(error),
        }
        _write_status(result)
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        return 1
