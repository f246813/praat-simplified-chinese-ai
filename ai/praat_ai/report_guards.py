"""Deterministic checks at the report boundary; no extra model request.

Evidence IDs follow state.evidence order. ``E1.q3`` names a parsed quantity,
not an arbitrary number in a prompt. Calculations use a small arithmetic AST
and are rendered by this module. These checks bind numeric claims and a set of
explicit prosody claims to their sources; they do not prove free-text semantics.
"""
from __future__ import annotations

import ast
import copy
import math
import re
from dataclasses import dataclass
from typing import Any

from pydantic_ai import ModelRetry

from .escape_policy import note_guard
from .tools import parse_object_context


#: 算不出来的推导式在正文里换成这个：不把内部语法漏给用户，也不因为一句推导丢掉整份报告。
UNVERIFIED_CALC = '[推导未核对]'


class CalcUnavailable(Exception):
    """``{{calc:…}}`` 算不出来（语法/量纲/引用问题）。

    这只说明**这一处推导没法核对**，不说明报告在编造测量：所以降级为"标注为未核对"，
    不再阻断整份报告（2026-10-06：20 个阻断点里有 13 个是这类内部语法问题）。
    """


def _block(state: Any, rule: str, message: str) -> None:
    """守卫里唯一允许中断报告的出口：只留客观、漏过去会真的错的规则。"""

    note_guard(state, 'block', rule)
    raise ModelRetry(message)


_N = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_NUMBER = re.compile(r"(?<![A-Za-z0-9_.])" + _N + r"(?![A-Za-z0-9_.])")
_UNIT = re.compile(
    r"\s*(kHz|Hz(?:\s*/\s*(?:s|秒))?|半音\s*/\s*(?:s|秒)|"
    r"milliseconds?|seconds?|msec|sec|ms|s|毫秒|秒|dB|Pa|%|％|倍|半音|八度)(?![A-Za-z])",
    re.I,
)
_RANGE = re.compile(
    r"(?P<a>" + _N + r")\s*(?P<ua>ms|s|毫秒|秒)?\s*[–—~～至到-]\s*"
    r"(?P<b>" + _N + r")\s*(?P<ub>milliseconds?|seconds?|msec|sec|ms|s|毫秒|秒)(?![A-Za-z])",
    re.I,
)
_CITATION = re.compile(r"\[E(\d+)\]")
_OBJECT_IDENTIFIER = re.compile(
    r'(?:对象\s*[:：]?\s*|(?<![A-Za-z0-9_])(?:object|id)\s*[:：]?\s*|#\s*)(\d+)(?![\d.])', re.I)
_CALC = re.compile(r"\{\{calc:([^{}|]+)\|([^{}|]+)\}\}")
_REF = re.compile(r"\b(E\d+)\.q([1-9]\d*)\b")
_GENERAL = re.compile(r"一般知识|一般原理|概念说明|概念解释|通用知识|示例[（(]非本录音[）)]|general knowledge", re.I)
_SPECIFIC = re.compile(r"本(?:段|次|录音|对象|材料)|这(?:段|个|次|份)|该(?:段|录音|对象)|你(?:的|这)|当前|实测|测得|测量结果")
_ADVICE = re.compile(r'^\s*(?:[-*]\s*)?(?:建议|下一步|请|可以尝试|可尝试|练习时|参数设置)')
_PROSODY = re.compile(
    r"平板型|头高型|中高型|尾高型|平板调|升调|降调|上升|下降|升高|降低|"
    r"(?:语调|音调|音高|基频).{0,12}(?:平淡|单调|平坦|平稳|起伏小|变化小)|"
    r"(?:平淡|单调|平坦|平稳)的?(?:语调|音调|音高)|"
    r"\b(?:heiban|atamadaka|rising|falling|flat intonation)\b", re.I,
)
_INABILITY = re.compile(r"不能|无法|不可(?:据此|判断|确定)|未能|尚不能|不(?:代表|足以|等于)|不足|缺少|缺乏|尚无|未测|还需|需要先|必须先")


@dataclass(frozen=True)
class Quantity:
    evidence: str
    index: int
    row: int
    value: float
    text: str
    unit: str
    role: str
    start: int
    end: int

    @property
    def ref(self) -> str:
        return f'{self.evidence}.q{self.index}'


@dataclass
class Record:
    id: str
    evidence: Any
    quantities: list[Quantity]
    target: str | None
    target_name: str
    interval: tuple[float, float] | None


