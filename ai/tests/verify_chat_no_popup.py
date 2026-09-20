"""手动回归：发指令时 Praat 的窗口一个都不许动。

用户报的两个问题（2026-09-20）：

1. 向前端发送指令时会弹出「Praat Info」的窗口；
2. 执行指令时声音编辑器（Sound 窗口）会跳到前面盖住对话窗口。

根因都在老投递方式 ``Praat.exe --send`` 上：它会对
``FindWindow ("PraatChildWindow… Praat")`` 找到的窗口做
``ShowWindow (SW_RESTORE) + SetForegroundWindow``，而那个「第一个窗口」实测就是
Info 窗口或声音编辑器。现在前端改成自己写 ``Message.txt`` + 发 ``WM_APP``
（``praat_ai/sendpraat.py``），这个脚本用真 Praat 检查它真的不动任何窗口。

脚本会先开一个「像对话窗口那样」的 Tk 窗口并把它置前（真机上用户的场景），
再发指令，然后检查：

1. Praat 的所有窗口（含「Praat Info」）可见/最小化状态一个都没变；
2. 前台窗口还是那个 Tk 窗口，没有被 Praat 抢走；
3. 指令真的执行了（对象列表刷新 + 一条只读查询拿到了结果）。

用法（仓库根目录）：

    python ai/tests/verify_chat_no_popup.py             # 检查现在的投递方式
    python ai/tests/verify_chat_no_popup.py --legacy    # 反证：用回 --send，窗口会被动

``--legacy`` 会把 ``PRAAT_AI_SEND_MODE=argv``，也就是老路径；那时窗口被还原/
置前是预期结果，脚本会把它当成「老路径的确会动窗口」报出来，不算失败。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praat_ai import chat, sendpraat, tools   # noqa: E402


def ensure_praat(problems: list[str]) -> tuple[str, subprocess.Popen[bytes] | None]:
    executable = chat.praat_executable()
    if not executable:
        problems.append("没有找到 Praat 可执行文件")
        return "", None
    if chat.praat_process_running(executable):
        return executable, None
    process = subprocess.Popen([executable])
    deadline = time.time() + 30
    while time.time() < deadline:
        if chat.praat_process_running(executable):
            time.sleep(6)   # 等它把窗口摆好
            return executable, process
        time.sleep(0.5)
    problems.append("Praat 启动超时")
    return executable, process


def snapshot() -> dict[str, tuple[bool, bool]]:
    """``进程号:标题 -> (可见, 最小化)``；标题重复时加序号区分。"""

    state: dict[str, tuple[bool, bool]] = {}
    for window in sendpraat.list_windows():
        key = f"{window.process_id}:{window.title}"
        if key in state:
            suffix = 2
            while f"{key}#{suffix}" in state:
                suffix += 1
            key = f"{key}#{suffix}"
        state[key] = window.state
    return state


def diff(
    before: dict[str, tuple[bool, bool]], after: dict[str, tuple[bool, bool]]
) -> tuple[list[str], list[str]]:
    """返回 ``(违规, 备注)``。

    只有「窗口变得可见 / 从任务栏被还原」才算违规——用户报的就是这两种现象。
    Praat 自己会为每个命令对话框留一个**隐藏**窗口（例如创建声音之后多出一个
    不可见的「创建纯音声音」窗口，只建一次、不会累积，实测三次创建仍然只有一个），
    那种不该算成「弹窗」。
    """

    violations: list[str] = []
    notes: list[str] = []
    for key in sorted(set(before) | set(after)):
        old = before.get(key)
        new = after.get(key)
        if old == new:
            continue
        label = key.encode("utf-8").decode("utf-8", "replace")
        if old is None:
            line = f"  新窗口：{label}（{new}）"
            (violations if new[0] else notes).append(line)
        elif new is None:
            line = f"  窗口消失：{label}（{old}）"
            (violations if old[0] else notes).append(line)
        else:
            restored = (old[1] and not new[1] and new[0]) or (not old[0] and new[0])
            line = f"  窗口状态变化：{label} {old} → {new}"
            (violations if restored else notes).append(line)
    return violations, notes


def make_front_window() -> tk.Tk | None:
    """开一个和对话窗口同类的 Tk 窗口并置前，用来验证「谁在前面」。"""

    try:
        root = tk.Tk()
    except tk.TclError as error:
        print(f"· 建不了 Tk 窗口（{error}），跳过前台焦点检查")
        return None
    root.title(FRONT_WINDOW_TITLE)
    root.geometry("420x160+60+60")
    root.attributes("-topmost", True)
    root.update()
    root.attributes("-topmost", False)
    root.lift()
    root.focus_force()
    root.update()
    return root


FRONT_WINDOW_TITLE = "Praat AI 验证窗口"


def pump(root: tk.Tk | None) -> None:
    if root is not None:
        root.update()


def stash_praat_windows() -> list[str]:
    """把 Praat 的 Info / 编辑器窗口收进任务栏。

    用户报现象时 Praat 的窗口就是最小化的：老路径会 ``ShowWindow (SW_RESTORE)``
    把它们拽出来，所以「收进任务栏再发指令」才是完整的复现条件。对象窗口留着
    不动（它一直在）。
    """

    minimized: list[str] = []
    for window in sendpraat.praat_windows():
        if window.title == sendpraat.PRAAT_OBJECTS_TITLE or window.minimized:
            continue
        if sendpraat.minimize_window(window.handle):
            minimized.append(window.title)
    return minimized


def main() -> int:
    problems: list[str] = []
    legacy = "--legacy" in sys.argv
    if legacy:
        os.environ[sendpraat.SEND_MODE_ENV] = sendpraat.ARGV_MODE
    executable, started = ensure_praat(problems)
    if problems:
        for problem in problems:
            print(f"！{problem}")
        return 1

    mode = sendpraat.send_mode()
    print(f"投递方式：{mode}（PRAAT_AI_SEND_MODE={os.getenv(sendpraat.SEND_MODE_ENV, '未设置')}）")
    print(f"Praat：{executable}")
    instances = chat.praat_process_ids(executable) or []
    print(f"运行中的 Praat 进程：{instances}")

    context_path = chat.context_path()
    started_at = time.time()
    front = make_front_window()
    stashed = stash_praat_windows()
    if stashed:
        print(f"· 已把 Praat 的窗口收进任务栏：{'、'.join(stashed)}")
    time.sleep(0.3)
    before = snapshot()
    foreground_before = sendpraat.foreground_window_title()
    front_is_foreground = foreground_before == FRONT_WINDOW_TITLE

    # 1. 每条指令前都会先送一次「刷新对象列表」的空脚本。
    refreshed, note = chat.refresh_object_context(executable)
    if not refreshed:
        problems.append(f"刷新对象列表失败：{note}")
    pump(front)
    ping_done = time.time()

    # 1b. 消息自消费：脚本第一句就把 Message.txt 换成空操作。这样队列里残留的
    # WM_APP 醒来时什么都没得执行，不会把下一条指令再执行一遍（guide.md §8.5）。
    message_file = sendpraat.message_file_path()
    if mode == sendpraat.WINDOW_MODE and message_file is not None:
        after_send = message_file.read_text(encoding="utf-8", errors="replace")
        if "runScript" in after_send:
            problems.append(
                f"投递之后消息文件里还有 runScript（自消费没生效）：{message_file}"
            )
        elif sendpraat.CONSUMED_NOTE not in after_send:
            problems.append(f"消息文件不是「已消费」的内容：{message_file}")
        else:
            print(f"· 消息文件已自消费：{message_file}")
    # 本次请求的脚本文件（带请求编号），脚本内容原样留在磁盘上方便排查。
    commands = sorted((chat.runtime_dir() / "commands").glob("chat_command_*.praat"))
    if commands:
        print(f"· 本条指令的脚本文件：{commands[-1].name}")

    # 2. 有对象的话，再送一条真正的只读查询指令。
    queried = ""
    rows = tools.parse_object_context(chat.object_context())
    created: list[int] = []
    if not rows and started is not None:
        # 这次是验证脚本自己开的 Praat（没有去动用户的会话），那就造一个对象，
        # 让「查询」这条路径也真的被验到；用完删掉。
        context = tools.ToolContext(
            objects=[],
            result_path=chat.result_path(),
            state_path=chat.state_path(),
        )
        ok, output = chat._send_script(
            executable,
            tools.render(
                "create_sound",
                {"duration": 0.2, "frequency": 220, "name": "no-popup-probe"},
                context,
            ),
        )
        if not ok:
            problems.append(f"建验证用对象失败：{output}")
        else:
            rows = tools.parse_object_context(chat.object_context())
            created = [row.id for row in rows if row.name.endswith("no-popup-probe")]
            print(f"· 造了一个验证用对象（用完会删）：{created}")
    if rows:
        row = next((item for item in rows if item.selected), rows[-1])
        context = tools.ToolContext(
            objects=rows,
            result_path=chat.result_path(),
            state_path=chat.state_path(),
        )
        try:
            script = tools.render("object_info", {"object": row.id}, context)
        except tools.ToolError as error:
            problems.append(f"渲染查询脚本失败：{error}")
        else:
            ok, output = chat._send_script(executable, script)
            if not ok:
                problems.append(f"查询「{row.name}」失败：{output}")
            else:
                queried = "；".join(chat._read_results())
            pump(front)
    else:
        print("· Praat 里没有对象，只验了「刷新对象列表」这条空脚本（投递路径完全相同）")

    after = snapshot()
    foreground_after = sendpraat.foreground_window_title()

    print(f"· 前台窗口：{foreground_before!r} → {foreground_after!r}")
    if front is not None and not front_is_foreground:
        print("· （验证窗口没能抢到前台，这次只比窗口状态）")
    if queried:
        print(f"· 查询结果：{queried}")
    if created:
        context = tools.ToolContext(
            objects=tools.parse_object_context(chat.object_context()),
            result_path=chat.result_path(),
            state_path=chat.state_path(),
        )
        for object_id in created:
            chat._send_script(
                executable,
                tools.render("remove_object", {"object": object_id}, context),
            )
        print(f"· 已删除验证用对象：{created}")
    print(
        f"· 对象列表文件：{context_path}（每条 app 消息之后 Praat 都会重写一次，mtime "
        f"{context_path.stat().st_mtime if context_path.is_file() else '缺失'}；"
        "脚本确实跑完了看上面的查询结果和 chat_state.txt）"
    )
    if ping_done - started_at > chat.EXECUTION_TIMEOUT_SEC:
        problems.append("刷新对象列表花的时间超过了执行超时，Praat 可能没在响应")

    violations, notes = diff(before, after)
    stole_focus = (
        front is not None
        and front_is_foreground
        and not legacy
        and foreground_after != FRONT_WINDOW_TITLE
    )

    if violations:
        print("· 窗口变化（违规）：")
        for line in violations:
            print(line)
    elif notes:
        print("· 窗口变化：可见/最小化状态都没动")
    else:
        print("· 窗口变化：无（可见/最小化状态都没动）")
    if notes:
        print("· 启用了新的隐藏窗口（不算弹窗，Praat 的命令对话框本来就常驻一个）：")
        for line in notes:
            print(line)

    if legacy:
        if violations or stole_focus:
            print("√ 老路径（--send）确实会动窗口 / 抢前台，和用户报的现象一致")
        else:
            print("？ 这次 --send 没动窗口：Praat 的窗口当时可能都不是最小化，现象不稳定")
    else:
        for line in violations:
            problems.append(f"发指令动了 Praat 窗口：{line.strip()}")
        if stole_focus:
            problems.append(
                f"Praat 把前台焦点从「{FRONT_WINDOW_TITLE}」抢到了 {foreground_after!r}"
            )

    if front is not None:
        front.destroy()
    if started is not None:
        started.terminate()

    if problems:
        print("")
        for problem in problems:
            print(f"！{problem}")
        return 1
    if not legacy:
        print("√ 发指令时 Praat 的窗口一个都没动（Info 窗口没弹出、声音窗口没顶到前面）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
