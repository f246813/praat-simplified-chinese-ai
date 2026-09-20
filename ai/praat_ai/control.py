from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .config import AppConfig, default_config_path, load_config
from .process import process_alive as _process_alive
from .server import (
    QwenServerError,
    QwenServerManager,
    endpoint_available,
    model_name_matches,
    running_model_info,
    server_model_state,
)
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


def _wait_for_process_exit(process_id: int, timeout: float = 20.0) -> bool:
    """True when the process really is gone (used before deleting the pid file)."""

    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _process_alive(process_id):
            return True
        time.sleep(0.2)
    return not _process_alive(process_id)


def _write_status(values: dict[str, Any]) -> dict[str, Any]:
    status_path().write_text(
        json.dumps(values, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return values


def configured_model_name(config: AppConfig | None = None) -> str:
    """The model file name written in the configuration."""

    config = config or load_config()
    return Path(config.server.model_path).name if config.server.model_path else ""


def collect_status(config_path: str | Path | None = None) -> dict[str, Any]:
    config = load_config(config_path)
    process_id = _read_pid()
    reachable = endpoint_available(config.qwen.base_url)
    running = reachable or _process_alive(process_id)
    gpu = detect_gpu()
    free_gb = round(gpu.free_mb / 1024.0, 2) if gpu else None
    total_gb = round(gpu.total_mb / 1024.0, 2) if gpu else None
    low_vram = free_gb is not None and free_gb < 2.0
    # 状态必须反映服务真正加载的模型，而不是配置里希望加载的模型。
    live_info = running_model_info(config.qwen.base_url) if reachable else {}
    live_model = str(live_info.get("id", ""))
    capabilities = [
        str(item).casefold() for item in (live_info.get("capabilities") or [])
    ]
    configured_model = configured_model_name(config)
    model = Path(live_model).name if live_model else configured_model
    status = {
        "success": True,
        "frontend_model": model,
        "frontend_model_configured": configured_model,
        "frontend_model_mismatch": bool(live_model)
        and not model_name_matches(live_model, config.server.model_path),
        "frontend_model_source": "server" if live_model else "config",
        "frontend_vision": any("multimodal" in item for item in capabilities),
        "frontend_running": running,
        "frontend_status": "running" if running else "stopped",
        "alignment_mode": config.alignment.backend,
        "vram_total_gb": total_gb,
        "vram_free_gb": free_gb,
        "vram_low": low_vram,
        "error": "",
    }
    return _write_status(status)


def _kill_process(process_id: int | None) -> None:
    if not process_id:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process_id), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.kill(process_id, signal.SIGTERM)
        except OSError:
            pass


def _parse_netstat_listening(text: str, port: int) -> list[int]:
    """Pick the PIDs that LISTEN on `port` from `netstat -ano` output."""

    suffix = f":{port}"
    process_ids: list[int] = []
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        if parts[0].upper() != "TCP" or "LISTENING" not in line.upper():
            continue
        if not parts[1].endswith(suffix):
            continue
        try:
            process_id = int(parts[-1])
        except ValueError:
            continue
        if process_id and process_id not in process_ids:
            process_ids.append(process_id)
    return process_ids


def _listening_pids(port: int) -> list[int]:
    if os.name != "nt":
        return []
    try:
        completed = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return _parse_netstat_listening(completed.stdout, port)


def _process_name(process_id: int) -> str:
    """Image name of a PID (empty when it cannot be read)."""

    if os.name != "nt":
        return ""
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {process_id}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in (completed.stdout or "").splitlines():
        first = line.split('","')[0].strip().strip('"').strip()
        if first and not first.upper().startswith("INFO"):
            return first
    return ""


def _stop_service_by_port(config: AppConfig) -> bool:
    """Fallback stop: find the configured llama-server by its listening port.

    只在 `runtime/qwen.pid` 丢失或失效时使用，而且必须同时满足「监听本项目的
    host/port」和「进程名等于配置里的 llama-server」两个条件才结束进程，
    避免误杀占用同一端口的其它程序。
    """

    expected = Path(config.server.llama_server).name.casefold()
    if not expected:
        return False
    stopped = False
    for process_id in _listening_pids(config.server.port):
        if _process_name(process_id).casefold() != expected:
            continue
        _kill_process(process_id)
        stopped = True
    if stopped:
        _remove_pid_file()
    return stopped


def _stop_running_service(config: AppConfig | None = None) -> bool:
    """Stop the llama-server started by this frontend; True if one was stopped."""

    stopped = False
    process_id = _read_pid()
    if process_id:
        _kill_process(process_id)
        # 只有确认进程真的退出才算停止成功，否则先保留 pid 文件。
        stopped = _wait_for_process_exit(process_id)
    # pid 文件丢失、过期或没杀掉时的兜底：按端口找出本项目的 llama-server
    if config is not None and _stop_service_by_port(config):
        stopped = True
    if stopped:
        _remove_pid_file()
    return stopped


def _remove_pid_file() -> None:
    try:
        pid_path().unlink()
    except FileNotFoundError:
        pass


def _wait_for_endpoint_gone(base_url: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not endpoint_available(base_url):
            return
        time.sleep(0.2)


def _launch_server(
    config: AppConfig,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    gpu = detect_gpu()
    profile = select_runtime_profile(
        gpu.free_mb if gpu else None,
        config.qwen.vision_when_requested,
    )
    config.server.auto_start = True
    manager = QwenServerManager(config, profile)
    manager.ensure_started()
    if manager.process and manager.process.pid:
        pid_path().write_text(str(manager.process.pid), encoding="utf-8")
    return collect_status(config_path)


def _restart_service(
    config: AppConfig,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Stop a service that loaded the wrong model and start it with the new config."""

    if not _stop_running_service(config):
        raise QwenServerError(
            f"{config.qwen.base_url} 上运行的服务不是本前端启动的，无法自动重启；"
            "请先手动停止该服务，再从菜单启动前端。"
        )
    _wait_for_endpoint_gone(config.qwen.base_url)
    return _launch_server(config, config_path)


def start_frontend(config_path: str | Path | None = None) -> dict[str, Any]:
    config = load_config(config_path)
    if endpoint_available(config.qwen.base_url):
        state = server_model_state(config.qwen.base_url, config.server.model_path)
        if state is not False:
            # True：端口上就是配置里的模型；None：读不到模型列表，保持原行为。
            return collect_status(config_path)
        # 端口上有服务，但加载的是别的模型：重启成配置里的模型。
        return _restart_service(config, config_path)
    return _launch_server(config, config_path)


def stop_frontend(config_path: str | Path | None = None) -> dict[str, Any]:
    _stop_running_service(load_config(config_path))
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
        # 记住「这个模型用哪个 mmproj」，这样切回旧模型时不会带错投影文件。
        mapping = dict(load_config(config_path).server.mmproj_by_model or {})
        mapping[str(model)] = str(mmproj)
        values["server"]["mmproj_by_model"] = mapping
    update_config(values, config_path)
    config = load_config(config_path)
    # 端口上已有服务却加载着旧模型时，必须重启，否则切换模型只是改了配置。
    if server_model_state(config.qwen.base_url, config.server.model_path) is False:
        return _restart_service(config, config_path)
    return collect_status(config_path)


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
    quiet = os.getenv("PRAAT_AI_CONTROL_QUIET") == "1"
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
        if not quiet:
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
