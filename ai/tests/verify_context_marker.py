"""手动回归：对象列表里的进程标记（C5 的另一半）。

用法（仓库根目录，需要 GUI 里的 Praat.exe）::

    python ai/tests/verify_context_marker.py

``ai/runtime/chat_context.tsv`` 里那句 ``# praat-pid=<进程号>`` 是 Praat 写进去的
（``sys/PraatAiControl.cpp`` 的 ``writeChatContext``）。前端看到标记就是**当前这个**
Praat，就直接用这份列表，不再投那条 ping（C5）。这里验证：

1. 本次启动的 Praat 真的会把**自己的进程号**写进去；
2. 标记就是这个进程时，再刷新一次**一条消息都不发**。

注意：对象列表文件是所有 Praat 共用的一个文件。同时开着别的 Praat（比如用户自己
那个）时它可能覆盖标记，所以这个脚本会重试几轮；仍然对不上就报出来。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praat_ai import chat, sendpraat, tools   # noqa: E402


PROJECT = Path(__file__).resolve().parents[2]
PRAAT = PROJECT / "Praat.exe"
CREATE_SOUND = (
    'Create Sound from formula: "tone", 1, 0, 1, 44100, '
    "~ 0.5 * sin (2*pi*220*x)\n"
)


def wait_for_own_window(process_id: int, timeout: float = 60.0) -> bool:
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


def newest_command_script() -> str:
    files = sorted(
        chat.command_dir().glob("chat_command_*.praat"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    return files[0].name if files else ""


def wait_for_marker(process_id: int, timeout: float = 5.0) -> int:
    """等标记变成我们自己的进程号。

    Praat 那边是「脚本先写完成标记，再重写对象列表」，所以前端刚看到完成时列表还
    可能是上一份；另外同时开着别的 Praat 时它也可能覆盖。这里轮询一小会儿，
    只要**看到过**自己的标记就算过。
    """

    deadline = time.monotonic() + timeout
    seen = 0
    while time.monotonic() < deadline:
        seen = chat.context_pid()
        if seen == process_id:
            return seen
        time.sleep(0.1)
    return seen


def main() -> int:
    if not PRAAT.is_file():
        print(f"没有找到 {PRAAT}，请先构建 Praat.exe。")
        return 2
    others = chat.praat_process_ids(str(PRAAT)) or []
    if others:
        print(f"（另外还开着 {len(others)} 个 Praat：{others}；标记可能被它覆盖，会重试）")
    process = subprocess.Popen([str(PRAAT)], cwd=str(PROJECT))
    failures = 0
    try:
        if not wait_for_own_window(process.pid):
            print("自己启动的 Praat 没有出现对象窗口，超时")
            return 2
        executable = str(PRAAT)
        for attempt in range(1, 4):
            chat._clear_result_files()
            ok, output = chat._send_script(
                executable,
                CREATE_SOUND
                + f'appendFileLine: {tools.quote(chat.state_path())}, "done"\n',
                process_id=process.pid,
            )
            if not ok:
                print(f"投递失败：{output}")
                failures += 1
                break
            marker = wait_for_marker(process.pid)
            if marker == process.pid:
                break
            print(f"  第 {attempt} 次没等到自己的标记（读到 {marker}），再试一次")
        ok = marker == process.pid
        print(
            f"{'OK  ' if ok else 'FAIL'} Praat 写下的进程标记 {marker}"
            f"（本次实例 {process.pid}）"
        )
        failures += 0 if ok else 1

        # 标记对上之后：再刷一次不该再投脚本。
        if ok:
            before = newest_command_script()
            refreshed, note = chat.refresh_object_context(executable, [process.pid])
            after = newest_command_script()
            quiet = before == after
            print(
                f"{'OK  ' if refreshed and quiet else 'FAIL'} 标记对上后不再投 ping"
                f"（{before} → {after}）{note[:60]}"
            )
            failures += 0 if (refreshed and quiet) else 1
    finally:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    total = 2
    print(f"\n{total - failures}/{total} 个「进程标记」用例通过")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
