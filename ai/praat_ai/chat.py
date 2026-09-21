"""Praat AI 对话窗口。

前端流程：

1. 读取 Praat 写出的对象列表（``runtime/chat_context.tsv``）。
2. Qwen 只负责选择工具并填参数，脚本由 :mod:`praat_ai.tools` 用固定模板生成。
3. 脚本通过 :mod:`praat_ai.sendpraat` 送到正在运行的 Praat 里执行（自己写
   ``Message.txt`` 再发 ``WM_APP``，不激活 Praat 的任何窗口）。
4. 脚本把数值结果写进 ``runtime/chat_result.tsv``，执行完成写
   ``runtime/chat_state.txt``；对话窗口轮询到完成标记后把结果读回来显示。

每条指令一个脚本文件（``runtime/commands/chat_command_<编号>.praat``）并且脚本开头
先写下自己的编号（``runtime/chat_started.txt``）：Praat 的 ``Message.txt`` 是全局
唯一的，超时指令还可能压在消息队列里，靠这两样才能保证「投递出去的那条」和
「真的执行了的那条」对得上（见 guide.md §8.5）。

注意：``An instance of Praat that is not me is already running.`` 是
``--send`` 转发脚本时的常规提示，不是错误，所以不显示给用户。
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
import tkinter as tk
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import ttk
from typing import Any, Callable, Mapping

from . import api_settings, praat_app, progress_popup, qwen, sendpraat, tools
from .config import api_is_active, load_config
from .presets import PresetError, active_preset, list_presets
from .server import running_model_info


SEND_NOISE = (
    "An instance of Praat that is not me is already running.",
)

EXECUTION_TIMEOUT_SEC = 25.0

#: ``runtime/commands/`` 里最多留几个脚本文件（旧的才删，见 :func:`prune_command_scripts`）。
MAX_COMMAND_SCRIPTS = 40

#: 超过这个岁数的旧脚本文件才允许删：``Message.txt`` 里可能还引用着最近几个。
COMMAND_SCRIPT_TTL_SEC = 3600.0


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


def script_path(request_id: str = "") -> Path:
    """这次请求的脚本路径。

    不带编号时返回老路径 ``runtime/chat_command.praat``（只用于兼容旧调用和排障）。
    带上编号就每条指令一个文件：``Message.txt`` 全局唯一，队列里可能还压着上一条
    超时消息；如果所有指令共用一个文件名，那条旧消息醒来时执行的会是**刚写进去的
    新脚本**。文件名分开之后，旧消息最多把它自己那条再跑一遍（用户要求的操作，
    而且 :func:`_wait_for_result` 能从编号看出来），不会把新指令执行成别的东西。
    """

    if not request_id:
        return runtime_dir() / "chat_command.praat"
    return command_dir() / f"chat_command_{request_id}.praat"


def command_dir() -> Path:
    path = runtime_dir() / "commands"
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_request_id() -> str:
    """一条指令的编号（用它区分脚本文件、完成标记是谁写的）。"""

    return uuid.uuid4().hex[:12]


def request_id_from_path(path: Path | str) -> str:
    """从脚本文件名反推请求编号（诊断和单测用）；不是这种名字就返回空串。"""

    name = Path(path).name
    if name.startswith("chat_command_") and name.endswith(".praat"):
        return name[len("chat_command_") : -len(".praat")]
    return ""


def started_marker_path() -> Path:
    return runtime_dir() / "chat_started.txt"


def failure_path() -> Path:
    """Praat 报错时写下的原始错误（见 ``PraatAiControl_reportChatScriptFailure``）。

    脚本自己报错时 Praat **不再弹模态错误框**（那会挡住后面所有消息），而是把错误
    写到这里 + 结果文件里，并补一句完成标记；前端看到这个文件就把这一条当失败，
    而不是把错误行当成正常结果。
    """

    return runtime_dir() / "chat_failure.txt"


def script_preamble(request_id: str) -> str:
    """脚本开头那句「我这条指令开始执行了」。

    完成标记（``chat_state.txt``）里只有 ``done``，光看它分不清是谁写的。脚本一
    开始就把编号写进 ``chat_started.txt``，等待完成时对一下编号，就能认出「上一条
    超时指令刚刚才跑完」这种情况，而不是把它的数值当成本次结果（见
    :func:`_wait_for_result`）。
    """

    if not request_id:
        return ""
    return (
        f"# praat-ai 请求 {request_id}\n"
        f'appendFileLine: {tools.quote(str(started_marker_path()))}, "started {request_id}"\n'
    )


def prune_command_scripts() -> int:
    """删掉又老又旧的脚本文件，返回删了几个。

    只删「数量超出 :data:`MAX_COMMAND_SCRIPTS` **而且** 超过
    :data:`COMMAND_SCRIPT_TTL_SEC`」的那些：``Message.txt`` 里可能还引用着最近
    几个，删早了会让残留消息找不到文件（Praat 会弹一句「文件不存在」的错误框）。
    """

    try:
        entries = sorted(
            command_dir().glob("chat_command_*.praat"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return 0
    removed = 0
    cutoff = time.time() - COMMAND_SCRIPT_TTL_SEC
    for index, path in enumerate(entries):
        if index < MAX_COMMAND_SCRIPTS:
            continue
        try:
            if path.stat().st_mtime >= cutoff:
                continue
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def send_log_path() -> Path:
    return runtime_dir() / "chat_send.log"


def praat_executable() -> str:
    """正在跑的那个 Praat 的可执行文件；找不到返回空字符串。

    具体去哪儿找见 :mod:`praat_ai.praat_app`（环境变量 → 仓库根目录 → ``PATH``
    → 常见安装位置，带缓存和 30 秒重试）。
    """

    return praat_app.find_praat()


def object_context() -> str:
    path = context_path()
    if not path.is_file():
        return "（未读取到对象列表）"
    try:
        return path.read_text(encoding="utf-8").strip() or "（对象列表为空）"
    except OSError as error:
        return f"（读取对象列表失败：{error}）"


#: Praat 写在对象列表文件末尾的进程标记（见 sys/PraatAiControl.cpp）。
CONTEXT_PID_PATTERN = re.compile(r"^#\s*praat-pid=(\d+)\s*$", re.MULTILINE)


def context_pid(text: str | None = None) -> int:
    """对象列表是哪一次 Praat 进程写的（没有标记返回 0）。

    有了它，前端就不必每条消息都先投一条空脚本「刷一遍」对象列表（C5）：标记就是
    当前这个 Praat，说明文件是最新的。对方的 Praat 不写标记（老版本、或者别人的
    Praat），返回值是 0，调用方会退回「刷一次」的老行为。

    ``text=None``（默认）时读 ``chat_context.tsv``；传字符串时只解析这份文本。
    """

    if text is None:
        text = object_context()
    match = CONTEXT_PID_PATTERN.search(text or "")
    return int(match.group(1)) if match else 0


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

    for path in (result_path(), state_path(), started_marker_path(), failure_path()):
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


def _cancelled_reason() -> str:
    return (
        "已取消：不再等这一条的结果。脚本可能已经在 Praat 里跑完了，"
        "结果文件里会有它的输出。"
    )


def _read_started_marker() -> str:
    """最后一次开始执行的请求编号（``chat_started.txt`` 里最后一个 ``started`` 行）。"""

    try:
        lines = started_marker_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        text = line.strip()
        if text.startswith("started "):
            return text.split(" ", 1)[1].strip()
    return ""


def _completion_state(request_id: str) -> tuple[bool, str]:
    """``chat_state.txt`` 出现没有？是不是**本次**请求写的？"""

    if not state_path().is_file():
        return False, ""
    if not request_id:
        return True, ""
    started = _read_started_marker()
    if started == request_id:
        return True, ""
    return False, (
        f"上一条超时指令（编号 {started or '未知'}）刚刚才执行完，"
        "已丢掉它的完成标记和结果，继续等本次指令。"
    )


def _discard_stale_output() -> None:
    for path in (state_path(), result_path()):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _wait_for_result(
    process: subprocess.Popen[bytes] | None,
    *,
    request_id: str = "",
    cancel: threading.Event | None = None,
) -> tuple[bool, str]:
    """轮询 ``chat_state.txt``；``process`` 只在那条 ``--send`` 兜底路径里非空。

    ``cancel``（C7）是对话窗口「停止」按钮置的那个事件：一置上就不再等，并且把
    排队中的 WM_APP 换成空脚本（否则它以后醒来会执行**下一条**指令的脚本）。
    """

    deadline = time.monotonic() + EXECUTION_TIMEOUT_SEC
    notes = ""
    while time.monotonic() < deadline:
        ready, stale_note = _completion_state(request_id)
        if ready:
            if process is not None:
                _close_send_process(process)
            return True, notes.strip()
        if cancel is not None and cancel.is_set():
            # 结果已经到了就不打断（上面的 ready 分支已经返回）；这里说明还没来。
            ready, _ = _completion_state(request_id)
            if ready:
                if process is not None:
                    _close_send_process(process)
                return True, notes.strip()
            if process is not None:
                _close_send_process(process)
            else:
                sendpraat.cancel_pending()
            return False, _join_notes(notes, _cancelled_reason())
        if stale_note:
            # 完成标记是别人的：连同它的结果一起丢掉，继续等本次指令。
            notes = stale_note
            _discard_stale_output()
        if process is not None and process.poll() is not None:
            break
        time.sleep(0.15)

    output = _clean_send_output(_read_send_log()) if process is not None else ""
    ready, _ = _completion_state(request_id)
    if ready:
        if process is not None:
            _close_send_process(process)
        return True, notes.strip()
    if process is None:
        # 自己投递时没有「发送进程」可看：这条 WM_APP 还排在 Praat 的消息队列里，
        # 得先把消息文件换成空脚本，否则它醒来时执行的会是下一条指令的脚本。
        # （正常情况下脚本开头那句「消息自消费」已经做过这件事，这里只是兜底。）
        sendpraat.cancel_pending()
        return False, _join_notes(notes, _blocked_reason())
    if process.poll() is None:
        _close_send_process(process)
        return False, _join_notes(output, notes, _blocked_reason())
    return False, _join_notes(output, notes)


def _join_notes(*parts: str) -> str:
    return "\n".join(part.strip() for part in parts if part and part.strip())


def render_action(
    action: Mapping[str, Any], context: tools.ToolContext
) -> tuple[str, str]:
    """渲染一个动作，返回 ``(脚本, 给用户的提示)``；提示为空表示没什么要说的。

    工具自己报错（参数不合法、对象找不到）而模型又同时给了 ``script`` 时，用模型
    那条脚本兜底，并把这件事告诉用户——这比直接失败好，也比悄悄换一条路好。
    """

    tool_name = str(action.get("tool", "") or "").strip()
    arguments = action.get("arguments") or {}
    custom_script = str(action.get("script", "") or "")
    if tool_name == tools.CUSTOM_SCRIPT_TOOL:
        return (
            tools.render(
                tool_name,
                {},
                context,
                custom_script=str(arguments.get("script", "") or ""),
            ),
            "",
        )
    try:
        return tools.render(tool_name, arguments, context), ""
    except tools.ToolError as error:
        if not custom_script.strip():
            raise
        return (
            tools.render(
                tools.CUSTOM_SCRIPT_TOOL,
                {},
                context,
                custom_script=custom_script,
            ),
            f"工具 {tool_name} 无法执行（{error}），改用模型给出的脚本。",
        )


#: 一次用户请求最多让模型规划几轮（每轮可以执行 1–3 个动作）。
#:
#: 一轮结束会把执行结果**回灌**给模型，让它接着做下一步或者把结果讲清楚；到上限
#: 还在调工具时就强制要一次纯文本回答。3 轮是权衡：多步请求够用，最坏情况也只多花
#: 一两次小模型调用（实测一次调用 0.3–1 秒）。
MAX_AGENT_ROUNDS = 3

#: 一次用户请求最多**实际执行**几个动作。小模型在多轮里会退化成重复调用同一个
#: 工具（实测「截取 0.2–0.5 秒」被它连做三遍），所以除了轮数还要卡总步数。
MAX_AGENT_STEPS = 5


@dataclass(slots=True)
class AgentStep:
    """一次工具执行，以及回灌给模型的那段观察结果。"""

    round_index: int
    tool: str
    arguments: dict[str, Any]
    ok: bool
    observation: str
    script: str = ""
    results: list[str] = field(default_factory=list)
    note: str = ""


@dataclass(slots=True)
class TurnOutcome:
    """一轮用户请求的结果（可能包含多步执行）。"""

    reply: str = ""
    results: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    steps: list[AgentStep] = field(default_factory=list)
    used_tools: bool = False
    failure: str = ""

    @property
    def last_script(self) -> str:
        for step in reversed(self.steps):
            if step.script:
                return step.script
        return ""


def _short_arguments(arguments: Mapping[str, Any], *, maximum: int = 60) -> str:
    if not arguments:
        return ""
    text = ", ".join(f"{key}={value}" for key, value in arguments.items())
    return text if len(text) <= maximum else text[: maximum - 1] + "…"


def _progress_text(step: AgentStep) -> str:
    head = step.tool + (f"（{_short_arguments(step.arguments)}）" if step.arguments else "")
    if step.ok:
        detail = "；".join(step.results) or "已执行"
        return f"第 {step.round_index} 轮：{head} → {detail}"
    return f"第 {step.round_index} 轮：{head} 未完成 → {step.observation}"


def _summary_of(outcome: TurnOutcome) -> str:
    """模型没给出文字时的兜底回答。"""

    if outcome.results:
        return "结果：" + "；".join(outcome.results)
    if outcome.failure:
        return "执行未完成：" + outcome.failure
    return "已完成。"


def _action_signature(action: Mapping[str, Any]) -> str:
    """动作签名（工具名 + 参数），用来认出重复调用。"""

    return json.dumps(
        [str(action.get("tool", "")), action.get("arguments") or {}],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )


#: 用户明确说了「还有下一步」的说法。第二轮之后要动对象，必须出现其中之一。
_FOLLOWUP_WORDS = (
    "然后",
    "再",
    "接着",
    "之后",
    "并且",
    "同时",
    "顺便",
    "第一步",
    "第二步",
    "先",
)


def wants_second_step(user_text: str) -> bool:
    """用户这句话是不是明确要求「不止一步」。

    「把前 0.3 秒截出来，**然后**把它改名」是两步；「打开这个声音的编辑器」只有一步。
    小模型（尤其 0.8B 预设）在第二轮之后爱顺手多做几步（实测会做频谱图、换掉选中
    对象），所以只有用户自己说要接着做，才允许后续轮次动对象。
    """

    text = (user_text or "").strip()
    return any(word in text for word in _FOLLOWUP_WORDS)


def _execute_action(
    action: Mapping[str, Any],
    context: tools.ToolContext,
    execute: Callable[[str], tuple[bool, list[str], str]],
    round_index: int,
    environment: tools.LocalEnvironment | None = None,
) -> AgentStep:
    """执行一个动作，把它变成一条可以回灌给模型的观察结果。

    工具自己拒绝请求（参数不合法、对象找不到）时**不再往上抛**：那是一条「这个动作
    没做成，原因是……」的观察结果，模型看到之后可以改参数重试（见 A4 的取舍）。

    ``environment`` 是给**本地工具**（例如 ``tools.RUN_SCRIPT_TOOL``）用的：
    「渲染脚本 → 投递」那套对它们不适用，它们要自己起批处理进程；没给环境时
    只回一句「这次没有可用的执行环境」，而不是崩掉（测试里直接调也会走到这）。
    """

    tool_name = str(action.get("tool", "") or "").strip()
    arguments = action.get("arguments") or {}
    if not isinstance(arguments, Mapping):
        arguments = {}
    # 本地工具（跑现成 .praat 脚本那种）不走「渲染脚本 → 投递」，先分流。
    if tool_name in tools.LOCAL_TOOLS:
        return _execute_local_action(
            tool_name, arguments, context, environment, round_index
        )
    try:
        script, note = render_action(action, context)
    except tools.ToolError as error:
        observation = f"工具 {tool_name} 没有执行：{error}"
        return AgentStep(round_index, tool_name, dict(arguments), False, observation)
    ok, results, failure = execute(script)
    if ok:
        detail = "；".join(results) if results else "（脚本跑完了，但没有输出结果行）"
        observation = (
            f"工具 {tool_name} 执行成功，结果：{detail}\n"
            "（如果这些结果已经够回答用户，就直接回答，不要再调工具、也不要顺手多做别的操作；"
            "只有确实还需要下一步时才继续调工具。）"
        )
    else:
        observation = f"工具 {tool_name} 执行失败：{failure}"
    return AgentStep(
        round_index,
        tool_name,
        dict(arguments),
        ok,
        observation,
        script,
        results,
        note,
    )


def _execute_local_action(
    tool_name: str,
    arguments: Mapping[str, Any],
    context: tools.ToolContext,
    environment: tools.LocalEnvironment | None,
    round_index: int,
) -> AgentStep:
    """跑一个**本地工具**：它自己在 Python 这边干活（例如起批处理跑现成脚本）。

    和模板工具一样，工具自己拒绝请求时只回一条「没有执行 + 原因」的观察结果；
    ``environment`` 缺失（有人在测试里直接调这个函数）时说清楚，而不是崩。
    """

    local = tools.LOCAL_TOOLS[tool_name]
    if environment is None:
        observation = (
            f"工具 {tool_name} 没有执行：它要在对话窗口里跑，这次没有可用的执行环境。"
        )
        return AgentStep(round_index, tool_name, dict(arguments), False, observation)
    try:
        ok, results, failure = local.run(arguments, context, environment)
    except tools.ToolError as error:
        observation = f"工具 {tool_name} 没有执行：{error}"
        return AgentStep(round_index, tool_name, dict(arguments), False, observation)
    if ok:
        detail = "；".join(results) if results else "（工具跑完了，但没有输出结果行）"
        observation = (
            f"工具 {tool_name} 执行成功，结果：{detail}\n"
            "（如果这些结果已经够回答用户，就直接回答，不要再调工具、也不要顺手多做别的操作；"
            "只有确实还需要下一步时才继续调工具。）"
        )
    else:
        observation = f"工具 {tool_name} 执行失败：{failure}"
    return AgentStep(
        round_index,
        tool_name,
        dict(arguments),
        ok,
        observation,
        "",
        results if ok else [],
        "",
    )


def _run_agent_turn(
    planner,
    *,
    context: tools.ToolContext,
    execute: Callable[[str], tuple[bool, list[str], str]],
    on_progress: Callable[[str], None] | None = None,
    max_rounds: int = MAX_AGENT_ROUNDS,
    max_steps: int = MAX_AGENT_STEPS,
    allow_followup_mutations: bool = False,
    environment: tools.LocalEnvironment | None = None,
    cancel: threading.Event | None = None,
) -> TurnOutcome:
    """循环本体：规划 → 执行 → 回灌 → 再规划（planner 负责具体接口）。

    两道防线对付小模型的退化行为（实测会重复调用同一个工具）：
    ① 同一个动作（工具名 + 参数完全相同）只执行一次，重复的调用只回灌一条
       「这一步刚才已经做过」；
    ② 一次请求最多实际执行 :data:`MAX_AGENT_STEPS` 个动作。

    还有一道针对「顺手多做」的护栏：用户没明确说要接着做时（见
    :func:`wants_second_step`），第二轮之后不许再执行会改动对象的工具
    （``tools.MUTATING_TOOLS``）——只读查询不受限制。
    """

    outcome = TurnOutcome()
    executed: dict[str, str] = {}
    steps_done = 0
    stopped_early = False
    cancelled = False
    for round_index in range(1, max_rounds + 1):
        if cancel is not None and cancel.is_set():
            # 用户在等上一轮结果时按了「停止」：不再规划、不再执行。
            cancelled = True
            break
        actions, reply = planner.next()
        if not actions:
            outcome.reply = reply or _summary_of(outcome)
            return outcome
        for action in actions:
            if cancel is not None and cancel.is_set():
                cancelled = True
                break
            signature = _action_signature(action)
            tool_name = str(action.get("tool", "") or "")
            if signature in executed:
                observation = (
                    "这一步刚才已经执行过，没有重复执行。"
                    f"上一次的结果：{executed[signature]}"
                )
                step = AgentStep(
                    round_index,
                    tool_name,
                    dict(action.get("arguments") or {}),
                    True,
                    observation,
                    "",
                    [],
                    "重复调用被跳过。",
                )
                outcome.steps.append(step)
                outcome.notes.append(f"跳过一次重复调用：{tool_name}")
                planner.observe(action, observation)
                continue
            if (
                round_index > 1
                and not allow_followup_mutations
                and tools.is_mutating(tool_name)
            ):
                # 用户这句话没有要求第二步，而这个动作会改动对象：不做。
                observation = (
                    f"没有执行这个动作：{tool_name} 会改动 Praat 里的对象，"
                    "而用户这次只要求做一件事。请直接用上面已经拿到的结果回答；"
                    "如果确实还需要这一步，就在回答里说明需要做什么。"
                )
                step = AgentStep(
                    round_index,
                    tool_name,
                    dict(action.get("arguments") or {}),
                    True,
                    observation,
                    "",
                    [],
                    f"拦下了一次多余的操作：{tool_name}（用户没有要求第二步）",
                )
                outcome.steps.append(step)
                outcome.notes.append(step.note)
                planner.observe(action, observation)
                continue
            if steps_done >= max_steps:
                stopped_early = True
                break
            step = _execute_action(
                action, context, execute, round_index, environment
            )
            steps_done += 1
            executed[signature] = step.observation
            outcome.steps.append(step)
            outcome.used_tools = True
            if step.ok:
                outcome.results.extend(step.results)
            else:
                outcome.failure = step.observation
                # 失败也可能带回结果行：脚本在 Praat 里报错时，Praat 会把错误原文
                # 写进结果文件（不再弹模态框），那一行要显示给用户看。
                outcome.results.extend(step.results)
            if step.note:
                outcome.notes.append(step.note)
            planner.observe(action, step.observation)
            if on_progress is not None:
                on_progress(_progress_text(step))
        if stopped_early or cancelled:
            break
    if cancelled:
        outcome.notes.append("已取消：后面的步骤没有再执行。")
        outcome.reply = "已取消这次操作（已经执行完的那几步结果还在下面）。"
        return outcome
    outcome.reply = planner.wrap_up() or _summary_of(outcome)
    return outcome


class _NativePlanner:
    """原生工具调用：自己维护 messages，逐轮把 tool 结果塞回去。"""

    def __init__(
        self,
        client: qwen.QwenClient,
        *,
        user_text: str,
        context_text: str,
        history: list[dict[str, str]],
        result_path: str,
        state_path: str,
    ) -> None:
        self.client = client
        self.messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": qwen.TOOL_PLANNER_INSTRUCTIONS
                + "\n\n"
                + tool_context_text(context_text, result_path, state_path),
            }
        ]
        self.messages.extend(qwen.history_messages(history))
        self.messages.append({"role": "user", "content": user_text})

    def next(self) -> tuple[list[dict[str, Any]], str]:
        message = self.client.chat_message(
            self.messages,
            tools=tools.tool_schemas(),
            max_tokens=self.client.config.plan_max_tokens,
            temperature=self.client.config.plan_temperature,
        )
        actions = qwen.extract_tool_actions(message)
        content = str(message.get("content") or "").strip()
        if not actions:
            # 没开 --jinja 时小模型偶尔把调用写成正文里的 <tool_call> 文本；
            # 那种情况也要当工具调用执行，而不是把一坨 XML 当成回答显示给用户。
            actions, content = qwen.parse_text_tool_calls(content)
        if actions:
            # 回灌形状必须和这次响应一致：assistant(tool_calls) + 每条 tool 结果。
            # 正文只留 XML 之外的文字，别把工具调用文本也塞回历史里（会把模型带偏）。
            self.messages.append(qwen.assistant_tool_message(message, actions, content))
        return actions, content

    def observe(self, action: Mapping[str, Any], observation: str) -> None:
        call_id = str(action.get("id", "") or "call-1")
        self.messages.append(qwen.tool_result_message(call_id, observation))

    def wrap_up(self) -> str:
        text = self.client.chat(
            self.messages,
            max_tokens=self.client.config.plan_max_tokens,
            temperature=self.client.config.plan_temperature,
        ).strip()
        # 收尾这轮也可能又写工具调用文本：那些不执行了，也不能显示给用户。
        _actions, leftover = qwen.parse_text_tool_calls(text)
        return leftover


class _JsonPlanner:
    """老的提示词接口：把观察结果写成一条「上一轮执行结果」再问一次。"""

    def __init__(
        self,
        client: qwen.QwenClient,
        *,
        user_text: str,
        context_text: str,
        history: list[dict[str, str]],
        result_path: str,
        state_path: str,
    ) -> None:
        self.client = client
        self.user_text = user_text
        self.context_text = context_text
        self.history = list(history)
        self.result_path = result_path
        self.state_path = state_path
        self.observations: list[str] = []

    def next(self) -> tuple[list[dict[str, Any]], str]:
        history = list(self.history)
        if self.observations:
            history.append(
                {
                    "role": "user",
                    "content": (
                        "上一步的执行结果：\n"
                        + "\n".join(self.observations)
                        + "\n请根据这些结果回答用户；如果需要继续操作就再选工具，"
                        "不需要就不要选工具。"
                    ),
                }
            )
        plan = self.client.plan_praat_command(
            self.user_text,
            self.context_text,
            history,
            tool_catalog=tools.catalog_text(),
            result_path=self.result_path,
            state_path=self.state_path,
        )
        return tools.plan_actions(plan), str(plan.get("reply", "") or "").strip()

    def observe(self, action: Mapping[str, Any], observation: str) -> None:
        tool_name = str(action.get("tool", "") or "")
        self.observations.append(f"{tool_name}：{observation}")

    def wrap_up(self) -> str:
        return ""


def tool_context_text(
    object_context: str, result_path: str, state_path: str
) -> str:
    """现场信息：结果文件、完成标记、当前选中、对象列表。"""

    return "\n".join(
        [
            f"结果文件（脚本把数值结果写到这里）：{result_path}",
            f'完成标记文件（脚本最后一行必须是 appendFileLine: "{state_path}", "done"）：'
            f"{state_path}",
            "",
            qwen.selected_object_hint(object_context),
            "",
            "当前 Praat 对象列表（id、类、名称、是否选中）：",
            object_context,
        ]
    )


def run_turn(
    client: qwen.QwenClient,
    *,
    user_text: str,
    context_text: str,
    history: list[dict[str, str]],
    context: tools.ToolContext,
    execute: Callable[[str], tuple[bool, list[str], str]],
    on_progress: Callable[[str], None] | None = None,
    native: bool | None = None,
    max_rounds: int = MAX_AGENT_ROUNDS,
    environment: tools.LocalEnvironment | None = None,
    cancel: threading.Event | None = None,
) -> TurnOutcome:
    """跑一轮用户请求：先规划，执行，把结果回灌，再规划（见 ``MAX_AGENT_ROUNDS``）。

    ``execute(脚本)`` 由调用方提供，返回 ``(是否成功, 结果行, 失败说明)``——对话窗口
    用它投递给正在运行的 Praat，验证脚本用它跑批处理。

    ``cancel``（C7）是「停止」按钮的事件；``context_text`` / ``history`` 会按
    token 预算裁一遍（A5），被省掉的部分写进 ``TurnOutcome.notes``。
    """

    use_native = (
        qwen.planner_mode() != qwen.JSON_MODE if native is None else native
    )
    schemas = tools.tool_schemas() if use_native else []
    # A5：先扣掉工具 schema、系统提示、用户这句话和回答预留，剩下的才是
    # 「现场信息 + 对话历史」能用的额度；对象列表最多拿三分之一（它得让模型看到
    # 当前选中，但不该把历史挤光）。
    # 老的 JSON 规划把工具清单写在提示词里，那份开销也要算进去。
    instructions = (
        qwen.TOOL_PLANNER_INSTRUCTIONS if use_native else tools.catalog_text()
    )
    budget = qwen.history_budget(
        client.config.max_context_tokens,
        instructions=instructions,
        tool_schemas=schemas,
        user_text=user_text,
        response_tokens=client.config.plan_max_tokens,
    )
    trimmed_context, hidden_rows = qwen.trim_object_context(
        context_text, max_tokens=max(120, budget // 3)
    )
    trimmed_history, dropped_turns = qwen.trim_history(
        history, max_tokens=max(0, budget - qwen.estimate_tokens(trimmed_context))
    )
    notes: list[str] = []
    if hidden_rows:
        notes.append(
            f"对象列表太长，这次只列了一部分给模型（还有 {hidden_rows} 个没列出）。"
            "先说清要操作哪个对象更稳。"
        )
    if dropped_turns:
        overhead = qwen.estimate_tokens(instructions) + qwen.estimate_tokens(
            json.dumps(schemas, ensure_ascii=False)
        )
        notes.append(
            f"对话太长：这一轮只带了最近 {len(trimmed_history)} 条历史"
            f"（省掉更早的 {dropped_turns} 条）。本机上下文窗口 "
            f"{client.config.max_context_tokens}，工具说明加系统提示约占 "
            f"{overhead} token——想多带历史可以在模型预设里把 context_tokens 调大。"
        )
    planner_class = _NativePlanner if use_native else _JsonPlanner
    planner = planner_class(
        client,
        user_text=user_text,
        context_text=trimmed_context,
        history=trimmed_history,
        result_path=str(context.result_path),
        state_path=str(context.state_path),
    )
    outcome = _run_agent_turn(
        planner,
        context=context,
        execute=execute,
        on_progress=on_progress,
        max_rounds=2 if not use_native else max_rounds,
        allow_followup_mutations=wants_second_step(user_text),
        environment=environment,
        cancel=cancel,
    )
    outcome.notes[:0] = notes
    return outcome


def _send_script(
    executable: str,
    script: str,
    *,
    request_id: str = "",
    cancel: threading.Event | None = None,
    process_id: int | None = None,
) -> tuple[bool, str]:
    """Hand the script to the running Praat and wait for its result files.

    默认走 :mod:`praat_ai.sendpraat`：自己写 ``Message.txt`` 再发 ``WM_APP``。
    这样 Praat 一个窗口都不会被激活——用户报的「弹出 Praat Info」和「声音窗口
    盖住对话窗口」都是老的 ``Praat.exe --send`` 干的（见 guide.md §8.5）。

    设 ``PRAAT_AI_SEND_MODE=argv`` 可以退回 ``--send`` 排障：那条路会激活一个
    Praat 子窗口，而且 ``--send`` 在 Praat 被模态窗口挡住时会一直阻塞（实测
    超过 60 秒，脚本其实已经排队），所以老路径仍然用「后台 Popen + 轮询」，
    不回到 ``subprocess.run(timeout=60)``。

    每条指令写一个自己的脚本文件，并在开头带上请求编号（:func:`script_preamble`）：
    这是「投递出去的那条」和「真的执行了的那条」对得上的凭据。

    ``process_id`` 指定送给哪一个 Praat（默认最新打开的那个，和 ``--send`` 一致）；
    验证脚本用它把自己开的那个实例和用户开着的实例区分开。
    """

    request_id = request_id or new_request_id()
    target = script_path(request_id)
    _clear_result_files()
    target.write_text(script_preamble(request_id) + script, encoding="utf-8")
    prune_command_scripts()
    if sendpraat.send_mode() == sendpraat.ARGV_MODE:
        return _send_script_via_argv(executable, target, request_id, cancel=cancel)
    delivered, note = sendpraat.deliver(ai_directory(), target, process_id=process_id)
    if not delivered:
        return False, note
    return _wait_for_result(None, request_id=request_id, cancel=cancel)


def _send_script_via_argv(
    executable: str,
    target: Path,
    request_id: str = "",
    *,
    cancel: threading.Event | None = None,
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
    return _wait_for_result(process, request_id=request_id, cancel=cancel)


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


def _read_failure() -> str:
    """Praat 写下的脚本错误（没有就返回空串）。"""

    path = failure_path()
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


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


def praat_process_running_from(process_ids: list[int] | None) -> bool:
    """按**已经查好的**进程列表判断 Praat 在不在跑。

    每条指令原来会起两次 ``tasklist``（一次判断在不在跑、一次数几个实例），这里
    让调用方查一次、两件事都用同一份结果——Praat 的进程名和实例数都不该在一次
    请求里被查两遍（``tasklist`` 是子进程，几十毫秒起步）。

    ``None`` 表示查不到（不是 Windows、tasklist 不可用），这时不拦用户：交给投递
    那一步自己报错，比前端误判「Praat 没开」强。
    """

    if process_ids is None:
        return True
    return bool(process_ids)


def praat_instance_warning_from(process_ids: list[int] | None) -> str:
    """按已经查好的进程列表给「多个 Praat」的提醒。"""

    if not process_ids or len(process_ids) < 2:
        return ""
    return (
        f"检测到 {len(process_ids)} 个 Praat 在运行：脚本只会送给最新打开的那个"
        "窗口。请关掉多余的 Praat，否则可能操作到别的对象列表。"
    )


def praat_process_running(executable: str) -> bool:
    return praat_process_running_from(praat_process_ids(executable))


def praat_instance_warning(executable: str) -> str:
    """同时开着多个 Praat 时返回一句提醒，否则返回空字符串。"""

    return praat_instance_warning_from(praat_process_ids(executable))


def model_status_text(config) -> str:
    """状态栏文案：模型来自服务实际加载的模型，而不是配置里的文件名。"""

    if api_is_active(config):
        label = config.api.label or "云端 API"
        return f"模型：{config.api.model}（{label}，API 模式，不需要本机服务）"
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


def refresh_object_context(
    executable: str,
    process_ids: list[int] | None = None,
    *,
    force: bool = False,
    assume_fresh: bool = False,
) -> tuple[bool, str]:
    """让正在运行的 Praat 重新写一次对象列表，返回 ``(是否成功, 说明)``。

    ``chat_context.tsv`` 由 Praat 维护：Praat 重启、换会话或对象被改动之后，
    对话窗口手里的列表可能是旧的。旧 id 会让脚本报「没有编号为 1」这种看不懂
    的错误，所以每次执行前先送一条空脚本刷新，顺带确认 Praat 还在响应用户。

    **C5**：Praat 会在文件末尾写 ``# praat-pid=<进程号>``。标记就是当前这个
    Praat 时说明列表是最新的（Praat 自己会在每条 app 消息之后、以及用户改选中或
    增删对象之后重写它），这时**一条消息都不发**；只有标记对不上（Praat 重启过）、
    文件缺失、或者对方的 Praat 不写标记时才真的投一条刷新。``force=True`` 强制刷。

    ``assume_fresh=True`` 是给「老版本 Praat（不写标记）」用的同一条捷径：Praat
    每执行完一条 app 消息都会重写对象列表（``cb_userMessage()`` 里那句），所以只要
    这一轮之前已经成功投递过一条脚本、而且还是同一个 Praat 进程，列表就是新的。
    对话窗口自己记着这件事（``ChatWindow.context_ready_pids``）。
    """

    if not executable:
        return False, ""
    if process_ids is None:
        process_ids = praat_process_ids(executable)
    if not praat_process_running_from(process_ids):
        return False, ""
    if not force and context_path().is_file():
        if assume_fresh or context_belongs_to(process_ids):
            return True, ""
    ok, output = _send_script(executable, context_ping_script())
    if ok:
        return True, ""
    return False, output or "Praat 没有响应，无法刷新对象列表。"


def context_belongs_to(process_ids: list[int] | None) -> bool:
    """对象列表文件是不是这几个正在跑的 Praat 之一写的。"""

    if not process_ids:
        return False
    path = context_path()
    if not path.is_file():
        return False
    try:
        marker = context_pid(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return False
    return marker != 0 and marker in set(process_ids)


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
        self.client = qwen.QwenClient(self.config.qwen)
        self.history: list[dict[str, str]] = []
        self.messages: queue.Queue[tuple[str, str]] = queue.Queue()
        self.busy = False
        #: C7：点「停止」时置上，正在等的投递/批处理/多轮循环都会看到。
        self.cancel_event = threading.Event()
        #: C5：已经投递过脚本的 Praat 进程集合——之后不用再送那条 ping 往返。
        self.context_ready_pids: frozenset[int] = frozenset()
        #: 加载/停止模型时的迷你进度小窗（懒创建，用完关掉）。
        self.progress_window = None

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
        # API 配置：填 key 接云端大模型（更大的模型当后端），不用本地 llama-server。
        self.api_button = ttk.Button(
            preset_row,
            text="API 配置…",
            width=12,
            command=self.open_api_settings,
        )
        self.api_button.grid(row=0, column=3, sticky="e", padx=(6, 0))
        self.preset_hint = tk.StringVar(value="")
        ttk.Label(
            preset_row,
            textvariable=self.preset_hint,
            style="Hint.TLabel",
            font=("Microsoft YaHei UI", 8),
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))
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
        # C7：等待可以取消。Praat 卡住、社区脚本跑太久时不用干等 25 秒。
        self.stop_button = ttk.Button(
            composer,
            text="停止",
            command=self.cancel_turn,
            width=8,
            state="disabled",
        )
        self.stop_button.grid(row=0, column=2, sticky="ns", padx=(6, 0))
        ttk.Label(
            composer,
            text=(
                "Enter 发送，Shift+Enter 换行；脚本在正在运行的 Praat 里执行，结果会回到这里；"
                "「停止」= 不再等这一步（Praat 里已经在跑的脚本不受影响）"
            ),
            foreground="#6B7280",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

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
        if api_is_active(self.config):
            label = self.config.api.label or "云端 API"
            return (
                f"当前是 API 模式：{label} / {self.config.api.model}"
                "（不需要本机 llama-server）；想回到本机模型就选一个预设再点「应用预设」。"
            )
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

            result = control.apply_preset(preset_id, progress=self._progress_sink())
        except (PresetError, qwen.QwenError, OSError, ValueError) as error:
            self.messages.put(("assistant", f"切换模型预设失败：{error}"))
        else:
            label = str(result.get("frontend_preset_label", "")) or preset_id
            model = str(result.get("frontend_model", ""))
            vision = "视觉已开" if result.get("frontend_vision") else "纯文本"
            self.messages.put(
                ("assistant", f"已切换模型预设：{label}（{model}，{vision}）")
            )
        finally:
            self.messages.put(("progress-done", ""))
            self.messages.put(("reload", ""))
            self.messages.put(("done", ""))

    # ------------------------------------------------------------ API 配置

    def _progress_sink(self):
        """把「加载/停止模型」的进度送到界面线程（迷你进度条那张小窗）。"""

        def sink(fraction: float, message: str) -> None:
            self.messages.put(("progress", f"{fraction:.4f}|{message}"))

        return sink

    def open_api_settings(self) -> None:
        """打开「API 配置」小窗口（填 key 接云端大模型）。"""

        # 已经开着就把它提到前面，别开一堆同样的窗口。
        existing = getattr(self, "api_dialog", None)
        if existing is not None:
            try:
                if existing.window.winfo_exists():
                    existing.window.lift()
                    existing.window.focus_set()
                    return
            except tk.TclError:
                pass
        dialog = api_settings.ApiSettingsDialog(
            self.root,
            config=self.config,
            on_saved=self.on_api_settings_saved,
        )
        self.api_dialog = dialog
        self.append_hint(
            "API 配置：填服务商、地址、模型名和 API key，点「测试连接」确认后保存，"
            "前端就会改用它（本机 llama-server 的配置会保留）。"
        )
        try:
            dialog.window.transient(self.root)
        except tk.TclError:
            pass

    def on_api_settings_saved(self, values: dict) -> None:
        """保存之后刷新界面；如果刚切到 API 模式，顺手停掉本机模型服务省显存。"""

        self.reload_config()
        if api_is_active(self.config):
            self.append_hint(
                f"已切到 API 模式：{self.config.api.label or '云端 API'} / "
                f"{self.config.api.model}（对话走云端，不再需要本机模型服务）。"
            )
            self.messages.put(("stop-local-service", ""))
        else:
            self.append_hint("已关闭 API 模式：前端回到本地模型预设。")

    def stop_local_service_worker(self) -> None:
        """API 模式下把还在跑的本机 llama-server 停掉（主要目的是腾显存）。"""

        from . import control

        try:
            result = control.stop_frontend(progress=self._progress_sink())
        except (OSError, ValueError) as error:
            self.messages.put(("hint", f"停止本机模型服务失败：{error}"))
        else:
            if result.get("api_enabled"):
                self.messages.put(("hint", "本机模型服务已停（API 模式下不再需要它）。"))
        finally:
            self.messages.put(("progress-done", ""))

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
        self.cancel_event.clear()
        self.send_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.preset_button.configure(state="disabled")
        self.status.set("Praat AI  |  正在处理请求…")
        self.append("user", text)
        threading.Thread(
            target=self.process_message,
            args=(text,),
            daemon=True,
        ).start()
        return "break"

    def cancel_turn(self) -> None:
        """C7：不再等这一步。已经在 Praat 里跑的脚本不受影响（它可能已经跑完）。"""

        if not self.busy:
            return
        self.cancel_event.set()
        self.stop_button.configure(state="disabled")
        self.append_hint("已请求停止：不再等这一步；Praat 里已经在跑的脚本不受影响。")

    def run_user_turn(self, text: str, executable: str) -> TurnOutcome:
        """规划并执行一轮用户请求（可能多步），返回最终回答和每一步的结果。

        执行由 :func:`_send_script` 完成，所以每一步都是一条独立的 app 消息（各自
        有请求编号）；每步跑完把结果（或错误）回灌给模型，让它接着做或者解释结果。
        """

        context_text = object_context()
        rows = tools.parse_object_context(context_text)
        context = tools.ToolContext(
            objects=rows,
            result_path=result_path(),
            state_path=state_path(),
        )

        def execute(script: str) -> tuple[bool, list[str], str]:
            ok, output = _send_script(executable, script, cancel=self.cancel_event)
            if not ok:
                return False, [], output or _blocked_reason()
            failure = _read_failure()
            if failure:
                # 脚本在 Praat 里报错了：Praat 把原文写进了 chat_failure.txt
                # （不再弹模态框），这里按「失败」回灌给模型。
                return False, _read_results(), failure
            return True, _read_results(), ""

        # 本地工具（跑现成 .praat 脚本那种）需要：往开着的 Praat 投递脚本、
        # 批处理用的 Praat 路径、放临时文件的地方，以及「用户点停止了吗」。
        environment = tools.LocalEnvironment(
            execute=execute,
            praat_executable=executable,
            runtime_directory=runtime_dir(),
            cancelled=self.cancel_event.is_set,
        )

        return run_turn(
            self.client,
            user_text=text,
            context_text=context_text,
            history=self.history,
            context=context,
            execute=execute,
            on_progress=lambda line: self.messages.put(("hint", line)),
            environment=environment,
            cancel=self.cancel_event,
        )

    def process_message(self, text: str) -> None:
        try:
            executable = praat_executable()
            # 一次 tasklist 查清「Praat 在不在跑」和「开了几个」——以前每条指令查两次。
            process_ids = praat_process_ids(executable) if executable else None
            praat_ready = bool(executable) and praat_process_running_from(process_ids)
            if praat_ready:
                warning = praat_instance_warning_from(process_ids)
                if warning:
                    self.messages.put(("hint", warning))
                # 先刷新对象列表，免得拿着过期 id 去规划。C5：已经确认过、而且还是
                # 同一个 Praat 进程时，这一步一次往返都不花。
                already_ready = self.context_ready_pids == frozenset(process_ids or [])
                refreshed, note = refresh_object_context(
                    executable, process_ids, assume_fresh=already_ready
                )
                if not refreshed and note:
                    self.messages.put(("hint", note))
                elif refreshed:
                    self.context_ready_pids = frozenset(process_ids or [])

            if not executable:
                raise OSError(
                    praat_app.describe_search()
                    + " 也可以从 Praat 菜单「前端 → 启动前端」重新打开对话窗口。"
                )
            if not praat_ready:
                raise OSError(
                    "没有检测到正在运行的 Praat。请先打开 Praat，"
                    "再从菜单「前端 → 启动前端」启动对话窗口。"
                )

            outcome = self.run_user_turn(text, executable)
            for note in outcome.notes:
                self.messages.put(("hint", note))

            if not outcome.used_tools:
                # 模型判断不需要动手（打招呼、或者这件事做不到），直接回话。
                self.messages.put(("assistant", outcome.reply))
                self.history.append({"role": "user", "content": text})
                self.history.append({"role": "assistant", "content": outcome.reply})
                return

            if outcome.results:
                body = f"{outcome.reply}\n结果：{'；'.join(outcome.results)}"
                self.messages.put(("assistant", body))
                self.messages.put(("result", "结果：\n" + "\n".join(outcome.results)))
                if outcome.failure:
                    # 前面几步成功、后面某一步没做成：结果照给，另起一句说明。
                    self.messages.put(("hint", outcome.failure))
                self.history.append({"role": "user", "content": text})
                self.history.append({"role": "assistant", "content": body})
                return

            message = (
                f"{outcome.reply}\n执行未完成：Praat 没有返回结果。"
                "常见原因是 Praat 里还开着别的模态窗口（错误提示、正在播放的窗口、"
                "没关掉的对话框）挡住了消息；关掉它们再发一次即可。"
                "脚本自己报错时 Praat 会把原文写回这里（见下面那行）。"
            )
            if outcome.failure:
                message += f"\n{outcome.failure}"
            else:
                message += (
                    "\n（Praat 没有输出任何信息：常见原因是脚本里的命令和当前"
                    "选中的对象不匹配，或者 Praat 正被对话框挡住。）"
                )
            if outcome.last_script:
                message += f"\n\n本次脚本：\n{tools.describe_script(outcome.last_script)}"
            self.messages.put(("assistant", message))
            self.history.append({"role": "user", "content": text})
            self.history.append(
                {"role": "assistant", "content": "（上次脚本执行未完成）"}
            )
        except (qwen.QwenError, tools.ToolError, PresetError, OSError) as error:
            self.messages.put(("assistant", f"处理失败：{error}"))
        finally:
            self.messages.put(("done", ""))

    def flush_messages(self) -> None:
        try:
            while True:
                role, text = self.messages.get_nowait()
                if role == "done":
                    self.busy = False
                    self.cancel_event.clear()
                    self.send_button.configure(state="normal")
                    self.stop_button.configure(state="disabled")
                    self.preset_button.configure(
                        state="normal" if self.presets else "disabled"
                    )
                    self.status.set("Praat AI  |  " + model_status_text(self.config))
                    self.context_label.set(selected_object_label())
                    self.entry.focus_set()
                elif role == "reload":
                    self.reload_config()
                elif role == "progress":
                    self.show_progress(text)
                elif role == "progress-done":
                    self.hide_progress()
                elif role == "stop-local-service":
                    threading.Thread(
                        target=self.stop_local_service_worker, daemon=True
                    ).start()
                elif role in {"result", "failure"}:
                    self.append_lines(role, text)
                elif role == "hint":
                    self.append_hint(text)
                else:
                    self.append(role, text)
        except queue.Empty:
            pass
        self.root.after(100, self.flush_messages)

    def show_progress(self, payload: str) -> None:
        """更新（必要时创建）迷你进度窗。``payload`` 是 ``"0.42|说明"``。"""

        fraction_text, _, message = payload.partition("|")
        try:
            fraction = float(fraction_text)
        except ValueError:
            fraction = 0.0
        if self.progress_window is None:
            self.progress_window = progress_popup.MiniProgress(
                self.root, message=message or "正在加载模型…"
            )
        self.progress_window.update(fraction, message or None)

    def hide_progress(self) -> None:
        if self.progress_window is not None:
            self.progress_window.close()
            self.progress_window = None

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
        self.client = qwen.QwenClient(self.config.qwen)
        self.presets = list_presets(self.config)
        self.refresh_preset_widgets()
        self.status.set("Praat AI  |  " + model_status_text(self.config))

    def run(self) -> int:
        self.root.mainloop()
        return 0


def main() -> int:
    return ChatWindow().run()
