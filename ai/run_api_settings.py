"""独立进程里打开「API 配置」小窗（由 start_api_settings.py 拉起来）。"""

from __future__ import annotations

from praat_ai import control


if __name__ == "__main__":
    raise SystemExit(control.run_api_settings_dialog())
