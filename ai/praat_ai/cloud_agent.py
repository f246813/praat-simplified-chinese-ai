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

os.environ.setdefault('PYDANTIC_AI_NO_BANNER', '1')
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field
from pydantic_ai import Agent, BinaryContent, ModelRetry, PromptedOutput, Tool
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.usage import RunUsage, UsageLimits
from pydantic_graph import GraphBuilder, StepContext

from . import model_capabilities as caps, qwen, tools
from . import delivery
from .escape_policy import AnalysisState, BranchExit, Evidence
from .dialogue_policy import dialogue_kind, effective_thinking_level, direct_measurement, reasoning_reserve
from .cloud_runtime import CloudRuntime


class Coverage(BaseModel):
    item: str
    status: Literal['complete', 'partial', 'missing']
    explanation: str = Field(min_length=8)
    missing_evidence: list[Literal['audio', 'measurement', 'reference']] = Field(default_factory=list)


class AnalysisReport(BaseModel):
    analysis: str = Field(min_length=30, description='解释原始目标的中文 Markdown 报告，不能仅有统计表')
    coverage: list[Coverage]


REPORT_INSTRUCTIONS = (
    '\n你正在独立分析，无执行工具。实际解释 original_goal 的每个交付项，给出对比、依据、限制和下一步。'
    'coverage.item 必须逐项原样对应 deliveries；状态为 complete/partial/missing。'
    '缺口用 missing_evidence 标记 audio（需要原始音频）、measurement（专业测量）、reference（参照资料）；仅列影响交付的缺口。'
    '不要把成功执行或覆盖结构当作结论正确。仅统计表或“已完成”不算解释。'
    '引用证据工具、参数、范围；区分测量、转写、模型音频分析、一般知识和推断。'
    'audio_observations 是此前模型对原音频的定性观察，引用时注明原模型和材料来源，不能当作专业测量。'
    'audio_input 为 false 时不得声称本轮重新听过录音；没有原音频或此前音频观察时，不能判断具体录音缺陷。')

#: 只有本轮真的有失败记录时才追加（提示词预算很紧，不能白付；实测 2048 上下文的
#: 预算用例只留了一百来个 token 的余量）。
FAILURE_INSTRUCTIONS = (
    '\nblocked_attempts/paused_branches/missing_reason 是实际执行失败的原因（没有运行中的 Praat、消息文件写不进去、'
    '脚本报错、超时…）：报告要如实交代失败原因和用户能照做的下一步，不能把投递或环境故障写成模型能力不足，'
    '也不能把没跑成的测量说成测量结果。'
    'audio_input=false 只表示本轮没把音频交给模型：Praat 测量不依赖它，不能据此说无法测量。')


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


def report_instructions(config, state) -> str:
    """报告阶段的系统提示。失败说明只在**这一轮真的有失败记录**时追加。

    提示词预算很紧（``drive`` 会把系统提示算进输入开销），而失败说明只有真出事时
    才有用；预检（:func:`minimum_continuation_tokens`）和真实报告都走这一个入口，
    免得两边算法不一致。
    """

    text = qwen.analysis_instructions(config.qwen) + REPORT_INSTRUCTIONS
    if state.failures or blocked_attempts(state):
        text += FAILURE_INSTRUCTIONS
    return text


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
    if state.audio_observations and state.previous_report == state.audio_observations[-1]['analysis']:
        context['previous_report'] = ''
        context['previous_report_source'] = 'audio_observations 最后一项（同一报告，避免重复）'
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


def create_model(config):
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    client = AsyncOpenAI(base_url=config.api.base_url.strip().rstrip('/'),
                         api_key=config.api.api_key or 'EMPTY', max_retries=0,
                         timeout=config.api.request_timeout_sec)
    from .cloud_stream import enable_stream_reuse
    enable_stream_reuse(client)
    preset = caps.audio_preset(config.api.base_url, config.api.model)
    profile = {'openai_chat_audio_input_encoding':'uri'} if preset.stream else None
    return OpenAIChatModel(config.api.model, provider=OpenAIProvider(openai_client=client), profile=profile)


