from __future__ import annotations

import argparse

from praat_ai.tutor import run_from_praat


def main() -> int:
    parser = argparse.ArgumentParser(description="Praat local AI pronunciation tutor")
    parser.add_argument("--config", help="Path to ai_config.json")
    parser.add_argument("--request", help="Path to an analysis request JSON file")
    parser.add_argument("--text", help="Natural-language request for Qwen")
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="Do not open the interactive form when no request is supplied",
    )
    arguments = parser.parse_args()
    return run_from_praat(
        config_path=arguments.config,
        request_path=arguments.request,
        user_text=arguments.text,
        interactive=not arguments.no_gui,
    )


if __name__ == "__main__":
    raise SystemExit(main())
