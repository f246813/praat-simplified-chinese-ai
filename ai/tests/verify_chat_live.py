"""手动回归：用真机 Praat + 真机模型跑一遍对话窗口的执行链路。

用法（仓库根目录，需要先装好 Python 依赖和本地模型服务）：

    python ai/tests/verify_chat_live.py

它会：

1. 新起一个 ``Praat.exe``（用户开着的那些不受影响，脚本只操作自己这个）；
2. 用对话窗口真正的发送函数 ``praat_ai.chat._send_script`` 送一个建声音的脚本；
3. 检查 Praat 有没有写出 ``ai/runtime/chat_context.tsv``（对象列表回传）；
4. 让本地 Qwen 规划「把选中的声音改名为 ...」「查询 0.5 秒处的基频」等请求，
   渲染模板、送给 Praat、把结果读回来；
5. 验证改名之后对象列表里的名字也跟着更新（对话上下文不是过期快照）。

这条链路会写 ``ai/runtime/`` 并启动 GUI，所以只在手动回归时跑，不会被
``unittest discover`` 收集。需要在没有沙箱限制的环境里执行。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praat_ai import chat, sendpraat, tools   # noqa: E402
from praat_ai.config import load_config   # noqa: E402
from praat_ai.qwen import QwenClient   # noqa: E402


PROJECT = Path(__file__).resolve().parents[2]
PRAAT = PROJECT / "Praat.exe"

CREATE_SOUND = "\n".join(
    [
        'Create Sound from formula: "tone", 1, 0, 1, 44100, '
        "~ 0.5 * sin (2*pi*220*x)",
        'appendFileLine: "@STATE@", "done"',
        "",
    ]
)


def praat_running() -> bool:
    return chat.praat_process_running(str(PRAAT))


#: 本次用的那个 Praat 的进程号：用户可能也开着一个 Praat，脚本只碰自己启动的这个。
TARGET_PID: int | None = None


def start_praat() -> subprocess.Popen[bytes] | None:
    global TARGET_PID
    if not PRAAT.is_file():
        raise SystemExit(f"没有找到 {PRAAT}")
    others = chat.praat_process_ids(str(PRAAT)) or []
    if others:
        print(f"· 另外还开着 {len(others)} 个 Praat；这里只操作本次启动的那个")
    print("· 启动 Praat.exe（总是新起一个，免得动到用户开着的窗口）")
    process = subprocess.Popen([str(PRAAT)])
    deadline = time.time() + 60
    while time.time() < deadline:
        if any(
            window.process_id == process.pid
            and window.title == sendpraat.PRAAT_OBJECTS_TITLE
            for window in sendpraat.praat_windows()
        ):
            time.sleep(1.0)   # 等窗口把消息回调挂好并进入空闲状态
            TARGET_PID = process.pid
            return process
        time.sleep(0.5)
    raise SystemExit("Praat 启动超时")


def context_rows() -> tuple[tools.ObjectRow, ...]:
    return tools.parse_object_context(chat.object_context())


def newest_command_script() -> str:
    """最近投递出去的那条命令脚本（``名字:纳秒``）。用来判断「有没有再投一条」。

    不能数文件个数：``runtime/commands`` 到上限会顺手删旧的（``prune_command_scripts``），
    数量会停在 40 不动。
    """

    files = sorted(
        chat.command_dir().glob("chat_command_*.praat"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    if not files:
        return ""
    stat = files[0].stat()
    return f"{files[0].name}:{stat.st_mtime_ns}"


def send(script: str) -> tuple[bool, str]:
    executable = chat.praat_executable()
    if not executable:
        raise SystemExit("没有找到 Praat 可执行文件")
    script = script.replace("@STATE@", chat.state_path().as_posix())
    ok, output = chat._send_script(executable, script, process_id=TARGET_PID)
    results = chat._read_results()
    return ok, ("；".join(results) if results else output.strip())


def ask(client: QwenClient, text: str) -> tuple[str, str, bool]:
    """走对话窗口真正那条路：run_turn 规划 + 投给正在运行的 Praat 执行。

    返回 ``(说明, 结果文字, 是否执行成功)``。
    """

    context = tools.ToolContext(
        objects=context_rows(),
        result_path=chat.result_path(),
        state_path=chat.state_path(),
    )
    executable = chat.praat_executable()

    def execute(script: str) -> tuple[bool, list[str], str]:
        ok, output = chat._send_script(executable, script, process_id=TARGET_PID)
        if not ok:
            return False, [], output or "Praat 没有响应"
        return True, chat._read_results(), ""

    outcome = chat.run_turn(
        client,
        user_text=text,
        context_text=chat.object_context(),
        history=[],
        context=context,
        execute=execute,
    )
    kind = (
        "、".join(f"{step.round_index}:{step.tool}" for step in outcome.steps) or "只回话"
    )
    failed = bool(outcome.steps) and not outcome.results
    detail = "；".join(outcome.results) or outcome.failure
    return f"{outcome.reply}（{kind}）", detail, not failed


def main() -> int:
    failures = 0
    instances = chat.praat_process_ids(str(PRAAT)) or []
    if len(instances) > 1:
        print(
            f"（检测到 {len(instances)} 个 Praat 在运行：{instances}；"
            "这个验证只操作它自己新起的那个，别的窗口不会被动到）"
        )
    started = start_praat()
    config = load_config()
    client = QwenClient(config.qwen)
    if not client.available():
        print("!! 本地模型服务没响应，请先启动前端")
        failures += 1
    try:
        # C5：强制刷一次（这一次会真的投一条 ping，Praat 顺手会把进程标记写进
        # 对象列表），然后再刷一次——第二次必须一条消息都不发。
        #
        # 注意：对象列表文件是所有 Praat 共用的一个文件，同时开着第二个 Praat
        # （例如用户自己的那个）时会互相覆盖，这条检查只有在「只剩本次这个
        # Praat」时才说得清——多实例时跳过，但别的检查照样跑。
        # ``instances`` 是**启动本次实例之前**数到的 Praat：只要当时还有别人的
        # Praat 在跑，对象列表文件就是两个实例共用的，这一条说不清，跳过。
        if not instances:
            print("· 先强制刷新一次对象列表（这一步会投一条 ping）")
            before = newest_command_script()
            refreshed, note = chat.refresh_object_context(
                str(PRAAT), [TARGET_PID], force=True
            )
            forced = newest_command_script()
            print(f"  刷新{'成功' if refreshed else '失败'}：{note}")
            if not refreshed or forced == before:
                print("  !! 强制刷新没有真的投出去")
                failures += 1

            marker = chat.context_pid()
            refreshed, note = chat.refresh_object_context(str(PRAAT), [TARGET_PID])
            after = newest_command_script()
            print(
                f"· C5：第二条消息没有再投 ping（{forced == after}）；"
                f"对象列表里的进程标记 {marker}（本次 Praat 是 {TARGET_PID}）"
            )
            if not refreshed or after != forced:
                print("  !! C5 没生效：第二条消息又投了一次 ping")
                failures += 1
            if marker != TARGET_PID:
                print("  !! 对象列表里的进程标记对不上（Praat.exe 需要重编？）")
                failures += 1
        else:
            print(
                "· C5：另外还开着 Praat，对象列表文件被两个实例共用，"
                "这条检查跳过（单独跑时才有意义；标记本身的检查见 "
                "verify_cancel_live.py 的说明）"
            )

        print("· 送一个建声音的脚本，检查对象列表回传")
        ok, detail = send(CREATE_SOUND)
        print(f"  发送{'成功' if ok else '失败'}：{detail}")
        if not ok:
            failures += 1
        rows = context_rows()
        print(f"  chat_context.tsv：{[(row.id, row.class_name, row.name) for row in rows]}")
        if not rows:
            print("  !! 没有读到对象列表")
            failures += 1

        cases = [
            "阅读当前对象的信息",
            "把当前对象改名为 测试音",
            "查询 0.5 秒处的基频",
            "把这个声音截取 0.2 到 0.5 秒",
            "打开当前声音的编辑器",
            "播放当前声音",
        ]
        for text in cases:
            reply, detail, ok = ask(client, text)
            print(f"· {text}")
            print(f"  执行{'成功' if ok else '失败'}：{reply}")
            if detail:
                print(f"  结果：{detail}")
            if not ok:
                failures += 1
            if text.startswith("把当前对象改名"):
                names = [row.name for row in context_rows()]
                print(f"  改名后的对象列表：{names}")
                if not any("测试音" in name for name in names):
                    print("  !! 对象列表没有跟着刷新")
                    failures += 1
    finally:
        if started is not None:
            print("· 关闭本次启动的 Praat")
            subprocess.run(
                ["taskkill", "/PID", str(started.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
    print(f"\n结论：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
