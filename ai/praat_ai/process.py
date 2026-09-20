"""进程存活判断。

注意：本机（Windows + Python 3.12）上 ``os.kill (pid, 0)`` 对**任何** PID 都
抛 ``OSError (errno=22, winerror=87)``，所以它不能用来判断进程是否存在。
下面用 ``OpenProcess`` + ``GetExitCodeProcess``（必要时退回 ``tasklist``）实现。
"""

from __future__ import annotations

import os
import subprocess


def _windows_process_alive(process_id: int) -> bool:
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return _windows_process_alive_via_tasklist(process_id)

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    SYNCHRONIZE = 0x00100000
    STILL_ACTIVE = 259
    ERROR_ACCESS_DENIED = 5

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE,
        False,
        process_id,
    )
    if not handle:
        # 打不开：没有权限说明进程确实存在，其它错误按“不存在”处理。
        return kernel32.GetLastError() == ERROR_ACCESS_DENIED
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _windows_process_alive_via_tasklist(process_id: int) -> bool:
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {process_id}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    output = (completed.stdout or "").strip()
    return bool(output) and not output.upper().startswith("INFO")


def process_alive(process_id: int | None) -> bool:
    """True when the PID belongs to a running process."""

    if not process_id or process_id <= 0:
        return False
    if os.name == "nt":
        return _windows_process_alive(int(process_id))
    try:
        os.kill(int(process_id), 0)
        return True
    except OSError:
        return False
