from __future__ import annotations

import csv
import io
import subprocess
from dataclasses import asdict, dataclass


@dataclass(slots=True)
class GpuMemory:
    name: str
    total_mb: int
    free_mb: int
    driver_version: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class RuntimeProfile:
    name: str
    device: str
    context_tokens: int
    n_gpu_layers: int
    vision_enabled: bool
    allow_asr_concurrent: bool
    unload_after_sec: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def detect_gpu() -> GpuMemory | None:
    command = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.free,driver_version",
        "--format=csv,noheader",
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    first_line = completed.stdout.strip().splitlines()
    if not first_line:
        return None
    row = next(csv.reader(io.StringIO(first_line[0])), [])
    if len(row) < 4:
        return None

    def as_megabytes(value: str) -> int:
        digits = "".join(character for character in value if character.isdigit())
        return int(digits) if digits else 0

    return GpuMemory(
        name=row[0].strip(),
        total_mb=as_megabytes(row[1]),
        free_mb=as_megabytes(row[2]),
        driver_version=row[3].strip(),
    )


def select_runtime_profile(
    free_vram_mb: int | None,
    vision_requested: bool,
) -> RuntimeProfile:
    if free_vram_mb is None or free_vram_mb < 2048:
        return RuntimeProfile(
            name="cpu-text",
            device="cpu",
            context_tokens=4096,
            n_gpu_layers=0,
            vision_enabled=False,
            allow_asr_concurrent=True,
            unload_after_sec=0,
        )
    if free_vram_mb < 4096:
        return RuntimeProfile(
            name="gpu-text-4k",
            device="cuda",
            context_tokens=4096,
            n_gpu_layers=-1,
            vision_enabled=False,
            allow_asr_concurrent=False,
            unload_after_sec=120,
        )
    if free_vram_mb < 6144:
        return RuntimeProfile(
            name="gpu-text-8k",
            device="cuda",
            context_tokens=8192,
            n_gpu_layers=-1,
            vision_enabled=vision_requested,
            allow_asr_concurrent=False,
            unload_after_sec=180,
        )
    if free_vram_mb < 8192:
        return RuntimeProfile(
            name="gpu-vision-8k",
            device="cuda",
            context_tokens=8192,
            n_gpu_layers=-1,
            vision_enabled=vision_requested,
            allow_asr_concurrent=False,
            unload_after_sec=300,
        )
    return RuntimeProfile(
        name="gpu-vision-16k",
        device="cuda",
        context_tokens=16384,
        n_gpu_layers=-1,
        vision_enabled=vision_requested,
        allow_asr_concurrent=False,
        unload_after_sec=600,
    )
