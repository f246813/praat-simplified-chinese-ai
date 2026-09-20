"""Praat AI 对话窗口。

前端流程：

1. 读取 Praat 写出的对象列表（``runtime/chat_context.tsv``）。
2. Qwen 只负责选择工具并填参数，脚本由 :mod:`praat_ai.tools` 用固定模板生成。
3. 脚本通过 :mod:`praat_ai.sendpraat` 送到正在运行的 Praat 里执行（自己写
   ``Message.txt`` 再发 ``WM_APP``，不激活 Praat 的任何窗口）。
4. 脚本把数值结果写进 ``runtime/chat_result.tsv``，执行完成写
   ``runtime/chat_state.txt``；对话窗口轮询到完成标记后把结果读回来显示。

注意：``An instance of Praat that is not me is already running.`` 是
``--send`` 转发脚本时的常规提示，不是错误，所以不显示给用户。
"""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from . import sendpraat, tools
from .config import load_config
from .presets import PresetError, active_preset, list_presets
from .qwen import QwenClient, QwenError
from .server import running_model_info


SEND_NOISE = (
    "An instance of Praat that is not me is already running.",
)

EXECUTION_TIMEOUT_SEC = 25.0


def context_ping_script() -> str:
    """一条不需要任何对象的脚本：Praat 每执行完一条命令都会刷新对象列表文件，
    所以用它既能确认 Praat 还在响应，又能把 ``chat_context.tsv`` 更新到最新。

    只能写文件：``appendInfoLine`` 这类命令会走 ``gui_information()``，把
    「Praat Info」窗口弹出来（这就是用户报的那个 bug，见 guide.md §8.5）。
    """

    return f'appendFileLine: {tools.quote(state_path())}, "done"\n'


def ai_directory() -> Path:
    """前端自己的目录（Praat 消息里的工作目录，相对路径按它解析）。"""

    return Path(__file__).resolve().parents[1]


def runtime_dir() -> Path:
    path = Path(__file__).resolve().parents[1] / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def context_path() -> Path:
    return runtime_dir() / "chat_context.tsv"


def result_path() -> Path:
    return runtime_dir() / "chat_result.tsv"


def state_path() -> Path:
    return runtime_dir() / "chat_state.txt"


def script_path() -> Path:
    return runtime_dir() / "chat_command.praat"


def send_log_path() -> Path:
    return runtime_dir() / "chat_send.log"


def praat_executable() -> str:
    configured = os.getenv("PRAAT_AI_PRAAT_EXECUTABLE", "").strip()
    if configured:
        return configured
    candidate = Path(__file__).resolve().parents[2] / "Praat.exe"
    if candidate.is_file():
        return str(candidate)
    return ""


def object_context() -> str:
    path = context_path()
    if not path.is_file():
        return "（未读取到对象列表）"
    try:
        return path.read_text(encoding="utf-8").strip() or "（对象列表为空）"
    except OSError as error:
        return f"（读取对象列表失败：{error}）"


def selected_object_label() -> str:
    rows = tools.parse_object_context(object_context())
    if not rows:
        return "当前对象：（Praat 对象列表为空）"
    row = next((item for item in rows if item.selected), rows[-1])
    marker = "已选中" if row.selected else "最近对象"
    return f"当前对象：{row.name}（id {row.id}，{marker}）"


