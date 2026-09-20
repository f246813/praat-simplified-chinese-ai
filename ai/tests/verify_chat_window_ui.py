"""手动回归：对话窗口能不能正常建起来（会短暂显示一个窗口）。

用法（仓库根目录）：

    python ai/tests/verify_chat_window_ui.py

它只构造窗口、跑一轮事件循环再关掉，不发送任何请求。用来确认改过布局、
预设下拉框或状态栏之后窗口没有在初始化时抛异常。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from praat_ai.chat import ChatWindow   # noqa: E402


def main() -> int:
    window = ChatWindow()
    problems: list[str] = []
    try:
        window.root.update()
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
    finally:
        window.root.destroy()
    for problem in problems:
        print(f"!! {problem}")
    print("结论：" + ("窗口正常" if not problems else f"{len(problems)} 项异常"))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
