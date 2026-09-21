"""手动回归：对话窗口能不能正常建起来，以及预设下拉框能不能真的切换模型。

用法（仓库根目录）：

    python ai/tests/verify_chat_window_ui.py                  # 只建窗口、跑一轮事件循环
    python ai/tests/verify_chat_window_ui.py --switch-presets # 再走一遍「应用预设」（会重启模型服务）
    python ai/tests/verify_chat_window_ui.py --ask            # 在真窗口里发一条请求并等结果

第一种用来确认改过布局、下拉框或状态栏之后窗口没在初始化时抛异常；第二种会真的点
一次「应用预设」，验证窗口 → control.apply_preset → 重启 llama-server → 刷新状态
这条链路（跑完切回原来的预设）；第三种会走完「输入 → 规划 → 送脚本 → 读结果 →
上屏」整条路径，需要 Praat 和本地模型都在（会临时开一个 Praat 并关掉）。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praat_ai import chat   # noqa: E402
from praat_ai.chat import ChatWindow   # noqa: E402
from praat_ai.server import running_model   # noqa: E402


CREATE_SOUND = (
    'Create Sound from formula: "tone", 1, 0, 1, 44100, '
    '~ 0.5 * sin (2*pi*220*x)\n'
)


def ensure_praat(problems: list[str]) -> subprocess.Popen[bytes] | None:
    executable = chat.praat_executable()
    if not executable:
        problems.append("没有找到 Praat 可执行文件")
        return None
    if chat.praat_process_running(executable):
        return None
    process = subprocess.Popen([executable])
    deadline = time.time() + 30
    while time.time() < deadline:
        if chat.praat_process_running(executable):
            time.sleep(6)
            return process
        time.sleep(0.5)
    problems.append("Praat 启动超时")
    return process


def ask_through_window(window: ChatWindow, problems: list[str]) -> None:
    """走一遍「用户输入 → 规划 → 执行 → 结果显示」的真实路径。"""

    executable = chat.praat_executable()
    ok, output = chat._send_script(
        executable,
        CREATE_SOUND
        + f'appendFileLine: {chat.tools.quote(chat.state_path())}, "done"\n',
    )
    if not ok:
        problems.append(f"建测试声音失败：{output}")
        return
    chat.refresh_object_context(executable)
    window.context_label.set(chat.selected_object_label())

    window.entry.delete("1.0", "end")
    window.entry.insert("1.0", "这个声音的总时长是多少")
    window.submit()
    pump(window, 120)
    transcript = window.transcript.get("1.0", "end")
    tail = "\n".join(line for line in transcript.splitlines()[-8:] if line.strip())
    print("· 窗口里的最后几行：")
    print(tail)
    if "总时长" not in transcript:
        problems.append("对话窗口没有把结果写回界面")
    if window.busy:
        problems.append("请求结束后窗口仍是忙碌状态")


def pump(window: ChatWindow, seconds: float, until_idle: bool = True) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        window.root.update()
        window.flush_messages()
        if until_idle and not window.busy:
            return
        time.sleep(0.1)


def switch_preset(window: ChatWindow, label: str, problems: list[str]) -> None:
    window.preset_choice.set(label)
    window.apply_selected_preset()
    pump(window, 90)
    status = window.status.get()
    print(f"· 切到「{label.split(' ·')[0]}」后状态栏：{status}")
    live = Path(running_model(window.config.qwen.base_url)).name
    expected = Path(window.config.server.model_path).name
    if live != expected:
        problems.append(f"端口上是 {live}，配置里是 {expected}")
    if window.busy:
        problems.append("切换之后窗口一直处于忙碌状态")


def main() -> int:
    switch = "--switch-presets" in sys.argv[1:]
    ask = "--ask" in sys.argv[1:]
    window = ChatWindow()
    problems: list[str] = []
    started: subprocess.Popen[bytes] | None = None
    try:
        pump(window, 2)
        labels = list(window.preset_box.cget("values"))
        print(f"· 预设下拉框：{labels}")
        if not labels:
            problems.append("下拉框是空的（配置里没有 server.presets？）")
        print(f"· 状态栏：{window.status.get()}")
        if "模型：" not in window.status.get():
            problems.append("状态栏没有显示模型")
        print(f"· 预设说明：{window.preset_hint.get()}")
        print(f"· 对象提示：{window.context_label.get()}")
        print(f"· 输入框可用：{window.entry.cget('state')}")
        # C7：等待可以取消。这里只验按钮和事件接上了（真投递的取消在
        # verify_cancel_live.py 里用真 Praat 跑）。
        try:
            print(
                "· 停止按钮：初始 "
                f"{window.stop_button.cget('state')}，事件 "
                f"{window.cancel_event.is_set()}"
            )
            if str(window.stop_button.cget("state")) != "disabled":
                problems.append("停止按钮初始应该是禁用状态")
            window.busy = True
            window.stop_button.configure(state="normal")
            window.cancel_turn()
            if not window.cancel_event.is_set():
                problems.append("点「停止」没有把取消事件置上")
            window.cancel_event.clear()
            window.busy = False
            window.stop_button.configure(state="disabled")
        except AttributeError as error:
            problems.append(f"对话窗口没有停止按钮：{error}")
        window.flush_messages()

        if switch and len(labels) >= 2:
            original = window.preset_choice.get()
            other = next(label for label in labels if label != original)
            switch_preset(window, other, problems)
            pump(window, 2)
            switch_preset(window, original, problems)
            pump(window, 2)
        elif switch:
            problems.append("预设少于两个，无法验证切换")

        if ask:
            started = ensure_praat(problems)
            if not problems:
                ask_through_window(window, problems)
    finally:
        if started is not None:
            print("· 关闭本次启动的 Praat")
            subprocess.run(
                ["taskkill", "/PID", str(started.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        window.root.destroy()
    for problem in problems:
        print(f"!! {problem}")
    print("结论：" + ("窗口正常" if not problems else f"{len(problems)} 项异常"))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
