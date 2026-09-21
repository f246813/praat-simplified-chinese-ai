from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

#: 进度回调：(0–1 的进度, 中文说明)。Praat 菜单那一路不用它——控制脚本把进度打到
#: 标准输出（`PRAAT_PROGRESS\t...`），由 Praat 变成带进度条的小窗口；对话窗口那一路
#: 自己弹一个迷你进度条，走这个回调。
ProgressSink = Callable[[float, str], None]

from .config import (
    AppConfig,
    api_is_active,
    default_config_path,
    load_config,
)
from .process import process_alive as _process_alive
from .presets import (
    PresetError,
    active_preset,
    apply_preset_to_profile,
    find_preset,
    list_presets,
    preset_config_values,
)
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
    gpu = detect_gpu()
    free_gb = round(gpu.free_mb / 1024.0, 2) if gpu else None
    total_gb = round(gpu.total_mb / 1024.0, 2) if gpu else None
    low_vram = free_gb is not None and free_gb < 2.0

    if api_is_active(config):
        # API 模式（云端大模型）：不去探本地端口——那是远程地址，探它没意义，
        # 也会让菜单里的状态变成「服务未响应」。key 一个字都不进状态文件。
        status = {
            "success": True,
            "api_enabled": True,
            "api_label": config.api.label,
            "api_model": config.api.model,
            "api_verified_at": config.api.verified_at,
            "frontend_model": config.api.model,
            "frontend_model_configured": config.api.model,
            "frontend_model_mismatch": False,
            "frontend_model_source": "api",
            "frontend_vision": False,
            "frontend_preset": "",
            "frontend_preset_label": "",
            "frontend_preset_matches_live": False,
            "frontend_preset_configured": config.server.active_preset,
            "presets": list_presets(config),
            "frontend_running": True,
            "frontend_status": "running (API)",
            "alignment_mode": config.alignment.backend,
            "vram_total_gb": total_gb,
            "vram_free_gb": free_gb,
            "vram_low": low_vram,
            "error": "",
        }
        return _write_status(status)

    process_id = _read_pid()
    reachable = endpoint_available(config.qwen.base_url)
    running = reachable or _process_alive(process_id)
    # 状态必须反映服务真正加载的模型，而不是配置里希望加载的模型。
    live_info = running_model_info(config.qwen.base_url) if reachable else {}
    live_model = str(live_info.get("id", ""))
    capabilities = [
        str(item).casefold() for item in (live_info.get("capabilities") or [])
    ]
    configured_model = configured_model_name(config)
    model = Path(live_model).name if live_model else configured_model
    current_preset = active_preset(config)
    preset_summaries = list_presets(config)
    if current_preset is not None and live_model:
        # 预设里写的模型和端口上实际加载的模型是否一致，界面要能区分这两种情况。
        preset_matches_live = model_name_matches(
            live_model, current_preset.model_path
        )
    else:
        preset_matches_live = False
    status = {
        "success": True,
        "frontend_model": model,
        "frontend_model_configured": configured_model,
        "frontend_model_mismatch": bool(live_model)
        and not model_name_matches(live_model, config.server.model_path),
        "frontend_model_source": "server" if live_model else "config",
        "frontend_vision": any("multimodal" in item for item in capabilities),
        "frontend_preset": current_preset.id if current_preset else "",
        "frontend_preset_label": (
            current_preset.display_name if current_preset else ""
        ),
        "frontend_preset_matches_live": preset_matches_live,
        "frontend_preset_configured": config.server.active_preset,
        "presets": preset_summaries,
        "frontend_running": running,
        "frontend_status": "running" if running else "stopped",
        "api_enabled": False,
        "api_label": config.api.label,
        "api_model": config.api.model,
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
    *,
    progress: ProgressSink | None = None,
) -> dict[str, Any]:
    _progress(0.05, "检查显卡与运行参数…", progress)
    gpu = detect_gpu()
    preset = active_preset(config)
    vision_requested = (
        preset.vision if preset is not None else config.qwen.vision_when_requested
    )
    profile = select_runtime_profile(
        gpu.free_mb if gpu else None,
        vision_requested,
    )
    profile = apply_preset_to_profile(profile, preset)
    config.server.auto_start = True
    _progress(0.08, "准备启动本地模型服务…", progress)
    # manager 的进度要同时「打印给 Praat」和「回调给对话窗口」：加载一个模型实测要
    # 8 秒左右，这段时间里进度条必须一直在涨。（2026-09-21 用户报的「窗口打开时没有
    # 进度条、随后闪一下就没了」有一半原因在这里：以前只回传给了对话窗口，
    # Praat 那条路一个中间进度都没有。）
    manager = QwenServerManager(
        config,
        profile,
        progress=lambda fraction, message: _progress(fraction, message, progress),
    )
    manager.ensure_started()
    if manager.process and manager.process.pid:
        pid_path().write_text(str(manager.process.pid), encoding="utf-8")
    _progress(1.0, "模型服务已就绪。", progress)
    return collect_status(config_path)


