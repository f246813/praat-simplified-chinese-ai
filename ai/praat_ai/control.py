from __future__ import annotations

import json
import os
import sys
import tempfile
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
from .process import (
    identities_match,
    process_alive as _process_alive,
    process_identity,
    terminate_process_if_identity_matches,
)
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


def _read_pid_record() -> dict[str, Any] | None:
    """Legacy integer PID files cannot prove ownership and are not killable."""

    try:
        raw = json.loads(pid_path().read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        process_id = raw.get("pid")
        executable = raw.get("executable")
        started = raw.get("started")
    except (OSError, ValueError, TypeError, KeyError):
        return None
    if (
        not isinstance(process_id, int)
        or isinstance(process_id, bool)
        or process_id <= 0
        or not isinstance(executable, str)
        or not isinstance(started, str)
    ):
        return None
    if not executable or not started:
        return None
    return {"pid": process_id, "executable": executable, "started": started}


def _write_pid_record(process_id: int) -> None:
    identity = process_identity(process_id)
    if not identity:
        raise QwenServerError("无法核实本机模型服务的进程身份，已取消启动。")
    target = pid_path()
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f"{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump({"pid": process_id, **identity}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


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


def local_base_url(config: AppConfig | None = None) -> str:
    """本机 llama-server 的地址（从 ``server.host/port`` 拼）。

    不能拿 ``config.qwen.base_url`` 代替：API 模式下 `apply_api_to_qwen` 会把它换成
    **云端**地址，拿它去等本机端口释放就会去请求云端（实测会白等 20 秒 + 打网络）。
    """

    config = config or load_config()
    host = config.server.host or "127.0.0.1"
    port = config.server.port or 8000
    return f"http://{host}:{port}/v1"


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

    pid_record = _read_pid_record()
    reachable = endpoint_available(config.qwen.base_url)
    recorded_process_running = bool(
        pid_record and _pid_is_owned_service(pid_record)
    )
    running = reachable or recorded_process_running
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


def _kill_process(process_id: int, identity: dict[str, str]) -> bool:
    return terminate_process_if_identity_matches(process_id, identity)


def _pid_is_owned_service(record: dict[str, Any]) -> bool:
    """A recorded process must still have the same executable and start time."""

    return identities_match(record, process_identity(record["pid"]))


def _stop_running_service() -> bool:
    """Stop the llama-server started by this frontend; True if one was stopped."""

    record = _read_pid_record()
    if record is None:
        # Missing or legacy PID records cannot distinguish this service from
        # another copy of llama-server on the same port.
        _remove_pid_file()
        return False
    process_id = record["pid"]
    if not _pid_is_owned_service(record):
        _remove_pid_file()
        return False
    if not _kill_process(process_id, record):
        return False
    stopped = _wait_for_process_exit(process_id)
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
    if endpoint_available(base_url):
        raise QwenServerError(f"本机模型服务仍在监听 {base_url}，未能确认停止。")


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
        try:
            _write_pid_record(manager.process.pid)
        except (OSError, QwenServerError):
            manager.stop()
            raise
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
    if not _stop_running_service():
        raise QwenServerError(
            f"{config.qwen.base_url} 上运行的服务不是本前端启动的，无法自动重启；"
            "请先手动停止该服务，再从菜单启动前端。"
        )
    _progress(0.15, "等待端口释放…", progress)
    _wait_for_endpoint_gone(config.qwen.base_url)
    return _launch_server(config, config_path, progress=progress)


def ensure_local_service(
    config: AppConfig,
    config_path: str | Path | None = None,
    *,
    progress: ProgressSink | None = None,
) -> dict[str, Any]:
    """保证配置里写的那个本地模型真的在服务上（回本地模型时都要走这里）。

    2026-09-22 的 WinError 10061 就是这条路缺了一段：从 API 切回本地（或者换一个
    本地预设）时，代码只在「端口上有服务、但加载的是别的模型」时重启，端口**空着**
    时什么都不做——配置已经切回本地、8000 端口却没人听，下一条消息直接「目标计算机
    积极拒绝」。这里的四种情况：

    - 端口空着 → 启动（``_launch_server``）；
    - 端口上是**别的**模型（``server_model_state() is False``）→ 重启；
    - 端口上就是配置里的模型（``True``）→ 什么都不做，只回报状态；
    - 读不到模型列表（``None``）→ 保持原语义，不擅自重启别人的服务。
    """

    if not endpoint_available(config.qwen.base_url):
        # 进度从 `_launch_server` 自己的 0.05 开始报（它一进门就报，用户不会干等）。
        return _launch_server(config, config_path, progress=progress)
    if server_model_state(config.qwen.base_url, config.server.model_path) is False:
        # 端口上有服务，但加载的是别的模型：重启成配置里的模型。
        return _restart_service(config, config_path, progress=progress)
    return collect_status(config_path)


def start_frontend(
    config_path: str | Path | None = None,
    *,
    progress: ProgressSink | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    if api_is_active(config):
        # API 模式不需要本地服务，但**一样要打进度**：Praat 的「正在处理中」小窗
        # 是子进程的标准输出里出现 `PRAAT_PROGRESS` 才弹的（见
        # sys/praat_python.cpp → Melder_progress），以前这里直接 return，菜单里点
        # 「启动前端」就完全没有反馈（2026-09-22 用户报的）。
        _progress(0.10, "当前是 API 模式，不需要本机模型服务。", progress)
        _progress(1.00, f"已就绪：{config.api.model}（云端）", progress)
        return collect_status(config_path)
    return ensure_local_service(config, config_path, progress=progress)


def stop_frontend(
    config_path: str | Path | None = None,
    *,
    progress: ProgressSink | None = None,
) -> dict[str, Any]:
    config = load_config(config_path)
    if api_is_active(config):
        # API 模式下本机服务是可停可留的：默认（`api.stop_local_service`）停掉腾
        # 显存，关掉这个选项就留着（切回本地模型时不用重新加载）。两条路都要发
        # 进度，不然菜单里点「停止前端」看着像没反应。
        if config.api.stop_local_service:
            _progress(0.10, "API 模式：按设置停掉本机模型服务（省显存）…", progress)
            stopped = _stop_running_service()
            base_url = local_base_url(config)
            if stopped:
                _progress(0.60, "等待端口释放…", progress)
                # API 模式下 config.qwen.base_url 是云端地址。
                _wait_for_endpoint_gone(base_url)
            elif endpoint_available(base_url):
                raise QwenServerError(
                    f"{base_url} 上的服务无法确认归属，未停止；请手动检查该端口。"
                )
            _progress(
                1.00,
                "本机模型服务已停。" if stopped else "本机模型服务本来就没在跑。",
                progress,
            )
        else:
            _progress(
                0.10,
                "API 模式：设置里取消了「顺手停掉本机模型服务」，本机服务保持不动。",
                progress,
            )
            _progress(1.00, "API 模式仍在运行；本机模型服务按设置保留。", progress)
        return collect_status(config_path)
    _progress(0.1, "正在停止模型服务…", progress)
    stopped = _stop_running_service()
    if stopped:
        _progress(0.6, "等待端口释放…", progress)
        _wait_for_endpoint_gone(config.qwen.base_url)
    elif endpoint_available(config.qwen.base_url):
        raise QwenServerError(
            f"{config.qwen.base_url} 上的服务无法确认归属，未停止；请手动检查该端口。"
        )
    _progress(1.0, "已停止。", progress)
    return collect_status(config_path)


def reconcile_api_transition(
    config_path: str | Path | None = None,
    *,
    progress: ProgressSink | None = None,
) -> dict[str, Any]:
    """Apply the saved API/local selection from either settings window."""

    from .service_lock import service_transition_lock

    with service_transition_lock(runtime_dir() / "service_transition.lock"):
        config = load_config(config_path)
        if api_is_active(config):
            return stop_frontend(config_path, progress=progress)
        return ensure_local_service(config, config_path, progress=progress)


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
    # 端口空着要启动、加载着旧模型要重启——都交给 ensure_local_service，
    # 否则「选了模型但端口没人听」会一直报 WinError 10061。
    return ensure_local_service(config, config_path, progress=progress)


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
    # 切回本地预设（或换一个预设）之后，服务必须真的跑起来：端口空着就启动，
    # 加载着别的模型就重启（见 ensure_local_service）。
    return ensure_local_service(config, config_path, progress=progress)


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
