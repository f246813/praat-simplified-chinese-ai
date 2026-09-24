"""进程存活判断。

注意：本机（Windows + Python 3.12）上 ``os.kill (pid, 0)`` 对**任何** PID 都
抛 ``OSError (errno=22, winerror=87)``，所以它不能用来判断进程是否存在。
下面用 ``OpenProcess`` + ``GetExitCodeProcess``（必要时退回 ``tasklist``）实现。
"""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path


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


def _windows_identity_from_handle(handle: int) -> dict[str, str] | None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    query_path = kernel32.QueryFullProcessImageNameW
    query_path.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    query_path.restype = wintypes.BOOL
    get_times = kernel32.GetProcessTimes
    get_times.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    get_times.restype = wintypes.BOOL

    path = ctypes.create_unicode_buffer(32768)
    size = wintypes.DWORD(len(path))
    created = wintypes.FILETIME()
    exited = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    if not query_path(handle, 0, path, ctypes.byref(size)):
        return None
    if not get_times(
        handle, ctypes.byref(created), ctypes.byref(exited),
        ctypes.byref(kernel), ctypes.byref(user),
    ):
        return None
    ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
    return {"executable": path.value, "started": f"win:{ticks}"}


def _windows_process_identity(process_id: int) -> dict[str, str] | None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    handle = open_process(0x1000, False, process_id)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        return _windows_identity_from_handle(handle)
    finally:
        kernel32.CloseHandle(handle)


def _linux_process_identity(process_id: int) -> dict[str, str] | None:
    try:
        executable = os.readlink(f"/proc/{process_id}/exe")
        stat = Path(f"/proc/{process_id}/stat").read_text(encoding="utf-8")
        # The command name is parenthesized and can contain spaces or ')'.
        fields = stat[stat.rfind(")") + 2:].split()
        started = fields[19]  # field 22, with field 3 at index 0
    except (OSError, IndexError, ValueError):
        return None
    return {"executable": executable, "started": f"proc:{started}"}


def _ps_process_identity(process_id: int) -> dict[str, str] | None:
    try:
        completed = subprocess.run(
            ["ps", "-ww", "-p", str(process_id), "-o", "lstart=", "-o", "command="],
            capture_output=True, text=True, errors="replace", timeout=15,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    fields = (completed.stdout or "").strip().split(maxsplit=5)
    if len(fields) != 6:
        return None
    return {
        "executable": fields[5],  # full command line where ps lacks /proc
        "started": "ps:" + " ".join(fields[:5]),
    }


def process_identity(process_id: int) -> dict[str, str] | None:
    """Read a PID's executable and creation token; return None if unverifiable."""

    if process_id <= 0:
        return None
    if os.name == "nt":
        return _windows_process_identity(process_id)
    if Path(f"/proc/{process_id}/stat").exists():
        return _linux_process_identity(process_id)
    return _ps_process_identity(process_id)


def identities_match(expected: dict[str, str], observed: dict[str, str] | None) -> bool:
    if not observed or not expected.get("executable") or not expected.get("started"):
        return False
    expected_path = os.path.normcase(os.path.realpath(expected["executable"]))
    observed_path = os.path.normcase(os.path.realpath(observed.get("executable", "")))
    return expected_path == observed_path and expected["started"] == observed.get("started")


def terminate_process_if_identity_matches(
    process_id: int, expected: dict[str, str]
) -> bool:
    """Terminate only the process represented by the recorded identity."""

    if process_id <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        open_process = kernel32.OpenProcess
        open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        open_process.restype = wintypes.HANDLE
        handle = open_process(0x1000 | 0x0001, False, process_id)  # QUERY | TERMINATE
        if not handle:
            return False
        try:
            if not identities_match(expected, _windows_identity_from_handle(handle)):
                return False
            terminate = kernel32.TerminateProcess
            terminate.argtypes = [wintypes.HANDLE, wintypes.UINT]
            terminate.restype = wintypes.BOOL
            return bool(terminate(handle, 1))
        finally:
            kernel32.CloseHandle(handle)

    # Linux pidfd keeps the target stable even if its numeric PID is reused.
    if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
        descriptor: int | None = None
        try:
            descriptor = os.pidfd_open(process_id)
        except OSError:
            # Older kernels may expose pidfd_open in Python but lack the syscall.
            # Fall through to the identity-checked os.kill path below.
            pass
        if descriptor is not None:
            try:
                if not identities_match(expected, process_identity(process_id)):
                    return False
                signal.pidfd_send_signal(descriptor, signal.SIGTERM)
                return True
            except OSError:
                return False
            finally:
                os.close(descriptor)

    if not identities_match(expected, process_identity(process_id)):
        return False
    try:
        os.kill(process_id, signal.SIGTERM)
        return True
    except OSError:
        return False
