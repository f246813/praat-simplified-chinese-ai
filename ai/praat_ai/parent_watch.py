"""前端窗口跟着 Praat 走：Praat 一关，对话窗口 / API 配置小窗自己退出。

Praat 菜单启动前端时会带两个环境变量（见 sys/PraatAiControl.cpp）：

``PRAAT_AI_PRAAT_PID``
    当时那个 Praat 的进程号，最可靠的一条线索；
``PRAAT_AI_PRAAT_EXECUTABLE``
    Praat.exe 的路径，没有进程号时用它在进程表里找（例如手工启动的窗口）。

用户报的 2026-09-21：关掉 Praat 之后，对话窗口还留在桌面上。
"""

from __future__ import annotations

import os
import time

from .process import process_alive

#: 启动前端时写进去的两个环境变量。
PARENT_PID_ENV = "PRAAT_AI_PRAAT_PID"
PRAAT_EXECUTABLE_ENV = "PRAAT_AI_PRAAT_EXECUTABLE"


def parent_pid() -> int | None:
    """启动这个窗口的那个 Praat 的进程号（没有/不合法时返回 ``None``）。"""

    raw = os.getenv(PARENT_PID_ENV, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def praat_executable(default: str = "") -> str:
    return os.getenv(PRAAT_EXECUTABLE_ENV, "").strip() or default


def praat_alive(executable: str = "") -> bool | None:
    """Praat 还在不在。``None`` = 查不出来（不是 Windows、tasklist 不可用）。"""

    pid = parent_pid()
    if pid is not None:
        return process_alive(pid)
    from . import chat   # 延迟导入：chat 也用本模块，模块级导入会成环

    ids = chat.praat_process_ids(executable or praat_executable())
    if ids is None:
        return None
    return bool(ids)


def should_watch() -> bool:
    """现在值不值得盯着。

    手工起一个对话窗口做开发时（根本没有 Praat 在跑）不该自己把自己关掉，
    所以只有「确实有 Praat」时才盯。
    """

    if parent_pid() is not None:
        return True
    return praat_alive() is True


class ParentWatcher:
    """盯着 Praat 的 Tk 定时器：它没了就把这个窗口关掉。

    只做两件事——``window.after`` 轮询、关掉时 ``window.destroy``，所以不碰
    Tk 之外的东西，也不跨线程。``grace_sec`` 是启动后的宽限期（刚起来的窗口
    别因为一次查询失败就自己关掉）。给了 ``on_close`` 就由它负责收尾（对话窗口
    要在关之前先说一句），这时 watcher 自己不再 destroy。
    """

    def __init__(
        self,
        window,
        *,
        interval_ms: int = 1000,
        grace_sec: float = 2.0,
        executable: str = "",
        on_close=None,
    ) -> None:
        self.window = window
        self.interval_ms = max(200, int(interval_ms))
        self.deadline = time.monotonic() + max(0.0, float(grace_sec))
        self.executable = executable
        self.on_close = on_close
        self.stopped = False

    def start(self) -> None:
        if self.stopped:
            return
        try:
            self.window.after(self.interval_ms, self._tick)
        except Exception:   # noqa: BLE001 - 窗口已经没了就算了
            self.stopped = True

    def _tick(self) -> None:
        if self.stopped:
            return
        if time.monotonic() >= self.deadline:
            if praat_alive(self.executable) is False:
                self.close_window()
                return
        self.start()

    def close_window(self) -> None:
        self.stopped = True
        if self.on_close is not None:
            try:
                self.on_close()
            except Exception:   # noqa: BLE001 - 关窗口之前的回调尽力而为
                pass
            return
        try:
            self.window.destroy()
        except Exception:   # noqa: BLE001
            pass