class CloudSession:
    def __init__(self, config, state, execute_action, cancel, progress, model, schemas,
                 materials, prepare_audio, correct_audio):
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
        self.materials, self.prepare_audio, self.correct_audio = materials, prepare_audio, correct_audio
        self.usage = RunUsage()
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
        self.executed = {e.signature:e for e in state.evidence}
        self.tool_running = False
        self.received_text = False
        #: 服务端拒过这次的输出上限时记下降额后的额度（续写不再把它抬回去）。
        self.rejected_output_cap = None
        state.metrics = {'first_text_seconds':None, 'request_timings':[],
                         'effective_thinking_level':config.api.thinking_level}
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

    def request_cost(self, messages, *, schema=False):
        # Estimate the complete input, including definitions and SDK messages.
        # Binary content is budgeted separately, never serialized into records.
        from pydantic_core import to_jsonable_python
        values = to_jsonable_python(messages, bytes_mode='base64')
        def without_binary(value):
            if isinstance(value, dict):
                if 'data' in value and 'media_type' in value:
                    return {'media_type':value['media_type'], 'content':'原始材料输入'}
                return {key:without_binary(item) for key, item in value.items()}
            if isinstance(value, list):
                return [without_binary(item) for item in value]
            return value
        value = json.dumps(without_binary(values), ensure_ascii=False)
        cost = qwen.estimate_tokens(value)
        if '原始材料输入' in value:
            # Conservative audio estimate; actual usage is recorded after requests.
            import wave
            with wave.open(str(self.materials.audio_path), 'rb') as reader:
                cost += int(reader.getnframes() / reader.getframerate() * 50)
        if schema:
            cost += qwen.estimate_tokens(json.dumps(self.schemas, ensure_ascii=False))
        return cost

    async def drive(self, agent, prompt, *, tool_phase=False, on_text=None):
        """跑一次模型对话；服务端拒绝输出上限时整轮重启一次（同一个 agent、新的 run）。

        pydantic-ai 的 ``node.stream()`` 一个节点只能进一次，所以不能在原地 ``continue``
        重试：必须重新开 run，否则会变成 ``stream() should only be called once per node``。
        """

        try:
            return await self._drive(agent, prompt, tool_phase=tool_phase, on_text=on_text,
                                     allow_output_retry=True)
        except OutputLimitRejected:
            self.progress('服务端不接受这个输出上限，按正文 ' + str(self.body_tokens()) + ' token 重试一次')
            return await self._drive(agent, prompt, tool_phase=tool_phase, on_text=on_text,
                                     allow_output_retry=False)

    async def _drive(self, agent, prompt, *, tool_phase=False, on_text=None, allow_output_retry=True):
        async with agent.iter(prompt, model_settings=self.settings, usage=self.usage,
                              usage_limits=self.limits) as run:
            node = run.next_node
            while not Agent.is_end_node(node):
                self.check()
                if Agent.is_model_request_node(node):
                    messages = run.all_messages()
                    if not any(message is node.request for message in messages):
                        messages = [*messages, node.request]
                    input_cost = self.request_cost(messages, schema=tool_phase)
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
                    if tool_phase:
                        self.state.planning_rounds += 1
                    contains_audio = any(
                        isinstance(part, UserPromptPart) and isinstance(part.content, (list, tuple))
                        and any(isinstance(item, BinaryContent) for item in part.content)
                        for message in messages for part in message.parts)
                    for attempt in range(2):
                        self.check()
                        self.state.requests += 1
                        request_started = time.monotonic()
                        timing = {'request':self.state.requests, 'phase':self.state.mode, 'retry':bool(attempt)}
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
                            temporary = status in {408, 429, 500, 502, 503, 504} or isinstance(error, (TimeoutError, ConnectionError)) or 'timeout' in type(error).__name__.lower()
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
                                continue
                            raise
                        finally:
                            timing.setdefault('status', 'cancelled')
                            timing['elapsed_seconds'] = time.monotonic()-request_started
                            self.state.metrics['request_timings'].append(timing)
                    node = next_node
                else:
                    tools_node = Agent.is_call_tools_node(node)
                    node = await run.next(node)
                    if tools_node and tool_phase and not Agent.is_end_node(node):
                        self.state.finish_round()
            return run.result.output

    def record_responses(self, messages):
        for message in reversed(messages):
            if isinstance(message, ModelResponse):
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
        validator = Draft202012Validator(function['parameters'])

        async def invoke(**arguments):
            self.check()
            self.state.tool_attempts += 1
            if self.state.tool_attempts > self.state.budget.tool_limit:
                raise BranchExit('本轮工具尝试总预算已用完')
            problem = name  # Bound original input/range, parameter text does not reset repairs.
            if self.state.failures.get(problem, 0) >= 2:
                raise BranchExit('此前失败分支仍暂停：' + name + '；需要新依据才能重试')
            signature = Evidence(name, arguments, [], self.state.context_text).signature
            if signature in self.executed:
                self.state.attempts.append({'tool':name, 'arguments':arguments, 'status':'not_executed', 'reason':'复用成功测量'})
                return {'status':'cached', 'rows':self.executed[signature].rows, 'source':'已有成功证据；未重复执行'}
            if any(a.get('signature') == signature for a in self.state.attempts):
                self.state.attempts.append({'tool':name, 'arguments':arguments, 'status':'not_executed', 'reason':'相同失败调用没有区别'})
                return {'status':'not_executed', 'reason':'相同调用没有区别；应退出该分支'}
            errors = sorted(validator.iter_errors(arguments), key=lambda e:str(e.path))
            if errors:
                reason = '；'.join(e.message for e in errors)
                self.state.attempts.append({'tool':name, 'arguments':arguments, 'signature':signature,
                                            'status':'not_executed', 'reason':reason})
                self.state.failed(problem, reason)
                raise ModelRetry('JSON Schema 校验失败：' + reason + '。仅允许一次有区别的纠正。')
            # Existing mutation policy applies to cloud too.
            from .chat import ANALYSIS_PREPARATION_TOOLS, wants_second_step
            if (self.state.planning_rounds > 1 and tools.is_mutating(name)
                    and name not in ANALYSIS_PREPARATION_TOOLS and not wants_second_step(self.state.goal)):
                self.state.attempts.append({'tool':name, 'arguments':arguments, 'status':'not_executed', 'reason':'未授权追加对象操作'})
                return {'status':'not_executed', 'reason':'用户未要求追加对象操作，请用已有证据报告'}
            self.tool_running = True
            try:
                step = await asyncio.to_thread(self.execute_action, name, arguments, self.state.planning_rounds)
            except BaseException:
                self.tool_running = False
                raise
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
                    self.executed[signature] = evidence
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
            self.state.failed(problem, step.observation, permanent=permanent)
            raise ModelRetry(step.observation + '；只允许一次有依据且有区别的修正')

        return Tool.from_schema(invoke, name=name, description=function.get('description'),
                                json_schema=function['parameters'], sequential=True)

    async def execute(self):
        self.event('L0', '按原始目标执行专用工具')
        if self.schemas is None: self.schemas = tools.tool_schemas()
        registered = [self.tool(schema) for schema in self.schemas]
        prompt = '原始目标：' + self.state.goal + '\n原目标对象与范围：\n' + self.state.context_text
        if self.state.evidence:
            prompt += '\n已有成功测量（复用，不重跑）：' + json.dumps([asdict(e) for e in self.state.evidence], ensure_ascii=False)
        if self.state.dialogue_context:
            prompt += '\n最近可见对话（仅帮助理解指代，不当作本次测量）：' + json.dumps(self.state.dialogue_context, ensure_ascii=False)
        if self.state.direction:
            prompt += '\n继续方向：' + self.state.direction
        agent = Agent(self.model, system_prompt=qwen.planner_instructions(self.config.qwen),
                      tools=registered, retries={'tools':1, 'output':0}, name='praat_tools')
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
        prompt = compact_report_context(context, max(400, state.budget.context_tokens - state.budget.reserve - 1800), preserve=modern)
        instruction = report_instructions(self.config, state)
        agent = Agent(self.model, system_prompt=instruction, output_type=PromptedOutput(AnalysisReport),
                      retries={'tools':0, 'output':1}, name='independent_analysis')

        @agent.output_validator
        def validate(ctx, report):
            if [item.item for item in report.coverage] != state.deliveries:
                raise ModelRetry('coverage 必须逐项对应原始 deliveries，原样保留每个 item')
            prose = re.sub(r'(?m)^\s*\|.*$', '', report.analysis).strip()
            if len(prose) < 30:
                raise ModelRetry('报告不能仅有统计表；请解释原始目标、依据和缺口')
            return report

        try:
            result = await self.drive(agent, [prompt, BinaryContent(audio, media_type='audio/wav')] if audio else prompt)
            state.report = result.analysis
            state.coverage = [item.model_dump() for item in result.coverage]
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
                    state.status = 'partial'
                    state.can_continue = True
                    return
                except Exception as redirected:
                    detail += '；证据报告失败：' + caps.safe_error(redirected, self.config.api.api_key)
            state.reason = (state.reason + '；' if state.reason else '') + detail
            state.status, state.can_continue = 'partial', True
            if force_audio and state.previous_report:
                state.report, state.coverage = state.previous_report, state.previous_coverage
                state.report += '\n\n补充音频分析未完成：' + detail
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
        instruction = qwen.identity_instructions(self.config.qwen)
        instruction += '\n自然回答用户，按问题需要控制长度。寒暄和能力介绍请简短。不能声称已执行测量或听过录音。'
        if kind == 'concept': instruction += '\n' + qwen.analysis_instructions(self.config.qwen)
        history = self.state.dialogue_context
        prompt = ('最近可见对话（仅用于理解，不能作为新的测量证据）：' + json.dumps(history, ensure_ascii=False) + '\n') if history else ''
        prompt += self.state.goal
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
        prompt = ('上一次回复因为长度上限被截断。请从中断处接着把剩下的内容写完：'
                  '不要重复已经写过的句子，也不要重新开头。\n已写内容（结尾部分）：\n' + partial[-1200:])
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
                   prepare_audio=None, correct_audio=None, runtime=None) -> AnalysisState:
    if runtime is not None and model is None:
        async def operation(shared_model):
            session = CloudSession(config, state, execute_action, cancel, progress, shared_model, tool_schemas,
                                   materials, prepare_audio, correct_audio)
            return await _run(session)
        try:
            return runtime.run(config, operation)
        except Exception as error:
            state.reason = caps.safe_error(error, config.api.api_key)
            state.status, state.can_continue = 'partial', True
            state.report = state.fallback_report()
            return state
    session = CloudSession(config, state, execute_action, cancel, progress, model, tool_schemas,
                           materials, prepare_audio, correct_audio)
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
