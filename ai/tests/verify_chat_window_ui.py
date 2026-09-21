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

        # 加载/停止模型时的「简约小窗口 + 进度条」（C7 那块 UI 之外的新东西）：
        # 这里只验数据通路——队列里来一条进度就弹小窗，来一条 progress-done 就关掉。
        try:
            window.messages.put(("progress", "0.30|正在加载模型…"))
            pump(window, 2)
            popup = window.progress_window
            print(
                "· 进度小窗："
                + (
                    f"出现，进度 {popup.bar.cget('value')}，文案「{popup.message.get()}」"
                    if popup is not None
                    else "没有出现"
                )
            )
            if popup is None:
                problems.append("发进度消息之后没有出现小窗")
            else:
                if abs(float(popup.bar.cget("value")) - 30.0) > 0.01:
                    problems.append(f"进度条没跟上（{popup.bar.cget('value')}）")
                window.messages.put(("progress", "0.80|正在启动模型服务…"))
                pump(window, 2)
                if abs(float(popup.bar.cget("value")) - 80.0) > 0.01:
                    problems.append(f"进度条没有更新（{popup.bar.cget('value')}）")
                window.messages.put(("progress-done", ""))
                # 小窗有最短显示时间（progress_popup.MINIMUM_VISIBLE_SEC = 0.8 秒），
                # 所以必须抽满事件循环再看它关没关：until_idle 会在窗口不忙时立刻
                # 返回，那样还没到 0.8 秒就误判成「小窗没有关掉」。
                pump(window, 2, until_idle=False)
                if window.progress_window is not None:
                    problems.append("进度结束后小窗没有关掉")
        except Exception as error:   # noqa: BLE001 - 这一条只是 UI 冒烟
            problems.append(f"进度小窗检查失败：{error}")

        # 「API 配置」入口：按钮在，点了能开出一个标题是「API 配置」的小窗。
        try:
            print(f"· API 配置按钮：{window.api_button.cget('text')}")
            window.open_api_settings()
            pump(window, 1)
            dialog = getattr(window, "api_dialog", None)
            if dialog is None:
                problems.append("点「API 配置…」没有打开窗口")
            else:
                print(f"· API 配置窗口标题：{dialog.window.title()}")
                dialog.close()
                pump(window, 1)
        except Exception as error:   # noqa: BLE001
            problems.append(f"API 配置窗口检查失败：{error}")

        # 「可以输入 api key」这件事要真的验一遍：填 key → 保存 → 写进配置。
        # 用**临时配置**，绝不碰真实的 ai_config.json。
        try:
            import json
            import tempfile

            from praat_ai import api_settings

            with tempfile.TemporaryDirectory() as raw:
                path = Path(raw) / "ai_config.json"
                path.write_text(
                    json.dumps(
                        {
                            "qwen": {"base_url": "http://127.0.0.1:8000/v1", "model": "local.gguf"},
                            "server": {"model_path": "D:/models/local.gguf"},
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                dialog = api_settings.ApiSettingsDialog(window.root, config_path=path)
                print(f"· API 配置窗口的 key 输入框：show = {dialog.key_entry.cget('show')!r}")
                if str(dialog.key_entry.cget("show")) != "•":
                    problems.append("API key 输入框默认没有打码")
                dialog.provider.set("DeepSeek")
                dialog._on_provider()
                dialog.model.set("deepseek-chat")
                dialog.api_key.set("sk-live-test")
                dialog.enabled.set(True)
                dialog.save()
                pump(window, 1)
                saved = json.loads(path.read_text(encoding="utf-8")).get("api", {})
                ok = (
                    saved.get("api_key") == "sk-live-test"
                    and saved.get("enabled") is True
                    and saved.get("model") == "deepseek-chat"
                    and saved.get("base_url", "").startswith("https://")
                )
                print(
                    f"· 填 key 并保存：{'成功' if ok else '失败'} "
                    f"（enabled={saved.get('enabled')}, model={saved.get('model')}, "
                    f"key 长度={len(saved.get('api_key', ''))}）"
                )
                if not ok:
                    problems.append(f"「填 API key 并保存」没有写进配置：{saved}")
                # 接上云端模型之后，窗口上方那一行「模型预设」必须显示**当前**模型
                # （2026-09-21 用户报的：还是显示本地 qwen 模型）。
                from praat_ai.config import api_is_active, load_config

                cloud = load_config(path)
                print(f"· 切到云端配置：api_is_active={api_is_active(cloud)}")
                window.config = cloud
                window.refresh_preset_widgets()
                pump(window, 1)
                shown = window.preset_choice.get()
                print(f"· 预设框显示：{shown!r}")
                if "deepseek-chat" not in shown or "云端 API" not in shown:
                    problems.append(f"接上 API 之后预设框没显示当前云端模型：{shown!r}")
                # 选中的就是「当前在用的云端模型」：点「应用预设」不该去重启本地服务。
                window.apply_selected_preset()
                pump(window, 1)
                if window.busy:
                    problems.append("选中云端那一行再点「应用预设」进入了忙碌状态")
                else:
                    print("· 选中云端那一行再点「应用预设」：没有触发本地模型切换")
                window.reload_config()
                pump(window, 1)
        except Exception as error:   # noqa: BLE001
            problems.append(f"API key 保存检查失败：{error}")
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
