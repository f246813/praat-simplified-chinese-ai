"""Single-cloud staircase using Pydantic Graph and Pydantic AI.

The SDK owns tool-message pairing and multimodal encoding. The application owns
evidence, side-effect safety, branch exits and budgets shared across all modes.
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
import threading
import os
import time
from dataclasses import asdict
from typing import Literal
from types import SimpleNamespace

os.environ.setdefault('PYDANTIC_AI_NO_BANNER', '1')
from pydantic import BaseModel, Field
from pydantic_ai import Agent, BinaryContent, ModelRetry, PromptedOutput, Tool
from pydantic_ai.capabilities import Hooks
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart, ModelRequest, SystemPromptPart, RetryPromptPart
from pydantic_ai.usage import RunUsage, UsageLimits
from pydantic_graph import GraphBuilder, StepContext

from . import model_capabilities as caps, qwen, tools
from . import delivery
from .escape_policy import AnalysisState, BranchExit, Evidence, note_guard
from .dialogue_policy import dialogue_kind, effective_thinking_level, direct_measurement, reasoning_reserve
from .cloud_runtime import CloudRuntime
from .tool_guards import ToolGuards
from .report_guards import (mask_rejected_numbers, rejected_values, report_context_data,
                            report_guard_instructions, validate_report)
from .session_context import PhaseContext, native_history, evidence_projection
from . import cloud_metrics, skill_registry


class Coverage(BaseModel):
    item: str
    status: Literal['complete', 'partial', 'missing']
    explanation: str = Field(min_length=8)
    missing_evidence: list[Literal['audio', 'measurement', 'reference']] = Field(default_factory=list)


class AnalysisReport(BaseModel):
    analysis: str = Field(min_length=30, description='解释原始目标的中文 Markdown 报告，不能仅有统计表')
    coverage: list[Coverage]


REPORT_INSTRUCTIONS = (
    '\n独立报告，无执行工具。逐项解释 original_goal，给出依据、限制、下一步，不能仅有统计表。'
    'coverage.item 原样对应 deliveries；缺口列 audio/measurement/reference。'
    'audio_observations 是此前模型定性观察，注明原模型和材料来源，不是专业测量。'
    'audio_input=false 未听本轮录音；无原音频或此前观察不判断具体录音缺陷。')

#: 选段定位必须是报告的第一节（2026-10-04 实测：报告把含「た」爆破点的选段说成
#: 「词首清辅音 /a/ 之前」，另一次直接断言「目标音素是 /a/」——而它对选段位置的唯一
#: 输入是对象名里那个词）。报告阶段没有工具，所以位置和音素身份要么算出来
#: （占比 + 该词的音素序列），要么说清缺对齐/标注。写成必写一节，是因为只写「要说明
#: 位置时必须先算」时，报告仍会跳过这一步直接谈音素（2026-10-04 23:51 那次就是这么错的）。
#: 只在真会谈到选段的请求上追加：提示词预算很紧，4096 上下文的续写预检只有十几
#: token 余量（test_general_continue_preflight_matches_actual_dialogue_context）。
_PLACEMENT_TOPICS = re.compile(
    r'标准音|对比|比较|纠音|发音|练习|音素|音节|位置|语调|口音|改进|选段|第几|选中|这段|录音|vot')

#: 谈音调类型/升降/「语调平淡」之前必须先量音高走向（2026-10-04 实测：报告只拿全段
#: 平均基频 81.6 Hz 就断言「あなた」是平板型，并据此给出「あ低な高」的练习；同一段的
#: 更早一次（改前端前）量过前半段 84.98 / 后半段 79.06，结论正好相反）。规划阶段先要求
#: 把走向测出来，报告阶段才引用得到；两段都按目标条件追加，不占对话预算。
_PROSODY_TOPICS = re.compile(r'语调|音调|重音|アクセント|accent|标准音|对比|比较|发音|练习', re.I)

#: 关掉思考的寒暄/能力介绍走单次快速回复：只给正文这么多（推理另算）。
DIALOGUE_FAST_TOKENS = 512
#: 正文额度的地板：续写或降档重试时再低就没有意义了。
OUTPUT_REQUEST_FLOOR = 256


class OutputTruncated(BranchExit):
    """模型输出被长度上限截断（``finish_reason='length'``）。

    消息文本与旧行为一致（``模型输出未完整结束：length``），分析路径照旧按失败收尾；
    流式对话路径会先尝试续写，最差也要把已经流出的正文留下来。
    """

    def __init__(self, reason: str = 'length'):
        super().__init__('模型输出未完整结束：' + reason)
        self.finish_reason = reason


#: 报告上下文里最多带几条失败/未执行的尝试。
_MAX_BLOCKED_ATTEMPTS = 6


class OutputLimitRejected(Exception):
    """服务端拒绝了这次请求的输出上限（``max_tokens``）。

    正文/推理额度已经按服务端能接受的范围降过；由 :meth:`CloudSession.drive` 重新开一轮
    重试一次——pydantic-ai 的 ``node.stream()`` 一个节点只能进一次，原地重试会直接断言失败。
    """


class PendingRequestRetry(Exception):
    """Resume the saved pending request in a fresh SDK run, without new input."""
    def __init__(self, logical_request):
        self.logical_request = logical_request


def output_limit_from_error(detail: str):
    """从服务端的报错里读出它允许的输出上限（读不出来返回 None）。

    各家的说法不一样（``supports at most 8192`` / ``Range of max_tokens should be [1, 8192]``
    / ``the max value is 8192``），所以按常见句式依次试；读不出来时调用方只能保守降额。
    """

    for pattern in (r'at most\s+(\d{2,7})', r'\[\s*\d+\s*,\s*(\d{2,7})\s*\]',
                    r'max(?:imum)?[^0-9]{0,24}?(\d{2,7})', r'最多\s*(\d{2,7})',
                    r'上限[^0-9]{0,12}(\d{2,7})'):
        match = re.search(pattern, detail or '', re.I)
        if match:
            value = int(match.group(1))
            if OUTPUT_REQUEST_FLOOR <= value <= 1_000_000:
                return value
    return None


def blocked_attempts(state, limit: int = _MAX_BLOCKED_ATTEMPTS):
    """实际没成的调用（失败、状态不明、未执行），去重后的简短记录。

    报告不能只看 ``missing_reason``：那里只放得下最后一条失败原因，而真正的原因
    （例如 ``Message.txt`` 写不进去）常常只留在更早的一条尝试里。2026-10-02 的 VOT
    请求就是这样：报告看不到投递失败，于是把「测不出来」解释成了「模型不支持音频」。
    """

    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for attempt in state.attempts:
        status = str(attempt.get('status') or '')
        reason = str(attempt.get('reason') or '').strip()
        if status not in {'failed', 'unknown', 'not_executed'} or not reason:
            continue
        if status == 'not_executed' and reason.startswith('复用成功测量'):
            continue
        key = (str(attempt.get('tool') or ''), status, reason)
        if key in seen:
            continue
        seen.add(key)
        rows.append({'tool':attempt.get('tool'), 'status':status, 'reason':reason[:400]})
    return rows[-limit:]


def planner_system(config, goal: str = '') -> str:
    return qwen.planner_instructions(config.qwen) + skill_registry.catalog('planner')


def dialogue_instructions(config):
    return qwen.analysis_instructions(config.qwen) + '\n自然回答用户，按问题需要控制长度。寒暄和能力介绍请简短。不能声称已执行测量或听过录音。'


def report_instructions(config, state) -> str:
    """固定报告规则和技能目录；条件指导由任务技能追加到用户历史尾部。"""

    text = qwen.analysis_instructions(config.qwen) + REPORT_INSTRUCTIONS
    # Guard conditional is fixed on the wire; task guidance goes at the tail.
    text += ('\n测量数值逐行引[E编号]，同对象/范围/量名/单位。quantity_refs第N项=E编号.qN；'
             '推导用{{calc:E1.q1/E2.q1*100|%}}。音调须有走向证据，平均值不足；无测量不填录音数值。')
    text += '\n文件名使用时注明“根据文件名推测”，用户说明优先；不作测量/词典/音频证据。'
    text += skill_registry.catalog('report')
    return text


#: 用户自己说过、会影响判断的说话人/录音条件。只做「原话搬运」，不改写、不推断——
#: 2026-10-04 实测：用户在第三轮才说「我是成年男性」，报告在前一轮只能列「若为男性…若为女性…」；
#: 而历史在压缩/老窗口那条路上不一定进得了报告，所以单独挑出来随报告上下文一起给。
_SELF_DESCRIPTION = re.compile(
    r'我是|本人|成年|男性|女性|男生|女生|母语|方言|普通话|口音|岁|录音|麦克风|手机|耳机')
#: modern_app 会把历史专业证据当一条 user 消息塞进对话上下文，那不是用户自述。
_NOT_USER_WORDS = ('历史专业证据与投递事实', '不能当作本轮新测量')


def user_facts(state, limit: int = 3) -> list[str]:
    """用户自述里可能影响判断的那几句（原话，最多 ``limit`` 条）。"""

    rows: list[str] = []
    for item in state.dialogue_context:
        if str(item.get('role')) != 'user':
            continue
        text = str(item.get('content') or '').strip()
        if not text or any(marker in text for marker in _NOT_USER_WORDS):
            continue
        if _SELF_DESCRIPTION.search(text):
            rows.append(text[:120])
    return rows[-limit:]


def report_context(state, *, audio=False, preserve=False):
    rows = tools.parse_object_context(state.context_text)
    target = [{'id':row.id, 'class':row.class_name, 'name':row.name, 'selection':row.selection}
              for row in rows if row.selected][:20] if rows else state.context_text[:1200]
    context = {
        'original_goal':state.goal, 'deliveries':state.deliveries, 'direction':state.direction,
        'target_material':target, 'evidence':[asdict(e) for e in state.evidence],
        'missing_reason':state.reason, 'paused_branches':dict(state.failures), 'audio_input':audio,
        'blocked_attempts':blocked_attempts(state),
        'previous_report':state.previous_report[:4000],
        'previous_coverage':[{**item, 'explanation':item['explanation'][:400]} for item in state.previous_coverage],
        'audio_observations':[{**item, 'analysis':item['analysis'][:2000]} for item in state.audio_observations[-3:]],
        'visible_dialogue':[dict(item) for item in state.dialogue_context] if state.mode == 'L4' else [],
    }
    context.update(report_context_data(state))
    if state.audio_observations and state.previous_report == state.audio_observations[-1]['analysis']:
        context['previous_report'] = ''
        context['previous_report_source'] = 'audio_observations 最后一项（同一报告，避免重复）'
    facts = user_facts(state)
    if facts:   # 没有自述时不加这个键：报告提示的预算很紧，空字段也是开销。
        context['user_facts'] = facts
    if preserve:
        context.update(
            target_material=[{'id':row.id, 'class':row.class_name, 'name':row.name, 'selection':row.selection}
                             for row in rows if row.selected] if rows else state.context_text,
            previous_report=state.previous_report,
            previous_coverage=copy.deepcopy(state.previous_coverage),
            audio_observations=copy.deepcopy(state.audio_observations),
            visible_dialogue=copy.deepcopy(state.dialogue_context))
        return context
    for evidence in context['evidence']:
        evidence['rows'] = [row[:1200] for row in evidence['rows'][:40]]
    return context


def compact_report_context(context, token_limit, *, preserve=False):
    """Legacy excerpts only; modern requests retain context and fail preflight if full."""
    if preserve:
        return json.dumps(context, ensure_ascii=False)
    while qwen.estimate_tokens(json.dumps(context, ensure_ascii=False)) > token_limit:
        if len(context['evidence']) > 1:
            context['evidence'].pop()
        else:
            excerpts = [(context, 'previous_report', 128), (context, 'missing_reason', 128)]
            excerpts += [(item, 'reason', 100) for item in context['blocked_attempts']]
            excerpts += [(item, 'analysis', 128) for item in context['audio_observations']]
            excerpts += [(item, 'explanation', 64) for item in context['previous_coverage']]
            excerpts += [(item, 'content', 100) for item in context['visible_dialogue']]
            reducible = [(owner, key, minimum) for owner, key, minimum in excerpts if len(owner[key]) > minimum]
            if reducible:
                owner, key, minimum = max(reducible, key=lambda item:len(item[0][item[1]]))
                owner[key] = owner[key][:max(minimum, len(owner[key]) // 2)]
            elif len(context['audio_observations']) > 1:
                context['audio_observations'].pop(0)
            elif len(context['blocked_attempts']) > 1:
                context['blocked_attempts'].pop(0)
            elif context['evidence'] and len(context['evidence'][0]['rows']) > 1:
                context['evidence'][0]['rows'].pop()
            elif context['evidence'] and context['evidence'][0]['rows'] and len(context['evidence'][0]['rows'][0]) > 128:
                row = context['evidence'][0]['rows'][0]
                context['evidence'][0]['rows'][0] = row[:max(128, len(row) // 2)]
            else:
                break  # Original goal and provenance cannot be removed to fake fit.
        context['excerpt_note'] = '本请求只含上下文可容纳的摘录；完整记录仍保留，未提供部分不能推测'
        context.pop('evidence_ids', None)
        context.pop('quantity_refs', None)
        context.update(report_context_data(SimpleNamespace(evidence=[Evidence(**item) for item in context['evidence']])))
    return json.dumps(context, ensure_ascii=False)


def minimum_continuation_tokens(config, state, *, mode='', direction=''):
    candidate = state.continued(direction or '解释已有证据及剩余缺口', mode=mode)
    candidate.mode = candidate.continuation_mode
    modern = config.api.token_mode is not None
    prompt = compact_report_context(report_context(candidate, preserve=modern), 400, preserve=modern)
    instruction = report_instructions(config, candidate)
    schema = json.dumps(AnalysisReport.model_json_schema(), ensure_ascii=False)
    return qwen.estimate_tokens(prompt + instruction + schema) + 256


def entry_mode(goal: str, context_text: str, *, audio_requested: bool = False) -> str:
    if audio_requested:
        return 'L3'
    # Pure concept discussion must not require a running Praat or its snapshot.
    concept = re.search(r'(什么是|如何理解|原理|解释一下|练习方法|一般来说|理论|科普|你好|hello|谢谢)', goal, re.I)
    material = re.search(r'(选中|选区|录音|这个声音|当前|测量|读取|打开|删除|创建|保存|截取|分析.*(?:音|对象))', goal)
    if concept and not material:
        return 'L4'
    return 'L0' if tools.parse_object_context(context_text) else 'L4'


def wants_audio(goal: str) -> bool:
    return bool(re.search(r'(直接.*(?:听|音频|录音)|听(?:一下|一听|这)|原始(?:音频|录音)|听感)', goal))


#: 守卫没核上的数值，在保留的草稿里换成这个占位符：正文能留，没测过的数字不能当实测。
UNVERIFIED_NUMBER = '[未通过核对的数值]'
#: 没核上的内部推导占位式（``{{calc:…}}``）也不能原样漏给用户。
_CALC_PLACEHOLDER = re.compile(r'\{\{calc:[^{}]*\}\}')


def rescued_report(draft: str, detail: str, values=(), *, state=None) -> str:
    """守卫拒了报告时，保住模型已经写好的正文，遮掉没核上的数值，再挂一句原因。

    2026-10-06 实测：报告守卫（``report_guards``）连拒两次后，当时只有一次机会的
    重试预算（``retries={'output':1}``）直接耗尽，整份回答被 ``fallback_report()``
    换成「本轮仅交付阶段记录」——工具明明测到了数据，用户却什么都看不到。守卫的职责是
    「不许拿没测过的数字当结论」，不是「没有合格报告就不给回答」，所以有草稿就留草稿：
    被拒的那几个数值换成 :data:`UNVERIFIED_NUMBER`，其余正文和结论照旧，并在末尾说明
    为什么。没有草稿时返回空串，由调用方回退到阶段记录。
    """

    text = str(draft or '').strip()
    if not text:
        return ''
    text = mask_rejected_numbers(text, values, UNVERIFIED_NUMBER, state=state)
    reason = mask_rejected_numbers(' '.join(str(detail or '').split())[:400], values, UNVERIFIED_NUMBER)
    text += ('\n\n（这份回答没有通过自动数值核对：' + reason
             + '。上面保留的是模型已经写好的内容，其中没通过核对的数值已标成 '
             + UNVERIFIED_NUMBER + '；请按这条提示核对引用的数值和范围。）')
    return _CALC_PLACEHOLDER.sub('[未通过核对的推导式]', text)


#: 模型漏报某个交付项时补的说明。
COVERAGE_FILL_EXPLANATION = '模型没有逐项交代这一项；已保留现有证据与诊断，缺什么见缺口说明。'


def repair_coverage(deliveries, coverage):
    """把 coverage 修成与交付项一一对应。

    交付项状态是界面要展示给用户的东西，而"必须逐项原样对应 deliveries"原来是一条
    会拒整份报告的硬规则：模型漏一项、多一项、改一个字就丢掉整份回答（2026-10-06）。
    缺项补成 partial，多出来的条目丢掉，正文不动。
    """

    remaining = {}
    for item in coverage:
        remaining.setdefault(item.item, item)
    repaired = []
    for name in deliveries:
        repaired.append(remaining.pop(name, None)
                        or Coverage(item=name, status='partial', explanation=COVERAGE_FILL_EXPLANATION))
    return repaired


def create_model(config):
    from openai import AsyncOpenAI, DefaultAsyncHttpxClient
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    # The application owns the single transport retry and shared budget.
    # Keep SDK retries disabled so they cannot stack or replay tools invisibly.
    client = AsyncOpenAI(base_url=config.api.base_url.strip().rstrip('/'),
                         api_key=config.api.api_key or 'EMPTY', max_retries=0,
                         timeout=config.api.request_timeout_sec,
                         http_client=DefaultAsyncHttpxClient(event_hooks={
                             'request':[cloud_metrics.observe_request], 'response':[cloud_metrics.observe_response]}))
    from .cloud_stream import enable_stream_reuse
    enable_stream_reuse(client)
    preset = caps.audio_preset(config.api.base_url, config.api.model)
    profile = {'openai_chat_audio_input_encoding':'uri'} if preset.stream else None
    return OpenAIChatModel(config.api.model, provider=OpenAIProvider(openai_client=client), profile=profile)


def temporary_request_error(error):
    """Recognize typed transport causes preserved by Pydantic AI wrappers.

    An HTTP response decides permanence; prose such as 'timed out' alone does
    not. Follow explicit causes only, with a cycle guard.
    """
    from openai import APIConnectionError
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        status = getattr(error, 'status_code', None)
        if status is not None:
            return status in {408, 429, 500, 502, 503, 504}
        if isinstance(error, (TimeoutError, ConnectionError, APIConnectionError)):
            return True
        error = error.__cause__
    return False


class CloudSession:
    def __init__(self, config, state, execute_action, cancel, progress, model, schemas,
                 materials, prepare_audio, correct_audio, refresh_context=None):
        self.started = time.monotonic()
        self.config, self.state = config, state
        if not config.api.limit_tokens and config.api.token_mode is None:
            # Finite application memory bound, independent of disabled user limits.
            state.budget.context_tokens = 131072
        self.execute_action, self.cancel = execute_action, cancel
        self.progress = progress or (lambda _: None)
        self.owns_model = model is None
        self.model = model or create_model(config)
        self.schemas = schemas
        self.refresh_context = refresh_context
        self.original_object_ids = {row.id for row in tools.parse_object_context(state.context_text)}
        self.active_guard_key = self.active_proposal_signature = ''
        self.materials, self.prepare_audio, self.correct_audio = materials, prepare_audio, correct_audio
        # Pre-phase session compaction has already spent part of this task's
        # budget. Seed the SDK counter as well as the application counter.
        prior_timings = state.metrics.get('request_timings', [])
        self.usage = RunUsage(requests=state.requests,
                              input_tokens=sum(t.get('input_tokens_total') or 0 for t in prior_timings),
                              output_tokens=sum(t.get('output_tokens') or 0 for t in prior_timings))
        self.limits = UsageLimits(request_limit=state.budget.request_limit, tool_calls_limit=state.budget.tool_limit)
        # 云端把 reasoning token 计入 max_tokens（实测概念解释那一轮 2048 里 1435 是推理）：
        # 先按思考档位把推理额度写进预算，再定输出上限，正文才不会被推理挤掉。
        state.budget.reasoning_tokens = reasoning_reserve(config.api.thinking_level)
        self.body_target = max(OUTPUT_REQUEST_FLOOR, state.budget.response_tokens)
        self.output_cap = self.body_target + state.budget.reasoning_tokens
        self.settings = {'max_tokens':self.output_cap, 'temperature':config.api.plan_temperature,
                         'parallel_tool_calls':False}
        if config.api.base_url.rstrip('/') == 'https://generativelanguage.googleapis.com/v1beta/openai' and config.api.model.startswith('gemini-3'):
            self.settings.pop('temperature', None)
        self.set_thinking(config.api.thinking_level)
        self.stream = caps.audio_preset(config.api.base_url, config.api.model).stream
        self.tool_running = False
        self.received_text = False
        #: 服务端拒过这次的输出上限时记下降额后的额度（续写不再把它抬回去）。
        self.rejected_output_cap = None
        state.metrics.setdefault('first_text_seconds', None)
        state.metrics.setdefault('request_timings', [])
        state.metrics.setdefault('effective_thinking_level', config.api.thinking_level)
        self.response_ids = set()
        self.phase = 'planner'
        if config.api.token_mode is not None:
            self.state.budget.reasoning_tokens = 0  # New reply cap is total output, not body + hidden reserve.
            self.body_target = min(self.body_target, config.api.plan_max_tokens)
            self.output_cap = config.api.plan_max_tokens
            self.apply_modern_settings()

    def apply_modern_settings(self, input_cost=0):
        from .modern_budget import model_settings
        for key in ('max_tokens', 'temperature', 'top_p', 'presence_penalty'):
            self.settings.pop(key, None)
        self.settings.update(model_settings(self.config.api, sdk=True, input_cost=input_cost))

    def set_thinking(self, level):
        from .config import QwenConfig
        fields = qwen.thinking_request_fields(QwenConfig(provider='api', base_url=self.config.api.base_url,
            model=self.config.api.model, thinking_level=level))
        for key, value in fields.items():
            if key == 'reasoning_effort':
                # Explicit force must not inherit a previous silent downgrade.
                from .dialogue_policy import force_high
                if force_high(self.config.api) or key not in qwen.rejected_thinking_fields(self.config.api.base_url):
                    self.settings['openai_reasoning_effort'] = value
            else:
                self.settings.setdefault('extra_body', {})[key] = value

    def body_tokens(self) -> int:
        """这次请求要交付的可见正文额度（推理不算在里面）。"""

        return self.body_target

    def set_body_tokens(self, limit: int) -> None:
        """把正文额度钉在 ``min(预算, limit)`` 上；推理预留照旧加回去。

        用户设置与预算只决定**正文**；推理额度由思考档位决定、始终额外留出，
        否则 reasoning 会把正文挤到长度上限（``模型输出未完整结束：length``）。
        """
        if self.config.api.token_mode is not None:
            self.state.budget.reasoning_tokens = 0
            self.body_target = min(int(limit), self.config.api.plan_max_tokens)
            self.output_cap = self.config.api.plan_max_tokens
            self.apply_modern_settings()
            return

        self.body_target = max(OUTPUT_REQUEST_FLOOR, min(self.state.budget.response_tokens, int(limit)))
        self.output_cap = self.body_target + self.state.budget.reasoning_tokens
        self.settings['max_tokens'] = self.output_cap

    def fit_output(self, input_cost: int) -> None:
        """上下文装不下「正文＋推理」时先缩推理，别把整轮判成失败。

        正文是必须交付的（放不下时由调用方的上下文校验明确报错）；推理只是让回答
        不撞长度上限的手段，所以剩余空间不够时按剩余空间给。
        """
        if self.config.api.token_mode is not None:
            self.apply_modern_settings(input_cost)
            return
        room = self.state.budget.context_tokens - input_cost - 256
        self.settings['max_tokens'] = min(self.output_cap, max(self.body_target, room))

    def check(self):
        if self.cancel.is_set():
            raise asyncio.CancelledError()

    def reject_output_limit(self, detail):
        """服务端拒绝了这次的输出上限：先让掉推理额度，再考虑正文。

        旧版本只发正文（正文 ≤ 旧上限时服务端是接受的），所以降额必须让「正文 + 推理」
        一起落到服务端能接受的范围：只砍正文时推理额度还在，总数可能永远超上限，重试必然
        再失败（典型：high=8192 预留 + 正文 2048 = 10240 > 百炼/DeepSeek 的 8192）。
        """

        limit = output_limit_from_error(detail)
        if limit:
            # 服务端点名了上限：正文优先，推理只吃上限内的剩余空间。
            self.state.budget.reasoning_tokens = max(0, min(self.state.budget.reasoning_tokens,
                                                            limit - self.body_target))
            self.set_body_tokens(min(self.body_target, limit))
        elif self.state.budget.reasoning_tokens:
            # 没说上限：先让掉这次新增的推理额度，正文维持原样（= 旧版本的请求形状）。
            self.state.budget.reasoning_tokens = 0
            self.set_body_tokens(self.body_target)
        else:
            # 推理本来就是 0（旧版本也会被拒）：只能砍正文，地板 OUTPUT_REQUEST_FLOOR。
            self.set_body_tokens(max(OUTPUT_REQUEST_FLOOR, self.body_target // 2))
        self.rejected_output_cap = self.settings.get('max_tokens')

    def event(self, mode, reason):
        self.state.event(mode, reason)
        self.progress(mode + '：' + reason)

    def request_cost(self, messages, *, schema=False, measured=True):
        # Port of Pi compaction.ts estimateTokens @28dcce2 (MIT): count model
        # content/tool arguments, not SDK timestamps, run IDs or usage metadata.
        # Retain AIPraat's CJK heuristic instead of Pi's chars/4 constant.
        content = []
        has_audio = False
        for message in messages:
            for part in message.parts:
                if isinstance(part, ToolCallPart):
                    content.append(part.tool_name + json.dumps(part.args, ensure_ascii=False))
                else:
                    value = getattr(part, 'content', '')
                    if isinstance(value, (list, tuple)):
                        has_audio |= any(isinstance(v, BinaryContent) for v in value)
                        value = '\n'.join(v for v in value if isinstance(v, str))
                    content.append(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
        cost = qwen.estimate_tokens('\n'.join(content)) + 8 * len(messages)
        if has_audio:
            # Conservative audio estimate; actual usage is recorded after requests.
            import wave
            with wave.open(str(self.materials.audio_path), 'rb') as reader:
                cost += int(reader.getnframes() / reader.getframerate() * 50)
        if schema:
            cost += qwen.estimate_tokens(json.dumps(self.schemas, ensure_ascii=False))
        # Pi's context estimate: observed total input + the appended tail. Cached
        # input remains part of the window. No measurement/evidence is trimmed.
        floor = getattr(self.state.phase_contexts.get(self.phase), 'calibration_start', 0)
        for index in range(len(messages)-1, floor-1, -1) if measured else ():
            message = messages[index]
            if isinstance(message, ModelResponse) and message.usage.input_tokens:
                tail = []
                for entry in messages[index:]:
                    for part in entry.parts:
                        value = getattr(part, 'content', None)
                        if isinstance(part, ToolCallPart):
                            value = part.tool_name + json.dumps(part.args, ensure_ascii=False)
                        if isinstance(value, (list, tuple)):
                            value = '\n'.join(v for v in value if isinstance(v, str))
                        if value is not None:
                            tail.append(value if isinstance(value, str) else str(value))
                measured = message.usage.input_tokens + qwen.estimate_tokens('\n'.join(tail))
                cost = max(cost, measured)
                break
        return cost

    async def drive(self, agent, prompt, *, tool_phase=False, on_text=None):
        """跑一次模型对话；服务端拒绝输出上限时整轮重启一次（同一个 agent、新的 run）。

        pydantic-ai 的 ``node.stream()`` 一个节点只能进一次，所以不能在原地 ``continue``
        重试：必须重新开 run，否则会变成 ``stream() should only be called once per node``。
        """

        await self.compact_phase(prompt, tool_phase=tool_phase)
        try:
            return await self._drive(agent, prompt, tool_phase=tool_phase, on_text=on_text,
                                     allow_output_retry=True)
        except OutputLimitRejected:
            self.progress('服务端不接受这个输出上限，按正文 ' + str(self.body_tokens()) + ' token 重试一次')
            return await self._drive(agent, None, tool_phase=tool_phase, on_text=on_text,
                                     allow_output_retry=False)

    async def compact_phase(self, prompt, *, tool_phase=False):
        """One budgeted summary at a phase boundary; execution authority is untouched."""
        if self.phase == 'summary':
            return
        context = self.state.phase_contexts[self.phase]
        cost = self.request_cost([*context.messages, ModelRequest(parts=[UserPromptPart(prompt)])], schema=tool_phase)
        if cost + self.state.budget.reserve < self.state.budget.context_tokens * .85:
            return
        # Keep the two latest complete user-started transactions. A tool return
        # never becomes a cut point, following Pi findValidCutPoints.
        starts = [i for i, m in enumerate(context.messages) if isinstance(m, ModelRequest)
                  and any(isinstance(p, UserPromptPart) for p in m.parts)
                  and not any(isinstance(p, SystemPromptPart) for p in m.parts)]
        if len(starts) < 3 or self.state.requests >= self.state.budget.request_limit - 2:
            return  # Existing request preflight/escape remains the authority.
        cut = starts[-2]
        older = copy.deepcopy(context.messages[:cut])
        if any(isinstance(p, UserPromptPart) and not isinstance(p.content, str) for m in older for p in m.parts):
            return  # Audio is task-local and is not summarized into fake observations.
        previous_phase = self.phase
        summary_context = PhaseContext(messages=[ModelRequest(parts=[p for p in m.parts if not isinstance(p, SystemPromptPart)])
                                                if isinstance(m, ModelRequest) else m for m in older], epoch=context.epoch)
        summary_context.messages = [m for m in summary_context.messages if m.parts]
        instruction = '忠实压缩历史。保留原目标、技能约束、范围、来源、已投递/未知事实。不得添加数字或把推测变成测量。完整证据由应用另存。'
        summary_context.configure(instruction)
        self.state.phase_contexts['summary'] = summary_context
        self.phase = 'summary'
        summary_agent = Agent(self.model, output_type=str, retries=0, name='history_summary')
        try:
            summary = await self._drive(summary_agent, '总结以上较早历史，不改变执行状态。', allow_output_retry=False)
        finally:
            self.phase = previous_phase
        candidate = [ModelRequest(parts=[SystemPromptPart(next(p.content for m in context.messages for p in m.parts
                      if isinstance(p, SystemPromptPart))), UserPromptPart('较早历史摘要（非测量证据）：\n' + summary)]),
                     *context.messages[cut:]]
        if self.request_cost([*candidate, ModelRequest(parts=[UserPromptPart(prompt)])], schema=tool_phase, measured=False) >= cost:
            raise BranchExit('阶段摘要未降低上下文开销；原消息与证据保留')
        context.archives.append(context.messages)
        context.messages = candidate
        context.calibration_start = len(candidate)
        context.epoch += 1
        self.progress('已压缩较早阶段历史；完整事务与原测量证据保留，沿用本轮预算')

    async def _drive(self, agent, prompt, *, tool_phase=False, on_text=None, allow_output_retry=True):
        pending_attempt, logical_request = 0, None
        while True:
            try:
                return await self._drive_run(agent, prompt, tool_phase=tool_phase, on_text=on_text,
                                             allow_output_retry=allow_output_retry,
                                             pending_attempt=pending_attempt, logical_request=logical_request)
            except PendingRequestRetry as retry:
                # Public message_history resumes the pending User/ToolReturn/
                # RetryPrompt request. Re-entering a node duplicates its prompt
                # and streaming nodes are single-use in Pydantic AI 2.52.0.
                prompt, pending_attempt, logical_request = None, 1, retry.logical_request

    async def _drive_run(self, agent, prompt, *, tool_phase=False, on_text=None, allow_output_retry=True,
                         pending_attempt=0, logical_request=None):
        context = self.state.phase_contexts[self.phase]
        async with agent.iter(prompt, message_history=context.messages, model_settings=self.settings, usage=self.usage,
                              usage_limits=self.limits) as run:
            node = run.next_node
            while not Agent.is_end_node(node):
                self.check()
                if Agent.is_model_request_node(node):
                    messages = run.all_messages()
                    if not any(message is node.request for message in messages):
                        messages = [*messages, node.request]
                    # Snapshot the pending native request, including validator
                    # RetryPromptPart. A new SDK run can then resume it without
                    # appending the original goal/materials a second time.
                    context.messages = copy.deepcopy(messages)
                    input_cost = self.request_cost(messages, schema=tool_phase)
                    if self.phase == 'report':
                        input_cost += qwen.estimate_tokens(json.dumps(AnalysisReport.model_json_schema(), ensure_ascii=False))
                    if tool_phase and (self.state.budget.should_close(input_cost)
                                       or self.state.requests >= self.state.budget.request_limit - 3):
                        raise BranchExit('上下文余量或跨阶段请求预算达到收尾阈值')
                    if not tool_phase and input_cost + self.body_target + 256 > self.state.budget.context_tokens:
                        # 正文必须放得下，否则这轮没有可交付的内容；推理额度按剩余空间缩
                        # （见 fit_output），所以这里只校验正文，口径与 reserve 里的
                        # 「正文 + 推理」一致：先保正文，再尽量给推理留位置。
                        raise BranchExit('最小报告上下文与输出预留无法容纳，请缩小范围或增加上下文设置')
                    self.fit_output(input_cost)
                    if self.state.requests >= self.state.budget.request_limit:
                        raise BranchExit('本轮模型请求总预算已用完')
                    if tool_phase and not pending_attempt:
                        self.state.planning_rounds += 1
                    contains_audio = any(
                        isinstance(part, UserPromptPart) and isinstance(part.content, (list, tuple))
                        and any(isinstance(item, BinaryContent) for item in part.content)
                        for message in messages for part in message.parts)
                    for attempt in range(pending_attempt, 2):
                        self.check()
                        self.state.requests += 1
                        request_started = time.monotonic()
                        correction = any(isinstance(p, RetryPromptPart) for p in node.request.parts)
                        timing = {'request':self.state.requests, 'phase':self.phase, 'mode':self.state.mode,
                                  'retry':bool(attempt or correction or allow_output_retry is False), 'attempt':attempt+1,
                                  'logical_request':logical_request or str(getattr(node.request, 'run_id', '') or self.state.requests),
                                  'session_id':self.state.session_id, 'task_id':self.state.task_id,
                                  'context_epoch':context.epoch, 'reason':'tool_loop' if tool_phase else 'phase_reply'}
                        token = cloud_metrics.current_request.set(timing)
                        if contains_audio:
                            # A request attempt is a fact even if transport or output
                            # validation fails; server acceptance requires a response.
                            self.state.audio_sent = True
                            self.state.events.append({'mode':'L3', 'reason':'audio_request_attempt',
                                                      'request':self.state.requests})
                        try:
                            if on_text is not None:
                                async with node.stream(run.ctx) as stream:
                                    async for text in stream.stream_text(delta=True, debounce_by=0.03):
                                        self.check()
                                        if text:
                                            self.received_text = True
                                            timing.setdefault('first_text_seconds', time.monotonic()-request_started)
                                            if self.state.metrics['first_text_seconds'] is None:
                                                self.state.metrics['first_text_seconds'] = time.monotonic()-self.started
                                            on_text(text)
                            elif self.stream:
                                async with node.stream(run.ctx) as stream:
                                    async for _ in stream:
                                        self.check()
                            next_node = await run.next(node)
                            if contains_audio:
                                self.state.audio_received = True
                                self.state.events.append({'mode':'L3', 'reason':'audio_response_received',
                                                          'request':self.state.requests})
                            self.record_responses(run.all_messages())
                            context.messages = copy.deepcopy(run.all_messages())
                            if on_text is not None:
                                response = next((m for m in reversed(run.all_messages()) if isinstance(m, ModelResponse)), None)
                                if response is not None and response.finish_reason == 'length':
                                    # 只有带流式回调的对话路径走这里：截断可以续写。
                                    # 分析路径（execute/report 不传 on_text）本来就不进这个判断，
                                    # 它的截断由 SDK 的输出校验/上游报错体现——本次改动不动它。
                                    raise OutputTruncated(response.finish_reason)
                                if response is not None and response.finish_reason in {'content_filter', 'error'}:
                                    raise BranchExit('模型输出未完整结束：' + response.finish_reason)
                            timing['status'] = 'complete'
                            break
                        except Exception as error:
                            status = getattr(error, 'status_code', None)
                            detail = caps.safe_error(error, self.config.api.api_key)
                            rejected = status == 400 and any(field in detail for field in ('reasoning_effort', 'enable_thinking', 'thinking'))
                            temporary = temporary_request_error(error)
                            timing.update(status='failed', http_status=status, error_type=type(error).__name__)
                            from .dialogue_policy import force_high
                            output_rejected = status == 400 and any(
                                field in detail for field in ('max_tokens', 'max_completion_tokens', 'output length'))
                            # 工具阶段的 400 不重启：重开会把 planning_rounds 又加一次，用户明确
                            # 要求的对象操作随后会被「未授权追加对象操作」挡掉。对话/报告阶段没有
                            # 这个副作用，才允许重开一轮。
                            if (allow_output_retry and not tool_phase and attempt == 0 and output_rejected
                                    and not self.received_text and self.settings.get('max_tokens', 0) > OUTPUT_REQUEST_FLOOR):
                                self.reject_output_limit(detail)
                                raise OutputLimitRejected() from error
                            if (attempt == 0 and not self.received_text and self.state.requests < self.state.budget.request_limit
                                    and (temporary or (rejected and 'openai_reasoning_effort' in self.settings
                                                       and not force_high(self.config.api)))):
                                if rejected:
                                    self.settings.pop('openai_reasoning_effort', None)
                                    qwen.remember_rejected_thinking_field(self.config.api.base_url, 'reasoning_effort')
                                self.progress('模型请求失败，进行一次有限重试：' + detail)
                                raise PendingRequestRetry(timing['logical_request']) from error
                            raise
                        finally:
                            timing.setdefault('status', 'cancelled')
                            timing['elapsed_seconds'] = time.monotonic()-request_started
                            timing.update(cloud_metrics.normalize_usage(timing.pop('raw_usage', {}),
                                          provider_url=self.config.api.base_url))
                            cloud_metrics.current_request.reset(token)
                            self.state.metrics['request_timings'].append(timing)
                    pending_attempt, logical_request = 0, None
                    node = next_node
                else:
                    tools_node = Agent.is_call_tools_node(node)
                    node = await run.next(node)
                    if tools_node and not Agent.is_end_node(node):
                        context.messages = copy.deepcopy(run.all_messages())
                        if tool_phase:
                            self.state.finish_round()
            context.messages = copy.deepcopy(run.all_messages())
            context.complete = True
            return run.result.output

    def phase_context(self, phase, instruction):
        self.phase = phase
        context = self.state.phase_contexts.get(phase)
        if context is None:
            context = self.state.phase_context if phase == 'dialogue' else None
            context = context or PhaseContext(messages=native_history(self.state.dialogue_context),
                                              epoch=self.state.context_epoch)
            self.state.phase_contexts[phase] = context
        context.configure(instruction, self.config.api.model + self.config.api.base_url,
                          baseline=self.state.dialogue_context)
        skill_registry.load(context, phase, self.state) if phase in {'planner', 'report'} else None
        return context

    def record_responses(self, messages):
        for message in reversed(messages):
            if isinstance(message, ModelResponse):
                if id(message) in self.response_ids:
                    return
                self.response_ids.add(id(message))
                usage = message.usage
                event = {'mode':self.state.mode, 'reason':'model_response',
                         'finish_reason':message.finish_reason, 'usage':{
                             'input_tokens':usage.input_tokens, 'output_tokens':usage.output_tokens},
                         'tool_proposals':[{'tool':part.tool_name, 'arguments':part.args, 'call_id':part.tool_call_id}
                                           for part in message.parts if isinstance(part, ToolCallPart)]}
                if not self.state.events or self.state.events[-1] != event:
                    self.state.events.append(event)
                return

    def tool(self, schema):
        function = schema['function']
        name = function['name']

        async def invoke(**arguments):
            self.check()
            problem = name  # Bound original input/range, parameter text does not reset repairs.
            signature = Evidence(name, arguments, [], self.state.context_text).signature
            self.tool_running = True
            tool_started = time.monotonic()
            try:
                step = await asyncio.to_thread(self.execute_action, name, arguments, self.state.planning_rounds)
            except BaseException:
                self.tool_running = False
                raise
            finally:
                self.state.metrics['tool_seconds'] = self.state.metrics.get('tool_seconds', 0) + time.monotonic()-tool_started
            status = 'success' if step.ok else ('not_executed' if not step.script else 'failed')
            # 投递事实优先：'unknown' 只给「交出去但没等到完成」的那一种，
            # 'not_delivered'（根本没送出去）和 'blocked'（本轮已停止投递）都不是
            # 状态不明，不能把它们升级成永久停掉整轮。execution 为空（外部替身执行器、
            # 本地工具）时才退回按说明文字判断。
            declared = getattr(step, 'execution', '')
            if not step.ok and declared == delivery.EXECUTION_BLOCKED:
                status = 'not_executed'
            unknown = not step.ok and (
                declared == delivery.EXECUTION_UNKNOWN
                or (not declared and any(s in step.observation for s in
                                         ('超时', '状态不明', '没有收到完成', '仍在执行', '不再等'))))
            blocked = not step.ok and declared == delivery.EXECUTION_BLOCKED
            if unknown:
                status = 'unknown'
            self.state.attempts.append({'tool':name, 'arguments':arguments, 'signature':signature,
                                        'guard_key':self.active_guard_key,
                                        'proposal_signature':self.active_proposal_signature,
                                        'status':status, 'execution':declared, 'reason':step.observation,
                                        'script':step.script, 'rows':step.results})
            self.progress(step.observation)
            if blocked:
                # 本轮已经不可能再投递（上一条指令结果不明）：停止执行分支，
                # 用已有证据收尾，而不是把它记成又一次「状态不明」。收尾原因要
                # 带上真正失败的那一条，否则报告只剩「已停止投递」，说不清为什么。
                self.tool_running = False
                reason = step.observation
                earlier = next((str(item.get('reason')) for item in reversed(self.state.attempts[:-1])
                                if item.get('status') in {'unknown', 'failed'} and item.get('reason')), '')
                if earlier and earlier not in reason:
                    reason = reason + '；上一条失败原因：' + earlier
                self.state.reason = reason
                self.state.event('L2', '停止投递：' + reason)
                raise BranchExit(reason)
            if step.ok:
                # Empty outputs and diagnostic text are not measurement evidence.
                if step.results:
                    evidence = Evidence(name, dict(arguments), list(step.results), self.state.context_text,
                                        'operation' if tools.is_mutating(name) else 'measurement')
                    self.state.add_evidence(evidence)
                if self.state.mode == 'L1':
                    self.event('L0', '有限纠正成功，继续专用执行')
                self.tool_running = False
                self.check()
                return {'status':'success', 'rows':step.results, 'source':'Praat/已注册专业工具'}
            self.tool_running = False
            self.check()
            permanent = unknown or any(s in step.observation.casefold() for s in (
                '缺少', '未安装', '没有可用', '未知工具', '不支持', 'not installed', 'dependency', 'unavailable'))
            permanent = permanent or '不可用' in step.observation
            note_guard(self.state, 'block', 'execution.' + problem)
            self.state.failed(problem, step.observation, permanent=permanent)
            raise ModelRetry(step.observation + '；只允许一次有依据且有区别的修正')

        return Tool.from_schema(invoke, name=name, description=function.get('description'),
                                json_schema=function['parameters'], sequential=True)

    async def execute(self):
        self.event('L0', '按原始目标执行专用工具')
        if self.schemas is None: self.schemas = tools.tool_schemas()
        guards = ToolGuards(self)
        registered = [self.tool(schema) for schema in sorted(self.schemas, key=lambda s:s['function']['name'])]
        instruction = planner_system(self.config)
        context = self.phase_context('planner', instruction)
        prompt = '原目标对象与范围：\n' + self.state.context_text
        if self.state.evidence:
            prompt += '\n已有成功测量（复用，不重跑）：' + json.dumps([asdict(e) for e in self.state.evidence], ensure_ascii=False)
        if self.state.historical_evidence:
            prompt += '\n历史专业证据与投递事实（非本轮新测量，不重放）：' + json.dumps(evidence_projection(self.state.historical_evidence), ensure_ascii=False)
        if self.state.material_metadata:
            prompt += '\n原始材料元数据：' + json.dumps(self.state.material_metadata, ensure_ascii=False)
        if self.state.direction:
            prompt += '\n继续方向：' + self.state.direction
        prompt += '\n原始目标：' + self.state.goal
        agent = Agent(self.model, system_prompt=instruction,
                      tools=registered, capabilities=[guards.hooks],
                      retries={'tools':2, 'output':0}, name='praat_tools')
        try:
            await self.drive(agent, prompt, tool_phase=True)
        except Exception as error:
            self.state.reason = caps.safe_error(error, self.config.api.api_key)
            self.event('L2', '专用执行结束：' + self.state.reason)

    def should_escalate_audio(self):
        state = self.state
        if (state.continuation or state.mode != 'L2' or self.config.api.limit_tokens
                or not self.config.api.audio_input_enabled or self.materials is None
                or self.materials.closed or self.cancel.is_set()
                or state.requests > state.budget.request_limit - 2):
            return False
        available = bool(self.materials.audio_path and self.materials.audio_path.is_file()) or (
            self.prepare_audio is not None and not self.materials.snapshot_attempted)
        if not available:
            return False
        for item in state.coverage:
            if item['status'] != 'complete' and ('audio' in item.get('missing_evidence', [])
                    or re.search(r'(?:缺少|缺乏|未提供|需要).{0,12}(?:原始音频|录音听感|听感证据)', item['explanation'])):
                return True
        return False

    async def report(self, *, force_audio=False, allow_escalation=True):
        self.check()
        state = self.state
        original_mode = state.mode
        audio_candidate = (force_audio or original_mode == 'L3' or (
            not state.continuation and original_mode != 'L4' and not self.config.api.limit_tokens and state.reason))
        audio = None
        if audio_candidate and self.config.api.audio_input_enabled:
            try:
                if self.prepare_audio is not None:
                    await asyncio.to_thread(self.prepare_audio)
                if self.materials is not None:
                    audio = self.materials.bytes()
                    if self.stream and ((len(audio) + 2) // 3 * 4) >= 10 * 1024 * 1024:
                        raise ValueError('当前供应商要求音频 Base64 小于 10 MiB，请缩小目标片段')
            except (OSError, ValueError, BranchExit) as error:
                self.progress('原目标材料不可用，改用已有证据：' + str(error))
                state.events.append({'mode':'material', 'reason':str(error)})
        if audio is not None:
            self.settings.setdefault('extra_body', {})['modalities'] = ['text']
            self.event('L3', '输入原目标临时音频；模型定性分析与专业测量分别注明来源')
        else:
            mode = 'L4' if original_mode == 'L4' or (not state.continuation and not self.config.api.limit_tokens
                                                   and not state.evidence and state.reason) else 'L2'
            self.event(mode, '重建独立分析上下文，解释原始目标及证据缺口')
        state.can_continue = bool(state.reason or self.config.api.limit_tokens)
        modern = self.config.api.token_mode is not None
        context = report_context(state, audio=audio is not None, preserve=modern)
        instruction = report_instructions(self.config, state)
        phase_context = self.phase_context('report', instruction)
        # A capability rejection discards only this unverified audio run. The
        # completed text chain before it remains available for the redirect.
        report_baseline = copy.deepcopy(phase_context.messages) if audio else None
        # Formal dialogue already exists as native roles. Don't inject it again.
        context.pop('visible_dialogue', None)
        context.pop('user_facts', None)
        goal = context.pop('original_goal')
        if state.historical_evidence:
            context['historical_evidence'] = evidence_projection(state.historical_evidence)
        if state.material_metadata:
            context['material_metadata'] = state.material_metadata
        context['original_goal'] = goal
        if not modern:
            # Existing legacy excerpt behavior stays confined to legacy entry.
            context = json.loads(compact_report_context({**context, 'original_goal':goal, 'visible_dialogue':[]},
                                  max(100, state.budget.context_tokens - state.budget.reserve -
                                      qwen.estimate_tokens(instruction) - 250)))
        prompt = json.dumps(phase_context.delta(context), ensure_ascii=False)
        guard_state = copy.copy(state)
        guard_state.evidence = [Evidence(**item) for item in context['evidence']]

        def remember(report):
            """守住模型这一版草稿：守卫拒绝时正文不该跟着一起丢（见 rescued_report）。"""

            if state.metrics.get('rejected_report') != report.analysis:
                state.metrics['rejected_values'] = []
            state.metrics['rejected_report'] = report.analysis
            state.metrics['rejected_coverage'] = [item.model_dump() for item in report.coverage]

        report_rejections = 0

        def guard_report(ctx, *, output_context, output):
            nonlocal report_rejections
            remember(output)
            try:
                return validate_report(guard_state, output)
            except ModelRetry as error:
                # 记下没核上的数值：报告最终留不住时，把这几处遮掉再给用户。
                state.metrics.setdefault('rejected_values', []).extend(rejected_values(str(error)))
                report_rejections += 1
                if report_rejections > 1:
                    # A resumed SDK run must not reset the single output retry.
                    from pydantic_ai.exceptions import UnexpectedModelBehavior
                    raise UnexpectedModelBehavior('Exceeded maximum output retries (1)') from error
                raise

        agent = Agent(self.model, system_prompt=instruction, output_type=PromptedOutput(AnalysisReport),
                      capabilities=[Hooks(after_output_process=guard_report, id='praat_report_guards')],
                      # 报告阶段的重试次数保持 1：这一轮的请求最大，带音频时每次重试都要
                      # 重发一遍原始音频。守卫再拒就由 rescued_report 保住正文，不靠加次数。
                      retries={'tools':0, 'output':1}, name='independent_analysis')

        @agent.output_validator
        def validate(ctx, report):
            remember(report)
            update = {}
            if [item.item for item in report.coverage] != state.deliveries:
                # 结构与措辞属于提示词层的要求：修好继续，不拒整份报告。
                update['coverage'] = repair_coverage(state.deliveries, report.coverage)
                note_guard(state, 'repair', 'report.coverage_repaired')
            prose = re.sub(r'(?m)^\s*\|.*$', '', report.analysis).strip()
            if len(prose) < 30:
                update['analysis'] = report.analysis + (
                    '\n\n（本次回答缺少解释性正文，只有数据或短语；'
                    '需要完整解释请再问一次。）')
                note_guard(state, 'repair', 'report.prose_short')
            return report.model_copy(update=update) if update else report

        try:
            result = await self.drive(agent, [prompt, BinaryContent(audio, media_type='audio/wav')] if audio else prompt)
            state.report = result.analysis
            state.metrics['report_verified'] = True
            state.coverage = [item.model_dump() for item in result.coverage]
            state.metrics.pop('rejected_report', None)
            state.metrics.pop('rejected_coverage', None)
            state.metrics.pop('rejected_values', None)
            state.status = 'complete' if all(item.status == 'complete' for item in result.coverage) else 'partial'
            state.can_continue = state.can_continue or state.status != 'complete'
            if audio is not None:
                state.audio_report_completed = True
                state.audio_observations.append({'kind':'model_audio', 'model':self.config.api.model,
                                                'source':self.materials.provenance(), 'analysis':result.analysis})
            if allow_escalation and self.should_escalate_audio():
                state.previous_report, state.previous_coverage = state.report, state.coverage
                self.progress('交付仍缺原始音频证据，沿用当前预算补充一次原目标音频分析')
                await self.report(force_audio=True, allow_escalation=False)
        except Exception as error:
            detail = caps.safe_error(error, self.config.api.api_key)
            status = getattr(error, 'status_code', None)
            if audio and caps.is_audio_unsupported(status, detail):
                self.config.api.audio_input_enabled = False
                phase_context.messages = report_baseline
                phase_context.complete = False
                phase_context.epoch += 1
                phase_context.projected['audio_input'] = False
                if 'extra_body' in self.settings:
                    self.settings['extra_body'].pop('modalities', None)
                self.event('L2', '当前 API 路径不接受音频，已关闭本轮直接音频能力，改用已有证据分析')
                if self.correct_audio:
                    try:
                        self.correct_audio(detail)
                    except OSError as save_error:
                        self.progress('能力纠正未保存：' + str(save_error))
                # One redirected report on the same budget, without audio.
                try:
                    result = await self.drive(agent, prompt.replace('"audio_input": true', '"audio_input": false'))
                    state.report, state.coverage = result.analysis, [item.model_dump() for item in result.coverage]
                    state.metrics['report_verified'] = True
                    state.status = 'partial'
                    state.can_continue = True
                    for key in ('rejected_report', 'rejected_coverage', 'rejected_values'):
                        state.metrics.pop(key, None)
                    return
                except Exception as redirected:
                    detail += '；证据报告失败：' + caps.safe_error(redirected, self.config.api.api_key)
            state.reason = (state.reason + '；' if state.reason else '') + detail
            state.status, state.can_continue = 'partial', True
            draft = str(state.metrics.pop('rejected_report', '') or '')
            rejected_coverage = state.metrics.pop('rejected_coverage', None)
            values = state.metrics.pop('rejected_values', [])
            rescued = rescued_report(draft, detail, values, state=guard_state)
            if rejected_coverage:
                for item in rejected_coverage:
                    item['explanation'] = mask_rejected_numbers(item['explanation'], values, UNVERIFIED_NUMBER, state=guard_state)
            state.metrics['report_verified'] = False
            if force_audio and state.previous_report:
                state.report, state.coverage = state.previous_report, state.previous_coverage
                state.report += '\n\n补充音频分析未完成：' + detail
            elif rescued:
                # 守卫拒的是核不上来源的数字，不是整份回答：保留草稿并说明原因，
                # 不再用「本轮仅交付阶段记录」把用户已经拿到的结论换掉。
                state.report = rescued
                if rejected_coverage:
                    state.coverage = rejected_coverage
            else:
                state.report = state.fallback_report()

    async def dialogue(self, kind, on_text):
        level = effective_thinking_level(self.config.api, kind)
        self.settings.pop('openai_reasoning_effort', None)
        self.settings.pop('extra_body', None)
        self.settings.pop('parallel_tool_calls', None)
        self.set_thinking(level)
        self.state.metrics['effective_thinking_level'] = level
        # 思考档位换了，推理预留跟着换（设置只管正文，推理额度永远额外留出）。
        self.state.budget.reasoning_tokens = reasoning_reserve(level)
        if kind == 'conversation' and level == 'off':
            self.set_body_tokens(DIALOGUE_FAST_TOKENS)
        else:
            # 寒暄/概念解释的正文上限来自设置（api.dialogue_max_tokens），同时仍被
            # 「云端最大回复 token」预算压着；这里不再有写死的 2048。
            self.set_body_tokens(self.config.api.dialogue_max_tokens)
        instruction = dialogue_instructions(self.config)
        self.phase_context('dialogue', instruction)
        prompt = self.state.goal
        self.event('chat', '普通对话直接回复' if kind == 'conversation' else '概念解释直接回复')
        agent = Agent(self.model, system_prompt=instruction, output_type=str, retries=0, name='direct_dialogue')
        collected: list[str] = []

        def sink(delta):
            collected.append(delta)
            on_text(delta)

        try:
            self.state.report = await self.drive(agent, prompt, on_text=sink)
        except OutputTruncated as truncated:
            self.state.report = await self.recover_truncated(agent, collected, truncated, sink)
        self.state.coverage = []
        if self.state.status == 'running':
            # 截断恢复路径已经定过状态（partial），不要在这里改回 complete。
            self.state.status, self.state.can_continue = 'complete', False

    def finish_truncated(self, partial, error):
        """截断又没续写完：保留已经流出的正文，并说清楚截断和能做什么。"""

        self.state.status, self.state.can_continue = 'partial', False
        self.state.reason = caps.safe_error(error, self.config.api.api_key)
        if not partial:
            return '本次回复未完成：' + self.state.reason
        return partial + ('\n\n（本次回复未完成：输出达到长度上限，以上是已经写完的部分。'
                          '可提高「云端对话最大回复 token」「云端最大回复 token」或降低思考档位后重问一次。）')

    async def recover_truncated(self, agent, collected, truncated, on_text):
        """``length`` 截断的恢复：先按正文满额续写一次，最差也保住已流出的正文。"""

        partial = ''.join(collected)
        if not partial:
            raise truncated        # 一个字都没流出来：沿用原来的失败路径
        if self.state.requests >= self.state.budget.request_limit:
            return self.finish_truncated(partial, truncated)
        self.state.event('chat', '输出被长度上限截断，自动续写一次')
        self.progress('输出被长度上限截断，自动续写一次')
        if self.rejected_output_cap is None:
            # 没被服务端拒过上限：正文给满，尽量一次写完。
            self.set_body_tokens(self.state.budget.response_tokens)
        # 被拒过就沿用当前（已经被接受的）额度，别把刚降下来的又抬回去。
        prompt = '上一次回复因为长度上限被截断。请从中断处接着写完；不要重复已经写过的句子，也不要重新开头。'
        try:
            answer = await self.drive(agent, prompt, on_text=on_text)
        except Exception as error:      # 续写失败或又被截断：保住累计文本，交代清楚
            return self.finish_truncated(''.join(collected), error)
        continuation = ''.join(collected)[len(partial):]
        return partial + (continuation or answer)

    def finish_metrics(self):
        self.state.metrics.update(total_seconds=time.monotonic()-self.started, requests=self.state.requests,
            input_tokens=self.usage.input_tokens, output_tokens=self.usage.output_tokens,
            reasoning_tokens=getattr(self.usage, 'details', {}).get('reasoning_tokens'))
        self.state.metrics['phases'] = cloud_metrics.aggregate(self.state.metrics['request_timings'])


async def _run(session):
    g = GraphBuilder(state_type=AnalysisState, output_type=AnalysisState, auto_instrument=False)

    @g.step
    async def route(ctx: StepContext[AnalysisState, None, None]) -> str:
        session.check()
        state = ctx.state
        if state.continuation:
            state.mode = state.continuation_mode or ('L4' if '一般' in state.direction else ('L3' if wants_audio(state.direction) else 'L2'))
            return state.mode
        state.mode = entry_mode(state.goal, state.context_text,
                                audio_requested=wants_audio(state.direction or state.goal)
                                or (session.materials is not None and session.materials.audio_path is not None
                                    and session.materials.source_kind == 'file'
                                    and session.config.api.audio_input_enabled and not state.direction))
        return state.mode

    @g.step
    async def execute(ctx: StepContext[AnalysisState, None, str]) -> str:
        await session.execute()
        return 'L2'

    @g.step
    async def report(ctx: StepContext[AnalysisState, None, str]) -> AnalysisState:
        await session.report()
        return ctx.state

    decision = g.decision().branch(g.match(str, matches=lambda mode:mode == 'L0').to(execute)).branch(g.match(str).to(report))
    g.add(g.edge_from(g.start_node).to(route), g.edge_from(route).to(decision),
          g.edge_from(execute).to(report), g.edge_from(report).to(g.end_node))
    graph = g.build()
    task = asyncio.create_task(graph.run(state=session.state))
    try:
        while not task.done():
            if session.cancel.is_set() and not session.tool_running:
                task.cancel()
                break
            await asyncio.wait({task}, timeout=0.05)
        return await task
    except asyncio.CancelledError:
        session.state.status, session.state.can_continue = 'cancelled', False
        session.state.report = '已取消后续分析，已完成的证据与执行记录已保留。'
        session.state.events.append({'mode':'cancelled', 'reason':'用户取消'})
        return session.state
    finally:
        session.finish_metrics()
        if session.owns_model and hasattr(session.model, 'client'):
            await session.model.client.close()


def run_cloud_turn(config, state: AnalysisState, *, execute_action, cancel: threading.Event,
                   progress=None, model=None, tool_schemas=None, materials=None,
                   prepare_audio=None, correct_audio=None, runtime=None, refresh_context=None) -> AnalysisState:
    if runtime is not None and model is None:
        async def operation(shared_model):
            session = CloudSession(config, state, execute_action, cancel, progress, shared_model, tool_schemas,
                                   materials, prepare_audio, correct_audio, refresh_context)
            return await _run(session)
        try:
            return runtime.run(config, operation)
        except Exception as error:
            state.reason = caps.safe_error(error, config.api.api_key)
            state.status, state.can_continue = 'partial', True
            state.report = state.fallback_report()
            return state
    session = CloudSession(config, state, execute_action, cancel, progress, model, tool_schemas,
                           materials, prepare_audio, correct_audio, refresh_context)
    try:
        return asyncio.run(_run(session))
    except Exception as error:
        state.reason = caps.safe_error(error, config.api.api_key)
        state.status, state.can_continue = 'partial', True
        state.report = state.fallback_report()
        return state


def run_dialogue_turn(config, state, *, kind, cancel, on_text, progress=None, model=None, runtime=None):
    async def operation(shared_model=None):
        session = CloudSession(config, state, None, cancel, progress, shared_model, [], None, None, None)
        try:
            task = asyncio.create_task(session.dialogue(kind, on_text))
            while not task.done():
                if cancel.is_set():
                    task.cancel()
                    break
                await asyncio.wait({task}, timeout=0.05)
            await task
        except asyncio.CancelledError:
            state.status, state.can_continue = 'cancelled', False
            state.report = '已取消本次回复；未将已显示的部分文字作为完整回答。'
        except Exception as error:
            state.reason = caps.safe_error(error, config.api.api_key)
            state.status, state.can_continue = 'partial', False
            state.report = '本次回复未完成：' + state.reason
        finally:
            session.finish_metrics()
            if session.owns_model and hasattr(session.model, 'client'): await session.model.client.close()
        return state
    if runtime is not None and model is None: return runtime.run(config, operation)
    return asyncio.run(operation(model))
