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

# 模型偶尔会把 Python 代码当成 Praat 脚本填进 script 字段。这类脚本在 Praat 里
# 只会得到一句莫名其妙的英文报错，所以这里直接识别出来并给出中文提示。
PYTHON_SCRIPT_PATTERNS = re.compile(
    r"^\s*(?:import|from)\s+[A-Za-z_][\w.]*(?:\s+import\s+|\s*$)"
    r"|^\s*def\s+\w+\s*\("
    r"|^\s*(?:print|input|len|range)\s*\("
    r"|\bparselmouth\b|\bnumpy\b|np\.\w+|\bos\.\w+\(",
    re.MULTILINE,
)

TEMPORARY_OBJECT_NAME = "ai-chat-temp"

CUSTOM_SCRIPT_TOOL = "custom_script"

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


@dataclass(frozen=True, slots=True)
class ObjectRow:
    id: int
    class_name: str
    name: str
    selected: bool
    # Praat 那边打开着这个对象的编辑器时，会多写两列：用户手动拖出来的选区。
    selection_start: float | None = None
    selection_end: float | None = None

    @property
    def selection(self) -> tuple[float, float] | None:
        """编辑器里手动拖出来的区间；只点了光标（首尾相等）时不算选区。"""

        if self.selection_start is None or self.selection_end is None:
            return None
        if self.selection_end - self.selection_start <= 0.0:
            return None
        return (self.selection_start, self.selection_end)

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


