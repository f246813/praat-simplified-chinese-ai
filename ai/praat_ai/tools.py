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

import json
import math
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import external_script, measures


class ToolError(ValueError):
    """Raised when a tool request cannot be turned into a safe Praat script."""


FORBIDDEN_SCRIPT_PATTERNS = re.compile(
    r"\b(?:runSystem|runSubprocess|deleteFile|filedelete|createFolder|createDirectory"
    r"|quit|exit|exitScript|system|shell|execute|python|runScript)\b",
    re.IGNORECASE,
)

SINGLE_QUOTED_LITERAL = re.compile(r"'([^'\n]*)'")

# 模型偶尔会把 Python 代码当成 Praat 脚本填进 script 字段。这类脚本在 Praat 里
# 只会得到一句莫名其妙的英文报错，所以这里直接识别出来并给出中文提示。
PYTHON_SCRIPT_PATTERNS = re.compile(
    r"^\s*(?:import|from)\s+[A-Za-z_][\w.]*(?:\s+import\s+|\s*$)"
    r"|^\s*def\s+\w+\s*\("
    r"|^\s*(?:print|input|len|range)\s*\("
    r"|\bparselmouth\b|\bnumpy\b|np\.\w+|\bos\.\w+\(",
    re.MULTILINE,
)

# 会弹出「Praat Info」窗口的输出命令。脚本是交给 GUI 版 Praat 执行的，这些命令
# 走 MelderInfo_* → gui_information()，于是每执行一次就把 Info 窗口顶到前面
# （用户报的 bug，见 guide.md §8.5）。自定义脚本里一律**改写成写结果文件**，
# 模型想让用户看到的内容一句都不许丢（参考 PraatPlugin 的 ADR-006：宁可原样带
# 过去，也不要静默丢输出）：
#   - 带值列表的 appendInfoLine / writeInfoLine / appendInfo / writeInfo 直接换成
#     appendFileLine，参数原样带过去；
#   - printline / print / echo 在 Praat 里是把这一行剩下的**字面文字**写给 Info
#     窗口（不参与表达式求值，见 sys/praat_script.cpp），所以整段抄成一个字符串
#     参数；
#   - printtab 只写一个制表符、clearinfo 只管清空 Info 窗口，这两条没有可保留的
#     内容，改成注释说明。
INFO_LINE_PATTERN = re.compile(
    r"^(\s*)(appendInfoLine|writeInfoLine)\s*:(.*)$", re.IGNORECASE
)
INFO_VALUE_PATTERN = re.compile(
    r"^(\s*)(appendInfo|writeInfo)\s*:(.*)$", re.IGNORECASE
)
INFO_LITERAL_PATTERN = re.compile(
    r"^(\s*)(printline|print|echo)\b(.*)$", re.IGNORECASE
)
INFO_OTHER_PATTERN = re.compile(
    r"^\s*(?:appendInfo|writeInfo|printline|printtab|print|echo|clearinfo)\b[^\n]*$",
    re.IGNORECASE,
)
INFO_NOISE_PATTERN = re.compile(
    r"^\s*(?:printtab|clearinfo)\b[^\n]*$", re.IGNORECASE
)

TEMPORARY_OBJECT_NAME = "ai-chat-temp"

CUSTOM_SCRIPT_TOOL = "custom_script"

#: 表驱动的测量工具；它的参数表是 ``ai/praat_ai/measures.tsv``。
MEASURE_TOOL = "measure"

#: 跑现成（社区）.praat 脚本的工具；它不走「渲染脚本 → 投递」那条路，
#: 见 :class:`LocalTool` 与 ``ai/praat_ai/external_script.py``。
RUN_SCRIPT_TOOL = "run_praat_script"

# 「有时长概念」的对象类：只有这些类才能用 Get total duration 之类的查询，
# 否则脚本会在 Praat 里直接报 “Command not available”，用户只看到一句英文错误。
TIME_DOMAIN_CLASSES = frozenset(
    {
        "Sound",
        "LongSound",
        "Pitch",
        "Formant",
        "Intensity",
        "Harmonicity",
        "Spectrogram",
        "BarkSpectrogram",
        "Cochleagram",
        "Excitation",
        "MFCC",
        "Manipulation",
        "PointProcess",
        "TextGrid",
        "TextTier",
        "IntervalTier",
        "DurationTier",
        "PitchTier",
        "IntensityTier",
        "AmplitudeTier",
        "FormantTier",
        "Polygon",
    }
)

# 只有 Sound 类对象有 Play / 采样率 / 通道数。
SOUND_CLASSES = frozenset({"Sound", "LongSound"})

# 共振峰工具可以直接查询已有 Formant，也可以从 Sound 临时计算；其他对象即使
# 有时长（例如 Harmonicity）也不能作为共振峰输入。
FORMANT_SOURCE_CLASSES = frozenset({"Sound", "Formant"})


@dataclass(frozen=True, slots=True)
class ObjectRow:
    id: int
    class_name: str
    name: str
    selected: bool
    # Praat 那边打开着这个对象的编辑器时，会多写两列：用户手动拖出来的选区。
    selection_start: float | None = None
    selection_end: float | None = None
    # SoundEditor 在 VOT 小窗初始化后，还会发布保持不变的分析上下文。
    selection_context_start: float | None = None
    selection_context_end: float | None = None

    @property
    def selection(self) -> tuple[float, float] | None:
        """编辑器里手动拖出来的区间；只点了光标（首尾相等）时不算选区。"""

        if self.selection_start is None or self.selection_end is None:
            return None
        if self.selection_end - self.selection_start <= 0.0:
            return None
        return (self.selection_start, self.selection_end)

    @property
    def selection_context(self) -> tuple[float, float] | None:
        """与当前编辑器选区配套的固定 VOT 分析上下文。"""

        if self.selection_context_start is None or self.selection_context_end is None:
            return None
        if (
            not math.isfinite(self.selection_context_start)
            or not math.isfinite(self.selection_context_end)
            or self.selection_context_start >= self.selection_context_end
        ):
            return None
        return (self.selection_context_start, self.selection_context_end)

    @property
    def label(self) -> str:
        return f"{self.id}: {self.name}"

    def name_variants(self) -> set[str]:
        """对象名可能带或不带类名前缀，这里把所有可接受的写法都列出来。"""

        variants = {self.name, self.label, f"{self.class_name} {self.name}"}
        for prefix in (f"{self.class_name} ", self.class_name):
            if self.name.startswith(prefix):
                variants.add(self.name[len(prefix) :].strip())
        variants.add(f"{self.class_name} {self.id}")
        return {_normalize_text(item) for item in variants if item}


def _normalize_text(value: Any) -> str:
    text = str(value or "").casefold()
    for character in ('"', "'", "“", "”", "‘", "’"):
        text = text.replace(character, "")
    text = text.replace("_", " ").replace("\u3000", " ")
    return re.sub(r"\s+", " ", text).strip()


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
        normalized = _normalize_text(text)
        # 「2 号」「#2」「id 2」都当成 id 处理。
        identifier = re.fullmatch(r"(?:id\s*)?#?(\d+)\s*(?:号|对象)?", normalized)
        if identifier:
            wanted = int(identifier.group(1))
            for row in self.objects:
                if row.id == wanted:
                    return row
        for row in self.objects:
            if normalized in row.name_variants():
                return row
        # 模型常把 "Sound tone" 简写成 "tone"，或反过来只写类名加编号；
        # 唯一命中就接受，多个候选就让用户挑，避免猜错对象。
        partial = [
            row
            for row in self.objects
            if any(
                normalized in variant or variant in normalized
                for variant in row.name_variants()
            )
        ]
        if len(partial) == 1:
            return partial[0]
        if len(partial) > 1:
            options = "、".join(f"{row.id}: {row.name}" for row in partial)
            raise ToolError(f"“{text}”对应多个对象，请用对象 id 指定：{options}")
        raise ToolError(f"对象列表里没有“{text}”，请先确认 Praat 中选中的对象。")

    def require_class(
        self,
        row: ObjectRow,
        classes: frozenset[str],
        description: str,
    ) -> None:
        if row.class_name not in classes:
            raise ToolError(
                f"{description}（对象 {row.id} 是 {row.class_name}）。"
            )

    def resolve_by_class(
        self,
        requested: Any,
        classes: frozenset[str],
        description: str,
    ) -> ObjectRow:
        """按对象类取对象：点错了类型而列表里只有一个候选时，直接用那个候选。

        用户说「这个 TextGrid」时，模型有时候会把当前选中的 Sound 填进 ``object``。
        这类工具本来就只对该类型的对象有效，所以只要列表里恰有一个合格对象，
        就用它，而不是把一句中文错误丢给用户。
        """

        row = self.resolve_object(requested)
        if row.class_name in classes:
            return row
        candidates = [item for item in self.objects if item.class_name in classes]
        if len(candidates) == 1:
            return candidates[0]
        raise ToolError(f"{description}（对象 {row.id} 是 {row.class_name}）。")

    def resolve_formant_source(self, requested: Any = None) -> ObjectRow:
        """取共振峰分析输入：只允许 Sound / Formant，显式对象绝不猜换。"""

        description = "共振峰分析只接受 Sound 或 Formant 对象"
        if requested is not None and requested != "":
            row = self.resolve_object(requested)
            if row.class_name not in FORMANT_SOURCE_CLASSES:
                raise ToolError(
                    f"{description}（对象 {row.id} 是 {row.class_name}）。"
                )
            return row

        if not self.objects:
            raise ToolError("Praat 对象列表为空，请先在 Praat 中打开或新建对象。")

        selected = next((row for row in self.objects if row.selected), None)
        if selected and selected.class_name in FORMANT_SOURCE_CLASSES:
            return selected

        candidates = [
            row for row in self.objects if row.class_name in FORMANT_SOURCE_CLASSES
        ]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            options = "、".join(f"{row.id}: {row.name}" for row in candidates)
            raise ToolError(f"{description}，但有多个候选，请用对象 id 指定：{options}")
        if selected:
            raise ToolError(
                f"{description}（当前对象 {selected.id} 是 {selected.class_name}）。"
            )
        raise ToolError(f"{description}（对象列表中没有可用对象）。")


def parse_object_context(text: str) -> tuple[ObjectRow, ...]:
    """Parse the ``id / class / name / selected`` TSV written by Praat.

    旧版本只写四列；打开着编辑器时 Praat 会多写选区和固定 VOT 上下文列。
    缺列就当作没有圈选或固定上下文。
    """

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
                selection_start=_optional_seconds(parts, 4),
                selection_end=_optional_seconds(parts, 5),
                selection_context_start=_optional_seconds(parts, 6),
                selection_context_end=_optional_seconds(parts, 7),
            )
        )
    return tuple(rows)


def _optional_seconds(parts: list[str], index: int) -> float | None:
    if len(parts) <= index or not parts[index]:
        return None
    try:
        return float(parts[index])
    except ValueError:
        return None


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


def _query_times(
    arguments: Mapping[str, Any],
    *,
    fallback: str,
    maximum: int = 8,
) -> list[str]:
    """``time`` 可以是数字、列表或 "0.25,0.75" 这类文本，返回 Praat 时间表达式。

    用户常一次问多个时刻（「0.25 秒和 0.75 秒的基频」），所以这里统一成列表，
    由模板逐个时刻写一行结果。
    """

    raw = arguments.get("time", arguments.get("times", None))
    if raw is None or raw == "":
        return [fallback]
    items = raw if isinstance(raw, (list, tuple)) else re.split(r"[,，、;；\s]+", str(raw))
    values: list[str] = []
    for item in items:
        if str(item).strip() == "":
            continue
        try:
            number = _number({"value": item}, "value", 0.0, 0.0, 36000.0)
        except ToolError as error:
            raise ToolError(f"时间只能是 0–36000 之间的秒数，收到：{item!r}") from error
        values.append(f"{number:.6f}")
    if not values:
        return [fallback]
    if len(values) > maximum:
        raise ToolError(f"一次最多查询 {maximum} 个时刻。")
    return values


def _clamp_time_lines(suffix_variable: str = "note$") -> list[str]:
    """把 ``time`` 夹进对象时长，并说明是否被截断。

    时间超出对象范围时 Praat 不会报错，而是返回 ``--undefined--``；
    这里先夹到有效区间，再让模板把 ``--undefined--`` 换成中文说明。
    """

    return [
        f'{suffix_variable} = ""',
        "if time < 0",
        "    time = 0",
        f'    {suffix_variable} = "（已按对象时长截断）"',
        "endif",
        "if time > duration",
        "    time = duration",
        f'    {suffix_variable} = "（已按对象时长截断）"',
        "endif",
    ]


def _clamp_range_lines() -> list[str]:
    """把 ``tmin`` / ``tmax`` 夹进对象时长（Praat 的 from/to/end 是保留字）。"""

    return [
        "if tmin < 0",
        "    tmin = 0",
        "endif",
        "if tmax > duration",
        "    tmax = duration",
        "endif",
        "if tmin > tmax",
        "    tmin = 0",
        "    tmax = duration",
        "endif",
    ]


def _unit_literal(arguments: Mapping[str, Any], default: str) -> str:
    value = str(arguments.get("unit", default) or default).strip()
    lowered = value.casefold()
    if lowered in {"bark", "巴克"}:
        return '"Bark"'
    if lowered in {"hertz", "hz", "赫兹"}:
        return '"hertz"'
    raise ToolError(f"单位 {value!r} 不受支持，只能用 hertz 或 Bark。")


def _unit_display(arguments: Mapping[str, Any], default: str) -> str:
    return " Bark" if _unit_literal(arguments, default) == '"Bark"' else " Hz"


def _formant_numbers(arguments: Mapping[str, Any]) -> list[int]:
    """支持 ``formant`` 写成一个数字、列表或 "1,2" 这类文本。"""

    raw = arguments.get("formant", arguments.get("formants", None))
    if raw is None or raw == "":
        return [2]
    items = raw if isinstance(raw, (list, tuple)) else re.split(r"[,，、;\s]+", str(raw))
    numbers: list[int] = []
    for item in items:
        if str(item).strip() == "":
            continue
        try:
            number = _integer({"value": item}, "value", 1, 1, 20)
        except ToolError as error:
            raise ToolError(
                f"共振峰编号只能是 1–20 的整数，收到：{item!r}"
            ) from error
        if number not in numbers:
            numbers.append(number)
    if not numbers:
        return [2]
    if len(numbers) > 6:
        raise ToolError("一次最多查询 6 条共振峰。")
    return numbers


def _finish(context: ToolContext) -> list[str]:
    return [f"appendFileLine: {quote(context.state_path)}, \"done\""]


def _id_fragment(variable: str = "newId") -> str:
    """结果行里的「（id N）」：多步请求要靠它认出刚建出来的那个对象。

    2026-09-20 实测：不写 id 时模型在第二步只能拿旧对象的 id 顶上
    （「截取前 0.3 秒再改名」变成了给**原对象**改名）。
    """

    return f"{quote('（id ')}, fixed$ ({variable}, 0), {quote('）')}"


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
    with_bandwidth: bool = False,
) -> list[str]:
    row = context.resolve_formant_source(arguments.get("object"))
    formatns = _formant_numbers(arguments)
    unit = _unit_literal(arguments, "hertz")
    unit_text = _unit_display(arguments, "hertz")
    times = _query_times(arguments, fallback=_default_time_expression(row))
    temporary = row.class_name == "Sound"
    lines = [f"selectObject: {row.id}", "duration = Get total duration"]
    if temporary:
        lines.extend(
            [
                "To Formant (burg): 0, 5, 5500, 0.025, 50",
                f"Rename: {quote(TEMPORARY_OBJECT_NAME)}",
            ]
        )
    for time_expression in times:
        lines.append(f"time = {time_expression}")
        lines.extend(_clamp_time_lines())
        for formant in formatns:
            lines.append(f'value = {command}: {formant}, time, {unit}, "linear"')
            if with_bandwidth:
                # 「F1 的频率和带宽」一次问完：带宽缺失时只省略带宽那半句。
                lines.append(
                    f'bandwidth = Get bandwidth at time: {formant}, time, {unit}, "linear"'
                )
                lines.append(
                    f'bandwidthText$ = "，带宽 " + fixed$ (bandwidth, 3) + "{unit_text}"'
                )
                lines.extend(
                    [
                        "if bandwidth = undefined",
                        '    bandwidthText$ = ""',
                        "endif",
                    ]
                )
            measured = "频率" if with_bandwidth else label
            lines.extend(
                [
                    "if value = undefined",
                    _write_result(
                        context,
                        [
                            quote(f"第 {formant} 共振峰{measured}（"),
                            "fixed$ (time, 3)",
                            quote(" 秒处）无法计算：该时刻没有可用的共振峰数据"),
                            "note$",
                        ],
                    ),
                    "else",
                    _write_result(
                        context,
                        (
                            [
                                quote(f"第 {formant} 共振峰（"),
                                "fixed$ (time, 3)",
                                quote(" 秒处）：频率 "),
                                "fixed$ (value, 3)",
                                quote(unit_text),
                                "bandwidthText$",
                                "note$",
                            ]
                            if with_bandwidth
                            else [
                                quote(f"第 {formant} 共振峰{label}（"),
                                "fixed$ (time, 3)",
                                quote(" 秒处）= "),
                                "fixed$ (value, 3)",
                                quote(unit_text),
                                "note$",
                            ]
                        ),
                    ),
                    "endif",
                ]
            )
    if temporary:
        lines.extend(["Remove", f"selectObject: {row.id}"])
    return lines


