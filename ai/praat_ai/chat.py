"""Praat AI 对话窗口。

前端流程：

1. 读取 Praat 写出的对象列表（``runtime/chat_context.tsv``）。
2. Qwen 只负责选择工具并填参数，脚本由 :mod:`praat_ai.tools` 用固定模板生成。
3. 脚本通过 ``Praat.exe --FULL-TRUST --send`` 送到正在运行的 Praat 里执行。
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

from . import tools
from .config import load_config
from .qwen import QwenClient, QwenError


SEND_NOISE = (
    "An instance of Praat that is not me is already running.",
    "Cannot write message file",
)

EXECUTION_TIMEOUT_SEC = 25.0


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


def _send_script(executable: str, script: str) -> tuple[bool, str]:
    """Hand the script to the running Praat and wait for its result files."""

    target = script_path()
    target.write_text(script, encoding="utf-8")
    for path in (result_path(), state_path()):
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    creation_flags = 0
    if os.name == "nt":
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            [executable, "--FULL-TRUST", "--send", str(target)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            timeout=60,
            creationflags=creation_flags,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"调用 Praat 失败：{error}"

    output = _clean_send_output(_decode_console(completed.stdout + completed.stderr))

    deadline = time.monotonic() + EXECUTION_TIMEOUT_SEC
    while time.monotonic() < deadline:
        if state_path().is_file():
            return True, output
        time.sleep(0.15)
    return False, output


def _read_results() -> list[str]:
    path = result_path()
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


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
        frame.rowconfigure(2, weight=1)
        frame.columnconfigure(0, weight=1)

        self.status = tk.StringVar(
            value=(
                f"Praat AI  |  {self.config.qwen.model}  |  "
                f"{'前端已连接' if self.client.available() else '前端未连接'}"
            )
        )
        ttk.Label(
            frame,
            textvariable=self.status,
            font=("Microsoft YaHei UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="ew", pady=(0, 4))

        self.context_label = tk.StringVar(value=selected_object_label())
        ttk.Label(
            frame,
            textvariable=self.context_label,
            style="Hint.TLabel",
            font=("Microsoft YaHei UI", 9),
        ).grid(row=1, column=0, sticky="ew", pady=(0, 10))

        transcript_frame = ttk.Frame(frame)
        transcript_frame.grid(row=2, column=0, sticky="nsew")
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
        composer.grid(row=3, column=0, sticky="ew", pady=(12, 0))
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
            "打开编辑器；查询 0.5 秒处的基频。"
        )
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self.flush_messages)
        self.root.after(400, self.entry.focus_set)

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
            reply, script = self.plan_script(text)
            if not script:
                self.messages.put(("assistant", reply))
                self.history.append({"role": "user", "content": text})
                self.history.append({"role": "assistant", "content": reply})
                return

            executable = praat_executable()
            if not executable:
                raise OSError(
                    "未配置 Praat 可执行文件路径，请从 Praat 菜单重新启动前端。"
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
                    "请查看 Praat 主窗口弹出的错误提示。"
                )
                if output:
                    message += f"\n{output}"
                message += f"\n\n本次脚本：\n{tools.describe_script(script)}"
                self.messages.put(("assistant", message))
                self.history.append({"role": "user", "content": text})
                self.history.append(
                    {"role": "assistant", "content": "（上次脚本执行未完成）"}
                )
        except (QwenError, tools.ToolError, OSError) as error:
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
                    self.status.set(f"Praat AI  |  {self.config.qwen.model}  |  就绪")
                    self.context_label.set(selected_object_label())
                    self.entry.focus_set()
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

    def run(self) -> int:
        self.root.mainloop()
        return 0


def main() -> int:
    return ChatWindow().run()
