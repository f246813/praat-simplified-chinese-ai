"""手动回归：对话窗口能不能正常建起来，以及预设下拉框能不能真的切换模型。

用法（仓库根目录）：

    python ai/tests/verify_chat_window_ui.py                  # 只建窗口、跑一轮事件循环
    python ai/tests/verify_chat_window_ui.py --switch-presets # 再走一遍「应用预设」（会重启模型服务）

第一种用来确认改过布局、下拉框或状态栏之后窗口没在初始化时抛异常；第二种会真的点
一次「应用预设」，验证窗口 → control.apply_preset → 重启 llama-server → 刷新状态
这条链路，跑完会把预设切回原来的那个。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praat_ai.chat import ChatWindow   # noqa: E402
from praat_ai.server import running_model   # noqa: E402


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
    window = ChatWindow()
    problems: list[str] = []
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
    finally:
        window.root.destroy()
    for problem in problems:
        print(f"!! {problem}")
    print("结论：" + ("窗口正常" if not problems else f"{len(problems)} 项异常"))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
