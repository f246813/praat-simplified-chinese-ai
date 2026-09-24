"""Serialize local model transitions across the chat and menu processes."""

from __future__ import annotations

import errno
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def service_transition_lock(path: Path, timeout: float = 120.0) -> Iterator[None]:
    """Hold a one-byte file lock until a model start/stop decision completes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()

        if os.name == "nt":
            import msvcrt

            def lock() -> None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

            def unlock() -> None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def lock() -> None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            def unlock() -> None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

        deadline = time.monotonic() + timeout
        while True:
            try:
                lock()
                break
            except OSError as error:
                busy = error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}
                busy = busy or getattr(error, "winerror", None) in {32, 33}
                if not busy:
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timed out waiting for the local model transition") from error
                time.sleep(0.05)
        try:
            yield
        finally:
            unlock()