def _unit(raw: str) -> tuple[str, float, tuple[int, int, str]]:
    """Frequency and time are independent dimensions; other units are named."""
    key = re.sub(r'\s+', '', raw).lower().replace('％', '%')
    if key in {'s', 'sec', 'second', 'seconds', '秒'}:
        return 's', 1.0, (0, 1, '')
    if key in {'ms', 'msec', 'millisecond', 'milliseconds', '毫秒'}:
        return 'ms', .001, (0, 1, '')
    if key in {'hz', 'khz'}:
        return 'kHz' if key == 'khz' else 'Hz', 1000.0 if key == 'khz' else 1.0, (1, 0, '')
    if key in {'hz/s', 'hz/秒'}:
        return 'Hz/s', 1.0, (1, -1, '')
    if key in {'半音/s', '半音/秒'}:
        return '半音/s', 1.0, (0, -1, '半音')
    if key in {'', '%', '倍'}:
        # Percent expressions explicitly multiply by 100, as ordinary formulas do.
        return key, 1.0, (0, 0, '')
    return raw.strip(), 1.0, (0, 0, key)


def _precision(text: str) -> float:
    mantissa, _, exponent = text.lower().partition('e')
    decimals = len(mantissa.split('.')[1]) if '.' in mantissa else 0
    return .5 * 10 ** ((int(exponent) if exponent else 0) - decimals)


def _role(prefix: str, tool: str = '') -> str:
    """Recognized quantity labels, kept separate from the numeric matcher."""
    pieces = re.split(r'[，,；;：:=＝]', prefix)
    nearby = next((part for part in reversed(pieces) if part.strip()), '')[-60:]
    full = prefix[-160:]
    formant = re.search(r'(?:\bF\s*([1-9])\b|第\s*([1-9])\s*共振峰|共振峰\s*([1-9]))', nearby, re.I)
    if not formant and 'formant' in tool:
        formant = re.search(r'(?:\bF\s*([1-9])\b|第\s*([1-9])\s*共振峰)', full, re.I)
    if formant:
        category = 'formant.' + next(x for x in formant.groups() if x)
    elif re.search(r'基频|音高|F0|pitch', nearby, re.I) or tool in {'pitch', 'pitch_statistics'}:
        category = 'pitch'
    elif re.search(r'强度|音强|响度|intensity', nearby, re.I) or 'intensity' in tool:
        category = 'intensity'
    elif re.search(r'VOT|嗓音起始|发声起始', nearby, re.I) or tool == 'vot':
        category = 'vot'
    elif re.search(r'时长|duration', nearby, re.I) or tool == 'duration':
        return 'duration'
    elif re.search(r'斜率', nearby) and re.search(r'基频|音高', full):
        category = 'pitch'
    else:
        category = ''
    if re.search(r'原始平均|raw\s*mean', nearby, re.I):
        metric = 'raw_mean'
    elif re.search(r'中位|median', nearby, re.I):
        metric = 'median'
    elif re.search(r'标准差|standard deviation|\bsd\b', nearby, re.I):
        metric = 'sd'
    elif re.search(r'斜率|slope', nearby, re.I):
        metric = 'slope_absolute' if '绝对' in nearby or '倍频跳变' in nearby else 'slope'
    elif re.search(r'起点|起始基频|start', nearby, re.I):
        metric = 'start'
    elif re.search(r'终点|结束基频|end', nearby, re.I):
        metric = 'end'
    elif re.search(r'最高点|峰值.{0,5}时|最大值.{0,5}时', nearby):
        return (category or 'pitch') + '.max_time'
    elif re.search(r'最低|最小|minimum|\bmin\b', nearby, re.I):
        metric = 'min'
    elif re.search(r'最高|最大|峰值|maximum|\bmax\b', nearby, re.I):
        metric = 'max'
    elif re.search(r'平均|均值|mean|average', nearby, re.I):
        metric = 'mean'
    else:
        metric = 'value'
    if category:
        return category + '.' + metric
    if metric != 'value':
        return metric
    label = re.sub(r'[^A-Za-z\u3400-\u9fff_]', '', nearby)[-20:]
    return label or 'value'


