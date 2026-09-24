"""手动回归：关掉 Praat 之后，对话窗口要跟着退出（2026-09-21 用户报的 bug）。

以前对话窗口是脱离 Praat 起的独立进程，谁也不知道 Praat 什么时候关，于是 Praat
关了它还杵在桌面上。现在启动前端时会带上 ``PRAAT_AI_PRAAT_PID`` /
``PRAAT_AI_PRAAT_EXECUTABLE``（见 sys/PraatAiControl.cpp），窗口每秒看一眼
（ai/praat_ai/parent_watch.py）。

这个脚本不需要模型、也不需要点菜单：

1. 起一个临时 Praat；
2. 按菜单的方式（带那两个环境变量）跑 ``ai/start_ai_chat.py``；
3. Praat 还活着时，窗口必须一直开着（别误关）；
4. 关掉 Praat，窗口必须在几秒内自己消失、进程退出、``chat.pid`` 清掉。

用法（仓库根目录）::

    python ai/tests/verify_frontend_follows_praat.py
    python ai/tests/verify_frontend_follows_praat.py --menu   # 走真菜单（要本地模型）

``--menu`` 那条更接近用户的真实路径：点「前端 → 启动前端」→ 本地模型起来 →
对话窗口弹出（环境变量由 Praat 的 C++ 侧写进去）→ 关掉 Praat → 窗口要跟着退。
它比不带参数的版本慢几十秒（要加载模型），也顺带验证了 C++ 那边的接线。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent))
sys.path.insert(0, str(TESTS_DIR))

from praat_ai import chat, sendpraat   # noqa: E402


PROJECT = Path(__file__).resolve().parents[2]
PRAAT = str(PROJECT / "Praat.exe")
CHAT_TITLE = "Praat AI 对话"


def chat_windows() -> list:
    return [
        window
        for window in sendpraat.list_windows()
        if window.visible and window.title == CHAT_TITLE
    ]


def wait_for(predicate, timeout: float, step: float = 0.25):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return None


def stop_chat_window() -> None:
    pid_file = Path(chat.runtime_dir()) / "chat.pid"
    if pid_file.is_file():
        try:
            chat_pid = int(pid_file.read_text(encoding="utf-8").strip())
        except ValueError:
            chat_pid = 0
        if chat_pid:
            subprocess.run(
                ["taskkill", "/PID", str(chat_pid), "/T", "/F"], capture_output=True
            )
        try:
            pid_file.unlink()
        except OSError:
            pass
    for window in chat_windows():
        subprocess.run(
            ["taskkill", "/PID", str(window.process_id), "/F"], capture_output=True
        )


def main() -> int:
    problems: list[str] = []
    use_menu = "--menu" in sys.argv
    print("· 先把可能开着的对话窗口收掉")
    stop_chat_window()
    time.sleep(0.5)

    print("· 开一个临时 Praat")
    praat = subprocess.Popen([PRAAT])
    praat_pid = wait_for(
        lambda: next(
            (
                w.process_id
                for w in sendpraat.list_windows()
                if w.process_id == praat.pid
                and w.title == sendpraat.PRAAT_OBJECTS_TITLE
            ),
            None,
        ),
        30,
    )
    if not praat_pid:
        print("！对象窗口没出来")
        praat.terminate()
        return 1
    print(f"  pid={praat_pid}")

    if use_menu:
        print("· 点菜单「前端 → 启动前端」（真路径：会顺便把本地模型拉起来）")
        import ctypes

        import verify_ai_menu_no_crash as menu_helper

        script = "\n".join(
            [
                'Create Sound from formula: "follow-praat", 1, 0, 0.3, 44100,'
                " ~ 0.3 * sin (2*pi*220*x)",
                "View & Edit",
                f'appendFileLine: {chat.tools.quote(chat.state_path())}, "done"',
                "",
            ]
        )
        chat._send_script(PRAAT, script)
        editor = wait_for(
            lambda: next(
                (
                    w
                    for w in sendpraat.list_windows()
                    if w.process_id == praat_pid
                    and w.visible
                    and "Sound" in w.title
                    and w.title != sendpraat.PRAAT_OBJECTS_TITLE
                ),
                None,
            ),
            20,
        )
        if editor is None:
            problems.append("编辑器窗口没出来，没法点菜单")
            subprocess.run(
                ["taskkill", "/PID", str(praat_pid), "/T", "/F"], capture_output=True
            )
            return 1
        command_id, path_text, labels = menu_helper.find_menu_command(
            editor.handle, ("启动前端", "Start frontend")
        )
        if not command_id:
            problems.append(f"没找到「启动前端」；现有菜单：{labels}")
            subprocess.run(
                ["taskkill", "/PID", str(praat_pid), "/T", "/F"], capture_output=True
            )
            return 1
        print(f"  触发 {path_text}（id={command_id}）")
        ctypes.windll.user32.PostMessageW(editor.handle, 0x0111, command_id, 0)
    else:
        print("· 按菜单的方式启动对话窗口（带上 Praat 的进程号和路径）")
        environment = dict(os.environ)
        environment["PRAAT_AI_PRAAT_PID"] = str(praat_pid)
        environment["PRAAT_AI_PRAAT_EXECUTABLE"] = PRAAT
        environment["PYTHONPATH"] = str(PROJECT / "ai")
        launcher = subprocess.run(
            [sys.executable, str(PROJECT / "ai" / "start_ai_chat.py")],
            capture_output=True,
            text=True,
            env=environment,
            timeout=60,
        )
        if launcher.returncode != 0:
            problems.append(
                f"启动器退出码 {launcher.returncode}：{launcher.stderr.strip()[:200]}"
            )

    window = wait_for(lambda: chat_windows() or None, 90 if use_menu else 30)
    if window is None:
        problems.append("对话窗口没有出现")
        print(f"！{problems[-1]}")
        praat.terminate()
        stop_chat_window()
        return 1
    chat_pid = window[0].process_id
    print(f"  对话窗口 pid={chat_pid}")

    print("· Praat 还开着：等 3 秒，窗口不许自己关掉")
    time.sleep(3.0)
    if not chat_windows():
        problems.append("Praat 还在的时候对话窗口就关掉了")

    print("· 关掉 Praat")
    subprocess.run(
        ["taskkill", "/PID", str(praat_pid), "/T", "/F"], capture_output=True
    )
    closed = wait_for(lambda: not chat_windows(), 15)
    still_there = chat_windows()
    print(f"  对话窗口{'已经跟着关掉' if closed else '还开着'}")
    if not closed:
        problems.append("关掉 Praat 之后对话窗口没有退出")

    pid_file = Path(chat.runtime_dir()) / "chat.pid"
    if closed and pid_file.is_file():
        try:
            leftover = int(pid_file.read_text(encoding="utf-8").strip())
        except ValueError:
            leftover = 0
        if leftover and chat.process_alive(leftover):
            problems.append("窗口关了但进程还在、chat.pid 也没清")

    print("· 收尾")
    if praat.poll() is None:
        subprocess.run(
            ["taskkill", "/PID", str(praat_pid), "/T", "/F"], capture_output=True
        )
    if still_there:
        stop_chat_window()
    if use_menu:
        # 菜单那条路会把本地 llama-server 拉起来；跑完别把它留着。
        from praat_ai import control

        print("· 停掉本地模型服务")
        try:
            control.stop_frontend()
        except Exception as error:   # noqa: BLE001 - 收尾失败不影响结论
            print(f"  （停服务时出错：{error}）")

    if problems:
        print("结论：" + str(len(problems)) + " 项异常")
        for item in problems:
            print(f"  ！{item}")
        return 1
    print("√ 关掉 Praat 之后对话窗口自己退出了；Praat 还在时它不会被误关")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
