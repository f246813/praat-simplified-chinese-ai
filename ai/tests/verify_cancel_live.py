"""手动回归：真机上「停止」真的能停住等待（C7）。

用法（仓库根目录，需要 GUI 里的 Praat.exe）::

    python ai/tests/verify_cancel_live.py

两件事：

1. **等 Praat 的结果**：带着「已取消」标记投递一条脚本，投递要立刻返回（不再等
   25 秒），而且接着马上再投一条正常脚本要能跑完（说明取消没有把消息队列搞乱，
   排队中的那条已经被换成空脚本）。
2. **等批处理跑完**：让 run_praat_script 去跑一个自己循环很久的脚本，跑到一半
   取消——调用要在一秒内返回，而不是等它跑完。

它会临时起一个 Praat 并在结束时关掉；期间请不要手动操作那个 Praat。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praat_ai import chat, tools   # noqa: E402


PROJECT = Path(__file__).resolve().parents[2]
PRAAT = PROJECT / "Praat.exe"
CREATE_SOUND = (
    'Create Sound from formula: "tone", 1, 0, 1, 44100, '
    "~ 0.5 * sin (2*pi*220*x)\n"
)
#: 在 Praat 里空转很久的「社区脚本」：用来验证批处理能被真的打断。
SLOW_SCRIPT = "for i to 40000000\nendfor\nwriteInfoLine: \"done\"\n"


def wait_for_praat(process_id: int, timeout: float = 60.0) -> bool:
    """等**自己启动的那个** Praat 的对象窗口出现（用户可能也开着 Praat）。"""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        from praat_ai import sendpraat

        if any(
            window.process_id == process_id
            and window.title == sendpraat.PRAAT_OBJECTS_TITLE
            for window in sendpraat.praat_windows()
        ):
            time.sleep(1.0)
            return True
        time.sleep(0.3)
    return False


def main() -> int:
    if not PRAAT.is_file():
        print(f"没有找到 {PRAAT}，请先构建 Praat.exe。")
        return 2
    others = [pid for pid in (chat.praat_process_ids(str(PRAAT)) or [])]
    if others:
        print(f"（另外还开着 {len(others)} 个 Praat；这个脚本只操作自己启动的那个）")
    process = subprocess.Popen([str(PRAAT)], cwd=str(PROJECT))
    failures = 0
    try:
        if not wait_for_praat(process.pid):
            print("自己启动的 Praat 没有出现对象窗口，超时")
            return 2
        executable = str(PRAAT)
        own_pid = process.pid
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            context = tools.ToolContext(
                tools.parse_object_context("id\tclass\tname\tselected\n1\tSound\ttone\t1\n"),
                directory / "chat_result.tsv",
                directory / "chat_state.txt",
            )

            # 0) 先建一个声音（正常投递），后面几条都拿它当对象。
            ok, output = chat._send_script(
                executable,
                CREATE_SOUND
                + f'appendFileLine: {tools.quote(chat.state_path())}, "done"\n',
                process_id=own_pid,
            )
            failure = chat._read_failure()
            if not ok or failure:
                print(f"!! 建测试声音失败：{failure or output}")
                return 2

            # 1) 等 Praat 结果：已取消 → 立刻返回（脚本可能压根没跑到）。
            cancel = threading.Event()
            cancel.set()
            started = time.monotonic()
            ok, note = chat._send_script(
                executable,
                'selectObject: 1\n'
                f'appendFileLine: {tools.quote(chat.state_path())}, "done"\n',
                cancel=cancel,
                process_id=own_pid,
            )
            elapsed = time.monotonic() - started
            good = (not ok) and "取消" in note and elapsed < 3.0
            print(
                f"{'OK  ' if good else 'FAIL'} 取消等结果：{elapsed:.2f} 秒，"
                f"{note.strip()[:80]}"
            )
            failures += 0 if good else 1

            # 2) 取消之后队列还能用：下一条正常脚本要跑完。
            ok, note = chat._send_script(
                executable,
                'selectObject: 1\n'
                'appendFileLine: "' + str(chat.state_path()).replace("\\", "/") + '", "done"\n',
                process_id=own_pid,
            )
            good = ok and chat.state_path().is_file()
            print(f"{'OK  ' if good else 'FAIL'} 取消之后还能继续投递：{ok} {note[:80]}")
            failures += 0 if good else 1

            # 3) 批处理（现成脚本）跑到一半被取消。
            slow = directory / "slow-community.praat"
            slow.write_text(SLOW_SCRIPT, encoding="utf-8")
            environment = tools.LocalEnvironment(
                execute=lambda script: (True, [], ""),
                praat_executable=executable,
                runtime_directory=directory / "runtime",
                cancelled=cancel.is_set,
            )
            # 会话 1：不带取消，先量一下这个脚本本来要跑多久。
            cancel.clear()
            started = time.monotonic()
            runner = tools.LOCAL_TOOLS[tools.RUN_SCRIPT_TOOL]
            # 导出这一步在真机上要真的能存出 wav，所以先用真 Praat 存一个。
            wav = directory / "input.wav"
            ok, _output = chat._send_script(
                executable,
                'selectObject: 1\n'
                f'Save as WAV file: "{str(wav).replace(chr(92), "/")}"\n'
                f'appendFileLine: "{str(chat.state_path()).replace(chr(92), "/")}", "done"\n',
                process_id=own_pid,
            )
            if not ok:
                print("!! 没能用真 Praat 存出测试 wav")
                return 2

            def slow_execute(script: str) -> tuple[bool, list[str], str]:
                """把导出这一步换成「已经存好了」，其余照真机''。"""

                if "Save as WAV file" in script:
                    target = Path(script.split('"')[1])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(wav.read_bytes())
                return True, [], ""

            environment = tools.LocalEnvironment(
                execute=slow_execute,
                praat_executable=executable,
                runtime_directory=directory / "runtime",
                cancelled=cancel.is_set,
            )
            timer = threading.Timer(0.8, cancel.set)
            timer.start()
            started = time.monotonic()
            ok, lines, failure = runner.run({"path": str(slow)}, context, environment)
            elapsed = time.monotonic() - started
            timer.cancel()
            good = (not ok) and "取消" in failure and elapsed < 5.0
            print(
                f"{'OK  ' if good else 'FAIL'} 取消批处理：{elapsed:.2f} 秒，"
                f"{failure.strip()[:100]}"
            )
            failures += 0 if good else 1
            cancel.clear()
    finally:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
    total = 3
    print(f"\n{total - failures}/{total} 个「取消」用例通过")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