def _quantities(eid: str, evidence: Any) -> list[Quantity]:
    result: list[Quantity] = []
    for row_number, row in enumerate(evidence.rows, 1):
        ranges = list(_RANGE.finditer(row))
        range_parts = {span: (role, unit) for match in ranges
                       for span, role, unit in ((match.span('a'), 'range.start', match['ua'] or match['ub']),
                                                (match.span('b'), 'range.end', match['ub']))}
        for match in _NUMBER.finditer(row):
            if re.match(r'\s*共振峰', row[match.end():]) or re.search(r'第\s*$', row[:match.start()]):
                continue
            unit_match = _UNIT.match(row, match.end())
            unit = unit_match[1] if unit_match else ''
            role = _role(row[:match.start()], evidence.tool)
            if role == 'pitch.slope' and evidence.tool == 'measure':
                parameters = evidence.arguments.get('parameters') or []
                if isinstance(parameters, str):
                    parameters = parameters.split(',')
                if set(parameters) & {'pitch_slope', 'pitch_slope_octave_free'}:
                    role = 'pitch.slope_absolute'
            if match.span() in range_parts:
                role, unit = range_parts[match.span()]
            elif not unit and not re.search(r'[=:＝]\s*$', row[:match.start()]):
                continue
            # Undefined rows contain range/time parameters, never a measured value.
            if re.search(r'无法计算|undefined|没有可用的数据', row, re.I) and not role.startswith('range.'):
                continue
            value = float(match[0])
            if not math.isfinite(value):
                continue
            result.append(Quantity(eid, len(result) + 1, row_number, value, match[0], unit,
                                   role, match.start(), unit_match.end() if unit_match else match.end()))
    return result


def _target(evidence: Any) -> tuple[str | None, str]:
    rows = parse_object_context(evidence.source or '')
    requested = evidence.arguments.get('object')
    selected = [row for row in rows if row.selected]
    for row in rows:
        if requested is not None and str(requested) in {str(row.id), row.name, f'{row.class_name} {row.name}'}:
            return str(row.id), row.name
    if requested is not None:
        return str(requested), ''
    if len(selected) == 1:
        return str(selected[0].id), selected[0].name
    return None, ''


def _records(state: Any) -> dict[str, Record]:
    records: dict[str, Record] = {}
    for number, evidence in enumerate(state.evidence, 1):
        eid = f'E{number}'
        quantities = _quantities(eid, evidence) if evidence.kind == 'measurement' else []
        target, name = _target(evidence)
        starts = [q for q in quantities if q.role == 'range.start']
        ends = [q for q in quantities if q.role == 'range.end']
        interval = None
        if starts and ends:
            interval = (starts[0].value * _unit(starts[0].unit)[1], ends[0].value * _unit(ends[0].unit)[1])
        elif 'from' in evidence.arguments and 'to' in evidence.arguments:
            try:
                interval = (float(evidence.arguments['from']), float(evidence.arguments['to']))
            except (ValueError, TypeError):
                pass
        records[eid] = Record(eid, evidence, quantities, target, name, interval)
    return records


#: 拒绝理由里那处没核上的数值：「数值“0.551 秒”未匹配…」。
_REJECTED_VALUE = re.compile(r'数值“([^”]{0,60})”')


def rejected_values(reason: str) -> list[str]:
    """从守卫的拒绝理由里取出没核上的数值。

    保留模型草稿时用得到：正文可以留，但这几个没通过核对的数字不能当实测给用户看。
    """

    return [item.strip() for item in _REJECTED_VALUE.findall(str(reason or '')) if item.strip()]


def report_context_data(state: Any) -> dict[str, Any]:
    """Compact IDs and row/role indexes, with no second copy of source values."""

    records = _records(state)
    if not records:
        return {}
    data: dict[str, Any] = {'evidence_ids': list(records)}
    refs = {eid: [f'r{q.row}:{q.role}' for q in record.quantities]
            for eid, record in records.items() if record.quantities}
    if refs:
        data['quantity_refs'] = refs
    return data


def report_guard_instructions(state: Any) -> str:
    if not state.evidence:
        return '\n没有测量时不填录音数值或下音调结论；一般知识明确标注，缺证据就说明。'
    return ('\n量化陈述逐行引[E编号]，须同对象、范围、量名、单位；一般知识明确标注。'
            'quantity_refs第N项即E编号.qN。推导用{{calc:E1.q1/E2.q1*100|%}}，仅真实输入和四则，程序写算式结果。'
            '具体录音音调结论须同目标且有定义值的走向证据，平均值不足。')


def _same_value(value: float, text: str, unit: str, quantity: Quantity) -> bool:
    _, scale, dimension = _unit(unit)
    _, source_scale, source_dimension = _unit(quantity.unit)
    if dimension != source_dimension:
        return False
    # Omitted units do not silently turn Hz into dimensionless numbers.
    if unit == '' and quantity.unit != '':
        return False
    tolerance = _precision(text) * scale + _precision(quantity.text) * source_scale + 1e-10
    return abs(value * scale - quantity.value * source_scale) <= tolerance


