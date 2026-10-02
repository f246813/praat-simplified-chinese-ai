"""A window owns one event loop and one reusable cloud model/client."""
from __future__ import annotations
import asyncio
import copy
import threading


class CloudRuntime:
    def __init__(self, *, model_factory=None):
        self.factory = model_factory
        self.thread = None
        self.loop = None
        self._ready = threading.Event()
        self._guard = threading.Lock()
        self._closed = False
        self._model = None
        self._key = None
        self._shutdown_future = None

    def _serve(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._gate = asyncio.Lock()
        self._ready.set()
        try:
            self.loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self.loop)
            for task in pending: task.cancel()
            if pending: self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close()

    async def _release(self):
        model, self._model, self._key = self._model, None, None
        if model is not None and hasattr(model, 'client'):
            await model.client.close()

    async def _invoke(self, config, operation):
        async with self._gate:
            api = config.api
            key = (api.base_url.strip().rstrip('/'), api.model.strip(), api.api_key, api.request_timeout_sec)
            if key != self._key:
                await self._release()
                if self.factory is None:
                    from .cloud_agent import create_model
                    self._model = create_model(config)
                else:
                    self._model = self.factory(config)
                self._key = key
            return await operation(self._model)

    def run(self, config, operation):
        with self._guard:
            if self._closed: raise RuntimeError('Cloud runtime is closed')
            if self.thread is None:
                self.thread = threading.Thread(target=self._serve, name='Praat-cloud-loop', daemon=True)
                self.thread.start()
            self._ready.wait()
            future = asyncio.run_coroutine_threadsafe(self._invoke(copy.deepcopy(config), operation), self.loop)
        return future.result()

    def close(self, *, wait=False):
        with self._guard:
            if not self._closed:
                self._closed = True
                if self.thread is not None:
                    async def shutdown():
                        async with self._gate: await self._release()
                    self._shutdown_future = asyncio.run_coroutine_threadsafe(shutdown(), self.loop)
                    self._shutdown_future.add_done_callback(lambda _:self.loop.call_soon_threadsafe(self.loop.stop))
            future, thread = self._shutdown_future, self.thread
        if wait and future is not None:
            future.result(timeout=5)
            thread.join(timeout=5)
