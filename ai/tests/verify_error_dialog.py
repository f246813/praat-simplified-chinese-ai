"""手动回归：脚本报错时**不许**弹出挡住后续消息的模态框。

用户报的 bug：投给 Praat 的脚本出错时，Praat 会弹一个模态错误框（Windows 上是
``MessageBox(... MB_TOPMOST)``，自带消息循环），于是**排在后面的每条指令都要等到
用户点掉它才会执行**，前端只能一条条超时。

这个脚本开一个真的 GUI Praat，按对话窗口那条路投递脚本：

1. 先投一条会报错的脚本 —— 修好之前这里会看到 ``#32770`` 的「Message」模态框；
2. 报错信息要回到 ``runtime/chat_result.tsv``，用户不用去点 Praat；
3. 再投一条正常脚本 —— 修好之前它会被模态框挡住（超时），修好之后几百毫秒就完。

用法（仓库根目录，需要 GUI 里的 Praat.exe，且没有别的 Praat 在跑）::

    python ai/tests/verify_error_dialog.py

它会临时起一个 Praat 并在结束时关掉；期间请不要手动操作那个 Praat。
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praat_ai import chat, sendpraat   # noqa: E402


PROJECT = Path(__file__).resolve().parents[2]
PRAAT = PROJECT / "Praat.exe"
AI_DIRECTORY = PROJECT / "ai"
DIALOG_CLASS = "#32770"   #: 标准对话框的窗口类名（MessageBox 用的就是它）
WM_CLOSE = 0x0010
DELIVERY_TIMEOUT_SEC = 25.0


def wait_for_praat(process_id: int, timeout: float = 60.0) -> bool:
    """等**自己启动的那个** Praat 出现对象窗口（用户可能也开着 Praat）。"""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(
            window.process_id == process_id
            and window.title == sendpraat.PRAAT_OBJECTS_TITLE
            for window in sendpraat.praat_windows()
        ):
            time.sleep(1.0)
            return True
        time.sleep(0.3)
    return False


#: 本次用的那个 Praat 的进程号：只碰自己启动的实例，不打扰用户开着的窗口。
TARGET_PID: int | None = None


def deliver(script: str, name: str, directory: Path) -> float:
    """投递一条脚本，返回「完成标记出现」花了多少秒（没出现返回 -1）。"""

    path = directory / f"{name}.praat"
    path.write_text(script, encoding="utf-8")
    chat._clear_result_files()
    started = time.monotonic()
    delivered, note = sendpraat.deliver(AI_DIRECTORY, path, process_id=TARGET_PID)
    if not delivered:
        raise RuntimeError(note)
    deadline = started + DELIVERY_TIMEOUT_SEC
    while time.monotonic() < deadline:
        if chat.state_path().is_file():
            return time.monotonic() - started
        time.sleep(0.1)
    return -1.0


def modal_dialogs() -> list[sendpraat.WindowInfo]:
    """**本次这个** Praat 进程里的模态对话框（``#32770``）。"""

    process_ids = {TARGET_PID} if TARGET_PID else set()
    return [
        window
        for window in sendpraat.list_windows()
        if window.process_id in process_ids and window.class_name == DIALOG_CLASS
    ]


def close_dialog(handle: int) -> None:
    """把对话框点掉（WM_CLOSE 等价于点「确定」）。"""

    ctypes.windll.user32.PostMessageW(handle, WM_CLOSE, 0, 0)


def state_line() -> str:
    return str(chat.state_path()).replace("\\", "/")


def deliver_foreign(statements: str) -> None:
    """像别的程序那样投递一条消息（不带 praat-ai 标记），用来验证「别人的报错照旧弹框」。"""

    path = sendpraat.message_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n# --FULL-TRUST\n" + statements + "\n", encoding="utf-8", newline=""
    )
    window = sendpraat.choose_window(sendpraat.praat_windows(), TARGET_PID)
    ctypes.windll.user32.PostMessageW(window.handle, sendpraat.WM_APP, 0, 0)


def result_text() -> str:
    path = chat.result_path()
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def main() -> int:
    global TARGET_PID
    if not PRAAT.is_file():
        print(f"没有找到 {PRAAT}，请先构建 Praat.exe。")
        return 2
    if sendpraat.praat_windows():
        print("（另外还开着 Praat；这个脚本只操作自己启动的那个实例）")

    process = subprocess.Popen([str(PRAAT)], cwd=str(PROJECT))
    failures = 0
    try:
        if not wait_for_praat(process.pid):
            print("自己启动的 Praat 没有出现对象窗口，超时。")
            return 2
        TARGET_PID = process.pid
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            prepare = (
                'Create Sound from formula: "tone", 1, 0, 1, 44100, '
                "~ 0.5 * sin (2*pi*220*x)\n"
                f'appendFileLine: "{state_line()}", "done"\n'
            )
            elapsed = deliver(prepare, "prepare", directory)
            ok = elapsed >= 0
            print(f"{'OK  ' if ok else 'FAIL'} 准备对象：{elapsed:.2f} 秒")
            failures += 0 if ok else 1

            broken = (
                "selectObject: 1\n"
                "nosuchcommand: 1\n"
                f'appendFileLine: "{state_line()}", "done"\n'
            )
            elapsed = deliver(broken, "broken", directory)
            dialogs = modal_dialogs()
            ok = not dialogs
            print(
                f"{'OK  ' if ok else 'FAIL'} 报错后没有模态框"
                f"（对话框：{[(item.class_name, item.title) for item in dialogs]}，"
                f"用时 {elapsed:.2f} 秒）"
            )
            failures += 0 if ok else 1

            text = result_text()
            ok = "nosuchcommand" in text and 0 <= elapsed <= 5.0
            print(
                f"{'OK  ' if ok else 'FAIL'} 报错马上回到结果文件"
                f"（用时 {elapsed:.2f} 秒）：{text.strip()[:200]!r}"
            )
            failures += 0 if ok else 1

            # 不清掉对话框（用户的真实情形就是这样）：下一条指令必须照样能跑。
            follow_up = f'selectObject: 1\nappendFileLine: "{state_line()}", "done"\n'
            elapsed = deliver(follow_up, "follow-up", directory)
            ok = 0 <= elapsed <= 5.0
            print(
                f"{'OK  ' if ok else 'FAIL'} 报错之后的指令没被挡住（{elapsed:.2f} 秒）"
            )
            failures += 0 if ok else 1

            # 5) 别人的 --send 消息（不带 praat-ai 标记）保持原样：照样弹框，
            #    而且不许把别人的错误写进我们的 runtime 文件。
            chat._clear_result_files()
            deliver_foreign("nosuchcommand: 1\n")
            time.sleep(2.0)
            dialogs = modal_dialogs()
            ok = bool(dialogs) and not chat.failure_path().is_file()
            print(
                f"{'OK  ' if ok else 'FAIL'} 别人的消息照旧弹框"
                f"（对话框 {len(dialogs)} 个，runtime 没被写："
                f"{not chat.failure_path().is_file()}）"
            )
            failures += 0 if ok else 1
    finally:
        for handle in modal_dialogs():
            close_dialog(handle.handle)
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

    total = 5
    print(f"\n{total - failures}/{total} 个「报错不挡消息」用例通过")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
