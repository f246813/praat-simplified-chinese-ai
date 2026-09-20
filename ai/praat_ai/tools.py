"""Deterministic Praat tool templates for the local AI chat frontend.

The chat window does not trust free-form model output for common operations:
every tool in this module renders a fixed Praat script template from validated
arguments, so the model only has to pick a tool and fill in a few numbers.
Free-form scripts remain available as a validated fallback.

本机已用批处理 Praat 实测确认的语法要点：

- 对象名带类名前缀（``selectObject: "Sound 思い出す"``）；数字 id 最稳，
  所以模板统一用对象 id。
- 字符串只能用双引号；单引号在 Praat 里是变量插值，会报 ``Unknown symbol``。
- 查询命令的返回值可以赋给变量，再用 ``appendFileLine`` 写回结果文件。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


class ToolError(ValueError):
    """Raised when a tool request cannot be turned into a safe Praat script."""


FORBIDDEN_SCRIPT_PATTERNS = re.compile(
    r"\b(?:runSystem|runSubprocess|deleteFile|filedelete|createFolder|createDirectory"
    r"|quit|exit|exitScript|system|shell|execute|python|runScript)\b",
    re.IGNORECASE,
)

SINGLE_QUOTED_LITERAL = re.compile(r"'([^'\n]*)'")

TEMPORARY_OBJECT_NAME = "ai-chat-temp"

CUSTOM_SCRIPT_TOOL = "custom_script"


@dataclass(frozen=True, slots=True)
class ObjectRow:
    id: int
    class_name: str
    name: str
    selected: bool

    @property
    def label(self) -> str:
        return f"{self.id}: {self.name}"


@dataclass(frozen=True, slots=True)
class ToolContext:
    objects: tuple[ObjectRow, ...]
    result_path: Path
    state_path: Path

    def default_object(self) -> ObjectRow:
        for row in self.objects:
            if row.selected:
                return row
        if self.objects:
            return self.objects[-1]
        raise ToolError("Praat 对象列表为空，请先在 Praat 中打开或新建对象。")

    def resolve_object(self, requested: Any = None) -> ObjectRow:
        if requested is None or requested == "":
            return self.default_object()
        text = str(requested).strip()
        for row in self.objects:
            if text == str(row.id):
                return row
        for row in self.objects:
            if text in {row.name, f"{row.class_name} {row.name}", row.label}:
                return row
        lowered = text.casefold()
        for row in self.objects:
            if lowered in {
                row.name.casefold(),
                row.label.casefold(),
                f"{row.class_name} {row.name}".casefold(),
            }:
                return row
        raise ToolError(f"对象列表里没有“{text}”，请先确认 Praat 中选中的对象。")


def parse_object_context(text: str) -> tuple[ObjectRow, ...]:
    """Parse the ``id / class / name / selected`` TSV written by Praat."""

    rows: list[ObjectRow] = []
    for line in (text or "").splitlines():
        parts = [part.strip() for part in line.split("\t")]
        if len(parts) < 4 or not parts[0].isdigit():
            continue
        rows.append(
            ObjectRow(
                id=int(parts[0]),
                class_name=parts[1],
                name=parts[2],
                selected=parts[3] == "1",
            )
        )
    return tuple(rows)


def praat_text(value: Any) -> str:
    """Render text that is safe inside a Praat double-quoted string."""

    text = str(value).replace("\\", "/").replace('"', '""')
    return text.replace("\r", " ").replace("\n", " ")


def quote(value: Any) -> str:
    return f'"{praat_text(value)}"'


def praat_path(path: Path) -> str:
    return praat_text(str(path))


def _number(
    arguments: Mapping[str, Any],
    key: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    value = arguments.get(key, None)
    if value is None or value == "":
        return default
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ToolError(f"参数 {key} 必须是数字，收到：{value!r}") from error
    if not minimum <= number <= maximum:
        raise ToolError(f"参数 {key} 必须在 {minimum} 与 {maximum} 之间。")
    return number


def _integer(
    arguments: Mapping[str, Any],
    key: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    number = _number(arguments, key, float(default), float(minimum), float(maximum))
    rounded = int(round(number))
    if abs(number - rounded) > 1e-6:
        raise ToolError(f"参数 {key} 必须是整数。")
    return rounded


def _time_line(arguments: Mapping[str, Any], *, fallback: str) -> str:
    value = arguments.get("time", None)
    if value is None or value == "":
        return f"time = {fallback}"
    return f"time = {_number(arguments, 'time', 0.0, 0.0, 36000.0):.6f}"


def _unit_literal(arguments: Mapping[str, Any], default: str) -> str:
    value = str(arguments.get("unit", default) or default).strip()
    lowered = value.casefold()
    if lowered in {"bark", "巴克"}:
        return '"Bark"'
    if lowered in {"hertz", "hz", "赫兹"}:
        return '"hertz"'
    raise ToolError(f"单位 {value!r} 不受支持，只能用 hertz 或 Bark。")


def _finish(context: ToolContext) -> list[str]:
    return [f"appendFileLine: {quote(context.state_path)}, \"done\""]


def _write_result(context: ToolContext, fragments: Sequence[str]) -> str:
    joined = ", ".join(fragments)
    return f"appendFileLine: {quote(context.result_path)}, {joined}"


def _assemble(lines: Sequence[str], context: ToolContext) -> str:
    body = [line for line in lines if line and line.strip()]
    body.extend(_finish(context))
    return "\n".join(body) + "\n"


def _formant_lines(
    arguments: Mapping[str, Any],
    context: ToolContext,
    *,
    command: str,
    label: str,
) -> list[str]:
    row = context.resolve_object(arguments.get("object"))
    formant = _integer(arguments, "formant", 2, 1, 20)
    unit = _unit_literal(arguments, "hertz")
    temporary = row.class_name != "Formant"
    lines = [f"selectObject: {row.id}", "duration = Get total duration"]
    lines.append(_time_line(arguments, fallback="duration / 2"))
    if temporary:
        lines.extend(
            [
                "To Formant (burg): 0, 5, 5500, 0.025, 50",
                f"Rename: {quote(TEMPORARY_OBJECT_NAME)}",
            ]
        )
    lines.append(f"value = {command}: {formant}, time, {unit}, \"linear\"")
    lines.append(
        _write_result(
            context,
            [
                quote(f"第 {formant} 共振峰{label}（"),
                "fixed$ (time, 3)",
                quote(" 秒处）= "),
                "fixed$ (value, 3)",
                quote(" Hz"),
            ],
        )
    )
    if temporary:
        lines.extend(["Remove", f"selectObject: {row.id}"])
    return lines


def _build_duration(arguments: Mapping[str, Any], context: ToolContext) -> str:
    row = context.resolve_object(arguments.get("object"))
    lines = [
        f"selectObject: {row.id}",
        "duration = Get total duration",
        _write_result(
            context,
            [quote(f"{row.name} 总时长 = "), "fixed$ (duration, 6)", quote(" 秒")],
        ),
    ]
    return _assemble(lines, context)


def _build_formant_bandwidth(arguments: Mapping[str, Any], context: ToolContext) -> str:
    return _assemble(
        _formant_lines(arguments, context, command="Get bandwidth at time", label="带宽"),
        context,
    )


def _build_formant_frequency(arguments: Mapping[str, Any], context: ToolContext) -> str:
    return _assemble(
        _formant_lines(arguments, context, command="Get value at time", label="频率"),
        context,
    )


def _build_pitch(arguments: Mapping[str, Any], context: ToolContext) -> str:
    row = context.resolve_object(arguments.get("object"))
    temporary = row.class_name != "Pitch"
    lines = [f"selectObject: {row.id}", "duration = Get total duration"]
    lines.append(_time_line(arguments, fallback="duration / 2"))
    if temporary:
        floor = _number(arguments, "pitch_floor", 75.0, 20.0, 1000.0)
        ceiling = _number(arguments, "pitch_ceiling", 600.0, 50.0, 2000.0)
        lines.extend(
            [
                f"To Pitch: 0, {floor:.6f}, {ceiling:.6f}",
                f"Rename: {quote(TEMPORARY_OBJECT_NAME)}",
            ]
        )
    lines.append('value = Get value at time: time, "Hertz", "linear"')
    lines.append(
        _write_result(
            context,
            [
                quote("基频（"),
                "fixed$ (time, 3)",
                quote(" 秒处）= "),
                "fixed$ (value, 3)",
                quote(" Hz"),
            ],
        )
    )
    if temporary:
        lines.extend(["Remove", f"selectObject: {row.id}"])
    return _assemble(lines, context)


def _build_intensity(arguments: Mapping[str, Any], context: ToolContext) -> str:
    row = context.resolve_object(arguments.get("object"))
    temporary = row.class_name != "Intensity"
    lines = [f"selectObject: {row.id}", "duration = Get total duration"]
    lines.append(_time_line(arguments, fallback="duration / 2"))
    if temporary:
        lines.extend(
            [
                'To Intensity: 100, 0, "yes"',
                f"Rename: {quote(TEMPORARY_OBJECT_NAME)}",
            ]
        )
    lines.append('value = Get value at time: time, "cubic"')
    lines.append(
        _write_result(
            context,
            [
                quote("强度（"),
                "fixed$ (time, 3)",
                quote(" 秒处）= "),
                "fixed$ (value, 3)",
                quote(" dB"),
            ],
        )
    )
    if temporary:
        lines.extend(["Remove", f"selectObject: {row.id}"])
    return _assemble(lines, context)


def _build_select(arguments: Mapping[str, Any], context: ToolContext) -> str:
    row = context.resolve_object(arguments.get("object"))
    lines = [
        f"selectObject: {row.id}",
        _write_result(context, [quote("已选中："), quote(row.name)]),
    ]
    return _assemble(lines, context)


def _build_view(arguments: Mapping[str, Any], context: ToolContext) -> str:
    row = context.resolve_object(arguments.get("object"))
    lines = [
        f"selectObject: {row.id}",
        "View & Edit",
        _write_result(context, [quote("已打开编辑器："), quote(row.name)]),
    ]
    return _assemble(lines, context)


def _build_play(arguments: Mapping[str, Any], context: ToolContext) -> str:
    row = context.resolve_object(arguments.get("object"))
    lines = [
        f"selectObject: {row.id}",
        "Play",
        _write_result(context, [quote("已播放："), quote(row.name)]),
    ]
    return _assemble(lines, context)


def _build_rename(arguments: Mapping[str, Any], context: ToolContext) -> str:
    row = context.resolve_object(arguments.get("object"))
    new_name = str(arguments.get("new_name", "") or "").strip()
    if not new_name:
        raise ToolError("重命名需要 new_name 参数。")
    lines = [
        f"selectObject: {row.id}",
        f"Rename: {quote(new_name)}",
        _write_result(context, [quote(f"{row.name} 已重命名为 {new_name}")]),
    ]
    return _assemble(lines, context)


def _build_remove(arguments: Mapping[str, Any], context: ToolContext) -> str:
    row = context.resolve_object(arguments.get("object"))
    lines = [
        f"selectObject: {row.id}",
        "Remove",
        _write_result(context, [quote("已删除："), quote(row.name)]),
    ]
    return _assemble(lines, context)


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    summary: str
    signature: str
    build: Callable[[Mapping[str, Any], ToolContext], str]

    def describe(self) -> str:
        return f"- {self.name}: {self.summary} 参数：{self.signature}"


TOOLS: tuple[Tool, ...] = (
    Tool(
        name="duration",
        summary="查询对象的时长（秒）。",
        signature="object（可选，对象 id 或名称）",
        build=_build_duration,
    ),
    Tool(
        name="formant_bandwidth",
        summary="查询第 n 共振峰在某一时刻的带宽（Hz）；对象是 Sound 时自动先做共振峰分析。",
        signature="formant（默认 2）、time（秒，默认中点）、unit（hertz/Bark）、object（可选）",
        build=_build_formant_bandwidth,
    ),
    Tool(
        name="formant_frequency",
        summary="查询第 n 共振峰在某一时刻的频率（Hz）；对象是 Sound 时自动先做共振峰分析。",
        signature="formant（默认 2）、time（秒，默认中点）、unit（hertz/Bark）、object（可选）",
        build=_build_formant_frequency,
    ),
    Tool(
        name="pitch",
        summary="查询某一时刻的基频（Hz）。",
        signature="time（秒，默认中点）、pitch_floor、pitch_ceiling、object（可选）",
        build=_build_pitch,
    ),
    Tool(
        name="intensity",
        summary="查询某一时刻的强度（dB）。",
        signature="time（秒，默认中点）、object（可选）",
        build=_build_intensity,
    ),
    Tool(
        name="select_object",
        summary="按 id 或名称选中对象。",
        signature="object",
        build=_build_select,
    ),
    Tool(
        name="view_edit",
        summary="用编辑器打开对象。",
        signature="object（可选）",
        build=_build_view,
    ),
    Tool(
        name="play",
        summary="播放选中的 Sound。",
        signature="object（可选）",
        build=_build_play,
    ),
    Tool(
        name="rename_object",
        summary="重命名对象。",
        signature="new_name、object（可选）",
        build=_build_rename,
    ),
    Tool(
        name="remove_object",
        summary="删除对象。",
        signature="object（可选）",
        build=_build_remove,
    ),
)

TOOL_MAP: dict[str, Tool] = {tool.name: tool for tool in TOOLS}


def catalog_text() -> str:
    lines = [tool.describe() for tool in TOOLS]
    lines.append(
        f"- {CUSTOM_SCRIPT_TOOL}: 只有在上面所有工具都无法完成请求时才使用；"
        "这时把完整 Praat 英文脚本写进 script 字段。"
    )
    return "\n".join(lines)


def normalize_script(script: str) -> str:
    """Fix the most common model mistakes in free-form Praat scripts."""

    text = (script or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    if not text:
        return ""
    # Praat uses single quotes for variable interpolation, so a model writing
    # 'Sound x' almost always means the string "Sound x".
    text = SINGLE_QUOTED_LITERAL.sub(lambda match: f'"{match.group(1)}"', text)
    return text.rstrip() + "\n"


def validate_script(script: str, *, maximum_length: int = 6000) -> str:
    normalized = normalize_script(script)
    if not normalized:
        raise ToolError("模型没有给出可执行的 Praat 脚本。")
    if len(normalized) > maximum_length:
        raise ToolError("模型生成的脚本过长。")
    if FORBIDDEN_SCRIPT_PATTERNS.search(normalized):
        raise ToolError("模型生成的脚本包含被禁止的命令。")
    for line in normalized.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.count('"') % 2 != 0:
            raise ToolError(f"脚本这一行的双引号不配对：{stripped}")
    return normalized


def render(
    tool_name: str,
    arguments: Mapping[str, Any] | None,
    context: ToolContext,
    *,
    custom_script: str = "",
) -> str:
    """Render the Praat script for one tool request."""

    name = (tool_name or "").strip()
    if not name:
        raise ToolError("模型没有选择工具。")
    if name == CUSTOM_SCRIPT_TOOL:
        script = validate_script(custom_script)
        return _assemble(script.rstrip("\n").splitlines(), context)
    tool = TOOL_MAP.get(name)
    if tool is None:
        raise ToolError(f"未知工具：{name}")
    if arguments is not None and not isinstance(arguments, Mapping):
        raise ToolError("arguments 必须是 JSON 对象。")
    return tool.build(arguments or {}, context)


def describe_script(script: str, *, maximum_lines: int = 14) -> str:
    lines = [line for line in script.splitlines() if line.strip()]
    shown = lines[:maximum_lines]
    text = "\n".join(shown)
    if len(lines) > maximum_lines:
        text += f"\n…（共 {len(lines)} 行）"
    return text