def _restart_service(
    config: AppConfig,
    config_path: str | Path | None = None,
    *,
    progress: ProgressSink | None = None,
) -> dict[str, Any]:
    """Stop a service that loaded the wrong model and start it with the new config."""

    _progress(0.05, "停止旧的模型服务…", progress)
    if not _stop_running_service(config):
        raise QwenServerError(
            f"{config.qwen.base_url} 上运行的服务不是本前端启动的，无法自动重启；"
            "请先手动停止该服务，再从菜单启动前端。"
        )
    _progress(0.15, "等待端口释放…", progress)
    _wait_for_endpoint_gone(config.qwen.base_url)
    return _launch_server(config, config_path, progress=progress)


def start_frontend(
    config_path: str | Path | None = None,
    *,
    progress: ProgressSink | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    if api_is_active(config):
        # API 模式不需要本地服务；状态里会说明用的是哪个云端模型。
        return collect_status(config_path)
    if endpoint_available(config.qwen.base_url):
        state = server_model_state(config.qwen.base_url, config.server.model_path)
        if state is not False:
            # True：端口上就是配置里的模型；None：读不到模型列表，保持原行为。
            return collect_status(config_path)
        # 端口上有服务，但加载的是别的模型：重启成配置里的模型。
        return _restart_service(config, config_path, progress=progress)
    return _launch_server(config, config_path, progress=progress)


def stop_frontend(
    config_path: str | Path | None = None,
    *,
    progress: ProgressSink | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    if api_is_active(config):
        # 云端模型没有「本地服务」可停；别去动本机端口上的东西。
        return collect_status(config_path)
    _progress(0.1, "正在停止模型服务…", progress)
    _stop_running_service(config)
    _progress(0.6, "等待端口释放…", progress)
    _wait_for_endpoint_gone(config.qwen.base_url)
    _progress(1.0, "已停止。", progress)
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
    *,
    progress: ProgressSink | None = None,
) -> dict[str, Any]:
    model = Path(model_path)
    if not model.is_file():
        raise FileNotFoundError(f"Model file not found: {model}")
    known = find_preset(load_config(config_path), str(model))
    values: dict[str, Any] = {
        "server": {
            "model_path": str(model),
            # 手动选中的模型如果命中预设，就同步预设状态，避免状态栏对不上。
            "active_preset": known.id if known else "",
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
    if api_is_active(config):
        # 现在用的是云端模型：只改本地配置（取消 API 之后生效），不要重启本地服务。
        _progress(1.0, "已记住本地模型路径（当前是 API 模式）。", progress)
        status = collect_status(config_path)
        status["api_note"] = (
            "API 模式已启用，这个本地模型路径要等取消 API 模式后才会用上。"
        )
        return status
    # 端口上已有服务却加载着旧模型时，必须重启，否则切换模型只是改了配置。
    if server_model_state(config.qwen.base_url, config.server.model_path) is False:
        return _restart_service(config, config_path, progress=progress)
    return collect_status(config_path)


def apply_preset(
    preset_key: str,
    config_path: str | Path | None = None,
    *,
    progress: ProgressSink | None = None,
) -> dict[str, Any]:
    """切换到配置里声明的模型预设（必要时真正重启 llama-server）。"""

    config = load_config(config_path)
    presets = config.server.presets or []
    if not presets:
        raise PresetError(
            "ai_config.json 里还没有配置模型预设（server.presets）。"
        )
    preset = find_preset(config, preset_key)
    if preset is None:
        available = "、".join(
            f"{item.id}（{item.display_name}）" for item in presets
        )
        raise PresetError(f"没有找到预设「{preset_key}」。可用预设：{available}")
    values = preset_config_values(preset, config.server.mmproj_by_model)
    if api_is_active(config):
        # 「应用本地预设」= 回到本地模型：顺手把 API 模式关掉，否则改了也不生效。
        values.setdefault("api", {})["enabled"] = False
        _progress(0.02, "切回本地模型（关闭 API 模式）…", progress)
    update_config(values, config_path)
    config = load_config(config_path)
    # 端口上已有服务却加载着别的模型时，必须重启，否则切换预设只是改配置。
    if server_model_state(config.qwen.base_url, config.server.model_path) is False:
        return _restart_service(config, config_path, progress=progress)
    return collect_status(config_path)


def _progress(
    fraction: float,
    message: str,
    sink: ProgressSink | None = None,
) -> None:
    """报告一次进度：写给 Praat 的标准输出 + 回调给对话窗口（有的话）。"""

    print(f"PRAAT_PROGRESS\t{fraction:.4f}\t{message}", flush=True)
    if sink is not None:
        sink(float(fraction), message)


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


def run_api_settings_dialog(config_path: str | Path | None = None) -> int:
    """打开「API 配置」小窗口（Praat 菜单那一路）。

    单独抽一层是为了能在测试里替换掉它——真开窗口会阻塞到用户点关闭。
    """

    from . import api_settings

    return api_settings.run_standalone(config_path)


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
    if normalized in {"set-preset", "preset"}:
        return apply_preset(value, config_path)
    if normalized == "presets":
        config = load_config(config_path)
        return {
            "success": True,
            "presets": list_presets(config),
            "active_preset": (
                active_preset(config).id if active_preset(config) else ""
            ),
        }
    if normalized == "set-mmproj":
        return set_frontend_model(
            load_config(config_path).server.model_path,
            value,
            config_path,
        )
    if normalized == "set-alignment-mode":
        return set_alignment_mode(value, config_path)
    if normalized in {"api-config", "api-settings"}:
        return {"success": run_api_settings_dialog(config_path) == 0}
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
