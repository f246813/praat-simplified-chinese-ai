"""手动回归：「前端 → API 配置…」这个菜单项真的存在、点了能弹出小窗口。

用法（仓库根目录，需要 GUI 里的 Praat.exe，且没有别的 Praat 在跑）::

    python ai/tests/verify_api_menu_live.py

它做的事情和用户手点一样：开一个临时 Praat → 建一个 Sound 并打开编辑器（「前端」
菜单在编辑器窗口上）→ 在菜单里找到「API 配置…」→ 给它发 `WM_COMMAND`（就是点击走
的那条回调）→ 等那个 Tk 小窗口出现 → 关掉它 → 确认 Praat 还活着、没有崩溃转储。

注意：菜单回调会一直阻塞到窗口被关掉（Python + Tk 的 mainloop），所以这里用
`PostMessage` 异步触发，不能等 `SendMessage` 返回。
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parents[0]))
sys.path.insert(0, str(TESTS_DIR))

from praat_ai import chat, sendpraat   # noqa: E402
import verify_ai_menu_no_crash as menu_helper   # noqa: E402


PROJECT = Path(__file__).resolve().parents[2]
PRAAT = str(PROJECT / "Praat.exe")
WM_COMMAND = 0x0111
WM_CLOSE = 0x0010
user32 = ctypes.windll.user32
user32.PostMessageW.argtypes = [
    wintypes.HWND,
    ctypes.c_uint,
    wintypes.WPARAM,
    wintypes.LPARAM,
]


def praat_pids() -> list[int]:
    return list(chat.praat_process_ids(PRAAT) or [])


def wait_for(predicate, timeout: float, label: str):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.25)
    raise SystemExit(f"等待超时：{label}")


def api_dialog_windows() -> list[sendpraat.WindowInfo]:
    """那个 Tk 小窗口（标题「API 配置」，进程是 Python，不是 Praat）。"""

    return [
        window
        for window in sendpraat.list_windows()
        if window.title.strip() == "API 配置"
    ]


def main() -> int:
    problems: list[str] = []
    if not Path(PRAAT).is_file():
        print(f"没有找到 {PRAAT}，请先构建 Praat.exe。")
        return 2
    if praat_pids():
        print("已经有一个 Praat 在跑，请先关掉它再跑这个回归。")
        return 2
    before_dumps = menu_helper.crash_dumps()
    process = subprocess.Popen([PRAAT])
    try:
        pid = wait_for(lambda: max(praat_pids()) if praat_pids() else None, 30, "Praat 进程")
        wait_for(
            lambda: [
                window
                for window in sendpraat.list_windows()
                if window.process_id == pid
                and window.title == sendpraat.PRAAT_OBJECTS_TITLE
            ],
            30,
            "对象窗口出现",
        )
        time.sleep(2.0)

        script = "\n".join(
            [
                'Create Sound from formula: "api-menu", 1, 0, 0.5, 44100, ~ 0.3 * sin (2*pi*220*x)',
                "View & Edit",
                f"appendFileLine: {chat.tools.quote(chat.state_path())}, \"done\"",
                "",
            ]
        )
        ok, note = chat._send_script(PRAAT, script)
        if not ok:
            problems.append(f"建声音/开编辑器失败：{note}")
        editor = wait_for(
            lambda: [
                window
                for window in sendpraat.list_windows()
                if window.process_id == pid
                and "Sound" in window.title
                and window.title != sendpraat.PRAAT_OBJECTS_TITLE
            ],
            20,
            "声音编辑器窗口",
        )[0]

        # 菜单上的文字是「API 配置...」（三个点，不是省略号），中英两种都认。
        command_id, path_text, all_labels = menu_helper.find_menu_command(
            editor.handle, ("API 配置...", "API settings...")
        )
        if not command_id:
            problems.append(f"编辑器菜单里没找到「API 配置…」；现有菜单：{all_labels}")
            print(f"！{problems[-1]}")
            return 1
        print(f"· 找到菜单项：{path_text}（命令 id = {command_id}）")

        # 异步触发：回调会阻塞到小窗口被关掉。
        user32.PostMessageW(editor.handle, WM_COMMAND, command_id, 0)
        dialog = wait_for(api_dialog_windows, 30, "「API 配置」小窗口出现")
        window = dialog[0]
        print(f"· 小窗口出现：{window.title}（进程 {window.process_id}）")

        alive = pid in praat_pids()
        print(f"· 弹出小窗口时 Praat 还在：{alive}")
        if not alive:
            problems.append("弹窗过程中 Praat 退出了")

        user32.PostMessageW(window.handle, WM_CLOSE, 0, 0)
        gone = wait_for(
            lambda: not api_dialog_windows(),
            20,
            "小窗口被关掉",
        )
        print(f"· 关掉小窗口：{'成功' if gone else '失败'}")

        time.sleep(2.0)
        if pid not in praat_pids():
            problems.append("关掉小窗口之后 Praat 退出了")
        new_dumps = menu_helper.crash_dumps() - before_dumps
        if new_dumps:
            problems.append(f"新增了崩溃转储：{sorted(new_dumps)}")
        # 打开窗口不该改配置（只有点「保存」才写）。
        config_path = Path(chat.ai_directory()) / "ai_config.json"
        print(f"· 配置文件还在：{config_path.is_file()}")
    finally:
        dialog_windows = api_dialog_windows()
        for window in dialog_windows:
            user32.PostMessageW(window.handle, WM_CLOSE, 0, 0)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        menu_helper.close_chat_window()

    if problems:
        print("")
        for problem in problems:
            print(f"！{problem}")
        return 1
    print("√ 「前端 → API 配置…」能打开小窗口，Praat 不受影响")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
