"""Installed menu entry: the modern host owns model lifecycle, not a Tk popup."""
from __future__ import annotations


def main() -> int:
    from start_ai_chat import main as start_chat
    return start_chat()


if __name__ == '__main__':
    raise SystemExit(main())