def _build_duration(arguments: Mapping[str, Any], context: ToolContext) -> str:
    row = context.resolve_object(arguments.get("object"))
    context.require_class(row, TIME_DOMAIN_CLASSES, "这个对象没有时长")
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
        _formant_lines(
            arguments,
            context,
            command="Get value at time",
            label="频率",
            with_bandwidth=True,
        ),
        context,
    )


def _build_pitch(arguments: Mapping[str, Any], context: ToolContext) -> str:
    row = context.resolve_object(arguments.get("object"))
    context.require_class(row, TIME_DOMAIN_CLASSES, "这个对象没有时长，无法做基频分析")
    temporary = row.class_name != "Pitch"
    lines = [f"selectObject: {row.id}", "duration = Get total duration"]
    if temporary:
        floor = _number(arguments, "pitch_floor", 75.0, 20.0, 1000.0)
        ceiling = _number(arguments, "pitch_ceiling", 600.0, 50.0, 2000.0)
        lines.extend(
            [
                f"To Pitch: 0, {floor:.6f}, {ceiling:.6f}",
                f"Rename: {quote(TEMPORARY_OBJECT_NAME)}",
            ]
        )
    lines.extend(
        _point_query_lines(
            arguments,
            context,
            command='Get value at time: time, "Hertz", "linear"',
            label="基频",
            unit_text=" Hz",
            undefined_message=(
                " 秒处）无法计算：该时刻没有周期性声源（可能是无声段或清音）"
            ),
            row=row,
        )
    )
    if temporary:
        lines.extend(["Remove", f"selectObject: {row.id}"])
    return _assemble(lines, context)


def _build_pitch_statistics(
    arguments: Mapping[str, Any],
    context: ToolContext,
) -> str:
    row = context.resolve_object(arguments.get("object"))
    context.require_class(row, TIME_DOMAIN_CLASSES, "这个对象没有时长，无法做基频分析")
    temporary = row.class_name != "Pitch"
    # 注意：Praat 里 from / to / end 都是保留字，变量名只能用 tmin / tmax。
    lines = [f"selectObject: {row.id}", "duration = Get total duration"]
    lines.extend(_range_lines(arguments, row))
    if temporary:
        floor = _number(arguments, "pitch_floor", 75.0, 20.0, 1000.0)
        ceiling = _number(arguments, "pitch_ceiling", 600.0, 50.0, 2000.0)
        lines.extend(
            [
                f"To Pitch: 0, {floor:.6f}, {ceiling:.6f}",
                f"Rename: {quote(TEMPORARY_OBJECT_NAME)}",
            ]
        )
    lines.extend(
        [
            'mean = Get mean: tmin, tmax, "Hertz"',
            'minimum = Get minimum: tmin, tmax, "Hertz", "Parabolic"',
            'maximum = Get maximum: tmin, tmax, "Hertz", "Parabolic"',
            'maxtime = Get time of maximum: tmin, tmax, "Hertz", "Parabolic"',
            "if mean = undefined",
            _write_result(
                context,
                [
                    quote("基频统计（"),
                    "fixed$ (tmin, 3)",
                    quote("–"),
                    "fixed$ (tmax, 3)",
                    quote(" 秒）无法计算：该区间没有周期性声源（可能是无声段或清音）"),
                    "rangeNote$",
                ],
            ),
            "else",
            _write_result(
                context,
                [
                    quote("基频统计（"),
                    "fixed$ (tmin, 3)",
                    quote("–"),
                    "fixed$ (tmax, 3)",
                    quote(" 秒）：平均 "),
                    "fixed$ (mean, 3)",
                    quote(" Hz，最低 "),
                    "fixed$ (minimum, 3)",
                    quote(" Hz，最高 "),
                    "fixed$ (maximum, 3)",
                    quote(" Hz，最高点出现在 "),
                    "fixed$ (maxtime, 3)",
                    quote(" 秒"),
                    "rangeNote$",
                ],
            ),
            "endif",
        ]
    )
    if temporary:
        lines.extend(["Remove", f"selectObject: {row.id}"])
    return _assemble(lines, context)


def _build_intensity(arguments: Mapping[str, Any], context: ToolContext) -> str:
    row = context.resolve_object(arguments.get("object"))
    context.require_class(row, TIME_DOMAIN_CLASSES, "这个对象没有时长，无法做强度分析")
    temporary = row.class_name != "Intensity"
    lines = [f"selectObject: {row.id}", "duration = Get total duration"]
    if temporary:
        lines.extend(
            [
                'To Intensity: 100, 0, "yes"',
                f"Rename: {quote(TEMPORARY_OBJECT_NAME)}",
            ]
        )
    lines.extend(
        _point_query_lines(
            arguments,
            context,
            command='Get value at time: time, "cubic"',
            label="强度",
            unit_text=" dB",
            undefined_message=" 秒处）无法计算：该时刻没有强度数据",
            row=row,
        )
    )
    if temporary:
        lines.extend(["Remove", f"selectObject: {row.id}"])
    return _assemble(lines, context)


def _build_intensity_statistics(
    arguments: Mapping[str, Any],
    context: ToolContext,
) -> str:
    row = context.resolve_object(arguments.get("object"))
    context.require_class(row, TIME_DOMAIN_CLASSES, "这个对象没有时长，无法做强度分析")
    temporary = row.class_name != "Intensity"
    lines = [f"selectObject: {row.id}", "duration = Get total duration"]
    lines.extend(_range_lines(arguments, row))
    if temporary:
        lines.extend(
            [
                'To Intensity: 100, 0, "yes"',
                f"Rename: {quote(TEMPORARY_OBJECT_NAME)}",
            ]
        )
    lines.extend(
        [
            'mean = Get mean: tmin, tmax, "energy"',
            'maximum = Get maximum: tmin, tmax, "Parabolic"',
            _write_result(
                context,
                [
                    quote("强度统计（"),
                    "fixed$ (tmin, 3)",
                    quote("–"),
                    "fixed$ (tmax, 3)",
                    quote(" 秒）：平均 "),
                    "fixed$ (mean, 3)",
                    quote(" dB，最高 "),
                    "fixed$ (maximum, 3)",
                    quote(" dB"),
                    "rangeNote$",
                ],
            ),
        ]
    )
    if temporary:
        lines.extend(["Remove", f"selectObject: {row.id}"])
    return _assemble(lines, context)


def _build_object_info(arguments: Mapping[str, Any], context: ToolContext) -> str:
    row = context.resolve_object(arguments.get("object"))
    has_duration = row.class_name in TIME_DOMAIN_CLASSES
    is_sound = row.class_name in SOUND_CLASSES
    lines = [f"selectObject: {row.id}"]
    if has_duration:
        lines.append("duration = Get total duration")
    if is_sound:
        lines.extend(["channels = Get number of channels", "rate = Get sampling frequency"])
    fragments = [quote(f"{row.class_name}「{row.name}」（id {row.id}）")]
    if has_duration:
        fragments.extend([quote("：时长 "), "fixed$ (duration, 3)", quote(" 秒")])
    if is_sound:
        fragments.extend(
            [
                quote("，通道数 "),
                "fixed$ (channels, 0)",
                quote("，采样率 "),
                "fixed$ (rate, 0)",
                quote(" Hz"),
            ]
        )
    if not has_duration:
        fragments.append(quote("：这类对象没有时长信息"))
    lines.append(_write_result(context, fragments))
    return _assemble(lines, context)


def _point_query_lines(
    arguments: Mapping[str, Any],
    context: ToolContext,
    *,
    command: str,
    label: str,
    unit_text: str,
    undefined_message: str,
    row: ObjectRow | None = None,
) -> list[str]:
    """按 ``time``（可以是多个时刻）写若干行「某时刻 = 数值」的结果。"""

    lines: list[str] = []
    fallback = "duration / 2" if row is None else _default_time_expression(row)
    for expression in _query_times(arguments, fallback=fallback):
        lines.append(f"time = {expression}")
        lines.extend(_clamp_time_lines())
        lines.extend(
            [
                f"value = {command}",
                "if value = undefined",
                _write_result(
                    context,
                    [
                        quote(f"{label}（"),
                        "fixed$ (time, 3)",
                        quote(undefined_message),
                        "note$",
                    ],
                ),
                "else",
                _write_result(
                    context,
                    [
                        quote(f"{label}（"),
                        "fixed$ (time, 3)",
                        quote(" 秒处）= "),
                        "fixed$ (value, 3)",
                        quote(unit_text),
                        "note$",
                    ],
                ),
                "endif",
            ]
        )
    return lines


def _selection_range(
    arguments: Mapping[str, Any], row: ObjectRow | None
) -> tuple[float, float] | None:
    """这句话该用编辑器里圈出来的选区，就返回它，否则返回 ``None``。

    两种情况算"用选区"：用户没在话里给范围；或者模型把 ``sel_start``/``sel_end``
    原样抄进了 ``from``/``to``（数值对得上 ±2 ms 时是同一段范围，仍按圈选报，
    回话里才有"按编辑器圈选"的出处）。显式给了别的范围时不抢用户的数。
    """

    if row is None:
        return None
    selection = row.selection
    if selection is None:
        return None
    start = arguments.get("from", arguments.get("start", None))
    end = arguments.get("to", arguments.get("end", None))
    if start in (None, "") and end in (None, ""):
        return selection
    if _echoes_editor_selection(start, end, selection):
        return selection
    return None


def _range_note(selection: tuple[float, float]) -> str:
    return (
        f'rangeNote$ = "（按编辑器圈选 {selection[0]:.3f}–{selection[1]:.3f} 秒）"'
    )


def _range_lines(
    arguments: Mapping[str, Any], row: ObjectRow | None = None
) -> list[str]:
    """设置 ``tmin`` / ``tmax``（默认整个对象）并夹进对象时长。

    用户没在话里给 from/to 时用编辑器里圈出来的选区，``rangeNote$`` 负责在回话里
    注明这段范围是圈出来的，不能静默换范围。
    """

    selection = _selection_range(arguments, row)
    lines = ["tmin = 0", "tmax = duration"]
    if selection is not None:
        lines.append(f"tmin = {selection[0]:.6f}")
        lines.append(f"tmax = {selection[1]:.6f}")
        lines.append(_range_note(selection))
    else:
        lines.append('rangeNote$ = ""')
        if arguments.get("from", arguments.get("start", None)) not in (None, ""):
            lines.append(
                f"tmin = {_number(arguments, 'from', 0.0, 0.0, 36000.0):.6f}"
            )
        if arguments.get("to", arguments.get("end", None)) not in (None, ""):
            lines.append(
                f"tmax = {_number(arguments, 'to', 0.0, 0.0, 36000.0):.6f}"
            )
    lines.extend(_clamp_range_lines())
    return lines


def _default_time_expression(row: ObjectRow) -> str:
    """点查询没给时刻时：圈了选区就用选区中点，否则用对象中点。"""

    selection = row.selection
    if selection is None:
        return "duration / 2"
    return f"{(selection[0] + selection[1]) / 2:.6f}"


def _build_formant_statistics(
    arguments: Mapping[str, Any],
    context: ToolContext,
) -> str:
    """一段时间内的共振峰平均值与标准差（「共振峰平均是多少」用这个）。"""

    row = context.resolve_formant_source(arguments.get("object"))
    formatns = _formant_numbers(arguments)
    unit = _unit_literal(arguments, "hertz")
    unit_text = _unit_display(arguments, "hertz")
    temporary = row.class_name == "Sound"
    lines = [f"selectObject: {row.id}", "duration = Get total duration"]
    lines.extend(_range_lines(arguments, row))
    if temporary:
        lines.extend(
            [
                "To Formant (burg): 0, 5, 5500, 0.025, 50",
                f"Rename: {quote(TEMPORARY_OBJECT_NAME)}",
            ]
        )
    for formant in formatns:
        # 每条共振峰各写一行：脚本里 mean/std 会被覆盖，不能等循环结束再统一写。
        lines.append(f"mean = Get mean: {formant}, tmin, tmax, {unit}")
        lines.append(f"std = Get standard deviation: {formant}, tmin, tmax, {unit}")
        lines.append(
            _write_result(
                context,
                [
                    quote(f"第 {formant} 共振峰平均（"),
                    "fixed$ (tmin, 3)",
                    quote("–"),
                    "fixed$ (tmax, 3)",
                    quote(" 秒）= "),
                    "fixed$ (mean, 1)",
                    quote(unit_text),
                    quote("（标准差 "),
                    "fixed$ (std, 1)",
                    quote("）"),
                    "rangeNote$",
                ],
            )
        )
    if temporary:
        lines.extend(["Remove", f"selectObject: {row.id}"])
    return _assemble(lines, context)


def _build_harmonicity_statistics(
    arguments: Mapping[str, Any],
    context: ToolContext,
) -> str:
    """谐噪比 HNR（Praat 的 Harmonicity，单位 dB）。"""

    row = context.resolve_object(arguments.get("object"))
    context.require_class(row, TIME_DOMAIN_CLASSES, "这个对象没有时长，无法做谐噪比分析")
    temporary = row.class_name != "Harmonicity"
    lines = [f"selectObject: {row.id}", "duration = Get total duration"]
    lines.extend(_range_lines(arguments, row))
    if temporary:
        lines.extend(
            [
                "To Harmonicity (cc): 0.01, 75, 0.1, 1",
                f"Rename: {quote(TEMPORARY_OBJECT_NAME)}",
            ]
        )
    lines.extend(
        [
            "mean = Get mean: tmin, tmax",
            'maximum = Get maximum: tmin, tmax, "Parabolic"',
            "if mean = undefined",
            _write_result(
                context,
                [
                    quote("谐噪比 HNR（"),
                    "fixed$ (tmin, 3)",
                    quote("–"),
                    "fixed$ (tmax, 3)",
                    quote(" 秒）无法计算：该区间没有周期性声源"),
                    "rangeNote$",
                ],
            ),
            "else",
            _write_result(
                context,
                [
                    quote("谐噪比 HNR（"),
                    "fixed$ (tmin, 3)",
                    quote("–"),
                    "fixed$ (tmax, 3)",
                    quote(" 秒）：平均 "),
                    "fixed$ (mean, 2)",
                    quote(" dB，最高 "),
                    "fixed$ (maximum, 2)",
                    quote(" dB"),
                    "rangeNote$",
                ],
            ),
            "endif",
        ]
    )
    if temporary:
        lines.extend(["Remove", f"selectObject: {row.id}"])
    return _assemble(lines, context)


def _build_spectrogram(arguments: Mapping[str, Any], context: ToolContext) -> str:
    """从 Sound 生成频谱图对象（「做成频谱图」用这个）。"""

    row = context.resolve_by_class(
        arguments.get("object"), SOUND_CLASSES, "只有声音对象可以做频谱图"
    )
    window_length = _number(arguments, "window_length", 0.005, 0.0001, 1.0)
    maximum_frequency = _number(arguments, "max_frequency", 5000.0, 100.0, 96000.0)
    time_step = _number(arguments, "time_step", 0.002, 0.0001, 1.0)
    frequency_step = _number(arguments, "frequency_step", 20.0, 1.0, 1000.0)
    name = _new_name(arguments, "频谱图")
    # 模型有时会把源对象的名字当新名字传进来，那样对象列表里会出现两个同名对象。
    if _normalize_text(name) in row.name_variants():
        name = f"{name} 频谱图"
    lines = [
        f"selectObject: {row.id}",
        f"newId = To Spectrogram: {window_length:.6f}, {maximum_frequency:.6f}, "
        f"{time_step:.6f}, {frequency_step:.6f}, \"Gaussian\"",
        f"Rename: {quote(name)}",
        "frames = Get number of frames",
        _write_result(
            context,
            [
                quote("已生成频谱图："),
                quote(name),
                _id_fragment(),
                quote(f"，分析窗口 {window_length * 1000:.1f} ms，最高频率 "),
                f"fixed$ ({maximum_frequency:.6f}, 0)",
                quote(" Hz，共 "),
                "fixed$ (frames, 0)",
                quote(" 帧（可用 Praat 的「绘制」菜单画到 Picture 窗口）"),
            ],
        ),
    ]
    return _assemble(lines, context)


