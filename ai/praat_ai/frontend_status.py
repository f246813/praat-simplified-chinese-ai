"""Read-only native menu snapshot: saved preset, live desktop, current GPU memory."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import api_is_active, load_config
from .desktop_launch import runtime_directory, write_record
from .presets import active_preset
from .process import identities_match, process_identity
from .vram import detect_gpu


def vram_warning(free_mb: int | None) -> str:
    if free_mb is None:
        return 'unknown'
    # Adapted from gpustat's memory_free nonnegative clamp (MIT; see CREDITS).
    free_mb = max(free_mb, 0)
    if free_mb < 512:
        return 'red'
    if free_mb < 1536:
        return 'yellow'
    return 'green'


def desktop_running(runtime: Path) -> bool:
    try:
        record = json.loads((runtime / 'frontend-ready.json').read_text(encoding='utf8'))
        pid = int(record['pid'])
        return bool(pid > 0 and record.get('phase') == 'react-connected'
                    and identities_match(record.get('identity') or {}, process_identity(pid)))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def collect_menu_status(config_path=None, *, runtime=None, gpu=None) -> dict:
    config = load_config(config_path)
    runtime = Path(runtime or runtime_directory())
    if config.api.enabled:
        model = '云端API模式'
        configured = api_is_active(config)
    else:
        preset = active_preset(config)
        model = preset.display_name if preset else Path(config.server.model_path).name
        configured = bool(config.server.model_path and config.server.llama_server
                          and Path(config.server.model_path).is_file()
                          and Path(config.server.llama_server).is_file())
    running = desktop_running(runtime)
    # Cloud inference does not use this machine's GPU. Do not publish a colour
    # for the native menu to repaint when it is opened again.
    free_mb = gpu.free_mb if gpu is not None and not config.api.enabled else None
    return dict(success=True, frontend_model=model or '未配置',
                frontend_status=('未配置' if not configured else '运行中' if running else '已停止'),
                frontend_running=running, configured=configured, frontend_local=not config.api.enabled,
                vram_warning=vram_warning(free_mb),
                vram_free_gb=None if free_mb is None else max(free_mb, 0) / 1024)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        status = collect_menu_status(gpu=detect_gpu())
    except (OSError, ValueError, TypeError, AttributeError):
        status = dict(success=False, frontend_model='未配置', frontend_status='未配置',
                      frontend_running=False, vram_warning='unknown')
    write_record(args.output, status)
    return 0
