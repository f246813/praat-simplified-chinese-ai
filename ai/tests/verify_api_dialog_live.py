"""手动回归：开着「API 配置」小窗时，Praat 必须还能正常响应、缩窗口不许假死。

用户报的（2026-09-21）：配置 API 时，缩小语图窗口或主窗口会导致程序崩溃。
真机复现出来的机制是**假死**而不是崩溃：

- 菜单项以前走 ``runControlCommand("api-config")`` → `praat_runPythonScriptFile`，
  Praat 会一直读子进程的标准输出**直到子进程退出**；
- 而那个 Tk 窗口要等用户点关闭才退出，于是 Praat 主线程整个被堵住，
  `SendMessageTimeout(..., SMTO_ABORTIFHUNG)` 直接报 `Responding=False`；
- 缩窗口时窗口变成白板/幽灵，再点关闭就是「未响应 → 结束进程」，用户看到的就是崩溃。

现在「API 配置…」跑在独立进程里（ai/start_api_settings.py），Praat 侧只等启动器
那零点几秒。这个脚本做两件事：

1. 打开窗口之后，用 ``SMTO_ABORTIFHUNG`` 问一句「你还响应吗」——必须是响应；
2. 用 ``SetWindowPos`` 反复缩小语图（编辑）窗口和对象窗口——这一步在卡死时会把
   脚本自己卡住（实测），所以它同时也是「有没有假死」的判据；
3. 结束时检查：Praat 还在、没有新增崩溃转储、窗口都还响应、小窗能正常关掉。

用法（仓库根目录）::

    python ai/tests/verify_api_dialog_live.py
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
sys.path.insert(0, str(TESTS_DIR.parent))
sys.path.insert(0, str(TESTS_DIR))

from praat_ai import chat, sendpraat   # noqa: E402
import verify_ai_menu_no_crash as menu_helper   # noqa: E402


PROJECT = Path(__file__).resolve().parents[2]
PRAAT = str(PROJECT / "Praat.exe")
WM_COMMAND = 0x0111
WM_CLOSE = 0x0010
WM_NULL = 0x0000
SMTO_ABORTIFHUNG = 0x0002
SMTO_BLOCK = 0x0001

user32 = ctypes.windll.user32


def crash_dumps() -> set[str]:
    folder = Path(os.environ["LOCALAPPDATA"]) / "CrashDumps"
    return {p.name for p in folder.glob("Praat.exe*.dmp")} if folder.is_dir() else set()


def responds(handle: int, timeout: int = 1500) -> bool:
    """窗口还理不理人。``SMTO_ABORTIFHUNG`` 让它在目标假死时立刻返回 0。"""

    result = ctypes.c_size_t(0)
    ok = user32.SendMessageTimeoutW(
        handle, WM_NULL, 0, 0, SMTO_ABORTIFHUNG | SMTO_BLOCK, timeout, ctypes.byref(result)
    )
    return bool(ok)


def find_window(title: str):
    for window in sendpraat.list_windows():
        if window.visible and window.title == title:
            return window
    return None


def resize(handle: int, dw: int, dh: int) -> bool:
    """缩一下窗口；目标线程假死时这个调用自己就会卡住（那正是要抓的毛病）。"""

    rect = wintypes.RECT()
    if not user32.GetWindowRect(handle, ctypes.byref(rect)):
        return False
    width = max(200, rect.right - rect.left + dw)
    height = max(150, rect.bottom - rect.top + dh)
    user32.SetWindowPos(handle, 0, rect.left, rect.top, width, height, 0x0004 | 0x0010)
    return True


def main() -> int:
    problems: list[str] = []
    before = crash_dumps()
    print("· 开一个临时 Praat")
    process = subprocess.Popen([PRAAT])
    pid = process.pid
    objects = None
    deadline = time.time() + 30
    while time.time() < deadline and objects is None:
        objects = next(
            (
                w
                for w in sendpraat.list_windows()
                if w.process_id == pid and w.title == sendpraat.PRAAT_OBJECTS_TITLE
            ),
            None,
        )
        if objects is None:
            time.sleep(0.25)
    if objects is None:
        print("！对象窗口没出来")
        process.terminate()
        return 1
    print(f"  pid={pid} 对象窗口 hwnd={objects.handle}")

    script = "\n".join(
        [
            'Create Sound from formula: "api-dialog", 1, 0, 0.5, 44100, ~ 0.3 * sin (2*pi*220*x)',
            "View & Edit",
            f'appendFileLine: {chat.tools.quote(chat.state_path())}, "done"',
            "",
        ]
    )
    ok, note = chat._send_script(PRAAT, script)
    if not ok:
        problems.append(f"建 Sound / 开编辑器失败：{note}")

    editor = None
    deadline = time.time() + 20
    while time.time() < deadline and editor is None:
        editor = next(
            (
                w
                for w in sendpraat.list_windows()
                if w.process_id == pid
                and w.visible
                and "Sound" in w.title
                and w.title != sendpraat.PRAAT_OBJECTS_TITLE
            ),
            None,
        )
        if editor is None:
            time.sleep(0.25)
    if editor is None:
        print("！编辑器窗口没出来")
        process.terminate()
        return 1
    print(f"  编辑器窗口 {editor.title!r} hwnd={editor.handle}")

    command_id, path_text, labels = menu_helper.find_menu_command(
        editor.handle, ("API 配置", "API settings")
    )
    if not command_id:
        print(f"！没找到「API 配置」菜单项；现有：{labels}")
        process.terminate()
        return 1
    print(f"· 触发菜单项：{path_text}（id={command_id}）")
    user32.PostMessageW(editor.handle, WM_COMMAND, command_id, 0)

    dialog = None
    deadline = time.time() + 20
    while time.time() < deadline and dialog is None:
        dialog = find_window("API 配置")
        if dialog is None:
            time.sleep(0.25)
    if dialog is None:
        problems.append("「API 配置」小窗没有出现")
        print(f"！{problems[-1]}")
    else:
        print(f"· API 小窗出现：pid={dialog.process_id} hwnd={dialog.handle}")
    if dialog is not None and dialog.process_id == pid:
        problems.append("小窗跑在 Praat 进程里（应该独立进程，否则会把 Praat 堵死）")

    responsive = responds(objects.handle)
    print(f"· 小窗开着时 Praat 还响应吗：{responsive}")
    if not responsive:
        problems.append("小窗开着时 Praat 不响应了（假死）")

    print("· 缩小语图（编辑）窗口与主（对象）窗口各三次")
    started = time.monotonic()
    for _ in range(3):
        resize(editor.handle, -60, -40)
        resize(objects.handle, -40, -30)
        time.sleep(0.4)
    print(f"  缩窗耗时 {time.monotonic() - started:.1f} 秒（卡死时会明显变长）")

    alive = process.poll() is None
    print(
        f"· 缩小之后：Praat 还在={alive}；"
        f"对象窗口响应={responds(objects.handle) if alive else '-'}；"
        f"编辑窗口响应={responds(editor.handle) if alive else '-'}"
    )
    if not alive:
        problems.append("缩窗口之后 Praat 不在了（崩溃/被结束）")
    elif not responds(objects.handle):
        problems.append("缩窗口之后 Praat 不响应了")
    new_dumps = crash_dumps() - before
    if new_dumps:
        problems.append(f"新增崩溃转储：{sorted(new_dumps)}")

    if dialog is not None:
        print("· 关掉 API 小窗")
        user32.PostMessageW(dialog.handle, WM_CLOSE, 0, 0)
        time.sleep(3.0)
        alive = process.poll() is None
        print(
            f"  关掉之后：Praat 还在={alive}；"
            f"对象窗口响应={responds(objects.handle) if alive else '-'}"
        )
        if not alive:
            problems.append("关掉 API 小窗之后 Praat 不在了")
        elif not responds(objects.handle):
            problems.append("关掉 API 小窗之后 Praat 不响应了")
        if find_window("API 配置") is not None:
            problems.append("API 小窗没有关掉")

    # 再开一次，然后直接关掉 Praat：小窗要跟着退（用户报的「关掉 Praat 后前端不关」）。
    print("· 再开一次 API 小窗，然后关掉 Praat 看它会不会跟着退")
    user32.PostMessageW(editor.handle, WM_COMMAND, command_id, 0)
    again = None
    deadline = time.time() + 20
    while time.time() < deadline and again is None:
        again = find_window("API 配置")
        if again is None:
            time.sleep(0.25)
    if again is None:
        problems.append("第二次没能再打开 API 小窗")
    else:
        print(f"  小窗 pid={again.process_id}（Praat 是 {pid}）")
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        closed = False
        deadline = time.time() + 15
        while time.time() < deadline:
            if find_window("API 配置") is None:
                closed = True
                break
            time.sleep(0.25)
        print(f"  Praat 关掉之后小窗{'也跟着退了' if closed else '还留着'}")
        if not closed:
            problems.append("关掉 Praat 之后 API 小窗没有退出")

    print("· 收尾：关掉 Praat")
    if process.poll() is None:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    for window in sendpraat.list_windows():
        if window.title == "API 配置":
            subprocess.run(
                ["taskkill", "/PID", str(window.process_id), "/F"], capture_output=True
            )

    if problems:
        print("结论：" + str(len(problems)) + " 项异常")
        for item in problems:
            print(f"  ！{item}")
        return 1
    print("√ 开着 API 配置小窗时 Praat 全程响，缩窗口不再假死/崩溃")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
