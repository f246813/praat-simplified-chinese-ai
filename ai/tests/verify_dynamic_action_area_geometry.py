"""Focused live check for the Windows dynamic action-area geometry and labels."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

if os.name != "nt":
    raise SystemExit("SKIP: this live check requires Windows")

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "ai"))
from praat_ai import sendpraat  # noqa: E402

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.EnumChildWindows.argtypes = [wintypes.HWND, ENUMPROC, wintypes.LPARAM]
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def control_text(hwnd: int) -> tuple[str, str]:
    cls = ctypes.create_unicode_buffer(256)
    title = ctypes.create_unicode_buffer(512)
    user32.GetClassNameW(hwnd, cls, len(cls))
    user32.GetWindowTextW(hwnd, title, len(title))
    return cls.value, title.value


def rect(hwnd: int) -> tuple[int, int, int, int]:
    bounds = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(bounds)):
        raise ctypes.WinError()
    return bounds.left, bounds.top, bounds.right, bounds.bottom


def terminate(pid: int) -> None:
    handle = kernel32.OpenProcess(0x0001, False, pid)
    if handle:
        try:
            kernel32.TerminateProcess(handle, 0)
        finally:
            kernel32.CloseHandle(handle)


def main() -> int:
    exe = Path(os.environ.get("PRAAT_EXECUTABLE_PATH", PROJECT / "Praat-paused.exe")).resolve()
    if not exe.is_file():
        raise SystemExit(f"Praat executable not found: {exe}")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".praat", delete=False) as script:
        script.write('Create Sound from formula: "layout-probe", 1, 0, 0.5, 44100, ~ 0.3 * sin (2*pi*220*x)\n')
        script_path = Path(script.name)

    process = subprocess.Popen([str(exe), "--FULL-TRUST", "--new-send", str(script_path)], cwd=PROJECT)
    try:
        deadline = time.monotonic() + 30
        objects = None
        while time.monotonic() < deadline:
            objects = next((w for w in sendpraat.list_windows()
                            if w.process_id == process.pid and w.title == sendpraat.PRAAT_OBJECTS_TITLE
                            and w.visible), None)
            if objects:
                break
            time.sleep(0.2)
        if not objects:
            raise AssertionError("Praat Objects window did not appear")

        def enumerate_buttons() -> list[tuple[str, tuple[int, ...], tuple[int, ...]]]:
            found: list[tuple[str, tuple[int, ...], tuple[int, ...]]] = []
            def visit(hwnd, _param) -> bool:
                cls, title = control_text(hwnd)
                if cls.casefold() == "button":
                    container = user32.GetParent(hwnd)
                    parent_cls, parent_title = control_text(container)
                    if parent_cls.casefold().startswith("praatchildwindow") and parent_title == "rowColumn":
                        found.append((title, rect(container), rect(hwnd)))
                return True
            user32.EnumChildWindows(objects.handle, ENUMPROC(visit), 0)
            return found

        buttons: list[tuple[str, tuple[int, ...], tuple[int, ...]]] = []
        signature = None
        stable_since = time.monotonic()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            current = enumerate_buttons()
            current_signature = tuple(current)
            if current_signature != signature:
                buttons, signature, stable_since = current, current_signature, time.monotonic()
            elif buttons and time.monotonic() - stable_since >= 1.5:
                break
            time.sleep(0.2)
        if not buttons:
            raise AssertionError("No dynamic submenu buttons found")

        mismatches = [(title, row, button) for title, row, button in buttons if row != button]
        padded = [title for title, _row, _button in buttons if title != title.strip() or title.endswith(">")]
        print(f"Observed {len(buttons)} dynamic menus; geometry mismatches={mismatches}; padded titles={padded}")
        if mismatches or padded:
            raise AssertionError("Dynamic action area buttons must fill their rows and use plain titles")
        print("PASS: dynamic menu buttons fill their rows and use plain titles")
        return 0
    finally:
        terminate(process.pid)
        try:
            script_path.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
