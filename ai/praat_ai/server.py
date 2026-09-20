from __future__ import annotations

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


class QwenServerManager:
    def __init__(self, config: AppConfig, profile: RuntimeProfile):
        self.config = config
        self.profile = profile
        self.process: subprocess.Popen[bytes] | None = None
        self.log_handle = None

    def ensure_started(self) -> bool:
        if endpoint_available(self.config.qwen.base_url):
            return False
        if not self.config.server.auto_start:
            return False

        server = Path(self.config.server.llama_server)
        model = Path(self.config.server.model_path)
        if not server.is_file():
            raise QwenServerError(f"llama-server not found: {server}")
        if not model.is_file():
            raise QwenServerError(f"Qwen model not found: {model}")

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
        if self.profile.vision_enabled:
            mmproj = Path(self.config.server.mmproj_path)
            if not mmproj.is_file():
                raise QwenServerError(
                    "Vision was requested, but the mmproj model file is missing."
                )
            command.extend(["--mmproj", str(mmproj)])

        log_dir = Path(__file__).resolve().parents[1] / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_handle = (log_dir / "qwen-server.log").open("ab")
        self.process = subprocess.Popen(
            command,
            stdout=self.log_handle,
            stderr=subprocess.STDOUT,
            creationflags=(
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            ),
        )

        deadline = time.time() + 60
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise QwenServerError("Qwen server exited while starting.")
            if endpoint_available(self.config.qwen.base_url):
                return True
            time.sleep(0.5)
        self.stop()
        raise QwenServerError("Timed out waiting for the Qwen server.")

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