def _decode_console(data: bytes) -> str:
    if not data:
        return ""
    for encoding in ("utf-8", "utf-16-le", "gbk"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\x00" not in text:
            return text
    return data.decode("utf-8", errors="replace").replace("\x00", "")


def _clean_send_output(text: str) -> str:
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if any(noise in line for noise in SEND_NOISE):
            continue
        lines.append(line)
    return "\n".join(lines)


def _clear_result_files() -> None:
    """每次投递前清掉上一次的结果和完成标记（等待时只看新的那个）。"""

    for path in (result_path(), state_path()):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _blocked_reason() -> str:
    return (
        f"Praat 在 {EXECUTION_TIMEOUT_SEC:.0f} 秒内没有执行这个脚本。"
        "常见原因：Praat 里有没关掉的对话框或错误提示、编辑器正在播放/被"
        "模态窗口挡住。关掉那些窗口后再发一次即可。"
    )


def _wait_for_result(process: subprocess.Popen[bytes] | None) -> tuple[bool, str]:
    """轮询 ``chat_state.txt``；``process`` 只在那条 ``--send`` 兜底路径里非空。"""

    deadline = time.monotonic() + EXECUTION_TIMEOUT_SEC
    while time.monotonic() < deadline:
        if state_path().is_file():
            if process is not None:
                _close_send_process(process)
            return True, ""
        if process is not None and process.poll() is not None:
            break
        time.sleep(0.15)

    output = _clean_send_output(_read_send_log()) if process is not None else ""
    if state_path().is_file():
        if process is not None:
            _close_send_process(process)
        return True, output
    if process is None:
        # 自己投递时没有「发送进程」可看：这条 WM_APP 还排在 Praat 的消息队列里，
        # 得先把消息文件换成空脚本，否则它醒来时执行的会是下一条指令的脚本。
        sendpraat.cancel_pending()
        return False, _blocked_reason()
    if process.poll() is None:
        _close_send_process(process)
        return False, f"{output}\n{_blocked_reason()}".strip()
    return False, output


def _send_script(executable: str, script: str) -> tuple[bool, str]:
    """Hand the script to the running Praat and wait for its result files.

    默认走 :mod:`praat_ai.sendpraat`：自己写 ``Message.txt`` 再发 ``WM_APP``。
    这样 Praat 一个窗口都不会被激活——用户报的「弹出 Praat Info」和「声音窗口
    盖住对话窗口」都是老的 ``Praat.exe --send`` 干的（见 guide.md §8.5）。

    设 ``PRAAT_AI_SEND_MODE=argv`` 可以退回 ``--send`` 排障：那条路会激活一个
    Praat 子窗口，而且 ``--send`` 在 Praat 被模态窗口挡住时会一直阻塞（实测
    超过 60 秒，脚本其实已经排队），所以老路径仍然用「后台 Popen + 轮询」，
    不回到 ``subprocess.run(timeout=60)``。
    """

    target = script_path()
    target.write_text(script, encoding="utf-8")
    _clear_result_files()
    if sendpraat.send_mode() == sendpraat.ARGV_MODE:
        return _send_script_via_argv(executable, target)
    delivered, note = sendpraat.deliver(ai_directory(), target)
    if not delivered:
        return False, note
    return _wait_for_result(None)


def _send_script_via_argv(
    executable: str, target: Path
) -> tuple[bool, str]:
    """排障兜底：``Praat.exe --FULL-TRUST --send``（会激活 Praat 的一个子窗口）。"""

    creation_flags = 0
    if os.name == "nt":
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    log_path = send_log_path()
    try:
        log_path.unlink()
    except FileNotFoundError:
        pass
    try:
        with log_path.open("wb") as log_handle:
            process = subprocess.Popen(
                [executable, "--FULL-TRUST", "--send", str(target)],
                cwd=ai_directory(),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
    except OSError as error:
        return False, f"调用 Praat 失败：{error}"
    return _wait_for_result(process)


def _read_send_log() -> str:
    try:
        data = send_log_path().read_bytes()
    except OSError:
        return ""
    return _decode_console(data)


def _close_send_process(process: subprocess.Popen[bytes]) -> None:
    """收掉发送进程：脚本已经交给 Praat 之后它就没事可做了。"""

    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _read_results() -> list[str]:
    path = result_path()
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def praat_process_ids(executable: str = "Praat.exe") -> list[int] | None:
    """正在运行的 Praat 进程 id；``None`` 表示查不到（不要据此拦截用户）。

    对话窗口把脚本交给「已经开着的 Praat」；如果 Praat 其实没开，
    ``Praat.exe --send`` 会另起一个空实例，脚本必然找不到对象，用户还要白等
    一次超时。而 ``--send`` 只能把脚本交给最新的那个 Praat，所以同时开多个
    实例时也要提醒用户，免得脚本跑进了错误的窗口。
    """

    if os.name != "nt" or not executable:
        return None
    name = Path(executable).name
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=15,
            creationflags=creation_flags,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (completed.stdout or "").strip()
    if not output or output.upper().startswith("INFO"):
        return []
    ids: list[int] = []
    for line in output.splitlines():
        parts = [item.strip().strip('"') for item in line.split('","')]
        if len(parts) >= 2 and parts[1].isdigit():
            ids.append(int(parts[1]))
    return ids


def praat_process_running(executable: str) -> bool:
    process_ids = praat_process_ids(executable)
    if process_ids is None:
        return True   # 查不到进程列表时不拦截，交给 --send 自己判断
    return bool(process_ids)


def praat_instance_warning(executable: str) -> str:
    """同时开着多个 Praat 时返回一句提醒，否则返回空字符串。"""

    process_ids = praat_process_ids(executable)
    if not process_ids or len(process_ids) < 2:
        return ""
    return (
        f"检测到 {len(process_ids)} 个 Praat 在运行：脚本只会送给最新打开的那个"
        "窗口。请关掉多余的 Praat，否则可能操作到别的对象列表。"
    )


def model_status_text(config) -> str:
    """状态栏文案：模型来自服务实际加载的模型，而不是配置里的文件名。"""

    info = running_model_info(config.qwen.base_url)
    live = Path(str(info.get("id", ""))).name if info else ""
    configured = (
        Path(config.server.model_path).name if config.server.model_path else ""
    )
    capabilities = [str(item).casefold() for item in (info.get("capabilities") or [])]
    vision = any("multimodal" in item for item in capabilities)
    preset = active_preset(config)
    parts = [f"模型：{live or configured or '未配置'}"]
    if live and vision:
        parts.append("视觉已开")
    if live and configured and live.casefold() != configured.casefold():
        parts.append(f"配置里是 {configured}")
    if not live:
        parts.append("服务未响应")
    if preset is not None:
        parts.append(f"预设：{preset.display_name}")
    return "  |  ".join(parts)


def refresh_object_context(executable: str) -> tuple[bool, str]:
    """让正在运行的 Praat 重新写一次对象列表，返回 ``(是否成功, 说明)``。

    ``chat_context.tsv`` 由 Praat 维护：Praat 重启、换会话或对象被改动之后，
    对话窗口手里的列表可能是旧的。旧 id 会让脚本报「没有编号为 1」这种看不懂
    的错误，所以每次执行前先送一条空脚本刷新，顺带确认 Praat 还在响应用户。
    """

    if not executable or not praat_process_running(executable):
        return False, ""
    ok, output = _send_script(executable, context_ping_script())
    if ok:
        return True, ""
    return False, output or "Praat 没有响应，无法刷新对象列表。"


def resolve_preset_id(presets: list[dict], label: str) -> str:
    """把下拉框里的显示文本换回预设 id（标签带模型名和「视觉/纯文本」后缀）。

    下拉框的值是给人看的文本，切换之后列表会重建，所以不能只按完全相等查，
    还要能按 id、模型文件名和标签前缀兜底。
    """

    text = (label or "").strip()
    if not text:
        return ""
    for preset in presets:
        if text == preset_label_text(preset):
            return preset["id"]
    for preset in presets:
        if text in {preset["id"], preset["model"]}:
            return preset["id"]
    for preset in presets:
        if text.startswith(preset["label"] or preset["model"]):
            return preset["id"]
    return ""


def preset_label_text(preset: dict) -> str:
    """下拉框里那一行文字（不含「当前」，切换后不会变）。"""

    parts = [preset["label"] or preset["model"]]
    if preset["model"]:
        parts.append(preset["model"])
    parts.append("视觉" if preset["vision"] else "纯文本")
    if not preset["available"]:
        parts.append("文件缺失")
    return " · ".join(item for item in parts if item)


class ChatWindow:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Praat AI 对话")
        self.root.geometry("900x680")
        self.root.minsize(680, 480)
        self.root.configure(background="#F3F4F6")
        self.config = load_config()
        self.client = QwenClient(self.config.qwen)
        self.history: list[dict[str, str]] = []
        self.messages: queue.Queue[tuple[str, str]] = queue.Queue()
        self.busy = False

        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Chat.TFrame", background="#F3F4F6")
        style.configure("Composer.TFrame", background="#FFFFFF")
        style.configure("Hint.TLabel", background="#F3F4F6", foreground="#6B7280")

        frame = ttk.Frame(self.root, padding=16, style="Chat.TFrame")
        frame.pack(fill="both", expand=True)
        frame.rowconfigure(3, weight=1)
        frame.columnconfigure(0, weight=1)

        self.presets: list[dict] = list_presets(self.config)
        self.preset_ids: dict[str, str] = {}
        self.status = tk.StringVar(value="Praat AI  |  " + model_status_text(self.config))
        ttk.Label(
            frame,
            textvariable=self.status,
            font=("Microsoft YaHei UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="ew", pady=(0, 4))

        preset_row = ttk.Frame(frame, style="Chat.TFrame")
        preset_row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        preset_row.columnconfigure(1, weight=1)
        ttk.Label(
            preset_row,
            text="模型预设",
            style="Hint.TLabel",
            font=("Microsoft YaHei UI", 9),
        ).grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.preset_choice = tk.StringVar(value="")
        self.preset_box = ttk.Combobox(
            preset_row,
            textvariable=self.preset_choice,
            values=[],
            state="readonly",
            width=56,
        )
        self.preset_box.grid(row=0, column=1, sticky="ew")
        self.preset_button = ttk.Button(
            preset_row,
            text="应用预设",
            width=10,
            command=self.apply_selected_preset,
        )
        self.preset_button.grid(row=0, column=2, sticky="e", padx=(8, 0))
        self.preset_hint = tk.StringVar(value="")
        ttk.Label(
            preset_row,
            textvariable=self.preset_hint,
            style="Hint.TLabel",
            font=("Microsoft YaHei UI", 8),
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self.refresh_preset_widgets()

        self.context_label = tk.StringVar(value=selected_object_label())
        ttk.Label(
            frame,
            textvariable=self.context_label,
            style="Hint.TLabel",
            font=("Microsoft YaHei UI", 9),
        ).grid(row=2, column=0, sticky="ew", pady=(0, 10))

        transcript_frame = ttk.Frame(frame)
        transcript_frame.grid(row=3, column=0, sticky="nsew")
        transcript_frame.rowconfigure(0, weight=1)
        transcript_frame.columnconfigure(0, weight=1)
        self.transcript = tk.Text(
            transcript_frame,
            wrap="word",
            state="disabled",
            font=("Microsoft YaHei UI", 10),
            background="#FFFFFF",
            foreground="#111827",
            relief="solid",
            borderwidth=1,
            padx=14,
            pady=12,
        )
        self.transcript.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            transcript_frame,
            orient="vertical",
            command=self.transcript.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.transcript.configure(yscrollcommand=scrollbar.set)
        self.transcript.tag_configure(
            "user_label",
            foreground="#2563EB",
            font=("Microsoft YaHei UI", 10, "bold"),
            spacing1=8,
        )
        self.transcript.tag_configure(
            "assistant_label",
            foreground="#047857",
            font=("Microsoft YaHei UI", 10, "bold"),
            spacing1=8,
        )
        self.transcript.tag_configure("body", lmargin1=18, lmargin2=18, spacing3=8)
        self.transcript.tag_configure(
            "result",
            lmargin1=18,
            lmargin2=18,
            foreground="#1F2937",
            background="#ECFDF5",
            font=("Consolas", 10),
            spacing3=6,
        )
        self.transcript.tag_configure(
            "failure",
            lmargin1=18,
            lmargin2=18,
            foreground="#991B1B",
            background="#FEF2F2",
            font=("Consolas", 10),
            spacing3=6,
        )
        self.transcript.tag_configure(
            "hint",
            lmargin1=18,
            lmargin2=18,
            foreground="#6B7280",
            font=("Microsoft YaHei UI", 9),
            spacing3=8,
        )

        composer = ttk.Frame(frame, padding=10, style="Composer.TFrame")
        composer.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        composer.columnconfigure(0, weight=1)
        self.entry = tk.Text(
            composer,
            height=3,
            wrap="word",
            font=("Microsoft YaHei UI", 10),
            relief="solid",
            borderwidth=1,
            padx=10,
            pady=8,
        )
        self.entry.grid(row=0, column=0, sticky="ew")
        self.entry.bind("<Return>", self.on_return)
        self.entry.bind("<KP_Enter>", self.on_return)
        self.entry.bind("<Shift-Return>", self.on_shift_return)
        self.send_button = ttk.Button(
            composer,
            text="发送",
            command=self.submit,
            width=10,
        )
        self.send_button.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        ttk.Label(
            composer,
            text="Enter 发送，Shift+Enter 换行；脚本在正在运行的 Praat 里执行，结果会回到这里",
            foreground="#6B7280",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self.append("assistant", "请直接用自然语言描述要执行的 Praat 操作。")
        self.append_hint(
            "例如：提取当前语音的第二共振峰带宽；把选中的声音改名为 测试；"
            "查询 0.5 秒处的基频；统计整段基频；截取 0.2–0.5 秒；"
            "把两个声音拼起来；另存为 D:/out/a.wav。"
        )
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self.flush_messages)
        self.root.after(400, self.entry.focus_set)

    # ------------------------------------------------------------ 模型预设

    def preset_label_for(self, preset: dict) -> str:
        # 标签里不要写「当前」：切换后标签会变，下拉框里的旧值就对不上了。
        # 当前预设显示在下拉框下面的提示行里。
        return preset_label_text(preset)

    def preset_hint_text(self) -> str:
        if not self.presets:
            return (
                "还没有配置模型预设：在 ai/ai_config.json 的 server.presets "
                "里添加模型条目后重启前端。"
            )
        current = next((preset for preset in self.presets if preset["active"]), None)
        if current is None:
            return "当前模型不在预设列表里；选中一个预设并点「应用预设」即可切换。"
        bits = [f"{current['label']}：{current['model']}", "当前预设"]
        if current["mmproj"]:
            bits.append(f"投影文件 {current['mmproj']}")
        if current["context_tokens"]:
            bits.append(f"上下文 {current['context_tokens']} token")
        return "；".join(item for item in bits if item)

    def refresh_preset_widgets(self) -> None:
        self.preset_ids = {
            self.preset_label_for(preset): preset["id"] for preset in self.presets
        }
        labels = list(self.preset_ids)
        self.preset_box.configure(
            values=labels,
            state="readonly" if labels else "disabled",
        )
        self.preset_button.configure(state="normal" if labels else "disabled")
        current = next((preset for preset in self.presets if preset["active"]), None)
        if current is not None:
            self.preset_choice.set(self.preset_label_for(current))
        elif labels:
            self.preset_choice.set(labels[0])
        else:
            self.preset_choice.set("")
        self.preset_hint.set(self.preset_hint_text())

    def apply_selected_preset(self, _event: object = None) -> None:
        if self.busy:
            return
        preset_id = resolve_preset_id(self.presets, self.preset_choice.get())
        if not preset_id:
            self.append_hint("预设列表已经变化，请重新选择一个预设再点「应用预设」。")
            return
        self.busy = True
        self.send_button.configure(state="disabled")
        self.preset_button.configure(state="disabled")
        self.status.set("Praat AI  |  正在切换模型预设…")
        threading.Thread(
            target=self.apply_preset_worker,
            args=(preset_id,),
            daemon=True,
        ).start()

    def apply_preset_worker(self, preset_id: str) -> None:
        try:
            from . import control

            result = control.apply_preset(preset_id)
        except (PresetError, QwenError, OSError, ValueError) as error:
            self.messages.put(("assistant", f"切换模型预设失败：{error}"))
        else:
            label = str(result.get("frontend_preset_label", "")) or preset_id
            model = str(result.get("frontend_model", ""))
            vision = "视觉已开" if result.get("frontend_vision") else "纯文本"
            self.messages.put(
                ("assistant", f"已切换模型预设：{label}（{model}，{vision}）")
            )
        finally:
            self.messages.put(("reload", ""))
            self.messages.put(("done", ""))

    def append(self, role: str, text: str) -> None:
        label = "你" if role == "user" else "Praat AI"
        label_tag = "user_label" if role == "user" else "assistant_label"
        self.transcript.configure(state="normal")
        self.transcript.insert("end", f"{label}\n", label_tag)
        self.transcript.insert("end", f"{text}\n", "body")
        self.transcript.configure(state="disabled")
        self.transcript.see("end")

    def append_lines(self, tag: str, text: str) -> None:
        self.transcript.configure(state="normal")
        self.transcript.insert("end", f"{text}\n", tag)
        self.transcript.configure(state="disabled")
        self.transcript.see("end")

    def append_hint(self, text: str) -> None:
        self.append_lines("hint", text)

    def on_return(self, _event: tk.Event) -> str:
        self.submit()
        return "break"

    def on_shift_return(self, _event: tk.Event) -> str:
        self.entry.insert("insert", "\n")
        return "break"

    def submit(self, _event: object = None) -> str:
        if self.busy:
            return "break"
        text = self.entry.get("1.0", "end").strip()
        if not text:
            return "break"
        self.entry.delete("1.0", "end")
        self.busy = True
        self.send_button.configure(state="disabled")
        self.preset_button.configure(state="disabled")
        self.status.set("Praat AI  |  正在处理请求…")
        self.append("user", text)
        threading.Thread(
            target=self.process_message,
            args=(text,),
            daemon=True,
        ).start()
        return "break"

    def plan_script(self, text: str) -> tuple[str, str]:
        """Return ``(reply, script)`` for one user message."""

        context_text = object_context()
        rows = tools.parse_object_context(context_text)
        context = tools.ToolContext(
            objects=rows,
            result_path=result_path(),
            state_path=state_path(),
        )
        plan = self.client.plan_praat_command(
            text,
            context_text,
            self.history,
            tool_catalog=tools.catalog_text(),
            result_path=str(result_path()),
            state_path=str(state_path()),
        )
        reply = str(plan.get("reply", "")).strip() or "已完成。"
        tool_name = str(plan.get("tool", "")).strip()
        arguments = plan.get("arguments") or {}
        custom_script = str(plan.get("script", "") or "")
        if not tool_name and custom_script.strip():
            tool_name = tools.CUSTOM_SCRIPT_TOOL
        if not tool_name:
            return reply, ""
        try:
            script = tools.render(tool_name, arguments, context)
        except tools.ToolError as error:
            if not custom_script.strip() or tool_name == tools.CUSTOM_SCRIPT_TOOL:
                raise
            self.messages.put(
                ("hint", f"工具 {tool_name} 无法执行（{error}），改用模型给出的脚本。")
            )
            script = tools.render(
                tools.CUSTOM_SCRIPT_TOOL,
                {},
                context,
                custom_script=custom_script,
            )
        return reply, script

    def process_message(self, text: str) -> None:
        try:
            executable = praat_executable()
            praat_ready = bool(executable) and praat_process_running(executable)
            if praat_ready:
                warning = praat_instance_warning(executable)
                if warning:
                    self.messages.put(("hint", warning))
                # 先刷新对象列表，免得拿着过期 id 去规划。
                refreshed, note = refresh_object_context(executable)
                if not refreshed and note:
                    self.messages.put(("hint", note))

            reply, script = self.plan_script(text)
            if not script:
                self.messages.put(("assistant", reply))
                self.history.append({"role": "user", "content": text})
                self.history.append({"role": "assistant", "content": reply})
                return

            if not executable:
                raise OSError(
                    "未配置 Praat 可执行文件路径，请从 Praat 菜单重新启动前端。"
                )
            if not praat_ready:
                raise OSError(
                    "没有检测到正在运行的 Praat。请先打开 Praat，"
                    "再从菜单「前端 → 启动前端」启动对话窗口。"
                )

            success, output = _send_script(executable, script)
            results = _read_results()
            if success:
                body = f"{reply}\n结果：{'；'.join(results)}" if results else reply
                self.messages.put(("assistant", body))
                if results:
                    self.messages.put(
                        ("result", "结果：\n" + "\n".join(results))
                    )
                elif output:
                    self.messages.put(("hint", f"Praat 返回：{output}"))
                self.history.append({"role": "user", "content": text})
                self.history.append({"role": "assistant", "content": body})
            else:
                message = (
                    f"{reply}\n执行未完成：Praat 没有返回结果，"
                    "请查看 Praat 主窗口弹出的错误提示（脚本执行失败时 Praat "
                    "会自己弹出提示，对话窗口拿不到那些文字）。"
                )
                if output:
                    message += f"\n{output}"
                else:
                    message += (
                        "\n（Praat 没有输出任何信息：常见原因是脚本里的命令和当前"
                        "选中的对象不匹配，或者 Praat 正被对话框挡住。）"
                    )
                message += f"\n\n本次脚本：\n{tools.describe_script(script)}"
                self.messages.put(("assistant", message))
                self.history.append({"role": "user", "content": text})
                self.history.append(
                    {"role": "assistant", "content": "（上次脚本执行未完成）"}
                )
        except (QwenError, tools.ToolError, PresetError, OSError) as error:
            self.messages.put(("assistant", f"处理失败：{error}"))
        finally:
            self.messages.put(("done", ""))

    def flush_messages(self) -> None:
        try:
            while True:
                role, text = self.messages.get_nowait()
                if role == "done":
                    self.busy = False
                    self.send_button.configure(state="normal")
                    self.preset_button.configure(
                        state="normal" if self.presets else "disabled"
                    )
                    self.status.set("Praat AI  |  " + model_status_text(self.config))
                    self.context_label.set(selected_object_label())
                    self.entry.focus_set()
                elif role == "reload":
                    self.reload_config()
                elif role in {"result", "failure"}:
                    self.append_lines(role, text)
                elif role == "hint":
                    self.append_hint(text)
                else:
                    self.append(role, text)
        except queue.Empty:
            pass
        self.root.after(100, self.flush_messages)

    def close(self) -> None:
        pid_path = runtime_dir() / "chat.pid"
        try:
            pid_path.unlink()
        except FileNotFoundError:
            pass
        self.root.destroy()

    def reload_config(self) -> None:
        """重新读取 ai_config.json（切换预设之后模型和 mmproj 都会变）。"""

        self.config = load_config()
        self.client = QwenClient(self.config.qwen)
        self.presets = list_presets(self.config)
        self.refresh_preset_widgets()
        self.status.set("Praat AI  |  " + model_status_text(self.config))

    def run(self) -> int:
        self.root.mainloop()
        return 0


def main() -> int:
    return ChatWindow().run()