def _roles_match(claim: str, source: str) -> bool:
    if claim.startswith('range.'):
        return claim == source
    if claim == source:
        return True
    if claim in {'mean', 'min', 'max', 'median', 'sd', 'start', 'end', 'slope', 'slope_absolute'}:
        return source.endswith('.' + claim)
    # A generic pitch summary may omit the word "mean", but may not become F1.
    if claim == 'pitch.value':
        return source in {'pitch.value', 'pitch.mean'}
    if claim.startswith('formant.') and claim.endswith('.value'):
        return source in {claim, claim.replace('.value', '.mean')}
    return False


#: 本身就算量名的角色（不在这个集合里、又不带类别的，只能当自由文本标签）。
_NAMED_ROLES = {'mean', 'min', 'max', 'median', 'sd', 'start', 'end',
                'slope', 'slope_absolute', 'duration', 'range.start', 'range.end'}


def _free_label(role: str) -> bool:
    """这个角色名只是解读数字出处的自由标签（「爆破」「浊音起始」），不是量名吗？

    证据侧的角色是按工具名和邻近词推出来的（``vot`` 行的每个数都被打成
    ``vot.value``），声明侧却是从模型自己的句子里取标签。两边的标签天然不会一字不差，
    所以自由标签不能直接比字符串；只有真的点名了量名（基频/共振峰/强度/VOT/时长…）
    才按量名核对。
    """

    if not role or role == 'value':
        return True
    if '.' in role:
        return False
    return role not in _NAMED_ROLES


def _line_targets(state: Any, text: str, records: dict[str, Record]) -> set[str]:
    explicit = set(_OBJECT_IDENTIFIER.findall(text))
    known = {str(row.id) for row in parse_object_context(state.context_text)}
    known.update(record.target for record in records.values() if record.target is not None)
    if explicit - known:
        _block(state, 'report.object_unknown', '报告引用了快照和证据中不存在的对象编号。')
    for record in records.values():
        if record.target and len(record.target_name) >= 2 and record.target_name in text:
            explicit.add(record.target)
    if explicit:
        return explicit
    return {str(row.id) for row in parse_object_context(state.context_text) if row.selected}


def _general(text: str, in_general: bool, records: dict[str, Record]) -> bool:
    marked = in_general or bool(_GENERAL.search(text))
    names_target = any(len(r.target_name) >= 2 and r.target_name in text for r in records.values())
    return marked and not _SPECIFIC.search(text) and not names_target and not _CITATION.search(text)


def _whole_ranges(state: Any, records: dict[str, Record]) -> dict[str, tuple[float, float]]:
    from .chat import _whole_recording_request
    if not _whole_recording_request(state.goal):
        return {}
    result = {}
    for record in records.values():
        durations = [q for q in record.quantities if q.role == 'duration' and _unit(q.unit)[2] == (0, 1, '')]
        if record.target is not None and durations:
            result[record.target] = (0, durations[0].value * _unit(durations[0].unit)[1])
    return result


def _identifier_number(cleaned: str, match: re.Match[str], targets: set[str]) -> bool:
    """这个数字是编号/标签而不是量值吗（Markdown 序号、对象编号、共振峰序号）。"""

    if re.match(r'^\s*(?:#{1,6}\s*)?$', cleaned[:match.start()]) and re.match(r'[.)、]\s', cleaned[match.end():]):
        return True
    if any(item.span(1) == match.span() and item[1] in targets
           for item in _OBJECT_IDENTIFIER.finditer(cleaned)):
        return True
    if re.match(r'\s*共振峰', cleaned[match.end():]) or re.search(r'第\s*$', cleaned[:match.start()]):
        return True
    return False


