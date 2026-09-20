from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from .config import AppConfig
from .vram import RuntimeProfile


class QwenServerError(RuntimeError):
    pass


def endpoint_available(base_url: str) -> bool:
    request = urllib.request.Request(f"{base_url.rstrip('/')}/models")
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError):
        return False


def _normalize_model_reference(value: str | Path) -> str:
    """Normalize a model path or name for comparison (Windows is case-insensitive)."""

    text = str(value or "").strip().strip('"')
    if not text:
        return ""
    return Path(text).as_posix().casefold()


def model_name_matches(running: str | Path, configured: str | Path) -> bool:
    """True if `running` refers to the same model file as `configured`."""

    running_norm = _normalize_model_reference(running)
    configured_norm = _normalize_model_reference(configured)
    if not running_norm or not configured_norm:
        return False
    if running_norm == configured_norm:
        return True
    # llama-server 也可能只报告文件名；这种情况按文件名判断。
    return Path(running_norm).name == Path(configured_norm).name


def _model_ids_from_payload(payload: object) -> list[str]:
    ids: list[str] = []

    def add(value: object) -> None:
        text = str(value or "").strip()
        if text and text not in ids:
            ids.append(text)

    if isinstance(payload, dict):
        for entry in payload.get("data") or []:
            if isinstance(entry, dict):
                add(entry.get("id"))
                add(entry.get("model"))
        for entry in payload.get("models") or []:
            if isinstance(entry, dict):
                add(entry.get("name"))
                add(entry.get("model"))
    return ids


def _fetch_models_payload(
    base_url: str,
    timeout: float = 2.0,
) -> object | None:
    request = urllib.request.Request(f"{base_url.rstrip('/')}/models")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError, UnicodeDecodeError):
        return None


def running_models(base_url: str, timeout: float = 2.0) -> list[str]:
    """Model ids reported by the running OpenAI-compatible server (empty if unreachable)."""

    payload = _fetch_models_payload(base_url, timeout)
    if payload is None:
        return []
    return _model_ids_from_payload(payload)


def running_model_info(base_url: str, timeout: float = 2.0) -> dict[str, object]:
    """What the running server reports about its model; {} when unreadable."""

    payload = _fetch_models_payload(base_url, timeout)
    if payload is None:
        return {}
    info: dict[str, object] = {}
    ids = _model_ids_from_payload(payload)
    if ids:
        info["id"] = ids[0]
    capabilities: list[str] = []
    if isinstance(payload, dict):
        entries = list(payload.get("data") or []) + list(payload.get("models") or [])
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for capability in entry.get("capabilities") or []:
                text = str(capability or "").strip()
                if text and text not in capabilities:
                    capabilities.append(text)
    if capabilities:
        info["capabilities"] = capabilities
    return info


def running_model(base_url: str, timeout: float = 2.0) -> str:
    """The model the running server actually loaded, or "" when unknown."""

    return str(running_model_info(base_url, timeout=timeout).get("id", ""))


def log_dir() -> Path:
    """Folder that holds the llama-server log."""

    path = Path(__file__).resolve().parents[1] / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def server_model_state(
    base_url: str,
    model_path: str | Path,
    timeout: float = 2.0,
) -> bool | None:
    """True/False when the server reports its models; None when that cannot be read."""

    ids = running_models(base_url, timeout=timeout)
    if not ids:
        return None
    return any(model_name_matches(item, model_path) for item in ids)