def _textgrid_row(arguments: Mapping[str, Any], context: ToolContext) -> ObjectRow:
    return context.resolve_by_class(
        arguments.get("object"),
        frozenset({"TextGrid"}),
        "只有 TextGrid 对象可以做标注",
    )


def _tier_number(arguments: Mapping[str, Any]) -> int:
    value = arguments.get("tier", arguments.get("tier_number", 1))
    try:
        return _integer({"value": value}, "value", 1, 1, 100)
    except ToolError as error:
        raise ToolError("层号必须是 1–100 的整数。") from error


def _insert_boundary_block(
    tier: int,
    time_variable: str,
    counter_variable: str,
    suffix: str,
) -> list[str]:
    """在 ``time_variable`` 处插入边界，跳过端点和已经有边界的位置。

    Praat 的 ``Insert boundary`` 遇到已存在的边界会直接报错，而 TextGrid 的起止点
    本来就各有一个边界，所以插入前先自己找一遍已有边界。
    """

    flag = f"needBoundary{suffix}"
    loop = f"boundaryIndex{suffix}"
    return [
        f"{flag} = 1",
        f"if {time_variable} <= 0",
        f"    {flag} = 0",
        "endif",
        f"if {time_variable} >= duration",
        f"    {flag} = 0",
        "endif",
        f"nIntervals = Get number of intervals: {tier}",
        f"for {loop} from 1 to nIntervals",
        f"    boundaryTime = Get start time of interval: {tier}, {loop}",
        f"    if abs (boundaryTime - {time_variable}) < 0.000001",
        f"        {flag} = 0",
        "    endif",
        "endfor",
        f"if {flag} = 1",
        f"    Insert boundary: {tier}, {time_variable}",
        f"    {counter_variable} = {counter_variable} + 1",
        "endif",
    ]


def _build_textgrid_info(arguments: Mapping[str, Any], context: ToolContext) -> str:
    row = _textgrid_row(arguments, context)
    maximum = _integer(arguments, "maximum_intervals", 12, 1, 100)
    lines = [
        f"selectObject: {row.id}",
        "duration = Get total duration",
        "tiers = Get number of tiers",
        _write_result(
            context,
            [
                quote(f"{row.name}：时长 "),
                "fixed$ (duration, 3)",
                quote(" 秒，共 "),
                "fixed$ (tiers, 0)",
                quote(" 层"),
            ],
        ),
        "for tier from 1 to tiers",
        "    tierName$ = Get tier name: tier",
        # Praat 里不能在 if 条件里直接调用命令，必须先赋值再判断。
        "    isInterval = Is interval tier: tier",
        "    if isInterval = 1",
        "        count = Get number of intervals: tier",
        _write_result(
            context,
            [
                quote("第 "),
                "fixed$ (tier, 0)",
                quote(" 层「"),
                "tierName$",
                quote("」（区间层）："),
                "fixed$ (count, 0)",
                quote(" 个区间"),
            ],
        ),
        "        shown = 0",
        "        for part from 1 to count",
        f"            if shown < {maximum}",
        "                startTime = Get start time of interval: tier, part",
        "                endTime = Get end time of interval: tier, part",
        "                label$ = Get label of interval: tier, part",
        _write_result(
            context,
            [
                quote("    区间 "),
                "fixed$ (part, 0)",
                quote("："),
                "fixed$ (startTime, 3)",
                quote("–"),
                "fixed$ (endTime, 3)",
                quote(" 秒，标签「"),
                "label$",
                quote("」"),
            ],
        ),
        "                shown = shown + 1",
        "            endif",
        "        endfor",
        f"        if count > {maximum}",
        _write_result(
            context,
            [
                quote("    ……还有 "),
                "fixed$ (count - shown, 0)",
                quote(" 个区间未列出（可用参数 maximum_intervals 调整）"),
            ],
        ),
        "        endif",
        "    else",
        "        count = Get number of points: tier",
        _write_result(
            context,
            [
                quote("第 "),
                "fixed$ (tier, 0)",
                quote(" 层「"),
                "tierName$",
                quote("」（点层）："),
                "fixed$ (count, 0)",
                quote(" 个点"),
            ],
        ),
        "        shown = 0",
        "        for part from 1 to count",
        f"            if shown < {maximum}",
        "                pointTime = Get time of point: tier, part",
        "                label$ = Get label of point: tier, part",
        _write_result(
            context,
            [
                quote("    点 "),
                "fixed$ (part, 0)",
                quote("："),
                "fixed$ (pointTime, 3)",
                quote(" 秒，标签「"),
                "label$",
                quote("」"),
            ],
        ),
        "                shown = shown + 1",
        "            endif",
        "        endfor",
        "    endif",
        "endfor",
    ]
    return _assemble(lines, context)


def _build_textgrid_set_interval(
    arguments: Mapping[str, Any],
    context: ToolContext,
) -> str:
    row = _textgrid_row(arguments, context)
    tier = _tier_number(arguments)
    start = _number(arguments, "start", 0.0, 0.0, 36000.0)
    raw_end = arguments.get("end", arguments.get("finish", None))
    if raw_end in (None, ""):
        # 「把这一段标成 x」：结束时间没给时用编辑器里圈出来的选区。
        selection = _selection_range(arguments, row)
        if selection is None:
            raise ToolError("标注区间需要 end 参数（结束时间，单位秒）。")
        start, end = selection
        range_note = _range_note(selection)
    else:
        end = _number({"end": raw_end}, "end", 0.0, 0.0, 36000.0)
        range_note = 'rangeNote$ = ""'
    if start >= end:
        raise ToolError("开始时间必须小于结束时间。")
    label = str(
        arguments.get("label", "")
        or arguments.get("text", "")
        or ""
    ).strip()
    if not label:
        raise ToolError("标注区间需要 label 参数（要写进 TextGrid 的文字）。")
    lines = [
        f"selectObject: {row.id}",
        f"tier = {tier}",
        "duration = Get total duration",
        range_note,
        f"t1 = {start:.6f}",
        f"t2 = {end:.6f}",
        "if t1 < 0",
        "    t1 = 0",
        "endif",
        "if t2 > duration",
        "    t2 = duration",
        "endif",
        "inserted = 0",
    ]
    lines.extend(_insert_boundary_block(tier, "t1", "inserted", "1"))
    lines.extend(_insert_boundary_block(tier, "t2", "inserted", "2"))
    lines.extend(
        [
            "t2i = t2 - 0.000001",
            "if t2i < t1",
            "    t2i = t1",
            "endif",
            f"i1 = Get interval at time: {tier}, t1",
            f"i2 = Get interval at time: {tier}, t2i",
            "if i2 < i1",
            "    i2 = i1",
            "endif",
            "count = i2 - i1 + 1",
            "for part from i1 to i2",
            f"    Set interval text: {tier}, part, {quote(label)}",
            "endfor",
            _write_result(
                context,
                [
                    quote("已把第 "),
                    "fixed$ (tier, 0)",
                    quote(" 层的 "),
                    "fixed$ (t1, 3)",
                    quote("–"),
                    "fixed$ (t2, 3)",
                    quote(" 秒（"),
                    "fixed$ (count, 0)",
                    quote(" 个区间）标成「"),
                    quote(label),
                    quote("」"),
                    "rangeNote$",
                ],
            ),
        ]
    )
    return _assemble(lines, context)


def _build_textgrid_insert_boundary(
    arguments: Mapping[str, Any],
    context: ToolContext,
) -> str:
    row = _textgrid_row(arguments, context)
    tier = _tier_number(arguments)
    value = arguments.get("time", arguments.get("at", None))
    if value in (None, ""):
        raise ToolError("插入边界需要 time 参数（时间，单位秒）。")
    time_value = _number(arguments, "time", 0.0, 0.0, 36000.0)
    lines = [
        f"selectObject: {row.id}",
        f"tier = {tier}",
        "duration = Get total duration",
        f"t1 = {time_value:.6f}",
        "if t1 < 0",
        "    t1 = 0",
        "endif",
        "if t1 > duration",
        "    t1 = duration",
        "endif",
        "inserted = 0",
    ]
    lines.extend(_insert_boundary_block(tier, "t1", "inserted", "b"))
    lines.extend(
        [
            "if inserted = 1",
            _write_result(
                context,
                [
                    quote("已在第 "),
                    "fixed$ (tier, 0)",
                    quote(" 层的 "),
                    "fixed$ (t1, 3)",
                    quote(" 秒处插入边界"),
                ],
            ),
            "else",
            _write_result(
                context,
                [
                    quote("第 "),
                    "fixed$ (tier, 0)",
                    quote(" 层的 "),
                    "fixed$ (t1, 3)",
                    quote(" 秒处已经有边界（或在 TextGrid 起止点上），没有改动"),
                ],
            ),
            "endif",
        ]
    )
    return _assemble(lines, context)


def _echoes_editor_selection(
    start: Any, end: Any, selection: tuple[float, float]
) -> bool:
    """Keep provenance when the model repeats a range already selected in Praat."""

    if start in (None, "") and end in (None, ""):
        return False
    for value, bound in ((start, selection[0]), (end, selection[1])):
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        if abs(number - bound) > 0.002:
            return False
    return True


def _build_vot_textgrid_explicit(
    arguments: Mapping[str, Any],
    context: ToolContext,
    row: ObjectRow,
    burst: float,
    voicing: float,
) -> str:
    """Keep the existing TextGrid boundary insertion workflow for manual labels."""

    tier = _tier_number(arguments)
    lines = [
        f"selectObject: {row.id}",
        f"t1 = {burst:.6f}",
        f"t2 = {voicing:.6f}",
        "vot = t2 - t1",
        "duration = Get total duration",
        f"tier = {tier}",
        "inserted = 0",
        *_insert_boundary_block(tier, "t1", "inserted", "v1"),
        *_insert_boundary_block(tier, "t2", "inserted", "v2"),
        'note$ = ""',
        "if inserted > 0",
        '    note$ = "，并在该层补上了边界"',
        "endif",
        _write_result(
            context,
            [
                quote("VOT = "),
                "fixed$ (vot, 4)",
                quote(" 秒（"),
                "fixed$ (vot * 1000, 1)",
                quote(" 毫秒）：第 "),
                "fixed$ (tier, 0)",
                quote(" 层 "),
                "fixed$ (t1, 3)",
                quote(" 秒（爆破）→ "),
                "fixed$ (t2, 3)",
                quote(" 秒（浊音起始）"),
                "note$",
            ],
        ),
    ]
    return _assemble(lines, context)


def _vot_time(
    arguments: Mapping[str, Any], key: str, alias: str = ""
) -> float | None:
    """读一个可选的时刻参数；没给返回 ``None``，给了不是数字就报中文错。"""

    raw = arguments.get(key, arguments.get(alias, None) if alias else None)
    if raw in (None, ""):
        return None
    try:
        number = float(raw)
    except (TypeError, ValueError):
        raise ToolError(f"参数 {key} 必须是数字（秒），收到：{raw!r}") from None
    if not math.isfinite(number) or not -36000.0 <= number <= 36000.0:
        raise ToolError(f"参数 {key} 必须是 -36000 到 36000 之间的有限秒数。")
    return number


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
    row = context.resolve_by_class(
        arguments.get("object"), SOUND_CLASSES, "只有声音对象可以直接播放"
    )
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


def _new_name(arguments: Mapping[str, Any], default: str) -> str:
    name = str(
        arguments.get("name", "") or arguments.get("new_name", "") or ""
    ).strip()
    return name or default


def _build_create_sound(arguments: Mapping[str, Any], context: ToolContext) -> str:
    name = _new_name(arguments, "新建声音")
    duration = _number(arguments, "duration", 1.0, 0.001, 3600.0)
    frequency = _number(arguments, "frequency", 220.0, 0.0, 20000.0)
    amplitude = _number(arguments, "amplitude", 0.5, 0.0, 1.0)
    if frequency <= 0.0:
        lines = [
            f"newId = Create Sound from formula: {quote(name)}, 1, 0, "
            f"{duration:.6f}, 44100, ~ 0",
            "duration = Get total duration",
        ]
        description = "静音"
    else:
        lines = [
            f"newId = Create Sound as pure tone: {quote(name)}, 1, 0, "
            f"{duration:.6f}, 44100, {frequency:.6f}, {amplitude:.6f}, 0.01, 0.01",
            "duration = Get total duration",
        ]
        description = f"{frequency:.1f} Hz 纯音"
    lines.append(
        _write_result(
            context,
            [
                quote(f"已创建{description}："),
                quote(name),
                _id_fragment(),
                quote("，时长 "),
                "fixed$ (duration, 3)",
                quote(" 秒"),
            ],
        )
    )
    return _assemble(lines, context)


def _build_concatenate(arguments: Mapping[str, Any], context: ToolContext) -> str:
    first = context.resolve_by_class(
        arguments.get("object"), SOUND_CLASSES, "只有声音对象可以拼接"
    )
    other = arguments.get("object2", arguments.get("other", None))
    if other in (None, ""):
        raise ToolError("拼接需要 object2 参数，指出第二个声音对象。")
    second = context.resolve_by_class(other, SOUND_CLASSES, "只有声音对象可以拼接")
    if first.id == second.id:
        raise ToolError("拼接需要两个不同的声音对象。")
    name = _new_name(arguments, "拼接结果")
    lines = [
        f"selectObject: {first.id}",
        f"plusObject: {second.id}",
        "newId = Concatenate",
        f"Rename: {quote(name)}",
        "duration = Get total duration",
        _write_result(
            context,
            [
                quote(f"已把 {first.name} 和 {second.name} 拼成："),
                quote(name),
                _id_fragment(),
                quote("，时长 "),
                "fixed$ (duration, 3)",
                quote(" 秒"),
            ],
        ),
    ]
    return _assemble(lines, context)


def _build_extract_part(arguments: Mapping[str, Any], context: ToolContext) -> str:
    row = context.resolve_by_class(
        arguments.get("object"), SOUND_CLASSES, "只有声音对象可以截取片段"
    )
    start = _number(arguments, "start", 0.0, 0.0, 36000.0)
    raw_end = arguments.get("end", arguments.get("finish", None))
    if raw_end in (None, ""):
        # 「把这段截出来」：结束时间没给时用编辑器里圈出来的选区。
        selection = _selection_range(arguments, row)
        if selection is None:
            raise ToolError("截取片段需要 end 参数（结束时间，单位秒）。")
        start, end = selection
        range_note = _range_note(selection)
    else:
        # finish 是 end 的别名，取值要按别名来，否则会被当成没给。
        end = _number({"end": raw_end}, "end", 0.0, 0.0, 36000.0)
        range_note = 'rangeNote$ = ""'
    if start >= end:
        raise ToolError("开始时间必须小于结束时间。")
    name = _new_name(arguments, "片段")
    lines = [
        f"selectObject: {row.id}",
        "duration = Get total duration",
        range_note,
        # Praat 里 start / end 不是保留字，但为了和其它模板一致，统一用 t1 / t2。
        f"t1 = {start:.6f}",
        f"t2 = {end:.6f}",
        "if t2 > duration",
        "    t2 = duration",
        "endif",
        "if t1 > t2 - 0.001",
        "    t1 = t2 - 0.001",
        "endif",
        "if t1 < 0",
        "    t1 = 0",
        "endif",
        'newId = Extract part: t1, t2, "rectangular", 1, "no"',
        f"Rename: {quote(name)}",
        "duration = Get total duration",
        _write_result(
            context,
            [
                quote("已截取片段："),
                quote(name),
                _id_fragment(),
                quote("，区间 "),
                "fixed$ (t1, 3)",
                quote("–"),
                "fixed$ (t2, 3)",
                quote(" 秒，共 "),
                "fixed$ (duration, 3)",
                quote(" 秒"),
                "rangeNote$",
            ],
        ),
    ]
    return _assemble(lines, context)


