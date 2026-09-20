from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def process_alive(process_id: int) -> bool:
    if process_id <= 0:
        return False
    try:
        os.kill(process_id, 0)
        return True
    except OSError:
        return False


def main() -> int:
    directory = Path(__file__).resolve().parent
    runtime = directory / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    pid_path = runtime / "chat.pid"
    if pid_path.is_file():
        try:
            if process_alive(int(pid_path.read_text(encoding="utf-8").strip())):
                return 0
        except ValueError:
            pass

    chat_script = directory / "run_ai_chat.py"
    creation_flags = 0
    if os.name == "nt":
        creation_flags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    process = subprocess.Popen(
        [sys.executable, str(chat_script)],
        cwd=directory,
        creationflags=creation_flags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    pid_path.write_text(str(process.pid), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
