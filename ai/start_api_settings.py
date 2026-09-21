"""从 Praat 菜单拉起「API 配置」小窗：立刻返回，绝不让 Praat 等着。

2026-09-21 用户报的「配置 API 时缩小语图窗口或主窗口会崩」：原来菜单项直接走
``runControlCommand("api-config")``，也就是 `praat_runPythonScriptFile` —— Praat
会在那里**读子进程的标准输出直到子进程退出**，而 Tk 那种窗口要一直挂到用户点
关闭才退出，于是 Praat 的主线程整个被堵住（实测 `Responding=False`）：窗口变成
白板、缩窗变幽灵、再点关闭就是「未响应 → 结束进程」，看起来就是崩溃。

这里跟 start_ai_chat.py 一个套路：这个脚本只负责把真正的窗口进程**脱离**着拉起来
（父进程立刻退出），Praat 等到的只是 Python 启动那零点几秒。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def start_api_settings_window(directory: Path) -> int:
    script = directory / "run_api_settings.py"
    creation_flags = 0
    if os.name == "nt":
        # 不要控制台窗口，但也不要跟 Praat 死绑在一起。
        creation_flags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    subprocess.Popen(
        [sys.executable, str(script)],
        cwd=directory,
        creationflags=creation_flags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return 0


def main() -> int:
    return start_api_settings_window(Path(__file__).resolve().parent)


if __name__ == "__main__":
    raise SystemExit(main())
