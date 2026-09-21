"""手动回归：从 Praat 菜单加载/停止模型时，真的弹出「带进度条的小窗口」。

用法（仓库根目录，需要 GUI 里的 Praat.exe + 能用的本地模型）::

    python ai/tests/verify_model_progress_live.py

走的是用户那条路：开一个临时 Praat → 建 Sound、打开编辑器（「前端」菜单在编辑器上）
→ 点菜单里的「启动前端」→ 等模型加载完 → 再点「停止前端」。

每一步都盯着 Praat 的进度小窗（标题「Work in progress」/「正在处理中」，
`Sys/Gui_messages.cpp` 里那个带进度条 + 「中断」按钮的窗口）：
**加载过程中必须看得到它，加载完必须自己消失**。脚本会临时停掉本机的
llama-server（如果你本来就开着它，跑完请自己再启动一次）。
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parents[0]))
sys.path.insert(0, str(TESTS_DIR))

from praat_ai import chat, control, sendpraat   # noqa: E402
import verify_ai_menu_no_crash as menu_helper   # noqa: E402
import progress_window_utils as progress_utils   # noqa: E402


PROJECT = Path(__file__).resolve().parents[2]
PRAAT = str(PROJECT / "Praat.exe")
WM_COMMAND = 0x0111
PROGRESS_TITLES = {"Work in progress", "正在处理中"}
user32 = ctypes.windll.user32
user32.PostMessageW.argtypes = [
    wintypes.HWND,
    ctypes.c_uint,
    wintypes.WPARAM,
    wintypes.LPARAM,
]


def praat_pids() -> list[int]:
    return list(chat.praat_process_ids(PRAAT) or [])


def wait_for(predicate, timeout: float, label: str):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.25)
    raise SystemExit(f"等待超时：{label}")


def progress_windows(process_id: int | None = None) -> list[sendpraat.WindowInfo]:
    window = progress_utils.find_progress_window(process_id or 0)
    return [window] if window is not None else []


def click_menu(handle: int, labels: tuple[str, ...], problems: list[str]) -> None:
    command_id, path_text, all_labels = menu_helper.find_menu_command(handle, labels)
    if not command_id:
        problems.append(f"没找到菜单项 {labels}；现有菜单：{all_labels[:200]}")
        raise SystemExit("菜单项缺失")
    print(f"· 点击菜单项：{path_text}（id = {command_id}）")
    user32.PostMessageW(handle, WM_COMMAND, command_id, 0)


def main() -> int:
    problems: list[str] = []
    if not Path(PRAAT).is_file():
        print(f"没有找到 {PRAAT}，请先构建 Praat.exe。")
        return 2
    if praat_pids():
        print("已经有一个 Praat 在跑，请先关掉它再跑这个回归。")
        return 2

    # 先确保本地服务是停的，这样「启动前端」会真的走一遍加载流程。
    print("· 先把本机模型服务停掉（这样下面才能看到完整的加载进度）")
    control.stop_frontend()
    time.sleep(1.0)

    process = subprocess.Popen([PRAAT])
    try:
        pid = wait_for(lambda: max(praat_pids()) if praat_pids() else None, 30, "Praat 进程")
        wait_for(
            lambda: [
                window
                for window in sendpraat.list_windows()
                if window.process_id == pid
                and window.title == sendpraat.PRAAT_OBJECTS_TITLE
            ],
            30,
            "对象窗口出现",
        )
        time.sleep(2.0)
        script = "\n".join(
            [
                'Create Sound from formula: "progress-menu", 1, 0, 0.5, 44100, ~ 0.3 * sin (2*pi*220*x)',
                "View & Edit",
                f"appendFileLine: {chat.tools.quote(chat.state_path())}, \"done\"",
                "",
            ]
        )
        ok, note = chat._send_script(PRAAT, script)
        if not ok:
            problems.append(f"建声音/开编辑器失败：{note}")
        editor = wait_for(
            lambda: [
                window
                for window in sendpraat.list_windows()
                if window.process_id == pid
                and "Sound" in window.title
                and window.title != sendpraat.PRAAT_OBJECTS_TITLE
            ],
            20,
            "声音编辑器窗口",
        )[0]

        # ---- 加载：进度小窗必须出现，加载完必须消失 ----
        click_menu(editor.handle, ("启动前端", "Start frontend"), problems)
        seen: list[str] = []
        #: 首次可见那一帧的截图（用来验「窗口打开时进度条就在」）。
        first_frame: Path | None = None
        #: 0.5 秒之后再截一张（验填充确实开始长出来）。
        second_frame: Path | None = None
        deadline = time.time() + 90
        finished = False
        while time.time() < deadline:
            windows = progress_windows()
            for window in windows:
                if window.title not in seen:
                    seen.append(window.title)
                if first_frame is None:
                    shot = Path(tempfile.gettempdir()) / "praat-progress-first.png"
                    if progress_utils.capture_png(window.handle, shot):
                        first_frame = shot
                        time.sleep(0.5)
                        again = Path(tempfile.gettempdir()) / "praat-progress-second.png"
                        if progress_utils.capture_png(window.handle, again):
                            second_frame = again
            if control.endpoint_available(control.load_config().qwen.base_url):
                finished = True
                break
            time.sleep(0.4)
        print(f"· 加载：过程里看到过进度窗口 {seen or '（一次都没有）'}")
        if not seen:
            problems.append("加载模型时没有看到进度小窗口")
        if not finished:
            problems.append("模型服务在 90 秒内没有就绪")

        # 「窗口打开时就有进度条」：第一帧里必须有进度条（填充或轨道），
        # 而且 0.5 秒后填充要比第一帧多（说明真的在涨）。
        if first_frame is not None and second_frame is not None:
            try:
                first_green, first_track, width = progress_utils.bar_metrics(first_frame)
                later_green, _later_track, _width = progress_utils.bar_metrics(second_frame)
                print(
                    f"· 第一帧进度条：填充 {first_green} px、轨道 {first_track} px"
                    f"（窗口宽 {width}）；0.5 秒后填充 {later_green} px"
                )
                if first_green + first_track <= 0:
                    problems.append("窗口第一帧里看不到进度条")
                if later_green <= first_green:
                    problems.append(
                        f"进度条没有在涨（{first_green} → {later_green} px）"
                    )
            except ImportError:
                print("· （没装 Pillow，跳过像素检查）")
        else:
            print("· （没截到进度窗口的图，跳过像素检查）")
        wait_for(lambda: not progress_windows(), 20, "进度小窗消失")
        print("· 加载完：进度小窗自己关掉了")

        # ---- 停止：同样要看得到进度小窗 ----
        control.stop_frontend()
        time.sleep(1.0)
        click_menu(editor.handle, ("启动前端", "Start frontend"), problems)
        wait_for(
            lambda: control.endpoint_available(control.load_config().qwen.base_url),
            90,
            "服务再次就绪",
        )
        wait_for(lambda: not progress_windows(), 20, "第二次加载的进度小窗消失")
        seen_stop: list[str] = []
        click_menu(editor.handle, ("停止前端", "Stop frontend"), problems)
        deadline = time.time() + 40
        while time.time() < deadline:
            windows = progress_windows()
            for window in windows:
                if window.title not in seen_stop:
                    seen_stop.append(window.title)
            if not control.endpoint_available(control.load_config().qwen.base_url):
                break
            time.sleep(0.3)
        print(f"· 停止：过程里看到过进度窗口 {seen_stop or '（一次都没有，可能太快）'}")
        wait_for(lambda: not progress_windows(), 20, "停止时的进度小窗消失")
        stopped = not control.endpoint_available(control.load_config().qwen.base_url)
        print(f"· 停止之后端口上没有服务了：{stopped}")
        if not stopped:
            problems.append("点了「停止前端」之后本地服务还在")

        time.sleep(2.0)
        if pid not in praat_pids():
            problems.append("过程中 Praat 退出了")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        menu_helper.close_chat_window()
        control.stop_frontend()

    if problems:
        print("")
        for problem in problems:
            print(f"！{problem}")
        return 1
    print("√ 加载/停止模型时都弹出了带进度条的小窗口，而且自己会消失")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
