"""手动回归：「前端 → 启动前端」不能再把 Praat 打死（2026-09-20 的闪退 bug）。

用户报的现象：选中一个日文名字的声音，点「前端 → 启动前端」，Praat 没有任何提示
就消失。根因是 `praat_runPythonScriptFile()` 导出选中对象时，用
`std::filesystem::path` 收窄构造文件名（按系统 ANSI 代码页解释 UTF-8 字节），
名字的字节不是合法 GBK 序列时抛 `std::filesystem::filesystem_error`；菜单回调只
catch `MelderError`，异常穿出窗口过程 → `std::terminate` → `abort()`。详见
guide.md §8.6。

这个脚本不用鼠标：开一个全新的 Praat → 建一个日文名的 Sound（对象名会变成
“Sound あなた”）→ 打开它的编辑器（AI 菜单挂在编辑窗口上）→ 给编辑器窗口发
`WM_COMMAND`（就是点那一项菜单的真实回调路径）→ 检查

1. Praat 进程还活着（没闪退）；
2. 没有新增 `%LOCALAPPDATA%\\CrashDumps\\Praat.exe.<pid>.dmp`；
3. `%TEMP%\\praat_py_workspace_<pid>\\praat_context.json` 写完整（不是停在 28 字节）；
4. 导出的临时文件名是正确的 `<id>_<对象名>.wav`，不是 GBK 乱码。

用法（仓库根目录，需要先在非沙箱环境里跑）：

    python ai/tests/verify_ai_menu_no_crash.py
    python ai/tests/verify_ai_menu_no_crash.py --name 思い出す   # 对照用

它会启动一个临时 Praat（跑完关掉），如果「启动前端」真的把前端拉起来了，也会把
对话窗口一并关掉。
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praat_ai import chat, sendpraat   # noqa: E402


PROJECT = Path(__file__).resolve().parents[2]
PRAAT = str(PROJECT / "Praat.exe")

WM_COMMAND = 0x0111
SMTO_ABORTIFHUNG = 0x0002
SMTO_BLOCK = 0x0001
MF_BYPOSITION = 0x00000400

user32 = ctypes.windll.user32
user32.GetMenu.argtypes = [wintypes.HWND]
user32.GetMenu.restype = wintypes.HMENU
user32.GetSubMenu.argtypes = [wintypes.HMENU, ctypes.c_int]
user32.GetSubMenu.restype = wintypes.HMENU
user32.GetMenuItemCount.argtypes = [wintypes.HMENU]
user32.GetMenuItemID.argtypes = [wintypes.HMENU, ctypes.c_int]
user32.GetMenuItemID.restype = ctypes.c_int
user32.GetMenuStringW.argtypes = [
    wintypes.HMENU,
    ctypes.c_uint,
    wintypes.LPWSTR,
    ctypes.c_int,
    ctypes.c_uint,
]
user32.GetMenuStringW.restype = ctypes.c_int
user32.SendMessageTimeoutW.restype = wintypes.LPARAM


def menu_text(hmenu, index: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetMenuStringW(hmenu, index, buffer, 256, MF_BYPOSITION)
    return buffer.value


def find_menu_command(hwnd: int, wanted: tuple[str, ...]) -> tuple[int, str, str]:
    """在窗口菜单栏里找一项；返回 (命令 id, 路径文本, 所有菜单项文本)。"""

    bar = user32.GetMenu(hwnd)
    if not bar:
        return 0, "", ""
    labels: list[str] = []
    for i in range(user32.GetMenuItemCount(bar)):
        top = menu_text(bar, i)
        sub = user32.GetSubMenu(bar, i)
        if not sub:
            continue
        for j in range(user32.GetMenuItemCount(sub)):
            label = menu_text(sub, j)
            labels.append(f"{top} / {label}")
            if any(item in label for item in wanted):
                return user32.GetMenuItemID(sub, j), f"{top} / {label}", "；".join(labels)
    return 0, "", "；".join(labels)


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


def crash_dumps() -> set[str]:
    folder = Path(os.environ["LOCALAPPDATA"]) / "CrashDumps"
    return {p.name for p in folder.glob("Praat.exe*.dmp")} if folder.is_dir() else set()


def close_chat_window() -> None:
    pid_file = Path(chat.runtime_dir()) / "chat.pid"
    if not pid_file.is_file():
        return
    try:
        chat_pid = int(pid_file.read_text(encoding="utf-8").strip())
    except ValueError:
        chat_pid = 0
    if chat_pid:
        subprocess.run(
            ["taskkill", "/PID", str(chat_pid), "/T", "/F"],
            capture_output=True,
            text=True,
        )
    try:
        pid_file.unlink()
    except FileNotFoundError:
        pass


def main() -> int:
    name = "あなた"
    if "--name" in sys.argv:
        name = sys.argv[sys.argv.index("--name") + 1]
    problems: list[str] = []

    before_dumps = crash_dumps()
    print(f"· 开一个临时 Praat，建一个名字是「{name}」的 Sound")
    process = subprocess.Popen([PRAAT])
    pid = wait_for(
        lambda: max(praat_pids()) if praat_pids() else None, 30, "Praat 进程出现"
    )
    print(f"  pid = {pid}")
    wait_for(
        lambda: [
            w
            for w in sendpraat.list_windows()
            if w.process_id == pid and w.title == sendpraat.PRAAT_OBJECTS_TITLE
        ],
        30,
        "对象窗口出现",
    )
    time.sleep(2.0)

    script = "\n".join(
        [
            f'Create Sound from formula: "{name}", 1, 0, 0.5, 44100, ~ 0.3 * sin (2*pi*220*x)',
            "View & Edit",
            f'appendFileLine: {chat.tools.quote(chat.state_path())}, "done"',
            "",
        ]
    )
    ok, note = chat._send_script(PRAAT, script)
    if not ok:
        problems.append(f"建声音失败：{note}")
    chat.refresh_object_context(PRAAT)
    print(f"  对象列表：{chat.object_context().strip()!r}")

    editor = wait_for(
        lambda: [
            w
            for w in sendpraat.list_windows()
            if w.process_id == pid and "Sound" in w.title and w.title != sendpraat.PRAAT_OBJECTS_TITLE
        ],
        20,
        "声音编辑器窗口出现",
    )[0]
    command_id, path_text, all_labels = find_menu_command(
        editor.handle, ("启动前端", "Start frontend")
    )
    if not command_id:
        problems.append(f"编辑器窗口里没找到「启动前端」；现有菜单：{all_labels}")
        print(f"！{problems[-1]}")
        process.terminate()
        return 1

    print(f"· 触发菜单项：{path_text}（命令 id = {command_id}，走的就是鼠标点击的回调）")
    result = ctypes.c_size_t(0)
    user32.SendMessageTimeoutW(
        editor.handle,
        WM_COMMAND,
        command_id,
        0,
        SMTO_ABORTIFHUNG | SMTO_BLOCK,
        15000,
        ctypes.byref(result),
    )
    time.sleep(5.0)

    alive = pid in praat_pids()
    if not alive:
        problems.append("Praat 闪退了（进程已经不在）")
    new_dumps = crash_dumps() - before_dumps
    if new_dumps:
        problems.append(f"新增了崩溃转储：{sorted(new_dumps)}")

    workspace = Path(os.environ["TEMP"]) / f"praat_py_workspace_{pid}"
    context = workspace / "praat_context.json"
    if not context.is_file():
        problems.append(f"没有写出 {context}")
    else:
        text = context.read_text(encoding="utf-8", errors="replace")
        print(f"· praat_context.json（{len(text.encode('utf-8'))} 字节）：{text!r}")
        if not text.rstrip().endswith("}"):
            problems.append("praat_context.json 没写完（导出选中对象时就断了）")
        expected = f"{1}_{name}.wav"   # 对象名会带上类名前缀，导出名形如 1_Sound_あなた.wav
        exported = sorted(workspace.glob("*.wav")) + sorted(workspace.glob("*.TextGrid"))
        print(f"· 导出文件：{[item.name for item in exported]}")
        if exported and not any(name in item.name for item in exported):
            problems.append(
                f"导出文件名里没有「{name}」，可能是 ANSI/GBK 乱码："
                f"{[item.name for item in exported]}"
            )
        elif not exported:
            problems.append(f"工作目录里没有导出文件（期望形如 {expected}）")

    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    close_chat_window()

    if problems:
        print("")
        for problem in problems:
            print(f"！{problem}")
        return 1
    print("√ 「启动前端」没有把 Praat 打死，也没有写出乱码文件名")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