def _build_read_file(arguments: Mapping[str, Any], context: ToolContext) -> str:
    """把磁盘上的文件读进 Praat 变成一个对象（``save_sound`` 的反方向）。

    为什么要单独一个工具（2026-09-20）：换到原生 function calling 之后，模型手里
    有 ``save_sound``（「另存为 WAV」）却没有「读入文件」，于是「读取 D:/x.wav」
    被它理解成保存 WAV（方向反了，还跑得"成功"）。按 guide.md §8.4 的约定——
    加工具比加提示词管用——这里把「读文件」也做成一个工具。

    文件在不在由**脚本里**的 ``fileReadable()`` 判断，不在 Python 侧拦：同一条指令
    里的前一个动作完全可能刚刚写出这个文件（渲染时它还不存在），那种情况不该拦。
    """

    raw = str(arguments.get("path", "") or arguments.get("file", "") or "").strip()
    raw = raw.strip('"')
    if not raw:
        raise ToolError("需要给出要读取的文件路径（path），例如 D:/in/a.wav。")
    path = praat_path(Path(raw))
    lines = [
        f"if not fileReadable ({quote(path)})",
        _write_result(
            context,
            [quote("找不到要读取的文件："), quote(path), quote("（请检查路径是否存在）")],
        ),
        "else",
        f"readAiObject__ = Read from file: {quote(path)}",
        "selectObject: readAiObject__",
        "readAiName$ = selected$ ()",
        _write_result(
            context,
            [
                quote("已读入文件："),
                "readAiName$",
                quote("（"),
                quote(path),
                quote("）"),
            ],
        ),
        "endif",
    ]
    return _assemble(lines, context)


def _build_save_sound(arguments: Mapping[str, Any], context: ToolContext) -> str:
    row = context.resolve_by_class(
        arguments.get("object"), SOUND_CLASSES, "只有声音对象可以保存为 WAV 文件"
    )
    path = str(
        arguments.get("path", "") or arguments.get("file", "") or ""
    ).strip().strip('"')
    if not path:
        raise ToolError("保存声音需要 path 参数，例如 D:/out/a.wav。")
    if not re.match(r"^(?:[A-Za-z]:[\\/]|\\\\|/)", path):
        raise ToolError(f"保存路径必须是完整路径，收到：{path}")
    if not path.lower().endswith(".wav"):
        path += ".wav"
    # Praat 的「Save as WAV file」不会自己建文件夹，缺目录时只会报一句英文。
    # 这里先把目标文件夹建好，用户说「另存到 D:/out/a.wav」就直接能用。
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ToolError(
            f"保存路径的文件夹无法创建：{target.parent}（{error}）"
        ) from error
    lines = [
        f"selectObject: {row.id}",
        f"Save as WAV file: {quote(path)}",
        _write_result(context, [quote("已保存 WAV 文件："), quote(path)]),
    ]
    return _assemble(lines, context)


def _build_resample(arguments: Mapping[str, Any], context: ToolContext) -> str:
    row = context.resolve_by_class(
        arguments.get("object"), SOUND_CLASSES, "只有声音对象可以改变采样率"
    )
    rate = _integer(arguments, "rate", 16000, 1000, 768000)
    lines = [
        f"selectObject: {row.id}",
        f"newId = Resample: {rate}, 50",
        "actual = Get sampling frequency",
        _write_result(
            context,
            [
                quote("已重采样为新对象，采样率 "),
                "fixed$ (actual, 0)",
                quote(" Hz"),
                _id_fragment(),
                quote("（原对象保持不变）"),
            ],
        ),
    ]
    return _assemble(lines, context)


def _build_duplicate(arguments: Mapping[str, Any], context: ToolContext) -> str:
    row = context.resolve_object(arguments.get("object"))
    default_name = row.name if row.name else f"对象 {row.id}"
    name = _new_name(arguments, f"{default_name} 副本")
    # 模型常把「复制一份」理解成「用同一个名字复制」，那样看不出哪个是副本。
    if _normalize_text(name) in row.name_variants():
        name = f"{name} 副本"
    lines = [
        f"selectObject: {row.id}",
        f"newId = Copy: {quote(name)}",
        _write_result(context, [quote("已复制为："), quote(name), _id_fragment()]),
    ]
    return _assemble(lines, context)


# ── 借用 chengafni/praat 的现成测量（B3） ────────────────────────────────────
#
# 下面六个工具的公式照抄 Chen Gafni（https://github.com/chengafni/praat，
# chengafni.wordpress.com）的插件脚本，出处和文献都写在各自的 docstring 里。
# 两处按「对象列表」的实际情况做了说明性调整（他的脚本大多跑在编辑器里）：
#   * 编辑器里才有的命令换成对象列表上的等价命令（例如 ``Get intensity (dB)``
#     在对象列表上就是整段声音的强度，和编辑器里同一个实现）；
#   * 需要分析的中间对象（Pitch / Spectrum / Ltas / Matrix）用完就删，不污染
#     用户的对象列表。


def _build_spectral_emphasis(
    arguments: Mapping[str, Any], context: ToolContext
) -> str:
    """谱强调（spectral emphasis）。

    照抄 ``plugin_SpectralEmphasis/spectralEmphasis.praat``：
    谱强调 = 原声音强度 − 低通滤波后的强度，低通上限 = 该段平均基频 × multiplier。
    用于嗓音质量分析，见 Traunmüller & Eriksson (2000)。
    """

    row = context.resolve_by_class(
        arguments.get("object"), SOUND_CLASSES, "谱强调需要声音对象"
    )
    multiplier = _number(arguments, "multiplier", 1.5, 0.1, 10.0)
    smoothing = _number(arguments, "smoothing", 20.0, 0.1, 5000.0)
    floor = _number(arguments, "pitch_floor", 75.0, 20.0, 1000.0)
    ceiling = _number(arguments, "pitch_ceiling", 600.0, 50.0, 2000.0)
    lines = [
        f"selectObject: {row.id}",
        "duration = Get total duration",
        "intensity = Get intensity (dB)",
        f"To Pitch: 0, {floor:.6f}, {ceiling:.6f}",
        'meanPitch = Get mean: 0, 0, "Hertz"',
        "Remove",
        f"selectObject: {row.id}",
        "if meanPitch = undefined",
        _write_result(
            context,
            [quote("谱强调无法计算：这段声音里没有可用的基频（全是清音或无声段）。")],
        ),
        "else",
        f"cutoff = meanPitch * {multiplier:.6f}",
        f"Filter (pass Hann band): 0, cutoff, {smoothing:.6f}",
        "filtered = Get intensity (dB)",
        "Remove",
        f"selectObject: {row.id}",
        "emphasis = intensity - filtered",
        _write_result(
            context,
            [
                quote("谱强调（Spectral emphasis）= "),
                "fixed$ (emphasis, 2)",
                quote(" dB：低通上限 "),
                "fixed$ (cutoff, 1)",
                quote(" Hz（该段平均基频 "),
                "fixed$ (meanPitch, 1)",
                quote(f" Hz × {multiplier:g}），平滑 {smoothing:g} Hz"),
            ],
        ),
        "endif",
    ]
    return _assemble(lines, context)


def _build_hl_ratio(arguments: Mapping[str, Any], context: ToolContext) -> str:
    """高/低频段能量比（H/L）。

    照抄 ``plugin_HL/HL.praat``：``Get band energy`` 两段的能量相除
    （默认 0–4000 Hz 与 4000–8000 Hz）。输入是 Sound 时先做 ``To Spectrum``。
    """

    row = context.resolve_object(arguments.get("object"))
    low_from = _number(arguments, "low_from", 0.0, 0.0, 96000.0)
    low_to = _number(arguments, "low_to", 4000.0, 1.0, 96000.0)
    high_from = _number(arguments, "high_from", 4000.0, 1.0, 96000.0)
    high_to = _number(arguments, "high_to", 8000.0, 2.0, 96000.0)
    if low_to > high_from:
        raise ToolError("低频段上限不能高于高频段下限（默认 0–4000 与 4000–8000 Hz）。")
    temporary = row.class_name != "Spectrum"
    if temporary:
        context.require_class(
            row, SOUND_CLASSES, "H/L 需要声音对象，或者现成的 Spectrum 对象"
        )
    lines = [f"selectObject: {row.id}"]
    if temporary:
        lines.extend(['To Spectrum: "yes"', f"Rename: {quote(TEMPORARY_OBJECT_NAME)}"])
    lines.extend(
        [
            f"lowBand = Get band energy: {low_from:.6f}, {low_to:.6f}",
            f"highBand = Get band energy: {high_from:.6f}, {high_to:.6f}",
            "if lowBand = 0",
            _write_result(
                context,
                [quote("H/L 无法计算：低频段能量为 0（可能是静音，或者低频段选得太窄）。")],
            ),
            "else",
            "hl = highBand / lowBand",
            _write_result(
                context,
                [
                    quote("H/L = "),
                    "fixed$ (hl, 4)",
                    quote(f"（高频 {high_from:g}–{high_to:g} Hz 能量 ÷ 低频 "),
                    quote(f"{low_from:g}–{low_to:g} Hz 能量）"),
                ],
            ),
            "endif",
        ]
    )
    if temporary:
        lines.append("Remove")
    lines.append(f"selectObject: {row.id}")
    return _assemble(lines, context)


def _build_hammarberg_index(
    arguments: Mapping[str, Any], context: ToolContext
) -> str:
    """Hammarberg 指数。

    照抄 ``plugin_HammarbergIndex/hammarbergIndex.praat``：
    0–2000 Hz 的 LTAS 最大电平 减去 2000–5000 Hz 的 LTAS 最大电平（dB）。
    见 Hammarberg et al. (1980)。输入是 Sound 时先做 ``To Ltas``。
    """

    row = context.resolve_object(arguments.get("object"))
    low_from = _number(arguments, "low_from", 0.0, 0.0, 96000.0)
    low_to = _number(arguments, "low_to", 2000.0, 1.0, 96000.0)
    high_from = _number(arguments, "high_from", 2000.0, 1.0, 96000.0)
    high_to = _number(arguments, "high_to", 5000.0, 2.0, 96000.0)
    bandwidth = _number(arguments, "bandwidth", 100.0, 1.0, 1000.0)
    temporary = row.class_name != "Ltas"
    if temporary:
        context.require_class(
            row, SOUND_CLASSES, "Hammarberg 指数需要声音对象，或者现成的 Ltas 对象"
        )
    lines = [f"selectObject: {row.id}"]
    if temporary:
        lines.extend([f"To Ltas: {bandwidth:.6f}", f"Rename: {quote(TEMPORARY_OBJECT_NAME)}"])
    lines.extend(
        [
            f'lowBand = Get maximum: {low_from:.6f}, {low_to:.6f}, "Parabolic"',
            f'highBand = Get maximum: {high_from:.6f}, {high_to:.6f}, "Parabolic"',
            "hammarberg = lowBand - highBand",
            _write_result(
                context,
                [
                    quote("Hammarberg 指数 = "),
                    "fixed$ (hammarberg, 2)",
                    quote(" dB（0–2000 Hz 最大电平 "),
                    "fixed$ (lowBand, 2)",
                    quote(" dB − 2000–5000 Hz 最大电平 "),
                    "fixed$ (highBand, 2)",
                    quote(" dB）"),
                ],
            ),
        ]
    )
    if temporary:
        lines.append("Remove")
    lines.append(f"selectObject: {row.id}")
    return _assemble(lines, context)


def _build_pitch_peak_latency(
    arguments: Mapping[str, Any], context: ToolContext
) -> str:
    """基频峰值延迟。

    照抄 ``plugin_PitchPeakLatency/pitchPeakLatency.praat``：
    （峰值时刻 − 区间起点）÷ 区间时长，0.5 表示峰值正好在区间中间。
    """

    row = context.resolve_object(arguments.get("object"))
    # 只有声音能现做 Pitch、或者直接给 Pitch；TextGrid 这类有时长但没有「To Pitch」
    # 命令的对象要在这里拦住，不然 Praat 会弹一句英文错误框，还会挡住后面的消息。
    if row.class_name not in SOUND_CLASSES:
        context.require_class(row, frozenset({"Pitch"}), "基频峰值延迟需要声音对象或 Pitch 对象")
    temporary = row.class_name != "Pitch"
    floor = _number(arguments, "pitch_floor", 75.0, 20.0, 1000.0)
    ceiling = _number(arguments, "pitch_ceiling", 600.0, 50.0, 2000.0)
    lines = [f"selectObject: {row.id}", "duration = Get total duration"]
    lines.extend(_range_lines(arguments, row))
    if temporary:
        lines.extend(
            [
                f"To Pitch: 0, {floor:.6f}, {ceiling:.6f}",
                f"Rename: {quote(TEMPORARY_OBJECT_NAME)}",
            ]
        )
    lines.extend(
        [
            'peakTime = Get time of maximum: tmin, tmax, "Hertz", "Parabolic"',
            "if peakTime = undefined",
            _write_result(
                context,
                [
                    quote("基频峰值延迟无法计算："),
                    "fixed$ (tmin, 3)",
                    quote("–"),
                    "fixed$ (tmax, 3)",
                    quote(" 秒这一段里没有可用的基频（全是清音或无声段）。"),
                ],
            ),
            "else",
            "latency = (peakTime - tmin) / (tmax - tmin)",
            _write_result(
                context,
                [
                    quote("基频峰值延迟 = "),
                    "fixed$ (latency, 3)",
                    quote("（峰值 "),
                    "fixed$ (peakTime, 3)",
                    quote(" 秒出现在 "),
                    "fixed$ (tmin, 3)",
                    quote("–"),
                    "fixed$ (tmax, 3)",
                    quote(" 秒这一段里；0.5 = 正好在中间）"),
                    "rangeNote$",
                ],
            ),
            "endif",
        ]
    )
    if temporary:
        lines.extend(["Remove", f"selectObject: {row.id}"])
    return _assemble(lines, context)


def _build_peak_to_average_ratio(
    arguments: Mapping[str, Any], context: ToolContext
) -> str:
    """峰值/平均值比（peak-to-average ratio）。

    出处 Hillenbrand et al. (1994)，参考 ``plugin_PA/peak_to_average.praat``。

    **和原脚本的一处差别**：原脚本用 ``Get mean``（有符号均值）当分母，对一段语音来说
    那个值接近 0，比值会跑到几万、同一个音两次能差一个数量级。这里用同一套「幅度
    统计」里稳定的 **RMS（有效值）** 当分母，结果落在 1–5 这种可比较的范围内，
    同时把峰值和有效值都写进结果，便于核对。
    """

    row = context.resolve_by_class(
        arguments.get("object"), SOUND_CLASSES, "峰值/平均值比需要声音对象"
    )
    lines = [f"selectObject: {row.id}", "duration = Get total duration"]
    lines.extend(_range_lines(arguments, row))
    lines.extend(
        [
            'peak = Get maximum: tmin, tmax, "Sinc70"',
            "rms = Get root-mean-square: tmin, tmax",
            "if rms = 0",
            _write_result(
                context,
                [
                    quote("峰值/平均值比无法计算："),
                    "fixed$ (tmin, 3)",
                    quote("–"),
                    "fixed$ (tmax, 3)",
                    quote(" 秒这一段是静音（有效值为 0）。"),
                ],
            ),
            "else",
            "ratio = peak / rms",
            _write_result(
                context,
                [
                    quote("峰值/有效值 = "),
                    "fixed$ (ratio, 2)",
                    quote("（峰值 "),
                    "fixed$ (peak, 4)",
                    quote(" Pa ÷ 有效值 "),
                    "fixed$ (rms, 4)",
                    quote(" Pa，"),
                    "fixed$ (tmin, 3)",
                    quote("–"),
                    "fixed$ (tmax, 3)",
                    quote(" 秒）"),
                    "rangeNote$",
                ],
            ),
            "endif",
        ]
    )
    return _assemble(lines, context)


