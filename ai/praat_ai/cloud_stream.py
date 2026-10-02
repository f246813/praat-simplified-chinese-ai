"""Finish HTTP response consumption after SSE DONE so keep-alive can work."""
from __future__ import annotations
import asyncio
import json
from typing import TypeVar, get_args
from openai import AsyncStream

T = TypeVar('T')


class DrainingAsyncStream(AsyncStream[T]):
    async def _iter_events(self):
        events = super()._iter_events()
        completed = False
        async for event in events:
            if event.data.startswith('[DONE]'):
                completed = True
                # The SDK closes at DONE before httpx observes the body EOF.
                # Drain only its protocol tail, with a short bound; cancellation
                # and errors before DONE still close immediately.
                async def drain():
                    async for _ in events: pass
                try:
                    await asyncio.wait_for(drain(), timeout=0.2)
                except Exception:
                    # A complete SSE result already arrived. Failure of this
                    # optional tail drain only forfeits connection reuse.
                    pass
            elif 'finish_reason' in event.data:
                try:
                    completed |= any(choice.get('finish_reason') is not None
                                     for choice in json.loads(event.data).get('choices', []))
                except (TypeError, ValueError, AttributeError):
                    pass  # SDK parsing still reports malformed content.
            yield event
        if not completed:
            raise RuntimeError('模型文字流在完成标记之前结束')


def enable_stream_reuse(client):
    request = client.request
    async def reusable_request(*args, **kwargs):
        stream_cls = kwargs.get('stream_cls')
        if kwargs.get('stream') and stream_cls is not None:
            arguments = get_args(stream_cls)
            kwargs['stream_cls'] = DrainingAsyncStream[arguments[0]] if arguments else DrainingAsyncStream
        return await request(*args, **kwargs)
    # Scope the SDK stream adapter to this client, not a global monkey patch.
    client.request = reusable_request