def _numeric_claim_sources(state: Any, line: str, records: dict[str, Record]):
    """核对一行里的数值，并返回它们命中的证据 id。

    返回 ``(sources, failure)``：``sources`` 是命中的证据 id（按出现顺序去重），
    ``failure`` 是 ``(rule, message)`` 或 ``None``。匹配引擎只此一份——「拦下」还是
    「把引证补上」由调用方决定，避免两套规则各自漂移（2026-10-06 的教训）。
    数值未匹配时 failure 的第三项是本行数值/单位的精确跨度，供草稿救援定位。
    """

    cites = [f'E{x}' for x in _CITATION.findall(line)]
    for eid in cites:
        if eid not in records:
            # 正常路径到不了这里：_strip_unknown_citations 会在验证前清掉并计数。
            return [], ('report.evidence_unknown', f'不存在证据[{eid}]；请引用现有证据或说明缺测量。')
    targets = _line_targets(state, line, records)
    sources: list[str] = []
    for clause_match in re.finditer(r'[^；;。\n]+', line):
        clause = clause_match[0]
        clause_cites = [f'E{x}' for x in _CITATION.findall(clause)] or cites
        # 漏写引证时按「同对象的所有证据」核对，命中的证据由调用方补进正文：引证是守卫
        # 自己的记账方式，不该要求模型逐行照抄格式，更不该因为漏写就判成编造数据。
        available = [records[eid] for eid in clause_cites] if clause_cites else list(records.values())
        if targets:
            available = [r for r in available if r.target in targets]
        if re.search(r'整段|全段|整个(?:声音|录音|音频|对象)|whole|entire', clause, re.I) and not re.search(r'中点|时刻|秒处|采样点', clause):
            whole_ranges = _whole_ranges(state, records)
            def full_scope(record):
                if record.evidence.tool in {'duration', 'object_info'}:
                    return True
                if record.evidence.tool in {'pitch', 'intensity', 'formant_frequency', 'formant_bandwidth'}:
                    return False
                required = whole_ranges.get(record.target)
                if required is not None:
                    return record.interval is not None and abs(record.interval[0] - required[0]) <= .001 and abs(record.interval[1] - required[1]) <= .001
                args = record.evidence.arguments
                return args.get('_whole_object') and not any(args.get(key) is not None for key in ('from', 'to', 'start', 'end'))
            available = [record for record in available if full_scope(record)]
            if not available and clause_cites and re.search(r'平均|均值|统计|数值|mean|average', clause, re.I):
                return sources, ('report.range_whole_partial', '整段量化陈述不能引用局部分段值；请保留真实范围或取得整段测量。')
        ranges = list(_RANGE.finditer(clause))
        range_parts = {span: (role, unit) for match in ranges
                       for span, role, unit in ((match.span('a'), 'range.start', match['ua'] or match['ub']),
                                                (match.span('b'), 'range.end', match['ub']))}
        if len(ranges) == 1:
            match = ranges[0]
            start = float(match['a']) * _unit(match['ua'] or match['ub'])[1]
            end = float(match['b']) * _unit(match['ub'])[1]
            available = [r for r in available if r.interval is not None and
                         abs(r.interval[0] - start) <= _precision(match['a']) * _unit(match['ua'] or match['ub'])[1] + .0005 and
                         abs(r.interval[1] - end) <= _precision(match['b']) * _unit(match['ub'])[1] + .0005]
        cleaned = _CITATION.sub(lambda m: ' ' * len(m[0]), clause)
        for match in _NUMBER.finditer(cleaned):
            if _identifier_number(cleaned, match, targets):
                continue
            unit_match = _UNIT.match(cleaned, match.end())
            unit = unit_match[1] if unit_match else ''
            role = _role(cleaned[:match.start()])
            if match.span() in range_parts:
                role, unit = range_parts[match.span()]
            value = float(match[0])
            # 声明侧没点名量名（只有「爆破」「浊音起始」这类出处标签）时按「同对象 +
            # 同范围 + 同量纲 + 同数值」核对；点名了量名的仍走严格规则（F1 不能冒充
            # 平均基频）。_free_label 见上。
            hit = [record for record in available
                   if any((_roles_match(role, q.role) or _free_label(role))
                          and _same_value(value, match[0], unit, q) for q in record.quantities)]
            if not hit:
                return sources, ('report.number_unmatched',
                                 f'数值“{match[0]} {unit}”未匹配同对象/范围/量名的测量。逐行引证；推导用calc占位式，缺测量就说明。',
                                 (clause_match.start() + match.start(),
                                  clause_match.start() + (unit_match.end() if unit_match else match.end())))
            for record in hit:
                if record.id not in sources:
                    sources.append(record.id)
    return sources, None


def mask_rejected_numbers(text: str, values, marker: str, *, state=None) -> str:
    """Mask whole rejected quantities, never substrings of decimals/IDs/labels.

    With evidence, reuse the guard's failing span so an equal, valid quantity
    elsewhere survives. This only locates rejected values; it grants no pass.
    """
    rejected = {re.sub(r'\s+', '', str(value)) for value in values}
    if state is not None:
        state = copy.copy(state)
        state.metrics = {}  # Locating a rejected value must not recount guards.
    records = _records(state) if state is not None else None
    out = []
    in_general = False
    for line in text.splitlines(keepends=True):
        if records is not None:
            if re.match(r'^\s*#{1,6}\s', line):
                in_general = bool(_GENERAL.search(line))
            if (_general(line, in_general, records)
                    or (_ADVICE.search(line) and not _SPECIFIC.search(line) and not _CITATION.search(line))):
                out.append(line)
                continue
            while True:
                try:
                    _, failure = _numeric_claim_sources(state, line, records)
                except ModelRetry:
                    break  # Other gates do not authorize numeric replacement.
                if not failure or len(failure) != 3:
                    break
                start, end = failure[2]
                if re.sub(r'\s+', '', line[start:end]) not in rejected:
                    break
                line = line[:start] + marker + line[end:]
        else:
            # Standalone rescue/reason text has no evidence: exact lexical tokens.
            targets = set(_OBJECT_IDENTIFIER.findall(line))
            spans = []
            for match in _NUMBER.finditer(line):
                if _identifier_number(line, match, targets):
                    continue
                unit = _UNIT.match(line, match.end())
                end = unit.end() if unit else match.end()
                if re.sub(r'\s+', '', line[match.start():end]) in rejected:
                    spans.append((match.start(), end))
            for start, end in reversed(spans):
                line = line[:start] + marker + line[end:]
        out.append(line)
    return ''.join(out)