def _build_intensity_slope(arguments: Mapping[str, Any], context: ToolContext) -> str:
    """强度曲线的平均斜率（dB/s）。

    照抄 ``plugin_IntensitySlope/meanIntensitySlope.praat``：

    - ``local``：相邻两点绝对差 ÷ 时间步长，再取平均，
      即 mean{|I[t+1]−I[t]| / dt}；
    - ``global``：区间首尾之差 ÷ 区间时长，即 {I[tmax]−I[tmin]} / (tmax−tmin)。

    范围默认整段；给了 from/to（或编辑器圈选）时，先按这个范围把声音截出来再分析。
    """

    row = context.resolve_object(arguments.get("object"))
    if row.class_name not in SOUND_CLASSES:
        context.require_class(
            row, frozenset({"Intensity"}), "强度斜率需要声音对象或 Intensity 对象"
        )
    method = str(arguments.get("method", "local") or "local").strip().casefold()
    if method not in {"local", "global", "局部", "整体"}:
        raise ToolError("method 只能是 local（局部）或 global（整体）。")
    local = method in {"local", "局部"}
    pitch_floor = _number(arguments, "pitch_floor", 100.0, 20.0, 1000.0)
    time_step = _number(arguments, "time_step", 0.001, 0.0001, 1.0)
    lines = [f"selectObject: {row.id}", "duration = Get total duration"]
    extracted = ""
    if row.class_name in SOUND_CLASSES:
        # 整段分析时不会截片段，所以先给 extractedId 一个初值（0 = 没截）。
        lines.append("extractedId = 0")
        lines.extend(_range_lines(arguments, row))
        # 只分析一段时先把这一段截出来（Intensity 对象本身没有「取片段」的命令）。
        lines.extend(
            [
                "if tmin > 0 or tmax < duration",
                "extractedId = Extract part: tmin, tmax, \"rectangular\", 1, \"no\"",
                f"Rename: {quote(TEMPORARY_OBJECT_NAME)}",
                "tmin = 0",
                "tmax = Get total duration",
                "endif",
            ]
        )
        extracted = "extractedId"
    else:
        # Intensity / Pitch 这类对象没有「取片段」命令：只能整段算，别假装能按范围算。
        if arguments.get("from", arguments.get("start", None)) not in (None, "") or arguments.get(
            "to", arguments.get("end", None)
        ) not in (None, ""):
            raise ToolError(
                "对已经提取出来的 Intensity 对象只能整段算斜率；"
                "要按时间范围算，请直接对声音对象用这个工具。"
            )
        lines.extend(["tmin = 0", "tmax = duration", 'rangeNote$ = ""'])
    lines.extend(
        [
            f'intensityId = To Intensity: {pitch_floor:.6f}, {time_step:.6f}, "yes"',
            "Down to Matrix",
            'matrixId = selected ("Matrix")',
            "colsNum = Get number of columns",
        ]
    )
    if local:
        result_lines = [
            'Formula: "abs(self[col+1]-self[col])/dx"',
            "matSum = Get sum",
            "lastEl = Get value in cell: 1, colsNum",
            "slope = (matSum - lastEl) / (colsNum - 1)",
            _write_result(
                context,
                [
                    quote("强度局部斜率（相邻点绝对差 ÷ 时间步长，取平均）= "),
                    "fixed$ (slope, 2)",
                    quote(" dB/s（"),
                    "fixed$ (colsNum, 0)",
                    quote(f" 个点，步长 {time_step:g} 秒）"),
                    "rangeNote$",
                ],
            ),
        ]
    else:
        result_lines = [
            "firstTime = Get lowest x",
            "lastTime = Get highest x",
            "firstEl = Get value in cell: 1, 1",
            "lastEl = Get value in cell: 1, colsNum",
            "slope = (lastEl - firstEl) / (lastTime - firstTime)",
            _write_result(
                context,
                [
                    quote("强度整体斜率（首尾差 ÷ 时长）= "),
                    "fixed$ (slope, 2)",
                    quote(" dB/s（"),
                    "fixed$ (firstEl, 2)",
                    quote(" dB → "),
                    "fixed$ (lastEl, 2)",
                    quote(" dB）"),
                    "rangeNote$",
                ],
            ),
        ]
    lines.extend(result_lines)
    # 收尾：把中间对象删掉，恢复用户原来的选中对象。
    lines.append("selectObject: matrixId")
    lines.append("Remove")
    lines.append("selectObject: intensityId")
    lines.append("Remove")
    if extracted:
        # extractedId = 0 表示这次没截片段（整段分析），别去删一个不存在的对象。
        lines.append(f"if {extracted} <> 0")
        lines.append(f"    selectObject: {extracted}")
        lines.append("    Remove")
        lines.append("endif")
    lines.append(f"selectObject: {row.id}")
    return _assemble(lines, context)


# ---------------------------------------------------------------------------
# B1：表驱动的声学测量。
#
# 参数表在 ``ai/praat_ai/measures.tsv``（列的含义和出处见 measures.py）。
# 这里只负责把「一行参数」拼成脚本：基础对象 → 只用到的派生对象 → 每条查询一行
# 结果 → 删掉临时对象 → 把选中对象还给用户。
# ---------------------------------------------------------------------------

#: 走表时 ``arguments`` 里这些键是「怎么查」，不是分析设置。
_MEASURE_RESERVED_KEYS = frozenset(
    {"parameter", "parameters", "object", "from", "to", "start", "end", "unit"}
)

#: 已经分析好的对象能直接顶上对应派生对象时用（选中 Pitch 就别再 To Pitch 一次）。
_MEASURE_CLASS_DERIVATIONS: dict[str, str] = {
    "Pitch": "pitch",
    "Intensity": "intensity",
    "Formant": "formant",
    "Spectrum": "spectrum",
    "Ltas": "ltas",
    "Harmonicity": "harmonicity",
    "PointProcess": "pointProcess",
    "PowerCepstrogram": "powerCepstrogram",
}


def measure_parameter_help() -> str:
    """``measure`` 能测的参数名 + 中文说明（工具 JSON Schema 和 catalog 共用）。"""

    return "、".join(
        f"{entry.parameter}（{entry.label}）" for entry in measures.load_table().entries
    )


def measure_signature() -> str:
    """``measure`` 的参数说明（设置项也由表生成，schema 才不会漏改）。"""

    keys = "、".join(measures.load_table().settings)
    return (
        'parameter（参数名，可写多个如 "f1,f2"）、from、to（秒，默认整个对象或编辑器圈选）'
        "、unit（hertz/Bark）、object（可选）"
        f"、{keys}"
    )


def _measure_schema() -> dict[str, Any]:
    table = measures.load_table()
    properties: dict[str, Any] = {
        "parameter": {
            "type": "string",
            "enum": table.parameters(),
            "description": "要测哪一个参数：" + measure_parameter_help(),
        },
        "from": _seconds_arg("起点（秒），不填就是整个对象或编辑器圈选"),
        "to": _seconds_arg("终点（秒），不填就是整个对象或编辑器圈选"),
        "unit": _unit_arg(),
        "object": _object_arg(),
    }
    for key, setting in table.settings.items():
        description = f"{setting.note}（默认 {setting.value}）"
        if setting.is_integer:
            properties[key] = _integer_arg(description)
        else:
            properties[key] = _number_arg(description)
    return {"type": "object", "properties": properties, "required": ["parameter"]}


def _measure_names(arguments: Mapping[str, Any]) -> list[str]:
    """``parameter`` 可以是名字、``"f1,f2"`` 或列表（JSON 规划那条路会传列表）。"""

    raw = arguments.get("parameter", arguments.get("parameters"))
    if raw is None or raw == "":
        raise ToolError("measure 要用 parameter 指定参数名。")
    if isinstance(raw, (list, tuple, set)):
        pieces = [str(item) for item in raw]
    else:
        pieces = re.split(r"[,，、;；\s]+", str(raw))
    names = [piece.strip() for piece in pieces if piece.strip()]
    if not names:
        raise ToolError("measure 要用 parameter 指定参数名。")
    return names


def _measure_entries(arguments: Mapping[str, Any]) -> list[measures.Entry]:
    table = measures.load_table()
    entries: list[measures.Entry] = []
    for name in _measure_names(arguments):
        try:
            entries.append(table.find(name))
        except KeyError as error:
            known = "、".join(table.parameters())
            raise ToolError(
                f"measure 不认识参数「{name}」。可用参数有：{known}。"
            ) from error
    return entries


def _measure_settings(
    arguments: Mapping[str, Any], table: measures.Table
) -> dict[str, int | float]:
    """按表里的 ``@@ settings`` 取值：默认值在表里，模型可以用同名参数覆盖。"""

    values: dict[str, int | float] = {}
    for key, setting in table.settings.items():
        if setting.is_integer:
            values[key] = _integer(
                arguments,
                key,
                int(float(setting.value)),
                int(float(setting.minimum)),
                int(float(setting.maximum)),
            )
        else:
            values[key] = _number(
                arguments,
                key,
                float(setting.value),
                float(setting.minimum),
                float(setting.maximum),
            )
    # 上下限写反的话 Praat 会弹一句英文错误框（还会卡住后面的消息），这里先拦下。
    floor = values.get("pitch_floor")
    ceiling = values.get("pitch_ceiling")
    if isinstance(floor, (int, float)) and isinstance(ceiling, (int, float)):
        if floor >= ceiling:
            raise ToolError("pitch_floor（基频下限）必须小于 pitch_ceiling（基频上限）。")
    return values


def _measure_expand(
    text: str,
    settings: Mapping[str, int | float],
    *,
    unit_literal: str,
    unit_text: str,
) -> str:
    """把 ``{pitch_floor}`` / ``{unit}`` / ``{unit_text}`` 换成实际值。"""

    expanded = text
    for key, value in settings.items():
        rendered = str(value) if isinstance(value, int) else f"{value:.6f}"
        expanded = expanded.replace("{" + key + "}", rendered)
    expanded = expanded.replace("{unit}", unit_literal)
    expanded = expanded.replace("{unit_text}", unit_text)
    return expanded


def _measure_plan(
    table: measures.Table,
    entries: Sequence[measures.Entry],
    variables: Mapping[str, str],
) -> list[str]:
    """按表的顺序算出要建哪些派生对象（只用到的才建，依赖排在前面）。"""

    wanted: set[str] = set()
    pending: list[str] = []
    for entry in entries:
        for key in measures.source_keys(entry.source):
            if key != "sound" and key not in variables and key not in wanted:
                wanted.add(key)
                pending.append(key)
    while pending:
        key = pending.pop()
        derivation = table.derivations.get(key)
        if derivation is None:
            raise ToolError(f"measure 的表里没有「{key}」的派生规则。")
        source = derivation.source.strip()
        if source and source != "Sound" and source not in variables and source not in wanted:
            wanted.add(source)
            pending.append(source)
    return [key for key in table.derivations if key in wanted]


def _measure_select_lines(keys: Sequence[str], variables: Mapping[str, str]) -> list[str]:
    """一条查询要选中哪些对象：第一个 ``selectObject``，其余 ``plusObject``。"""

    lines: list[str] = []
    for index, key in enumerate(keys):
        target = variables.get(key)
        if target is None:
            raise ToolError(
                f"这个参数要对「{key}」算，但当前对象只能直接给「"
                + "、".join(sorted(variables))
                + "」；请在 Praat 里选中声音对象再试。"
            )
        lines.append(("selectObject: " if index == 0 else "plusObject: ") + target)
    return lines


def _build_measure(arguments: Mapping[str, Any], context: ToolContext) -> str:
    """表驱动的测量：一行参数 = 一条 Praat 查询（表在 ai/praat_ai/measures.tsv）。"""

    table = measures.load_table()
    entries = _measure_entries(arguments)
    delegated = [entry for entry in entries if entry.kind == "dedicated"]
    if delegated:
        if len(entries) > 1:
            names = "、".join(f"{e.parameter}（改用 {e.tool}）" for e in delegated)
            raise ToolError(
                f"{names} 要好几步才能算出来，得单独调用各自的专用工具，"
                "一次 measure 里别和别的参数混在一起。"
            )
        entry = delegated[0]
        tool = TOOL_MAP.get(entry.tool)
        if tool is None:
            raise ToolError(
                f"measure 的表把 {entry.parameter} 指向了不存在的工具 {entry.tool}。"
            )
        merged = {
            key: value
            for key, value in arguments.items()
            if key not in {"parameter", "parameters"}
        }
        merged.update(json.loads(entry.arguments or "{}"))
        return tool.build(merged, context)

    queries = [entry for entry in entries if entry.kind == "query"]
    editor_only = [entry for entry in entries if entry.kind == "editor"]
    row = context.resolve_object(arguments.get("object"))
    variables: dict[str, str] = {}
    if row.class_name in SOUND_CLASSES:
        variables["sound"] = str(row.id)
    else:
        alias = _MEASURE_CLASS_DERIVATIONS.get(row.class_name)
        if alias is None:
            raise ToolError(
                f"measure 需要声音对象（对象 {row.id} 是 {row.class_name}）："
                "声学测量都是对声音做的，或者把已经分析好的 Pitch/Intensity 等对象选上。"
            )
        variables[alias] = str(row.id)

    settings = _measure_settings(arguments, table)
    unit_literal = _unit_literal(arguments, "hertz")
    unit_text = _unit_display(arguments, "hertz").strip()
    created = _measure_plan(table, entries, variables)

    uses_range = any(
        "tmin" in entry.command or "tmax" in entry.command for entry in queries
    )
    lines = [f"selectObject: {row.id}"]
    if uses_range:
        lines.append("duration = Get total duration")
        lines.extend(_range_lines(arguments, row))
    for key in created:
        derivation = table.derivations[key]
        # Praat 的 To X 生成的新对象会顶掉当前选中：每建一个派生对象之前都要把
        # 它该从哪个对象来重新选一遍，否则第二个派生对象就是对中间对象做了。
        source = derivation.source.strip() or "Sound"
        lines.extend(
            _measure_select_lines(
                ["sound" if source == "Sound" else source], variables
            )
        )
        command = _measure_expand(
            derivation.command,
            settings,
            unit_literal=unit_literal,
            unit_text=unit_text,
        )
        lines.append(f"{key}Id = {command}")
        variables[key] = f"{key}Id"

    for entry in queries:
        lines.extend(_measure_select_lines(measures.source_keys(entry.source), variables))
        command = _measure_expand(
            entry.command, settings, unit_literal=unit_literal, unit_text=unit_text
        )
        statements = [piece.strip() for piece in command.split(";") if piece.strip()]
        if not any("=" in statement for statement in statements):
            statements[0] = f"value = {statements[0]}"
        lines.extend(statements)
        unit = _measure_expand(
            entry.unit, settings, unit_literal=unit_literal, unit_text=unit_text
        )
        decimals = int(entry.decimals)
        entry_range = "tmin" in entry.command or "tmax" in entry.command
        if entry_range:
            prefix = [
                quote(f"{entry.label}（"),
                "fixed$ (tmin, 3)",
                quote("–"),
                "fixed$ (tmax, 3)",
                quote(" 秒）= "),
            ]
            missing = [
                quote(f"{entry.label}（"),
                "fixed$ (tmin, 3)",
                quote("–"),
                "fixed$ (tmax, 3)",
                quote(" 秒）无法计算：这一段里没有可用的数据"),
            ]
        else:
            prefix = [quote(f"{entry.label} = ")]
            missing = [quote(f"{entry.label} 无法计算：这个对象里没有可用的数据")]
        measured = prefix + [f"fixed$ (value, {decimals})"]
        if unit:
            measured.append(quote(f" {unit}"))
        lines.append("if value = undefined")
        lines.extend(
            [_write_result(context, missing + (["rangeNote$"] if entry_range else []))]
        )
        lines.append("else")
        lines.extend(
            [
                _write_result(
                    context,
                    measured + (["rangeNote$"] if entry_range else []),
                )
            ]
        )
        lines.append("endif")

    for entry in editor_only:
        lines.append(
            _write_result(
                context,
                [
                    quote(
                        f"{entry.label}：这个参数只能在 Praat 的编辑器里查"
                        f"（{entry.command}），对象列表里没有对应命令。"
                    )
                ],
            )
        )

    for key in reversed(created):
        lines.append(f"selectObject: {key}Id")
        lines.append("Remove")
    lines.append(f"selectObject: {row.id}")
    return _assemble(lines, context)


# ---------------------------------------------------------------------------
# C3：把现成的（社区）Praat 脚本跑起来。
#
# 不走「渲染脚本 → 投递给开着的 Praat」：现成脚本普遍带表单和报错对话框，两条都
# 会把用户开着的 Praat 卡住（模态框挡住后面所有消息）。所以这里导出对象副本、
# 在**批处理**里跑（见 external_script.py 的模块说明）。
# ---------------------------------------------------------------------------

#: 外部脚本的输出最多回灌几行给对话窗口（长报告别把上下文撑爆）。
EXTERNAL_OUTPUT_LINES = 40


def save_textgrid_script(context: ToolContext, row: ObjectRow, path: Path) -> str:
    """把 TextGrid 另存为文本文件（本地工具导出用；和模板一样带完成标记）。"""

    return _assemble(
        [f"selectObject: {row.id}", f"Save as text file: {quote(praat_path(path))}"],
        context,
    )


def _external_textgrid(
    arguments: Mapping[str, Any], context: ToolContext
) -> ObjectRow | None:
    """要一起交给外部脚本的 TextGrid：显式给的优先，否则用列表里唯一那个。"""

    requested = arguments.get("textgrid")
    if requested not in (None, ""):
        return context.resolve_by_class(
            requested, frozenset({"TextGrid"}), "textgrid 要给一个 TextGrid 对象"
        )
    candidates = [row for row in context.objects if row.class_name == "TextGrid"]
    return candidates[0] if len(candidates) == 1 else None


