"""Model metadata + thin request/compaction policy, not a Pi agent runtime.

Metadata subset from @mariozechner/pi-ai 0.73.1, git 781152fc24841dc54b22284514604048ebe5e2c9 (MIT).
"""
from __future__ import annotations

import asyncio
import copy
import json
from urllib.parse import urlsplit

from . import qwen
from .config import apply_api_to_qwen

MODELS = [
    dict(id='gpt-4o', provider='openai', contextWindow=128000, maxTokens=16384),
    dict(id='gpt-4o-mini', provider='openai', contextWindow=128000, maxTokens=16384),
    dict(id='gpt-4.1', provider='openai', contextWindow=1047576, maxTokens=32768),
    dict(id='gpt-4.1-mini', provider='openai', contextWindow=1047576, maxTokens=32768),
]


def metadata(config):
    # Names at arbitrary gateways do not prove the upstream model window.
    if (urlsplit(config.base_url).hostname or '').lower() == 'api.openai.com':
        return next((dict(m) for m in MODELS if m['id'] == config.model), None)
    return None


def prepare(config, *, explicit_window=False):
    config = copy.deepcopy(config)
    section = config.api if config.api.enabled else config.qwen
    mode = section.token_mode or ('manual' if section.limit_tokens else 'provider')
    section.token_mode = mode
    model = metadata(section)
    if mode == 'auto':
        if not model:
            raise ValueError('此端点/模型尚无已适配窗口；请使用手动模式填写真实上下文窗口')
        section.max_context_tokens = model['contextWindow']
        section.plan_max_tokens = min(model['maxTokens'], max(128, model['contextWindow'] // 8))
    elif mode == 'provider':
        if model:
            section.max_context_tokens = model['contextWindow']
        elif not explicit_window:
            raise ValueError('服务商决定模式仍需真实窗口才能压缩；请先填写并保存上下文窗口')
    elif mode != 'manual':
        raise ValueError('无效 token 模式')
    if section.plan_max_tokens >= section.max_context_tokens and mode != 'provider':
        raise ValueError('回复上限必须小于上下文窗口')
    section.limit_tokens = mode != 'provider'
    if config.api.enabled:
        apply_api_to_qwen(config)
    return config


def model_settings(section, *, sdk=False, input_cost=0):
    result = {}
    if section.plan_temperature is not None:
        result['temperature'] = section.plan_temperature
    if section.top_p is not None:
        result['top_p'] = section.top_p
    if section.presence_penalty is not None:
        result['presence_penalty'] = section.presence_penalty
    if section.token_mode != 'provider':
        room = section.max_context_tokens - input_cost - 256
        if room < 128:
            raise ValueError('真实上下文余量不足；未发送截断的历史或工具调用')
        result['max_tokens'] = min(section.plan_max_tokens, room)
    if (section.base_url.rstrip('/') == 'https://generativelanguage.googleapis.com/v1beta/openai'
            and section.model.startswith('gemini-3')):
        for key in ('temperature', 'top_p', 'presence_penalty'):
            result.pop(key, None)
    return result


def text_request(config, messages, *, cancel=None):
    """Shared validation/summary adapter without hidden probe sampling defaults."""
    if cancel is not None and cancel.is_set():
        raise RuntimeError('已取消请求')
    if not config.api.enabled:
        return qwen.QwenClient(config.qwen).chat(messages, max_tokens=config.qwen.plan_max_tokens,
                                               temperature=config.qwen.plan_temperature)
    from pydantic_ai import Agent
    from .cloud_agent import create_model
    from .config import QwenConfig
    async def run():
        model = create_model(config)
        settings = model_settings(config.api, sdk=True, input_cost=qwen.estimate_tokens(json.dumps(messages, ensure_ascii=False)))
        thinking = qwen.thinking_request_fields(QwenConfig(provider='api', base_url=config.api.base_url,
                                                           model=config.api.model, thinking_level=config.api.thinking_level))
        for key, value in thinking.items():
            if key == 'reasoning_effort':
                settings['openai_reasoning_effort'] = value
            else:
                settings.setdefault('extra_body', {})[key] = value
        async def invoke():
            return (await Agent(model, output_type=str, retries=0).run(json.dumps(messages, ensure_ascii=False), model_settings=settings)).output
        task = asyncio.create_task(invoke())
        try:
            while not task.done():
                if cancel is not None and cancel.is_set():
                    task.cancel()
                    raise RuntimeError('已取消请求')
                await asyncio.wait({task}, timeout=.05)
            return await task
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if hasattr(model, 'client'):
                await model.client.close()
    return asyncio.run(run())


def context_estimate(config, history, evidence, text, target=''):
    """Same heuristic as compaction; not tokenizer/billing usage. No requests."""
    from .tools import tool_schemas
    overhead = qwen.estimate_tokens(qwen.planner_instructions(config.qwen) + json.dumps(tool_schemas(), ensure_ascii=False))
    content = json.dumps(history, ensure_ascii=False) + json.dumps(evidence, ensure_ascii=False) + text + target
    return dict(inputTokens=qwen.estimate_tokens(content) + overhead, overheadTokens=overhead)


def compact(store, sid, config, history, evidence, text, target, *, cancel, emit, requester=text_request):
    """One real summary pass near the actual window, in ALL token modes.

    Keep recent complete turns, original immutable records and structured evidence.
    Refuse overfull requests when one pass cannot safely fit, rather than silently trim.
    """
    section = config.api if config.api.enabled else config.qwen
    structured = json.dumps(evidence, ensure_ascii=False)
    estimate = context_estimate(config, history, evidence, text, target)
    overhead, cost = estimate['overheadTokens'], estimate['inputTokens']
    reserve = (section.plan_max_tokens if section.token_mode != 'provider' else max(512, section.max_context_tokens // 10))
    if cost + reserve < section.max_context_tokens * .85:
        return [{k: item[k] for k in ('role', 'content')} for item in history]
    recent = history[-6:]
    older = history[:-6]
    if not older:
        raise ValueError('近期消息/专业证据已接近真实窗口，不能安全压缩；请缩小输入或增加窗口')
    prompt = [dict(role='system', content='压缩对话为忠实摘要。保留原任务目标、指代、用户约束、范围、证据来源和执行事实。不得添加测量数字或将推断升级为测量。工具证据另行保留，不以摘要替代。'),
              dict(role='user', content=json.dumps([{k: x[k] for k in ('role', 'content')} for x in older], ensure_ascii=False))]
    if qwen.estimate_tokens(json.dumps(prompt, ensure_ascii=False)) + reserve >= section.max_context_tokens:
        raise ValueError('较早历史已超过安全摘要窗口；未裁剪或删除原历史')
    summary = requester(config, prompt, cancel=cancel)
    if cancel.is_set() or not str(summary).strip():
        raise RuntimeError('上下文摘要未完成；原历史保留')
    through = max((x.get('_seq', 0) for x in older), default=0)
    candidate = [dict(role='user', content='较早对话摘要（不是测量证据）：\n' + summary), *[{k: x[k] for k in ('role', 'content')} for x in recent]]
    if qwen.estimate_tokens(json.dumps(candidate, ensure_ascii=False) + structured + text + target) + overhead + reserve >= section.max_context_tokens:
        raise ValueError('本轮真实摘要后仍无法容纳证据和近期消息；未覆盖已存上下文')
    store.summarize(sid, summary, through)
    emit('activity', dict(id='compression-' + str(through), type='compression', text='已完成一轮真实上下文摘要；原始记录和专业证据保留', status='complete'))
    return candidate
