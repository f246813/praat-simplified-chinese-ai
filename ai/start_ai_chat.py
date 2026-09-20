from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


try:   # 正常情况下来自包内实现（os.kill 在本机不可用，见 praat_ai/process.py）
    from praat_ai.process import process_alive
except ImportError:   # 独立运行时的兜底
    def process_alive(process_id: int) -> bool:
        if process_id <= 0:
            return False
        try:
            os.kill(process_id, 0)
            return True
        except OSError:
            return False


def start_new_chat_window(directory: Path, pid_path: Path) -> int:
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


def focus_existing_window(process_id: int) -> bool:
    """Bring the chat window of an already running frontend to the front.

    菜单点「启动前端」时，如果对话窗口本来就开着，之前会静默返回；现在改成
    把已存在的窗口还原并置前，用户至少能看到反馈。
    """

    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return False

    user32 = ctypes.windll.user32
    handles: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd, _param):   # type: ignore[no-untyped-def]
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == process_id and user32.IsWindowVisible(hwnd):
            handles.append(hwnd)
        return True

    user32.EnumWindows(collect, 0)
    if not handles:
        return False

    hwnd = handles[0]
    user32.ShowWindow(hwnd, 9)   # SW_RESTORE
    foreground = user32.GetForegroundWindow()
    current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    attached = False
    if foreground and user32.GetWindowThreadProcessId(foreground, None) != current_thread:
        attached = bool(user32.AttachThreadInput(current_thread, target_thread, True))
    try:
        if not user32.SetForegroundWindow(hwnd):
            user32.BringWindowToTop(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(current_thread, target_thread, False)
    return True


def main(runtime: Path | None = None) -> int:
    """Start the chat window, or bring the already running one to the front."""

    directory = Path(__file__).resolve().parent
    runtime = runtime or (directory / "runtime")
    runtime.mkdir(parents=True, exist_ok=True)
    pid_path = runtime / "chat.pid"
    if pid_path.is_file():
        try:
            process_id = int(pid_path.read_text(encoding="utf-8").strip())
        except ValueError:
            process_id = 0
        if process_id and process_alive(process_id):
            focus_existing_window(process_id)
            return 0
    return start_new_chat_window(directory, pid_path)


if __name__ == "__main__":
    raise SystemExit(main())