def _run_external_script(
    arguments: Mapping[str, Any],
    context: ToolContext,
    environment: LocalEnvironment,
) -> tuple[bool, list[str], str]:
    """跑一个现成的 ``.praat`` 脚本，把它的输出读回来。"""

    cancelled = environment.cancelled
    if cancelled is not None and cancelled():
        raise ToolError("已取消：这个脚本没有开始跑。")
    raw_path = str(arguments.get("path", "") or "").strip()
    if not raw_path:
        raise ToolError("要跑哪个脚本？请给出 .praat 文件的完整路径（path）。")
    timeout = _number(arguments, "timeout", 60.0, 5.0, 900.0)
    target = Path(raw_path).expanduser()
    try:
        source = external_script.read_script(target)
        fields = external_script.parse_form(source)
        payload = external_script.run_arguments(fields)
    except external_script.ExternalScriptError as error:
        raise ToolError(str(error)) from error

    row = context.resolve_by_class(
        arguments.get("object"), SOUND_CLASSES, "外部脚本的输入需要声音对象"
    )
    work = environment.runtime_directory / "external" / uuid.uuid4().hex
    work.mkdir(parents=True, exist_ok=True)

    # 1) 让开着的 Praat 存一份声音副本（用户的对象一个都不动）。
    sound_path = work / "input.wav"
    ok, _results, failure = environment.execute(
        render("save_sound", {"path": str(sound_path), "object": row.id}, context)
    )
    if not ok or not sound_path.is_file():
        return False, [], f"没能把当前声音导出成 WAV：{failure or '文件没有生成'}"

    # 2) 有 TextGrid 就一起导出（标注类脚本都要它）。
    grid = _external_textgrid(arguments, context)
    grid_path: Path | None = None
    if grid is not None:
        candidate = work / "input.TextGrid"
        ok, _results, failure = environment.execute(
            save_textgrid_script(context, grid, candidate)
        )
        if ok and candidate.is_file():
            grid_path = candidate

    # 3) 批处理里跑现成脚本。
    wrapper = work / "wrapper.praat"
    wrapper.write_text(
        external_script.wrapper_script(
            sound_path=sound_path,
            grid_path=grid_path,
            target=target,
            arguments=payload,
            sound_name=row.name,
            grid_name=grid.name if grid is not None else "",
        ),
        encoding="utf-8",
        newline="\n",
    )
    before = external_script.folder_snapshot(target.parent)
    ok, output = external_script.run_batch(
        environment.praat_executable,
        wrapper,
        timeout=timeout,
        working_directory=work,
        cancelled=cancelled,
    )
    after = external_script.folder_snapshot(target.parent)

    if not ok:
        return (
            False,
            [],
            f"外部脚本 {target.name} 在批处理里没跑成：{output}\n"
            "（注意：批处理里看不到你当前的对象列表，脚本拿到的是导出的声音副本；"
            "需要编辑器或交互的脚本请直接在 Praat 里运行。）",
        )

    lines: list[str] = [
        f"外部脚本 {target.name} 跑完了（在批处理里跑的，没有动你开着的 Praat）。"
    ]
    if fields:
        lines.append(
            f"脚本的表单按它自己的默认值填了 {len(fields)} 个字段"
            "（批处理里不显示表单）："
            + "、".join(f"{field.label or field.kind}={field.default}" for field in fields)
        )
    lines.append(
        f"输入：{row.class_name}「{row.name}」的副本"
        + (f"，外加 TextGrid「{grid.name}」" if grid is not None else "")
    )
    if output:
        for line in output.splitlines()[:EXTERNAL_OUTPUT_LINES]:
            if line.strip():
                lines.append(f"脚本输出：{line.strip()}")
    else:
        lines.append("脚本没有打印任何结果（它可能把结果写进了文件或新的对象里）。")
    written = external_script.changed_files(before, after)
    if written:
        shown = "、".join(written[:10])
        lines.append(f"脚本在自己那个目录里新增/改动了 {len(written)} 个文件：{shown}")
    return True, lines, ""


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    summary: str
    signature: str
    build: Callable[[Mapping[str, Any], ToolContext], str]

    def describe(self) -> str:
        return f"- {self.name}: {self.summary} 参数：{self.signature}"


@dataclass(frozen=True, slots=True)
class LocalEnvironment:
    """本地（不在 Praat 里跑）的工具需要的外部能力。

    由对话窗口提供：``execute(脚本)`` 把脚本投给**正在运行的 Praat**（见
    ``chat._send_script``），返回 ``(是否成功, 结果行, 失败说明)``；
    ``praat_executable`` 是批处理要用的 Praat，``runtime_directory`` 是
    ``ai/runtime``。
    """

    execute: Callable[[str], tuple[bool, list[str], str]]
    praat_executable: str
    runtime_directory: Path
    #: 用户按了「停止」没有（C7）：批处理、多步流程每一步都问一次。
    cancelled: Callable[[], bool] | None = None


@dataclass(frozen=True, slots=True)
class LocalTool:
    """在前端（Python）里执行的工具：不需要渲染 Praat 脚本模板。

    `build` 那套模板适合「一句话 → 一条固定脚本」的查询；像「把现成 .praat
    脚本跑起来」（C3）这种要起批处理进程、还要读文件的工具，走这里。
    """

    name: str
    summary: str
    signature: str
    parameters: dict[str, Any]
    run: Callable[
        [Mapping[str, Any], ToolContext, LocalEnvironment],
        tuple[bool, list[str], str],
    ]

    def describe(self) -> str:
        return f"- {self.name}: {self.summary} 参数：{self.signature}"


def _vot_range_arguments(
    arguments: Mapping[str, Any],
    row: ObjectRow,
) -> tuple[tuple[float, float], tuple[float | None, float | None]]:
    """Resolve the target exactly and keep acoustic context as a separate range."""

    start = arguments.get("from", arguments.get("start"))
    end = arguments.get("to", arguments.get("end"))
    if start in (None, "") and end in (None, ""):
        target = row.selection
        if target is None:
            raise ToolError(
                "VOT 需要目标选区：请在编辑器中拖选目标音素，或同时提供 from 和 to；不会退回整段音频。"
            )
    elif start in (None, "") or end in (None, ""):
        raise ToolError("VOT 的 from 和 to 必须同时提供。")
    else:
        target = (_vot_time(arguments, "from"), _vot_time(arguments, "to"))
        assert target[0] is not None and target[1] is not None
        target = (target[0], target[1])
    if not all(math.isfinite(value) for value in target) or target[0] >= target[1]:
        raise ToolError("VOT 目标范围必须是递增的有限时间。")

    context_start = arguments.get("context_from")
    context_end = arguments.get("context_to")
    if context_start in (None, "") and context_end in (None, ""):
        selection_context = row.selection_context
        if (
            selection_context is not None
            and selection_context[0] <= target[0]
            and selection_context[1] >= target[1]
        ):
            return target, selection_context
        return target, (None, None)
    if context_start in (None, "") or context_end in (None, ""):
        raise ToolError("VOT 的 context_from 和 context_to 必须同时提供。")
    context = (
        _vot_time(arguments, "context_from"),
        _vot_time(arguments, "context_to"),
    )
    assert context[0] is not None and context[1] is not None
    if context[0] >= context[1] or context[0] > target[0] or context[1] < target[1]:
        raise ToolError("VOT 固定上下文必须递增并完整包含目标范围。")
    return target, (context[0], context[1])


def _vot_sample_index(
    time_seconds: float,
    *,
    first_sample_time: float,
    sample_period_sec: float,
    sample_count: int,
) -> int:
    """Match SoundEditor::editorSampleIndexAtTime on the original sample axis."""

    if not math.isfinite(time_seconds):
        raise ToolError("VOT 时间必须是有限数字。")
    domain_start = first_sample_time - sample_period_sec * 0.5
    domain_end = first_sample_time + (sample_count - 0.5) * sample_period_sec
    scale = max(
        1.0,
        abs(time_seconds),
        abs(domain_start),
        abs(domain_end),
        abs(first_sample_time),
    )
    domain_tolerance = 8.0 * math.ulp(scale)
    if (
        time_seconds < domain_start - domain_tolerance
        or time_seconds > domain_end + domain_tolerance
    ):
        raise ToolError("VOT 目标或上下文超出音频对象的时间轴。")
    offset = (time_seconds - first_sample_time) / sample_period_sec
    # Subtraction and division can move a mathematically exact half-sample
    # below the tie (for example 220 / 44100 against a half-sample origin).
    # Snap only within the floating-point resolution of the time inputs so
    # this keeps the same tie-up rule as SoundEditor without widening it by a
    # meaningful fraction of a sample.
    offset_scale = max(
        abs(time_seconds),
        abs(first_sample_time),
        abs(offset * sample_period_sec),
        sample_period_sec,
    )
    offset_tolerance = 8.0 * math.ulp(offset_scale) / sample_period_sec
    lower_tie = math.floor(offset) + 0.5
    if abs(offset - lower_tie) <= offset_tolerance:
        offset = lower_tie
    return min(sample_count, max(0, math.floor(offset + 0.5)))


def _finite_vot_parameter(arguments: Mapping[str, Any], *names: str, default: float) -> float:
    raw: Any = default
    for name in names:
        if arguments.get(name) not in (None, ""):
            raw = arguments[name]
            break
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ToolError(f"VOT 参数 {names[0]} 必须是有限数字。") from None
    if not math.isfinite(value):
        raise ToolError(f"VOT 参数 {names[0]} 必须是有限数字。")
    return value