class QwenServerManager:
    def __init__(self, config: AppConfig, profile: RuntimeProfile):
        self.config = config
        self.profile = profile
        self.process: subprocess.Popen[bytes] | None = None
        self.log_handle = None
        self.vision_active = False
        self.last_warning = ""

    def ensure_started(self) -> bool:
        state = server_model_state(
            self.config.qwen.base_url,
            self.config.server.model_path,
        )
        if state is True:
            return False   # 已经在跑同一个模型
        if state is None and endpoint_available(self.config.qwen.base_url):
            return False   # 服务在跑但读不到模型列表：保持原行为，不擅自重启
        if state is False:
            raise QwenServerError(
                "The running Qwen server already serves a different model. "
                "Stop it first, or use the frontend menu so it can be restarted: "
                f"{self.config.server.model_path}"
            )
        if not self.config.server.auto_start:
            return False

        server = Path(self.config.server.llama_server)
        model = Path(self.config.server.model_path)
        if not server.is_file():
            raise QwenServerError(f"llama-server not found: {server}")
        if not model.is_file():
            raise QwenServerError(f"Qwen model not found: {model}")

        mmproj = self._vision_mmproj()

        attempts: list[tuple[bool, list[str]]] = []
        if mmproj is not None:
            attempts.append((True, self._build_command(server, model, mmproj)))
        attempts.append((False, self._build_command(server, model, None)))

        last_error = ""
        for use_vision, command in attempts:
            try:
                self._spawn(command)
                self._wait_for_endpoint()
            except QwenServerError as error:
                last_error = str(error)
                self.stop()
                continue
            self.vision_active = use_vision
            if mmproj is not None and not use_vision:
                # 视觉投影文件与所选模型不匹配时，纯文本启动仍然可用。
                self.last_warning = (
                    "视觉投影文件（mmproj）与所选模型不匹配，已按纯文本模式启动："
                    f"{self.config.server.mmproj_path}"
                )
                self._log_warning()
            return True
        raise QwenServerError(last_error or "Qwen server exited while starting.")

    def _vision_mmproj(self) -> Path | None:
        """Pick the projector that belongs to the configured model.

        `server.mmproj_by_model` 按模型路径（或文件名）给出各自的投影文件；
        没有条目时退回 `server.mmproj_path`。
        """

        if not self.profile.vision_enabled:
            return None
        configured = self.config.server.mmproj_path
        for key, value in (self.config.server.mmproj_by_model or {}).items():
            if value and model_name_matches(key, self.config.server.model_path):
                configured = str(value)
                break
        if not configured:
            raise QwenServerError(
                "Vision was requested, but the mmproj model file is missing."
            )
        mmproj = Path(configured)
        if not mmproj.is_file():
            raise QwenServerError(
                "Vision was requested, but the mmproj model file is missing: "
                f"{mmproj}"
            )
        return mmproj

    def _build_command(
        self,
        server: Path,
        model: Path,
        mmproj: Path | None,
    ) -> list[str]:
        command = [
            str(server),
            "-m",
            str(model),
            "--host",
            self.config.server.host,
            "--port",
            str(self.config.server.port),
            "--ctx-size",
            str(self.profile.context_tokens),
            "--n-gpu-layers",
            str(self.profile.n_gpu_layers),
            "--threads",
            str(self.config.server.threads),
            "--parallel",
            str(self.config.server.parallel),
            "--no-webui",
        ]
        if mmproj is not None:
            command.extend(["--mmproj", str(mmproj)])
        return command

    def _spawn(self, command: list[str]) -> None:
        self.log_handle = (log_dir() / "qwen-server.log").open("ab")
        self.process = subprocess.Popen(
            command,
            stdout=self.log_handle,
            stderr=subprocess.STDOUT,
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            ),
        )

    def _wait_for_endpoint(self) -> None:
        deadline = time.time() + 60
        while time.time() < deadline:
            if self.process is None:
                raise QwenServerError("Qwen server is not running.")
            if self.process.poll() is not None:
                raise QwenServerError("Qwen server exited while starting.")
            if endpoint_available(self.config.qwen.base_url):
                return
            time.sleep(0.5)
        self.stop()
        raise QwenServerError("Timed out waiting for the Qwen server.")

    def _log_warning(self) -> None:
        try:
            with (log_dir() / "qwen-server.log").open(
                "a",
                encoding="utf-8",
                errors="replace",
            ) as handle:
                handle.write(f"\n=== PRAAT-AI: {self.last_warning} ===\n")
        except OSError:
            pass

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
        if self.log_handle:
            self.log_handle.close()
            self.log_handle = None