def parse_object_context(text: str) -> tuple[ObjectRow, ...]:
    """Parse the ``id / class / name / selected`` TSV written by Praat.

    旧版本只写四列；打开着编辑器时 Praat 会多写 ``sel_start``/``sel_end`` 两列，
    缺列就当作没有圈选。
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
    row = context.resolve_object(arguments.get("object"))
    formatns = _formant_numbers(arguments)
    unit = _unit_literal(arguments, "hertz")
    unit_text = _unit_display(arguments, "hertz")
    times = _query_times(arguments, fallback=_default_time_expression(row))
    temporary = row.class_name != "Formant"
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

    row = context.resolve_object(arguments.get("object"))
    context.require_class(row, TIME_DOMAIN_CLASSES, "这个对象没有时长，无法做共振峰分析")
    formatns = _formant_numbers(arguments)
    unit = _unit_literal(arguments, "hertz")
    unit_text = _unit_display(arguments, "hertz")
    temporary = row.class_name != "Formant"
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
        f"To Spectrogram: {window_length:.6f}, {maximum_frequency:.6f}, "
        f"{time_step:.6f}, {frequency_step:.6f}, \"Gaussian\"",
        f"Rename: {quote(name)}",
        "frames = Get number of frames",
        _write_result(
            context,
            [
                quote("已生成频谱图："),
                quote(name),
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


def _build_vot_explicit(arguments: Mapping[str, Any], context: ToolContext) -> str:
    """VOT（嗓音起始时间）= 浊音起始时刻 − 爆破/除阻时刻。

    这里不做自动检测：VOT 依赖"爆破"和"浊音起始"这两个点的判断，靠脚本猜很容易
    给出看起来精确、其实错得离谱的数字。所以要么用用户/标注给出的两个时刻相减，
    要么由 TextGrid 的边界来定，并把用的两个时刻写进结果，让用户能核对。
    """

    row = context.resolve_by_class(
        arguments.get("object"),
        frozenset({"TextGrid", "Sound"}),
        "算 VOT 需要一个 TextGrid（按层补边界）或 Sound（直接按两个时刻相减）",
    )
    if arguments.get("burst", None) in (None, ""):
        raise ToolError(
            "算 VOT 需要 burst 参数：爆破/除阻时刻（秒）。"
            "前端不做自动检测，请先看波形或标出这个点。"
        )
    if arguments.get("voicing", arguments.get("onset", None)) in (None, ""):
        raise ToolError("算 VOT 需要 voicing 参数：浊音起始时刻（秒）。")
    burst = _number(arguments, "burst", 0.0, 0.0, 36000.0)
    voicing = _number(
        {"voicing": arguments.get("voicing", arguments.get("onset", None))},
        "voicing",
        0.0,
        0.0,
        36000.0,
    )
    if voicing <= burst:
        raise ToolError(
            f"浊音起始必须晚于爆破时刻（现在 burst={burst:.3f} 秒、"
            f"voicing={voicing:.3f} 秒）。"
        )
    tier = _tier_number(arguments)
    lines = [
        f"selectObject: {row.id}",
        f"t1 = {burst:.6f}",
        f"t2 = {voicing:.6f}",
        "vot = t2 - t1",
    ]
    if row.class_name == "TextGrid":
        lines.extend(
            [
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
        )
    else:
        lines.append(
            _write_result(
                context,
                [
                    quote("VOT = "),
                    "fixed$ (vot, 4)",
                    quote(" 秒（"),
                    "fixed$ (vot * 1000, 1)",
                    quote(" 毫秒）："),
                    "fixed$ (t1, 3)",
                    quote(" 秒（爆破）→ "),
                    "fixed$ (t2, 3)",
                    quote(" 秒（浊音起始）；按给出的两个时刻相减，未做自动检测"),
                ],
            )
        )
    return _assemble(lines, context)


def _echoes_editor_selection(
    start: Any, end: Any, selection: tuple[float, float]
) -> bool:
    """模型把编辑器里的圈选原样抄进 from/to 时，数值上应该和选区对得上。"""

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


def _seconds_argument(value: Any, key: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ToolError(f"参数 {key} 必须是数字，收到：{value!r}") from error
    return min(max(number, 0.0), 36000.0)


def _rise_onset_lines(prefix: str, env_var: str) -> list[str]:
    """在强度包络里找最陡的一段上升沿，写进 ``<prefix>Onset``/``<prefix>Rise``。

    判定靠"升幅 + 上升沿之前那段低能量"，不用"区间峰值 − x dB"：范围里只要还夹着
    别的强段（比如后面的元音），后者就会漂，同一个音两次能差好几毫秒。
    """

    return [
        f"selectObject: {env_var}",
        f"{prefix}N = Get number of frames",
        f"{prefix}Rise = -1000",
        f"{prefix}Best = -1",
        f"for i from 1 to {prefix}N",
        "    ft = Get time from frame number: i",
        "    back = i - 3",
        "    if back >= 1 and ft >= tmin and ft <= tmax",
        "        bt = Get time from frame number: back",
        "        if bt >= tmin",
        "            v = Get value in frame: i",
        "            v0 = Get value in frame: back",
        "            later = v",
        "            j = i + 5",
        f"            if j <= {prefix}N",
        "                later = Get value in frame: j",
        "            endif",
        # 上升沿之后能量要守得住才算一次真瞬态：被硬切出来的爆音"来了就走"，
        # 用它当爆破会把 VOT 报大几十毫秒。
        f"            if later >= v - 10 and v - v0 > {prefix}Rise",
        f"                {prefix}Rise = v - v0",
        f"                {prefix}Best = i",
        "            endif",
        "        endif",
        "    endif",
        "endfor",
        f"{prefix}Onset = tmin",
        f"if {prefix}Best >= 1",
        f"    {prefix}Onset = Get time from frame number: {prefix}Best",
        f"    {prefix}Ref = Get value in frame: {prefix}Best",
        f"    k = {prefix}Best - 1",
        "    found = 0",
        "    while k >= 1 and found = 0",
        "        vt = Get time from frame number: k",
        "        v = Get value in frame: k",
        f"        if vt < tmin or v < {prefix}Ref - 8",
        "            found = 1",
        "        else",
        f"            {prefix}Onset = vt",
        "            k = k - 1",
        "        endif",
        "    endwhile",
        "endif",
    ]


def _build_vot_auto(arguments: Mapping[str, Any], context: ToolContext) -> str:
    """在用户圈出的大概范围里自动估计 VOT（爆破 → 浊音起始）。

    爆破和浊音起始分成两步测，结果里分别写清楚，好让人判断是哪一步不稳：

    1. 爆破（释放瞬态）：把声音带通到 2–8 kHz 再算强度包络（1 ms 步长、3.2 ms
       窗口，比全频段窗口短，免得把爆破点平均到前面去），取最陡的一段上升沿，
       再退到这段上升沿之前的低能量帧。升幅不到 ``burst_db``（默认 6 dB）就换
       全频段包络兜底，两个都不够就报"找不到爆破瞬态"。不用"区间峰值 − x dB"
       当阈值：范围里只要还夹着别的强段，这个阈值就会漂。
    2. 浊音起始：``To Pitch (ac)``（2 ms 步长、默认浊音阈值，走的就是短时自相关）
       连续 3 帧（6 ms）都判出基频才算声带开始振动；谐噪比只截起点之后 50 ms
       那一小段算峰值，当谐波结构的依据写进结果——整段声音做交叉相关太慢
       （10 秒的声音上要 0.3 秒，用户能感觉出卡）。
       注意：``To Harmonicity (cc)`` 的 periodsPerWindow 给 0.5 会让 Praat 7.0.02
       直接在 Sound_to_Pitch.cpp 断言崩溃，只能 ≥ 1；而 4 ms 的窗口（minPitch 250）
       在 220 Hz 上会判成"全是噪声"，所以窗口就用 1/minPitch。
    3. VOT = 浊音起始 − 爆破时刻。

    范围整段都在浊音里时报"起点已是浊音"；范围内后面还有第二段浊音（中间隔了
    ≥20 毫秒的低谐噪比段）时只报第一个候选，并提示范围偏大。

    范围来自用户话里的 from/to，或者他在波形上手动拖出来的选区
    （``chat_context.tsv`` 的 ``sel_start``/``sel_end``）；模型把圈选抄成
    from/to 时结果里仍注明"按编辑器圈选"。

    这是估计值，不是人工标注：结果里写明两步各自的依据、范围和时间分辨率。
    """

    row = context.resolve_by_class(
        arguments.get("object"), SOUND_CLASSES, "自动检测 VOT 需要一个 Sound 对象"
    )
    burst_db = _number(arguments, "burst_db", 6.0, 3.0, 30.0)
    pitch_floor = _number(arguments, "pitch_floor", 75.0, 40.0, 500.0)
    start_arg = arguments.get("from", arguments.get("start", None))
    end_arg = arguments.get("to", arguments.get("end", None))
    editor_selection = row.selection
    # 模型常把编辑器里的圈选原样抄进 from/to；数值对得上就还按圈选报，
    # 否则回话里会丢掉「这段范围是用户自己在波形上圈的」这个出处。
    if editor_selection is not None and _echoes_editor_selection(
        start_arg, end_arg, editor_selection
    ):
        start_arg = None
        end_arg = None
    had_range = start_arg not in (None, "") or end_arg not in (None, "")
    if had_range:
        editor_selection = None
    lines = [
        f"selectObject: {row.id}",
        "duration = Get total duration",
        "tmin = 0",
        "tmax = duration",
    ]
    if editor_selection is not None:
        lines.append(f"tmin = {editor_selection[0]:.6f}")
        lines.append(f"tmax = {editor_selection[1]:.6f}")
    elif start_arg not in (None, ""):
        lines.append(f"tmin = {_seconds_argument(start_arg, 'from'):.6f}")
    if editor_selection is None and end_arg not in (None, ""):
        lines.append(f"tmax = {_seconds_argument(end_arg, 'to'):.6f}")
    if editor_selection is not None:
        note_lines = [
            f'rangeNote$ = "（按编辑器圈选 {editor_selection[0]:.3f}–'
            f'{editor_selection[1]:.3f} 秒）"'
        ]
    else:
        note_lines = [
            'rangeNote$ = "（未指定范围，按整个对象搜索）"',
            "if tmin > 0 or tmax < duration",
            '    rangeNote$ = ""',
            "endif",
        ]
    lines.extend(
        [
            "if tmin < 0",
            "    tmin = 0",
            "endif",
            "if tmax > duration",
            "    tmax = duration",
            "endif",
            "if tmin > tmax - 0.002",
            "    tmin = 0",
            "    tmax = duration",
            "endif",
            *note_lines,
            # ① 爆破（释放瞬态）：带通到 2–8 kHz 再求强度包络的最陡上升沿
            f"selectObject: {row.id}",
            f'To Harmonicity (cc): 0.002, {pitch_floor:.6f}, 0.1, 1.0',
            'hnrId = selected ("Harmonicity")',
            f"selectObject: {row.id}",
            "Filter (pass Hann band): 2000, 8000, 100",
            'hfSound = selected ("Sound")',
            'To Intensity: 2000, 0.001, "yes"',
            'hfEnv = selected ("Intensity")',
            *_rise_onset_lines("hf", "hfEnv"),
            f"selectObject: {row.id}",
            'To Intensity: 1000, 0.001, "yes"',
            'bbEnv = selected ("Intensity")',
            *_rise_onset_lines("bb", "bbEnv"),
            "burstTime = -1",
            "burstRise = 0",
            'burstBand$ = ""',
            f"if hfRise >= {burst_db:.1f}",
            "    burstTime = hfOnset",
            "    burstRise = hfRise",
            '    burstBand$ = "高频带 2–8 kHz"',
            f"elsif bbRise >= {burst_db:.1f}",
            "    burstTime = bbOnset",
            "    burstRise = bbRise",
            '    burstBand$ = "全频段"',
            "endif",
            "selectObject: hfEnv",
            "plusObject: bbEnv",
            "plusObject: hfSound",
            "Remove",
            # ② 浊音起始：自相关基频连续 3 帧（6 ms）成立；谐噪比另取一小段当佐证
            f"selectObject: {row.id}",
            f'To Pitch (ac): 0.002, {pitch_floor:.6f}, 15, "no", 0.03, '
            '0.45, 0.01, 0.35, 0.14, 600',
            "pn = Get number of frames",
            "voicingTime = -1",
            "f0Onset = 0",
            "firstVoicedTime = -1",
            "run = 0",
            "runStart = -1",
            "runStartF0 = 0",
            "lastVoiced = -1",
            "candTime = -1",
            "secondVoicingTime = -1",
            "for i from 1 to pn",
            "    ft = Get time from frame number: i",
            "    if ft >= tmin and ft <= tmax",
            '        v = Get value in frame: i, "Hertz"',
            "        if v <> undefined",
            "            run = run + 1",
            "            if run = 1",
            "                runStart = ft",
            "                runStartF0 = v",
            "            endif",
            "            if firstVoicedTime < 0",
            "                firstVoicedTime = ft",
            "            endif",
            "            if voicingTime < 0 and run >= 3 and runStart >= burstTime",
            "                voicingTime = runStart",
            "                f0Onset = runStartF0",
            "            endif",
            "            if candTime >= 0",
            "                if secondVoicingTime < 0",
            "                    secondVoicingTime = candTime",
            "                endif",
            "            elsif lastVoiced >= 0 and voicingTime >= 0 and ft - lastVoiced >= 0.02",
            "                candTime = ft",
            "            endif",
            "            lastVoiced = ft",
            "        else",
            "            run = 0",
            "            candTime = -1",
            "        endif",
            "    endif",
            "endfor",
            "Remove",
            "if firstVoicedTime >= 0 and firstVoicedTime <= tmin + 0.01",
            _write_result(
                context,
                [
                    quote("自动检测失败：范围起点附近（"),
                    "fixed$ (firstVoicedTime, 3)",
                    quote(" 秒）已经是浊音（自相关基频连续成立），"
                          "说明爆破不在这个范围里。请把 from 提前到闭音段"
                          "（爆破之前），或直接给出 burst 和 voicing 两个时刻。"),
                    "rangeNote$",
                ],
            ),
            "elsif burstTime < 0",
            _write_result(
                context,
                [
                    quote("自动检测失败："),
                    "fixed$ (tmin, 3)",
                    quote("–"),
                    "fixed$ (tmax, 3)",
                    quote(f" 秒里高频带和全频段能量都没有 {burst_db:.0f} dB 以上的陡升，"
                          "找不到爆破瞬态。请把范围收紧到爆破附近，"
                          "或直接给出 burst 和 voicing 两个时刻。"),
                    "rangeNote$",
                ],
            ),
            "elsif voicingTime < 0",
            _write_result(
                context,
                [
                    quote("自动检测失败：爆破点 "),
                    "fixed$ (burstTime, 3)",
                    quote(" 秒之后没有连续 3 帧以上的浊音（自相关基频），"
                          "范围里可能没有浊音段。"),
                    "rangeNote$",
                ],
            ),
            "else",
            # 谐噪比只当佐证，就只算起点之后 50 ms 那一小段：整段声音做交叉相关
            # 在 10 秒的声音上要 0.3 秒，用户能感觉出卡。
            "    hnrEnd = voicingTime + 0.05",
            "    if hnrEnd > duration",
            "        hnrEnd = duration",
            "    endif",
            "    hnrMax = 0",
            "    if hnrEnd - voicingTime >= 0.03",
            f"        selectObject: {row.id}",
            '        Extract part: voicingTime, hnrEnd, "rectangular", 1, "no"',
            '        ex = selected ("Sound")',
            f'        To Harmonicity (cc): 0.002, {pitch_floor:.6f}, 0.1, 1.0',
            "        hn = Get number of frames",
            "        if hn >= 1",
            "            for i from 1 to hn",
            "                hv = Get value in frame: i",
            "                if hv > hnrMax",
            "                    hnrMax = hv",
            "                endif",
            "            endfor",
            "        endif",
            "        Remove",
            "        selectObject: ex",
            "        Remove",
            "    endif",
            "    vot = voicingTime - burstTime",
            '    caution$ = ""',
            "    if vot < 0.005",
            '        caution$ = "（不到 5 毫秒：可能范围起点已在浊音里，'
            '也可能是不送气塞音，请核对）"',
            "    endif",
            '    secondNote$ = ""',
            "    if secondVoicingTime >= 0",
            '        secondNote$ = "；范围偏大：后面还有第 2 段浊音从 " + '
            'fixed$ (secondVoicingTime, 3) + " 秒开始，本次只报了第一个候选，建议收紧范围"',
            "    endif",
            _write_result(
                context,
                [
                    quote("VOT 估计值 = "),
                    "fixed$ (vot, 4)",
                    quote(" 秒（"),
                    "fixed$ (vot * 1000, 1)",
                    quote(" 毫秒）：爆破 "),
                    "fixed$ (burstTime, 3)",
                    quote(" 秒（"),
                    "burstBand$",
                    quote(" 能量升 "),
                    "fixed$ (burstRise, 1)",
                    quote(" dB）→ 浊音起始 "),
                    "fixed$ (voicingTime, 3)",
                    quote(" 秒（自相关基频 "),
                    "fixed$ (f0Onset, 1)",
                    quote(" Hz，之后 50 毫秒内谐噪比最高 "),
                    "fixed$ (hnrMax, 1)",
                    quote(" dB）；范围 "),
                    "fixed$ (tmin, 3)",
                    quote("–"),
                    "fixed$ (tmax, 3)",
                    quote(" 秒；爆破与浊音起始分开估计，请对着语图核对"),
                    "caution$",
                    "secondNote$",
                    "rangeNote$",
                ],
            ),
            "endif",
        ]
    )
    return _assemble(lines, context)


def _build_vot(arguments: Mapping[str, Any], context: ToolContext) -> str:
    """给了爆破/浊音两个时刻就相减，否则在大概范围里自动估计。"""

    has_burst = arguments.get("burst", None) not in (None, "")
    has_voicing = (
        arguments.get("voicing", arguments.get("onset", None)) not in (None, "")
    )
    if has_burst and has_voicing:
        return _build_vot_explicit(arguments, context)
    if has_burst or has_voicing:
        raise ToolError(
            "VOT 需要同时给出 burst（爆破）和 voicing（浊音起始）两个时刻；"
            "只想自动估计的话两个都不填，改用 from/to 给出大概范围。"
        )
    return _build_vot_auto(arguments, context)


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
            f"Create Sound from formula: {quote(name)}, 1, 0, "
            f"{duration:.6f}, 44100, ~ 0",
            "duration = Get total duration",
        ]
        description = "静音"
    else:
        lines = [
            f"Create Sound as pure tone: {quote(name)}, 1, 0, "
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
        "Concatenate",
        f"Rename: {quote(name)}",
        "duration = Get total duration",
        _write_result(
            context,
            [
                quote(f"已把 {first.name} 和 {second.name} 拼成："),
                quote(name),
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
        'Extract part: t1, t2, "rectangular", 1, "no"',
        f"Rename: {quote(name)}",
        "duration = Get total duration",
        _write_result(
            context,
            [
                quote("已截取片段："),
                quote(name),
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
        f"Resample: {rate}, 50",
        "actual = Get sampling frequency",
        _write_result(
            context,
            [
                quote("已重采样为新对象，采样率 "),
                "fixed$ (actual, 0)",
                quote(" Hz（原对象保持不变）"),
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
        f"Copy: {quote(name)}",
        _write_result(context, [quote("已复制为："), quote(name)]),
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
        name="vot",
        summary="算 VOT（嗓音起始时间）：给了 burst（爆破）和 voicing（浊音起始）就直接相减；只给 from/to 就在这个大概范围里自动估计（结果标注是估计值）。",
        signature="burst、voicing（秒，给全就相减）、from、to（秒，自动估计的范围）、burst_db（默认 6，爆破最小升幅 dB）、pitch_floor（默认 75）、tier（默认 1）、object（可选）",
        build=_build_vot,
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