def _check_numeric_line(state: Any, line: str, records: dict[str, Record]) -> None:
    _, failure = _numeric_claim_sources(state, line, records)
    if failure:
        _block(state, failure[0], failure[1])


def _trajectory(records: list[Record], directional: bool, whole_ranges: dict[str, tuple[float, float]]) -> bool:
    def covers(record: Record, required: tuple[float, float] | None) -> bool:
        return required is None or (record.interval is not None and
                                   record.interval[0] <= required[0] + .001 and
                                   record.interval[1] >= required[1] - .001)

    by_target: dict[str, list[Record]] = {}
    for record in records:
        if record.target is not None and record.evidence.kind == 'measurement':
            by_target.setdefault(record.target, []).append(record)
    for target, group in by_target.items():
        required = whole_ranges.get(target)
        for record in group:
            slopes = [q for q in record.quantities if q.role in {'pitch.slope', 'pitch.slope_absolute'}
                      and _unit(q.unit)[2] in {(1, -1, ''), (0, -1, '半音')}]
            if covers(record, required) and any(q.role == 'pitch.slope' or not directional for q in slopes):
                return True
        endpoints = [(record.interval, q.role) for record in group for q in record.quantities
                     if covers(record, required) and q.role in {'pitch.start', 'pitch.end'}
                     and _unit(q.unit)[2] == (1, 0, '')]
        if any(start_range == end_range and start_role == 'pitch.start' and end_role == 'pitch.end'
               for start_range, start_role in endpoints for end_range, end_role in endpoints):
            return True
        segments = [record for record in group if record.evidence.tool == 'pitch_statistics'
                    and record.interval is not None and any(q.role == 'pitch.mean' and _unit(q.unit)[2] == (1, 0, '')
                                                            for q in record.quantities)]
        if any(a.interval[1] <= b.interval[0] and a.interval[0] < a.interval[1] and b.interval[0] < b.interval[1]
               and (required is None or (a.interval[0] <= required[0] + .001 and b.interval[1] >= required[1] - .001
                                        and b.interval[0] - a.interval[1] <= .001))
               for a in segments for b in segments if a is not b):
            return True
    return False


def _check_prosody_line(state: Any, line: str, records: dict[str, Record]) -> None:
    cites = [f'E{x}' for x in _CITATION.findall(line)]
    targets = _line_targets(state, line, records)
    whole_ranges = _whole_ranges(state, records)
    for clause in re.split(r'[，,；;。！？!?]|(?:但|然而|不过)', line):
        claims = list(_PROSODY.finditer(clause))
        if not claims:
            continue
        for claim in claims:
            if re.fullmatch(r'上升|下降|升高|降低|rising|falling', claim[0], re.I) and not re.search(
                    r'音高|基频|语调|音调|声调|\bF0\b|pitch|intonation|tone', clause, re.I):
                continue
            if _INABILITY.search(clause[max(0, claim.start() - 45):claim.start()]):
                continue
            # Explicitly attributed conceptual explanations are handled by caller.
            applicable = [records[eid] for eid in cites if eid in records and
                          (not targets or records[eid].target in targets)]
            directional = bool(re.search(r'上升|下降|升高|降低|升调|降调|rising|falling', claim[0], re.I))
            if not _trajectory(applicable, directional, whole_ranges):
                _block(state, 'report.prosody_untraced',
                       '具体录音的音调/走向结论缺同目标且有定义值的走向引证；补分段基频、起终点或适用斜率，或明确不能判断。')


def _dim_operation(left: tuple[int, int, str], right: tuple[int, int, str], divide: bool = False) -> tuple[int, int, str]:
    if left[2] and right[2] and left[2] != right[2]:
        raise CalcUnavailable('calc输入单位不相容。')
    if divide:
        named = '' if left[2] == right[2] else (left[2] if not right[2] else f'{left[2]}/{right[2]}')
    else:
        named = f'{left[2]}*{right[2]}' if left[2] and right[2] else (left[2] or right[2])
    return (left[0] - right[0], left[1] - right[1], named) if divide else (left[0] + right[0], left[1] + right[1], named)


