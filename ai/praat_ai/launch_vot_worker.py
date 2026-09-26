from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    request = os.environ.get("PRAAT_AI_VOT_REQUEST", "").strip()
    project = Path(os.environ.get("PRAAT_AI_PROJECT_DIR", Path(__file__).resolve().parents[1]))
    if not request:
        raise SystemExit("PRAAT_AI_VOT_REQUEST is required")
    command = [sys.executable, "-m", "praat_ai.vot_editor_worker", request]
    options: dict[str, object] = {
        "cwd": str(project),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
        "env": os.environ.copy(),
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    subprocess.Popen(command, **options)  # type: ignore[arg-type]
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