def _run_vot(
    arguments: Mapping[str, Any],
    context: ToolContext,
    environment: LocalEnvironment,
) -> tuple[bool, list[str], str]:
    """Build one canonical request, then invoke the native snapshot and detector."""

    requested_object = arguments.get("object")
    if requested_object not in (None, ""):
        row = context.resolve_object(requested_object)
    else:
        row = context.default_object()
    if row.class_name not in SOUND_CLASSES | {"TextGrid"}:
        raise ToolError("VOT 需要 Sound、LongSound 或 TextGrid 对象。")

    burst = _vot_time(arguments, "burst")
    voicing = _vot_time(arguments, "voicing", alias="onset")
    if (burst is None) != (voicing is None):
        raise ToolError("人工确认 VOT 必须同时提供 burst 和 voicing 两个边界。")
    if row.class_name == "TextGrid":
        if burst is None or voicing is None:
            raise ToolError("TextGrid 的 VOT 工具需要人工提供 burst 和 voicing 边界。")
        script = _build_vot_textgrid_explicit(arguments, context, row, burst, voicing)
        return environment.execute(script)

    mode_value = arguments.get("mode")
    if mode_value in (None, ""):
        mode_value = "manual" if burst is not None else "model_assisted"
    mode_value = str(mode_value).strip().lower()
    if mode_value not in {"model_assisted", "acoustic_only", "manual"}:
        raise ToolError("VOT mode 必须是 model_assisted、acoustic_only 或 manual。")
    if mode_value == "manual" and burst is None:
        raise ToolError("人工确认模式需要同时提供 burst 和 voicing。")
    if mode_value != "manual" and burst is not None:
        raise ToolError("提供了 burst/voicing 时，请选择 manual 模式。")

    target_seconds, context_seconds = _vot_range_arguments(arguments, row)
    metadata_script = _assemble(
        [
            f"selectObject: {row.id}",
            "sampleRate = Get sampling frequency",
            "sampleCount = Get number of samples",
            "firstSampleTime = Get time from sample number: 1",
            _write_result(
                context,
                [
                    "fixed$ (sampleCount, 0)",
                    quote("|"),
                    "fixed$ (sampleRate, 15)",
                    quote("|"),
                    "fixed$ (firstSampleTime, 20)",
                ],
            ),
        ],
        context,
    )
    ok, rows, failure = environment.execute(metadata_script)
    if not ok:
        return False, [], failure or "Praat 无法读取 VOT 音频采样信息。"
    metadata = next((line for line in rows if line.count("|") == 2), None)
    if metadata is None:
        return False, [], "Praat 没有返回完整的 VOT 音频采样信息。"
    try:
        sample_count_text, sample_rate_text, first_sample_text = metadata.split("|")
        sample_count = int(sample_count_text)
        sample_rate = float(sample_rate_text)
        first_sample_time = float(first_sample_text)
        sample_period = 1.0 / sample_rate
    except (ValueError, TypeError):
        return False, [], "Praat 返回了无效的 VOT 音频采样信息。"
    if (
        sample_count <= 0
        or sample_rate <= 0
        or not math.isfinite(first_sample_time)
        or not math.isfinite(sample_period)
        or sample_period <= 0
    ):
        return False, [], "Praat 返回了无效的 VOT 音频采样信息。"

    target_range = tuple(
        _vot_sample_index(
            value,
            first_sample_time=first_sample_time,
            sample_period_sec=sample_period,
            sample_count=sample_count,
        )
        for value in target_seconds
    )
    if context_seconds == (None, None):
        domain_start = first_sample_time - 0.5 * sample_period
        domain_end = first_sample_time + (sample_count - 0.5) * sample_period
        context_seconds = (
            max(domain_start, target_seconds[0] - 0.5),
            min(domain_end, target_seconds[1] + 0.5),
        )
    context_range = tuple(
        _vot_sample_index(
            value,
            first_sample_time=first_sample_time,
            sample_period_sec=sample_period,
            sample_count=sample_count,
        )
        for value in context_seconds
    )
    if not (
        context_range[0] <= target_range[0] < target_range[1] <= context_range[1]
    ):
        raise ToolError("VOT 目标选区在采样点精度下为空或超出固定上下文。")

    from .vot_editor_worker import _request_from_payload

    job_directory = environment.runtime_directory / "vot_ai" / uuid.uuid4().hex
    job_directory.mkdir(parents=True, exist_ok=False)
    manifest_path = job_directory / "snapshot.json"
    pcm_path = job_directory / "snapshot.f64le"
    wav_path = job_directory / "alignment.wav"
    snapshot_script = _assemble(
        [
            f"selectObject: {row.id}",
            "Write VOT audio snapshot: "
            f"{quote(manifest_path)}, {quote(pcm_path)}, {quote(wav_path)}, "
            f"{context_range[0]}, {context_range[1]}",
        ],
        context,
    )
    ok, _, failure = environment.execute(snapshot_script)
    if not ok:
        return False, [], failure or "Praat 无法创建当前音频的 VOT 快照。"

    parameters = {
        "burst_threshold_db": _finite_vot_parameter(
            arguments, "burst_threshold_db", "burst_db", default=6.0
        ),
        "pitch_floor_hz": _finite_vot_parameter(
            arguments, "pitch_floor_hz", "pitch_floor", default=75.0
        ),
        "pitch_ceiling_hz": 500.0,
    }
    manual_boundaries = None
    if mode_value == "manual":
        assert burst is not None and voicing is not None
        manual_boundaries = [
            _vot_sample_index(
                value,
                first_sample_time=first_sample_time,
                sample_period_sec=sample_period,
                sample_count=sample_count,
            )
            for value in (burst, voicing)
        ]
    payload = {
        "request_id": uuid.uuid4().hex,
        "job_directory": str(job_directory),
        "snapshot_paths": {
            "manifest": str(manifest_path),
            "pcm": str(pcm_path),
            "wav": str(wav_path),
        },
        "target_range": list(target_range),
        "acoustic_context_range": list(context_range),
        "alignment_context_range": list(context_range),
        "language": str(arguments.get("language", "") or ""),
        "transcript": str(arguments.get("transcript", "") or ""),
        "phonemes": arguments.get("phonemes", "") or "",
        "target_phone_index": arguments.get("target_phone_index", 0),
        "mode": mode_value,
        "parameters": parameters,
        "manual_boundaries": manual_boundaries,
    }
    request = _request_from_payload(payload)

    from .config import load_config
    from .forced_alignment import build_aligner
    from .vot import VOTAnalysisService, VOTMode
    from .vot_bridge import TSVVOTAcousticAnalyzer

    service = VOTAnalysisService(build_aligner(load_config().alignment))
    if request.mode == VOTMode.MANUAL:
        result = service.confirm_manual(request)
    else:
        prepared = service.prepare(request, use_cache=False)
        if prepared.status is not None:
            result = service.complete(prepared, None)
        else:
            acoustic_path = job_directory / "native-acoustic.tsv"
            aligned = prepared.target_phone
            aligned_start = aligned.start_sample if aligned else -1
            aligned_end = aligned.end_sample if aligned else -1
            parameters_json = json.dumps(
                {
                    **request.to_dict()["parameters"],
                    "mode": request.mode.value,
                    "manual_boundaries": None,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            acoustic_script = _assemble(
                [
                    f"selectObject: {row.id}",
                    "Analyse VOT audio snapshot: "
                    f"{quote(manifest_path)}, {quote(pcm_path)}, "
                    f"{target_range[0]}, {target_range[1]}, "
                    f"{context_range[0]}, {context_range[1]}, "
                    f"{aligned_start}, {aligned_end}, {quote(parameters_json)}, "
                    f"{quote(acoustic_path)}",
                ],
                context,
            )
            ok, _, failure = environment.execute(acoustic_script)
            if not ok:
                class MissingNativeResult:
                    def analyze(self, request, aligned_phone):
                        del request, aligned_phone
                        raise RuntimeError(failure or "native VOT detector did not run")

                result = service.complete(prepared, MissingNativeResult())
            else:
                result = service.complete(
                    prepared, TSVVOTAcousticAnalyzer(acoustic_path)
                )
    result_json = json.dumps(
        result.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return True, [result_json], ""


TOOLS: tuple[Tool, ...] = (
    Tool(
        name="object_info",
        summary="查看对象的基本信息：类型、名称、时长、通道数和采样率。",
        signature="object（可选，对象 id 或名称）",
        build=_build_object_info,
    ),
    Tool(
        name="duration",
        summary="查询对象的时长（秒）。",
        signature="object（可选，对象 id 或名称）",
        build=_build_duration,
    ),
    Tool(
        name="formant_bandwidth",
        summary="只查第 n 共振峰在某一时刻的带宽（不含频率）；对象是 Sound 时自动先做共振峰分析。",
        signature="formant（默认 2，可写 1,2 查多条）、time（秒，默认中点）、unit（hertz/Bark）、object（可选）",
        build=_build_formant_bandwidth,
    ),
    Tool(
        name="formant_frequency",
        summary="查询第 n 共振峰在某一时刻的频率，并同时给出带宽；要「F1/F2 的频率」「频率和带宽」都用这个。",
        signature="formant（默认 2，可写 1,2 查多条）、time（秒，默认中点，可写 0.25,0.75 查多个时刻）、unit（hertz/Bark）、object（可选）",
        build=_build_formant_frequency,
    ),
    Tool(
        name="formant_statistics",
        summary="统计一段时间的共振峰平均值和标准差。要「共振峰平均/F1 平均」时用这个。",
        signature="formant（默认 1，可写 1,2）、from、to（秒，默认整个对象）、unit（hertz/Bark）、object（可选）",
        build=_build_formant_statistics,
    ),
    Tool(
        name="pitch",
        summary="查询某一时刻的基频（Hz）。",
        signature="time（秒，默认中点，可写 0.25,0.75 查多个时刻）、pitch_floor、pitch_ceiling、object（可选）",
        build=_build_pitch,
    ),
    Tool(
        name="pitch_statistics",
        summary="统计一段时间的基频：平均值、最低值、最高值和最高点的时刻（Hz）。要「基频平均/最高/范围」时用这个。",
        signature="from、to（秒，默认整个对象）、pitch_floor、pitch_ceiling、object（可选）",
        build=_build_pitch_statistics,
    ),
    Tool(
        name="intensity",
        summary="查询某一时刻的强度（dB）。",
        signature="time（秒，默认中点，可写 0.25,0.75 查多个时刻）、object（可选）",
        build=_build_intensity,
    ),
    Tool(
        name="intensity_statistics",
        summary="统计一段时间的强度：平均值和最高值（dB）。",
        signature="from、to（秒，默认整个对象）、object（可选）",
        build=_build_intensity_statistics,
    ),
    Tool(
        name="harmonicity_statistics",
        summary="统计谐噪比 HNR（Harmonicity，dB）：平均值和最高值。要「谐噪比」时用这个。",
        signature="from、to（秒，默认整个对象）、object（可选）",
        build=_build_harmonicity_statistics,
    ),
    Tool(
        name="spectrogram",
        summary="把 Sound 做成频谱图对象（不是图片，画图用 Praat 的绘制菜单）。",
        signature="window_length（默认 0.005 秒）、max_frequency（默认 5000 Hz）、time_step、frequency_step、name、object（可选）",
        build=_build_spectrogram,
    ),
    Tool(
        name="textgrid_info",
        summary="查看 TextGrid 的层数、每层名称、区间/点的数量和标签。要「这个 TextGrid 有几个区间/标了什么」时用这个。",
        signature="maximum_intervals（每层最多列几个，默认 12）、object（可选）",
        build=_build_textgrid_info,
    ),
    Tool(
        name="textgrid_set_interval",
        summary="给 TextGrid 的某一层在指定时间区间写上标签（需要时自动插入边界）。要「把 0.2–0.5 秒标成 a」时用这个。",
        signature="start、end（秒）、label（写入的文字）、tier（层号，默认 1）、object（可选）",
        build=_build_textgrid_set_interval,
    ),
    Tool(
        name="textgrid_insert_boundary",
        summary="在 TextGrid 某一层的指定时刻插入一个边界。",
        signature="time（秒）、tier（层号，默认 1）、object（可选）",
        build=_build_textgrid_insert_boundary,
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
    Tool(
        name="create_sound",
        summary="新建一个声音对象：frequency 大于 0 生成纯音，等于 0 生成静音。",
        signature="duration（秒，默认 1）、frequency（Hz，默认 220）、amplitude（0–1）、name（可选）",
        build=_build_create_sound,
    ),
    Tool(
        name="concatenate_sounds",
        summary="把两个 Sound 首尾拼接成一个新 Sound。",
        signature="object、object2（两个声音）、name（可选）",
        build=_build_concatenate,
    ),
    Tool(
        name="extract_part",
        summary="按时间区间从一个 Sound 里截取片段（生成新对象）。",
        signature="start、end（秒）、name（可选）、object（可选）",
        build=_build_extract_part,
    ),
    Tool(
        name="save_sound",
        summary="把 Sound 另存为 WAV 文件。",
        signature="path（完整路径，例如 D:/out/a.wav）、object（可选）",
        build=_build_save_sound,
    ),
    Tool(
        name="read_file",
        summary=(
            "把磁盘上的文件读进 Praat 变成一个对象（wav / TextGrid / Pitch 等）；"
            "要和「另存为文件」区分开：这个是**读进来**。"
        ),
        signature="path（完整路径，例如 D:/in/a.wav）",
        build=_build_read_file,
    ),
    Tool(
        name="resample_sound",
        summary="改变采样率，生成一个新的 Sound 对象。",
        signature="rate（Hz，常用 16000/22050/44100）、object（可选）",
        build=_build_resample,
    ),
    Tool(
        name="duplicate_object",
        summary="复制一个对象。",
        signature="name（可选，新名称）、object（可选）",
        build=_build_duplicate,
    ),
    Tool(
        name="spectral_emphasis",
        summary=(
            "算谱强调（spectral emphasis）：低通滤波前后损失多少强度（dB），"
            "用于嗓音质量分析（Traunmüller & Eriksson 2000）。"
        ),
        signature=(
            "multiplier（默认 1.5，低通上限 = 平均基频 × 它）、smoothing（默认 20 Hz）、"
            "pitch_floor（默认 75）、pitch_ceiling（默认 600）、object（必须是 Sound）"
        ),
        build=_build_spectral_emphasis,
    ),
    Tool(
        name="hl_ratio",
        summary="算高频段与低频段的能量比 H/L（默认 4–8 kHz ÷ 0–4 kHz）。",
        signature=(
            "low_from（默认 0）、low_to（默认 4000）、high_from（默认 4000）、"
            "high_to（默认 8000）、object（Sound 或 Spectrum）"
        ),
        build=_build_hl_ratio,
    ),
    Tool(
        name="hammarberg_index",
        summary=(
            "算 Hammarberg 指数：0–2 kHz 的 LTAS 最大电平 减去 2–5 kHz 的最大电平"
            "（dB，Hammarberg et al. 1980）。"
        ),
        signature=(
            "low_from（默认 0）、low_to（默认 2000）、high_from（默认 2000）、"
            "high_to（默认 5000）、bandwidth（做 Ltas 的带宽，默认 100）、"
            "object（Sound 或 Ltas）"
        ),
        build=_build_hammarberg_index,
    ),
    Tool(
        name="pitch_peak_latency",
        summary=(
            "算基频峰值延迟：（基频最高点 − 区间起点）÷ 区间时长，"
            "0.5 表示峰值正好在中间。"
        ),
        signature=(
            "from、to（秒，默认整个对象或编辑器圈选）、pitch_floor（默认 75）、"
            "pitch_ceiling（默认 600）、object（可选）"
        ),
        build=_build_pitch_peak_latency,
    ),
    Tool(
        name="peak_to_average_ratio",
        summary=(
            "算峰值/有效值比（peak-to-average，Hillenbrand et al. 1994）："
            "峰值幅度 ÷ RMS。"
        ),
        signature="from、to（秒，默认整个对象或编辑器圈选）、object（必须是 Sound）",
        build=_build_peak_to_average_ratio,
    ),
    Tool(
        name="intensity_slope",
        summary=(
            "算强度曲线的平均斜率（dB/s）：local = 相邻点绝对差的平均 ÷ 时间步长，"
            "global = 首尾差 ÷ 时长。"
        ),
        signature=(
            "method（local/global，默认 local）、from、to（秒，默认整个对象）、"
            "pitch_floor（做 Intensity 用，默认 100）、time_step（默认 0.001 秒）、"
            "object（Sound 或 Intensity）"
        ),
        build=_build_intensity_slope,
    ),
    Tool(
        name=MEASURE_TOOL,
        summary=(
            "表驱动的声学测量：jitter / shimmer、共振峰带宽、频谱重心/偏度/峰度、"
            "CPPS、基频与强度的各种统计量都在这里。parameter 一次可以写多个"
            "（逗号隔开），例如 \"f1,f2\"。"
        ),
        signature=measure_signature(),
        build=_build_measure,
    ),
)

TOOL_MAP: dict[str, Tool] = {tool.name: tool for tool in TOOLS}


#: 没有参数的工具（或没登记 schema 的工具）用这个。
EMPTY_PARAMETERS: dict[str, Any] = {"type": "object", "properties": {}, "required": []}


def _object_arg(description: str = "对象 id 或名称；不填就用当前选中的对象") -> dict[str, Any]:
    return {"type": ["integer", "string"], "description": description}


def _seconds_arg(description: str) -> dict[str, Any]:
    """一个时刻或一段时长（秒）。只允许数字：以前允许字符串时模型会把说明文字
    当成值填进来（例如把「默认按 Praat 自动」写进 time_step）。"""

    return {"type": "number", "description": description}


def _times_arg(description: str) -> dict[str, Any]:
    """可以一次给多个时刻的 ``time``：数字或 ``"0.25,0.75"`` 这样的文本。"""

    return {"type": ["number", "string"], "description": description}


def _number_arg(description: str) -> dict[str, Any]:
    return {"type": "number", "description": description}


def _integer_arg(description: str) -> dict[str, Any]:
    return {"type": "integer", "description": description}


def _text_arg(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


def _unit_arg() -> dict[str, Any]:
    return {
        "type": "string",
        "enum": ["hertz", "Bark"],
        "description": "单位，默认 hertz",
    }


#: 每个工具的 JSON Schema（原生 function calling 用）。
#:
#: 集中定义在这里，而不是塞进 26 个 ``Tool(...)`` 里，是为了能一眼比对各工具的参数
#: 和必填项；``ai/tests/test_chat_tools.py`` 守着「每个工具都有 schema」和
#: 「schema 里的参数名都出现在 ``Tool.signature`` 里」两条，改动不会悄悄跑偏。
#: 秒数和编号允许字符串（``time`` 可以写 ``"0.25,0.75"``），因为模板本来就接受这种
#: 写法，模型也常这么填。
TOOL_PARAMETERS: dict[str, dict[str, Any]] = {
    "object_info": {
        "type": "object",
        "properties": {"object": _object_arg()},
        "required": [],
    },
    "duration": {
        "type": "object",
        "properties": {"object": _object_arg()},
        "required": [],
    },
    "formant_bandwidth": {
        "type": "object",
        "properties": {
            "formant": _integer_arg('第几共振峰，可写 2 或 "1,2"（最多 6 条）'),
            "time": _times_arg("秒，默认对象中点"),
            "unit": _unit_arg(),
            "object": _object_arg(),
        },
        "required": [],
    },
    "formant_frequency": {
        "type": "object",
        "properties": {
            "formant": _integer_arg('第几共振峰，可写 2 或 "1,2"（最多 6 条）'),
            "time": _times_arg('秒，可写多个时刻，如 "0.25,0.75"'),
            "unit": _unit_arg(),
            "object": _object_arg(),
        },
        "required": [],
    },
    "formant_statistics": {
        "type": "object",
        "properties": {
            "formant": _integer_arg('第几共振峰，可写 1 或 "1,2"'),
            "from": _seconds_arg("起点（秒），不填就是整个对象"),
            "to": _seconds_arg("终点（秒），不填就是整个对象"),
            "unit": _unit_arg(),
            "object": _object_arg(),
        },
        "required": [],
    },
    "pitch": {
        "type": "object",
        "properties": {
            "time": _times_arg('秒，可写多个时刻，如 "0.25,0.75"'),
            "pitch_floor": _number_arg("基频下限 Hz，默认 75"),
            "pitch_ceiling": _number_arg("基频上限 Hz，默认 600"),
            "object": _object_arg(),
        },
        "required": [],
    },
    "pitch_statistics": {
        "type": "object",
        "properties": {
            "from": _seconds_arg("起点（秒），不填就是整个对象"),
            "to": _seconds_arg("终点（秒），不填就是整个对象"),
            "pitch_floor": _number_arg("基频下限 Hz，默认 75"),
            "pitch_ceiling": _number_arg("基频上限 Hz，默认 600"),
            "object": _object_arg(),
        },
        "required": [],
    },
    "intensity": {
        "type": "object",
        "properties": {
            "time": _times_arg('秒，可写多个时刻，如 "0.25,0.75"'),
            "object": _object_arg(),
        },
        "required": [],
    },
    "intensity_statistics": {
        "type": "object",
        "properties": {
            "from": _seconds_arg("起点（秒），不填就是整个对象"),
            "to": _seconds_arg("终点（秒），不填就是整个对象"),
            "object": _object_arg(),
        },
        "required": [],
    },
    "harmonicity_statistics": {
        "type": "object",
        "properties": {
            "from": _seconds_arg("起点（秒），不填就是整个对象"),
            "to": _seconds_arg("终点（秒），不填就是整个对象"),
            "object": _object_arg(),
        },
        "required": [],
    },
    "spectrogram": {
        "type": "object",
        "properties": {
            "window_length": _seconds_arg("窗长（秒），默认 0.005"),
            "max_frequency": _number_arg("最高频率 Hz，默认 5000"),
            "time_step": _seconds_arg("时间步长（秒）；不填就用 Praat 的默认值"),
            "frequency_step": _number_arg("频率步长 Hz；不填就用 Praat 的默认值"),
            "name": _text_arg("新对象的名字"),
            "object": _object_arg(),
        },
        "required": [],
    },
    "textgrid_info": {
        "type": "object",
        "properties": {
            "maximum_intervals": _integer_arg("每层最多列几个区间，默认 12"),
            "object": _object_arg(),
        },
        "required": [],
    },
    "textgrid_set_interval": {
        "type": "object",
        "properties": {
            "start": _seconds_arg("区间起点（秒）"),
            "end": _seconds_arg("区间终点（秒）"),
            "label": _text_arg("要写入的文字（空字符串表示清空）"),
            "tier": _integer_arg("层号，默认 1"),
            "object": _object_arg("TextGrid 对象"),
        },
        "required": ["start", "end", "label"],
    },
    "textgrid_insert_boundary": {
        "type": "object",
        "properties": {
            "time": _seconds_arg("插入时刻（秒）"),
            "tier": _integer_arg("层号，默认 1"),
            "object": _object_arg("TextGrid 对象"),
        },
        "required": ["time"],
    },
    "vot": {
        "type": "object",
        "properties": {
            "burst": _seconds_arg(
                "人工确认的爆破释放时刻（秒）；必须和 voicing 同时提供"
            ),
            "voicing": _seconds_arg(
                "人工确认的浊音起始时刻（秒）；必须和 burst 同时提供"
            ),
            "from": _seconds_arg("目标音素选区起点（秒）；与 to 同时提供，否则使用编辑器选区"),
            "to": _seconds_arg("目标音素选区终点（秒）；与 from 同时提供，否则使用编辑器选区"),
            "context_from": _seconds_arg("固定分析上下文起点（秒）；需和 context_to 同时提供"),
            "context_to": _seconds_arg("固定分析上下文终点（秒）；需和 context_from 同时提供"),
            "language": _text_arg("MFA / wav2vec2 对齐所需的语言代码"),
            "transcript": _text_arg("完整上下文语句文字"),
            "phonemes": _text_arg("完整上下文音素序列，按空格分隔"),
            "target_phone_index": _integer_arg("目标音素在 phonemes 中的从零开始序号，默认 0"),
            "mode": {
                "type": "string",
                "enum": ["model_assisted", "acoustic_only", "manual"],
                "description": "分析模式；默认 model_assisted，给出两个人工边界时默认 manual",
            },
            "burst_threshold_db": _number_arg("C++ 爆破阈值 dB，默认 6"),
            "pitch_floor_hz": _number_arg("C++ 起声检测基频下限 Hz，默认 75"),
            "tier": _integer_arg("TextGrid 层号，默认 1"),
            "object": _object_arg("当前 Praat 对象列表中的 Sound、LongSound 或 TextGrid"),
        },
        "required": [],
    },
    "select_object": {
        "type": "object",
        "properties": {"object": _object_arg("要选中的对象 id 或名称")},
        "required": ["object"],
    },
    "view_edit": {
        "type": "object",
        "properties": {"object": _object_arg()},
        "required": [],
    },
    "play": {
        "type": "object",
        "properties": {"object": _object_arg("要播放的 Sound（必须是 Sound）")},
        "required": [],
    },
    "rename_object": {
        "type": "object",
        "properties": {
            "new_name": _text_arg("新名字"),
            "object": _object_arg(),
        },
        "required": ["new_name"],
    },
    "remove_object": {
        "type": "object",
        "properties": {"object": _object_arg()},
        "required": [],
    },
    "create_sound": {
        "type": "object",
        "properties": {
            "duration": _seconds_arg("时长（秒），默认 1"),
            "frequency": _number_arg("频率 Hz；填 0 生成静音，默认 220"),
            "amplitude": _number_arg("振幅 0–1，默认 0.5"),
            "name": _text_arg("新对象的名字"),
        },
        "required": [],
    },
    "concatenate_sounds": {
        "type": "object",
        "properties": {
            "object": _object_arg("第一个声音"),
            "object2": _object_arg("第二个声音"),
            "name": _text_arg("结果对象的名字"),
        },
        "required": ["object", "object2"],
    },
    "extract_part": {
        "type": "object",
        "properties": {
            "start": _seconds_arg("起点（秒）"),
            "end": _seconds_arg("终点（秒）"),
            "name": _text_arg("片段对象的名字"),
            "object": _object_arg(),
        },
        "required": ["start", "end"],
    },
    "save_sound": {
        "type": "object",
        "properties": {
            "path": _text_arg("完整路径，例如 D:/out/a.wav"),
            "object": _object_arg(),
        },
        "required": ["path"],
    },
    "read_file": {
        "type": "object",
        "properties": {
            "path": _text_arg("要读入的文件完整路径，例如 D:/in/a.wav"),
        },
        "required": ["path"],
    },
    "resample_sound": {
        "type": "object",
        "properties": {
            "rate": _integer_arg("采样率 Hz，常用 16000 / 22050 / 44100"),
            "object": _object_arg(),
        },
        "required": ["rate"],
    },
    "duplicate_object": {
        "type": "object",
        "properties": {
            "name": _text_arg("副本的新名字"),
            "object": _object_arg(),
        },
        "required": [],
    },
    "spectral_emphasis": {
        "type": "object",
        "properties": {
            "multiplier": _number_arg("低通上限 = 平均基频 × 这个倍数，默认 1.5"),
            "smoothing": _number_arg("低通滤波的平滑带宽 Hz，默认 20"),
            "pitch_floor": _number_arg("求平均基频用的下限 Hz，默认 75"),
            "pitch_ceiling": _number_arg("求平均基频用的上限 Hz，默认 600"),
            "object": _object_arg("要分析的 Sound"),
        },
        "required": [],
    },
    "hl_ratio": {
        "type": "object",
        "properties": {
            "low_from": _number_arg("低频段起点 Hz，默认 0"),
            "low_to": _number_arg("低频段终点 Hz，默认 4000"),
            "high_from": _number_arg("高频段起点 Hz，默认 4000"),
            "high_to": _number_arg("高频段终点 Hz，默认 8000"),
            "object": _object_arg("Sound 或现成的 Spectrum"),
        },
        "required": [],
    },
    "hammarberg_index": {
        "type": "object",
        "properties": {
            "low_from": _number_arg("低频段起点 Hz，默认 0"),
            "low_to": _number_arg("低频段终点 Hz，默认 2000"),
            "high_from": _number_arg("高频段起点 Hz，默认 2000"),
            "high_to": _number_arg("高频段终点 Hz，默认 5000"),
            "bandwidth": _number_arg("做 Ltas 用的带宽 Hz，默认 100"),
            "object": _object_arg("Sound 或现成的 Ltas"),
        },
        "required": [],
    },
    "pitch_peak_latency": {
        "type": "object",
        "properties": {
            "from": _seconds_arg("区间起点（秒），不填就是整个对象或编辑器圈选"),
            "to": _seconds_arg("区间终点（秒），不填就是整个对象或编辑器圈选"),
            "pitch_floor": _number_arg("基频下限 Hz，默认 75"),
            "pitch_ceiling": _number_arg("基频上限 Hz，默认 600"),
            "object": _object_arg(),
        },
        "required": [],
    },
    "peak_to_average_ratio": {
        "type": "object",
        "properties": {
            "from": _seconds_arg("区间起点（秒），不填就是整个对象或编辑器圈选"),
            "to": _seconds_arg("区间终点（秒），不填就是整个对象或编辑器圈选"),
            "object": _object_arg("要分析的 Sound"),
        },
        "required": [],
    },
    "intensity_slope": {
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "enum": ["local", "global"],
                "description": "local = 相邻点绝对差的平均 ÷ 时间步长（默认）；global = 首尾差 ÷ 时长",
            },
            "from": _seconds_arg("起点（秒），不填就是整个对象或编辑器圈选"),
            "to": _seconds_arg("终点（秒），不填就是整个对象或编辑器圈选"),
            "pitch_floor": _number_arg("做 Intensity 用的下限 Hz，默认 100"),
            "time_step": _number_arg("Intensity 的时间步长（秒），默认 0.001"),
            "object": _object_arg("Sound 或现成的 Intensity"),
        },
        "required": [],
    },
    CUSTOM_SCRIPT_TOOL: {
        "type": "object",
        "properties": {
            "script": _text_arg(
                "完整 Praat 英文脚本；只有其它工具都做不到时才用它。"
                "字符串用双引号；要输出就写 appendFileLine。"
            )
        },
        "required": ["script"],
    },
}

#: ``measure`` 的 schema 由参数表生成（加一行参数就多一个 enum 项）。
TOOL_PARAMETERS[MEASURE_TOOL] = _measure_schema()

#: 在前端（Python）里执行的工具。它们不走「渲染脚本 → 投递」，所以单独一张表；
#: 工具说明、schema、catalog 和标签都要一起给模型看（见下面几个函数的合并逻辑）。
LOCAL_TOOLS: dict[str, LocalTool] = {
    "vot": LocalTool(
        name="vot",
        summary=(
            "用共享 VOT 分析服务处理当前 Sound / LongSound 快照：模型辅助自动、纯声学候选或人工确认。"
            "返回统一边界、VOT、状态、模型和检测依据；TextGrid 支持人工边界写入。"
        ),
        signature=(
            "from/to（目标选区；省略时必须有编辑器选区）、context_from/context_to（固定上下文）、"
            "language、transcript、phonemes、target_phone_index、mode、burst/voicing、"
            "burst_threshold_db、pitch_floor_hz、tier、object"
        ),
        parameters=TOOL_PARAMETERS["vot"],
        run=_run_vot,
    ),
    RUN_SCRIPT_TOOL: LocalTool(
        name=RUN_SCRIPT_TOOL,
        summary=(
            "跑一个现成的（社区）.praat 脚本：把它当成批处理跑，输入是当前声音的副本"
            "（脚本里表单的默认值会自动填进去）。脚本自己打印的结果会回到这里。"
            "注意批处理里看不到你当前的对象列表，也不能用编辑器/交互窗口；"
            "对编辑器圈选段做分析的脚本要在 Praat 里自己跑。"
        ),
        signature="path（.praat 文件完整路径）、object（可选，输入的声音）、textgrid（可选）、timeout（秒，默认 60）",
        parameters={
            "type": "object",
            "properties": {
                "path": _text_arg("要跑的 .praat 文件完整路径，例如 D:/scripts/vot.praat"),
                "object": _object_arg("作为输入的声音对象；不填就用当前选中的"),
                "textgrid": _object_arg("（可选）一起交给脚本的 TextGrid"),
                "timeout": _number_arg("批处理超时秒数，默认 60"),
            },
            "required": ["path"],
        },
        run=_run_external_script,
    )
}
TOOL_PARAMETERS[RUN_SCRIPT_TOOL] = LOCAL_TOOLS[RUN_SCRIPT_TOOL].parameters


def tool_parameters(name: str) -> dict[str, Any]:
    """取一个工具的 JSON Schema（没登记就用空参数表）。"""

    return TOOL_PARAMETERS.get(name, EMPTY_PARAMETERS)


def tool_schemas() -> list[dict[str, Any]]:
    """OpenAI 风格的 ``tools`` 参数，交给 llama-server 的原生 function calling。

    对比「把十几条规则和工具清单写进提示词、让模型自己拼 JSON」：schema 里带了
    类型、枚举和必填项，模型编不出不存在的工具名，``unit`` 这种只在两个值里选的
    参数也不会写错（见 guide.md §8.4 与 ai/docs/adr/ADR-003）。
    """

    schemas: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.summary,
                "parameters": tool_parameters(tool.name),
            },
        }
        for tool in TOOLS
    ]
    schemas.extend(
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.summary,
                "parameters": tool.parameters,
            },
        }
        for tool in LOCAL_TOOLS.values()
    )
    schemas.append(
        {
            "type": "function",
            "function": {
                "name": CUSTOM_SCRIPT_TOOL,
                "description": (
                    "只有在上面所有工具都无法完成请求时才使用；"
                    "这时把完整 Praat 英文脚本写进 script 字段。"
                ),
                "parameters": tool_parameters(CUSTOM_SCRIPT_TOOL),
            },
        }
    )
    return schemas