def _calculate(match: re.Match[str], records: dict[str, Record]) -> str:
    expression, requested_unit = match[1].strip(), match[2].strip()
    all_quantities = {q.ref: q for record in records.values() for q in record.quantities}
    used: dict[str, Quantity] = {}

    def replace(reference: re.Match[str]) -> str:
        ref = reference[0]
        if ref not in all_quantities:
            raise CalcUnavailable(f'calc输入{ref}不存在或未定义。')
        name = ref.replace('.', '_')
        used[name] = all_quantities[ref]
        return name

    if len(expression) > 300:
        raise CalcUnavailable('calc算式过长。')
    parsed_expression = _REF.sub(replace, expression)
    if not used:
        raise CalcUnavailable('calc必须引用真实证据量，不能只写常数。')
    try:
        tree = ast.parse(parsed_expression, mode='eval')
    except (SyntaxError, ValueError) as exc:
        raise CalcUnavailable('calc只接受证据量与四则算式。') from exc
    if len(list(ast.walk(tree))) > 80:
        raise CalcUnavailable('calc算式过长。')

    def visit(node: ast.AST) -> tuple[float, tuple[int, int, str]]:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Name) and node.id in used:
            quantity = used[node.id]
            _, scale, dimension = _unit(quantity.unit)
            return quantity.value * scale, dimension
        if isinstance(node, ast.Constant) and type(node.value) in {int, float} and node.value in {0, 1, 2, 10, 100, 1000}:
            return float(node.value), (0, 0, '')
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value, dimension = visit(node.operand)
            return (-value if isinstance(node.op, ast.USub) else value), dimension
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, ld = visit(node.left)
            right, rd = visit(node.right)
            if isinstance(node.op, (ast.Add, ast.Sub)):
                if ld != rd:
                    raise CalcUnavailable('calc加减输入单位不相容。')
                return (left + right if isinstance(node.op, ast.Add) else left - right), ld
            if isinstance(node.op, ast.Div):
                if right == 0:
                    raise CalcUnavailable('calc不能除以零。')
                return left / right, _dim_operation(ld, rd, True)
            return left * right, _dim_operation(ld, rd)
        raise CalcUnavailable('calc只接受已有证据量、换算/平均用常数与四则运算。')

    value, dimension = visit(tree)
    unit, scale, expected_dimension = _unit(requested_unit)
    if expected_dimension != dimension or not math.isfinite(value):
        raise CalcUnavailable('calc输出单位与输入/算式维度不符。')
    # A dimensionless result cannot be assigned an invented, unknown unit.
    if requested_unit and not _UNIT.fullmatch(requested_unit):
        raise CalcUnavailable('calc输出单位不受支持。')
    value /= scale
    substituted = _REF.sub(lambda r: f'({all_quantities[r[0]].text} {all_quantities[r[0]].unit})', expression)
    citations = ' '.join(f'[{eid}]' for eid in dict.fromkeys(q.evidence for q in used.values()))
    return f'{substituted} = {value:.6g} {unit} {citations}'.strip()


def _strip_unknown_citations(state: Any, text: str, records: dict[str, Record]) -> str:
    """清掉不存在的证据编号（``[E99]``），只计数不阻断：编号写错不等于数字是编的。"""

    def replace(match: re.Match[str]) -> str:
        if f'E{match.group(1)}' in records:
            return match[0]
        note_guard(state, 'repair', 'report.citation_unknown')
        return ''

    return _CITATION.sub(replace, text)


def _fill_citations(state: Any, text: str, records: dict[str, Record]) -> str:
    """给「有数字但没写引证」的行补上引证。

    引证是守卫自己的记账方式：模型只要数字对得上，守卫就负责把它落在哪条证据上写进
    正文（2026-10-06：因为漏写 ``[E1]`` 而拒整份报告，就是「逐行引证」这条提示词被
    硬化成闸门的后果）。数字对不上的行不补，交给验证阶段按原有规则拦。
    """

    out: list[str] = []
    in_general = False
    for line in text.splitlines():
        heading = re.match(r'^\s*#{1,6}\s', line)
        if heading:
            in_general = bool(_GENERAL.search(line))
        # 标题/一般知识/建议行不补引证：前者补了会改变标题文本，后两者的数字本来就不是
        # 本次测量。数字真编了，验证阶段照样拦。
        if (heading or _CITATION.search(line) or not _NUMBER.search(line) or in_general
                or _ADVICE.search(line) or _general(line, in_general, records)):
            out.append(line)
            continue
        sources, failure = _numeric_claim_sources(state, line, records)
        if failure or not sources:
            out.append(line)
            continue
        out.append(line + ' ' + ' '.join(f'[{eid}]' for eid in sources))
        note_guard(state, 'repair', 'report.citation_filled')
    return '\n'.join(out)


