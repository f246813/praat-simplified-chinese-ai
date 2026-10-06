"""Compatibility menu entry: open the assistant Model page, never a Tk dialog."""
from __future__ import annotations
import os


def main(config_path=None) -> int:
    from start_ai_chat import main as start_chat
    previous = os.environ.get('PRAAT_AI_CONFIG_PATH')
    try:
        if config_path is not None:
            os.environ['PRAAT_AI_CONFIG_PATH'] = str(config_path)
        return start_chat(model_settings=True)
    finally:
        if config_path is not None:
            if previous is None:
                os.environ.pop('PRAAT_AI_CONFIG_PATH', None)
            else:
                os.environ['PRAAT_AI_CONFIG_PATH'] = previous


if __name__ == '__main__':
    raise SystemExit(main())