#: 一次请求最多执行几个动作。模型会为「0.25 秒和 0.75 秒的基频」这类请求
#: 一次给多个工具调用（实测 Qwen3.5-2B 就会这么做），它们按顺序拼进同一条脚本里
#: 执行；给个上限是怕模型一口气列十几个，把一次投递变成一串没人看过的操作。
MAX_ACTIONS_PER_REQUEST = 3

#: 会**改动 Praat 里的对象**（建/删/改名/标注/写盘）的工具。
#:
#: 对话循环用它做第二道护栏：用户没说「然后再……」时，第二轮之后不许再动这些工具。
#: 实测 0.8B 预设下「打开当前声音的编辑器」会在第二轮顺手做两次频谱图，把选中对象
#: 也换掉，后面的请求全被带偏；只读查询（pitch、object_info 这类）不受限制。
#: 认不出来的工具（例如 custom_script）按「会改动」处理。
MUTATING_TOOLS: frozenset[str] = frozenset(
    {
        "create_sound",
        "extract_part",
        "concatenate_sounds",
        "duplicate_object",
        "resample_sound",
        "read_file",
        "rename_object",
        "remove_object",
        "save_sound",
        "spectrogram",
        "textgrid_insert_boundary",
        "textgrid_set_interval",
        CUSTOM_SCRIPT_TOOL,
        # 现成脚本可能只打印结果，也可能写文件，按「会改动」保守处理。
        RUN_SCRIPT_TOOL,
    }
)


def is_mutating(tool_name: str) -> bool:
    """这个工具会不会改动对象；没登记的工具按「会改动」处理（保守）。"""

    return (tool_name or "").strip() not in (set(TOOL_MAP) - MUTATING_TOOLS)


def tool_labels() -> dict[str, str]:
    """``工具名 -> 一句中文说明``，规划层用它给「模型只想执行、没写回话」兜底。"""

    labels = {tool.name: tool.summary for tool in TOOLS}
    labels.update({tool.name: tool.summary for tool in LOCAL_TOOLS.values()})
    labels[CUSTOM_SCRIPT_TOOL] = "执行模型给出的自定义 Praat 脚本。"
    return labels


def plan_actions(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    """把规划结果整理成有序的动作列表。

    两种规划接口都认：原生 function calling 给的 ``actions``（可能多个），以及
    老的 JSON 规划给的单个 ``tool`` / ``arguments`` / ``script``。
    """

    actions: list[dict[str, Any]] = []

    def add(item: Mapping[str, Any]) -> None:
        name = str(item.get("tool", "") or "").strip()
        if not name:
            return
        raw = item.get("arguments")
        actions.append(
            {
                "tool": name,
                "arguments": dict(raw) if isinstance(raw, Mapping) else {},
                "script": str(item.get("script", "") or ""),
            }
        )

    raw_actions = plan.get("actions")
    if isinstance(raw_actions, Sequence) and not isinstance(raw_actions, (str, bytes)):
        for item in raw_actions:
            if isinstance(item, Mapping):
                add(item)
    if not actions:
        add(plan)
    if not actions:
        script = str(plan.get("script", "") or "")
        if script.strip():
            actions.append(
                {
                    "tool": CUSTOM_SCRIPT_TOOL,
                    "arguments": {"script": script},
                    "script": "",
                }
            )
    return actions[:MAX_ACTIONS_PER_REQUEST]


def catalog_text() -> str:
    lines = [tool.describe() for tool in TOOLS]
    lines.append(
        f"- {MEASURE_TOOL}: 表驱动的声学测量（一行参数 = 一条查询，参数表在"
        f" ai/praat_ai/measures.tsv）。参数：{measure_parameter_help()}。"
    )
    lines.extend(tool.describe() for tool in LOCAL_TOOLS.values())
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
    if PYTHON_SCRIPT_PATTERNS.search(normalized):
        raise ToolError(
            "模型给出的是 Python 代码，不是 Praat 脚本。"
            "请换用内置工具描述这个操作，或让模型改用 Praat 英文命令。"
        )
    if FORBIDDEN_SCRIPT_PATTERNS.search(normalized):
        raise ToolError("模型生成的脚本包含被禁止的命令。")
    for line in normalized.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.count('"') % 2 != 0:
            raise ToolError(f"脚本这一行的双引号不配对：{stripped}")
    return normalized


def praat_literal(text: str) -> str:
    """把一段字面文字变成 Praat 字符串字面量（双引号写成两个）。"""

    return '"' + text.replace('"', '""') + '"'


def neutralize_info_commands(script: str, result_path: Path | str) -> str:
    """把自定义脚本里会弹出 Info 窗口的输出命令改写成写结果文件，内容不丢。

    前端把脚本送到 GUI 版 Praat 里跑，``appendInfoLine`` / ``writeInfoLine`` /
    ``print`` / ``echo`` 这些都会走 ``gui_information()`` 把「Praat Info」窗口
    弹出来（用户报的 bug）。所以这里在脚本层面兜底，把每一条都翻译成
    ``appendFileLine``：模型想给用户看的那句话照样回到对话窗口，而不是被注释掉
    之后凭空消失（以前 ``print`` / ``echo`` 就是这么丢的）。
    """

    target = quote(str(result_path))
    lines: list[str] = []
    for line in script.splitlines():
        match = INFO_LINE_PATTERN.match(line) or INFO_VALUE_PATTERN.match(line)
        if match:
            indent, _command, arguments = match.groups()
            payload = arguments.strip() or '""'
            lines.append(f"{indent}appendFileLine: {target}, {payload}")
            continue
        literal_match = INFO_LITERAL_PATTERN.match(line)
        if literal_match:
            indent, _command, rest = literal_match.groups()
            # Praat 这几条命令把关键字后面那**一个**空格当作分隔，再往后的都是内容。
            text = rest[1:] if rest.startswith(" ") else rest
            lines.append(f"{indent}appendFileLine: {target}, {praat_literal(text)}")
            continue
        if INFO_NOISE_PATTERN.match(line):
            lines.append(
                "# praat-ai: 已省略只影响 Info 窗口的命令：" f"{line.strip()}"
            )
            continue
        lines.append(line)
    return "\n".join(lines).rstrip("\n") + "\n"


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
        script = neutralize_info_commands(script, context.result_path)
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