def _validate_text(state: Any, text: str, records: dict[str, Record]) -> str:
    replacements: list[str] = []

    if '\ue000' in text or '\ue001' in text:
        # 模型不可能自己产出这两个内部标记；清掉继续，不拿它中断报告。
        text = text.replace('\ue000', '').replace('\ue001', '')
        note_guard(state, 'repair', 'report.internal_marker')
    text = _strip_unknown_citations(state, text, records)
    text = _fill_citations(state, text, records)

    def calculate(match: re.Match[str]) -> str:
        line_start = text.rfind('\n', 0, match.start()) + 1
        line_end = text.find('\n', match.end())
        source_line = text[line_start:line_end if line_end >= 0 else len(text)]
        targets = _line_targets(state, source_line, records)
        for reference in _REF.findall(match[1]):
            record = records.get(reference[0])
            if record and targets and record.target not in targets:
                _block(state, 'report.calc_other_target',
                       'calc引用了其他对象的量；须注明实际对象，不能冒充目标录音。')
        claim_role = _role(text[line_start:match.start()])
        category = claim_role.split('.')[0]
        if category in {'pitch', 'formant', 'intensity', 'vot'}:
            quantities = {q.ref: q for record in records.values() for q in record.quantities}
            for reference in _REF.findall(match[1]):
                q = quantities.get(f'{reference[0]}.q{reference[1]}')
                if q and not q.role.startswith('range.') and q.role.split('.')[0] != category:
                    _block(state, 'report.calc_quantity_mismatch',
                           'calc输入量名与声称的测量不相符。')
        try:
            rendered = _calculate(match, records)
        except CalcUnavailable:
            # 算不出来只说明这一处推导没核对，不说明报告在编造测量：标注即可。
            note_guard(state, 'repair', 'report.calc_unverified')
            return UNVERIFIED_CALC
        replacements.append(rendered)
        # Internal token contains no numbers and is never accepted from model text.
        return '\ue000' + chr(0xE100 + len(replacements) - 1) + '\ue001'

    masked = _CALC.sub(calculate, text)
    if '{{calc:' in masked:
        # 语法残缺、_CALC 没匹配上的占位式：同样只标注，不阻断。
        note_guard(state, 'repair', 'report.calc_malformed')
        masked = re.sub(r'\{\{calc:[^{}]*\}\}', UNVERIFIED_CALC, masked)
        if '{{calc:' in masked:
            masked = masked.replace('{{calc:', UNVERIFIED_CALC)
    in_general = False
    for line in masked.splitlines():
        if re.match(r'^\s*#{1,6}\s', line):
            in_general = bool(_GENERAL.search(line))
        if _general(line, in_general, records):
            continue
        # Suggested future parameters/counts are not claims of measurements.
        if _ADVICE.search(line) and not _SPECIFIC.search(line) and not _CITATION.search(line):
            _check_prosody_line(state, line, records)
            continue
        # Calculation citations remain visible to prosody validation, while its
        # deterministic numbers bypass a second check against raw measurements.
        evidence_line = line
        for index, rendered in enumerate(replacements):
            token = '\ue000' + chr(0xE100 + index) + '\ue001'
            evidence_line = evidence_line.replace(token, ' '.join(m[0] for m in _CITATION.finditer(rendered)))
        _check_numeric_line(state, evidence_line, records)
        _check_prosody_line(state, evidence_line, records)
    for index, rendered in enumerate(replacements):
        masked = masked.replace('\ue000' + chr(0xE100 + index) + '\ue001', rendered)
    return masked


def validate_report(state: Any, report: Any) -> Any:
    """Return a report with deterministic calculations, or request SDK retry.

    This works with AnalysisReport without importing cloud_agent (and creating
    a cycle). Coverage explanations share the report boundary; user delivery
    labels are identifiers and are not reinterpreted as measurement claims.
    """
    records = _records(state)
    analysis = _validate_text(state, report.analysis, records)
    coverage = []
    for entry in report.coverage:
        explanation = _validate_text(state, entry.explanation, records)
        coverage.append(entry.model_copy(update={'explanation': explanation})
                        if hasattr(entry, 'model_copy') else entry)
    if hasattr(report, 'model_copy'):
        return report.model_copy(update={'analysis': analysis, 'coverage': coverage})
    report.analysis = analysis
    return report
