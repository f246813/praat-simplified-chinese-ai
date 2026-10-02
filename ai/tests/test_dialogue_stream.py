"""Real SDK streaming and window-scoped connection lifecycle; no cloud requests."""
import asyncio
import copy
import json
import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pydantic_ai.models.function import FunctionModel
from praat_ai import cloud_agent, cloud_workflow
from praat_ai.config import AppConfig, apply_api_to_qwen
from praat_ai.conversation_store import ConversationStore
from praat_ai.escape_policy import AnalysisState


def config():
    cfg = AppConfig(); cfg.api.enabled = True
    cfg.api.base_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    cfg.api.model = 'qwen3.7-flash'; cfg.api.thinking_level = 'high'
    apply_api_to_qwen(cfg)
    return cfg


class DialogueStreamTests(unittest.TestCase):
    def test_cancel_while_waiting_for_first_text_returns_promptly(self):
        run=getattr(cloud_agent,'run_dialogue_turn',None)
        self.assertTrue(callable(run))
        async def slow(messages,info):
            await asyncio.sleep(1.5)
            yield 'late text'
        cancel=threading.Event(); timer=threading.Timer(0.06,cancel.set); timer.start()
        started=time.monotonic(); chunks=[]; state=AnalysisState('hello','')
        try: run(config(),state,kind='conversation',cancel=cancel,on_text=chunks.append,model=FunctionModel(stream_function=slow))
        finally: timer.cancel(); timer.join()
        self.assertLess(time.monotonic()-started,0.6)
        self.assertEqual(state.status,'cancelled'); self.assertEqual(chunks,[])

    def run_dialogue(self, cfg=None, cancel=None, delta=None, fail_after_first=False):
        run = getattr(cloud_agent, 'run_dialogue_turn', None)
        self.assertTrue(callable(run), 'Missing single-request text streaming path')
        settings = []
        async def stream(messages, info):
            self.assertFalse(info.function_tools)
            settings.append(copy.deepcopy(info.model_settings))
            yield '你好，'
            await asyncio.sleep(0.12)
            if fail_after_first: raise ConnectionError('fixture broken stream')
            yield '我可以介绍功能，也可以协助测量。'
        state = AnalysisState('Hello,what can u do for me?', '')
        started = time.monotonic(); chunks = []
        def on_delta(text):
            chunks.append((time.monotonic()-started, text))
            if delta: delta(text)
        run(cfg or config(), state, kind='conversation', cancel=cancel or threading.Event(),
            on_text=on_delta, model=FunctionModel(stream_function=stream))
        return state, settings, chunks

    def test_one_plain_request_streams_before_completion(self):
        state, settings, chunks = self.run_dialogue()
        self.assertEqual(state.requests, 1)
        self.assertEqual(state.coverage, [])
        self.assertEqual(state.report, ''.join(text for _,text in chunks))
        self.assertEqual(state.status, 'complete')
        self.assertEqual(settings[0]['extra_body']['enable_thinking'], False)
        self.assertLessEqual(settings[0]['max_tokens'], 512)
        self.assertLess(chunks[0][0]+0.06, state.metrics['total_seconds'])
        self.assertIsNotNone(state.metrics['first_text_seconds'])

    def test_forced_high_is_sent_for_ordinary_conversation(self):
        cfg=config(); cfg.api.force_deep_thinking=True
        state, settings, _ = self.run_dialogue(cfg)
        self.assertTrue(settings[0]['extra_body']['enable_thinking'])
        self.assertEqual(state.metrics['effective_thinking_level'], 'high')

    def test_cancellation_does_not_publish_partial_as_complete(self):
        cancel=threading.Event()
        state, _, chunks = self.run_dialogue(cancel=cancel, delta=lambda _:cancel.set())
        self.assertEqual(state.status,'cancelled')
        self.assertEqual(state.requests,1)
        self.assertNotEqual(state.report, ''.join(text for _,text in chunks))

    def test_failure_after_first_chunk_does_not_retry_or_duplicate_text(self):
        state, _, chunks = self.run_dialogue(fail_after_first=True)
        self.assertEqual(state.requests,1)
        self.assertEqual(state.status,'partial')
        self.assertNotEqual(state.report, ''.join(text for _,text in chunks))

    def test_fast_workflow_does_not_prepare_praat_or_task_materials(self):
        runtime_type=getattr(cloud_agent,'CloudRuntime',None)
        self.assertTrue(callable(runtime_type), 'Missing window scoped runtime')
        async def stream(messages, info): yield '您好！可以协助介绍功能和测量。'
        runtime=runtime_type(model_factory=lambda _:FunctionModel(stream_function=stream))
        with tempfile.TemporaryDirectory() as directory:
            store=ConversationStore(Path(directory)/'records.sqlite3')
            window=SimpleNamespace(config=config(),pending_analysis=None,history=[],task_materials=[],
                current_materials=None,analysis_state=None,store=store,session_id=store.new_session(),
                cancel_event=threading.Event(),messages=queue.Queue(),cloud_runtime=runtime,_closed=False)
            try:
                with (patch('praat_ai.chat.object_context', side_effect=AssertionError('Must not access objects')),
                      patch('praat_ai.cloud_workflow.TaskMaterials', side_effect=AssertionError('Must not create material'))):
                    cloud_workflow.process_cloud(window,'what can u do for me?')
                messages=[]
                while not window.messages.empty(): messages.append(window.messages.get_nowait())
                self.assertEqual(sum(role=='assistant-final' for role,text in messages),1)
                turns=[e['payload'] for e in store.records(window.session_id) if e['kind']=='turn']
                self.assertEqual(len(turns),1)
                self.assertEqual(turns[0]['requests'],1)
                self.assertEqual(turns[0]['goal'],'what can u do for me?')
                self.assertEqual(turns[0]['report'],'您好！可以协助介绍功能和测量。')
                self.assertEqual(window.task_materials,[])
            finally: runtime.close(wait=True)


class RuntimeTests(unittest.TestCase):
    def test_runtime_failure_is_a_safe_report_not_an_uncaught_worker_error(self):
        class Broken:
            def run(self,*_): raise OSError('fixture secret failed')
        cfg=config(); cfg.api.api_key='secret'
        state=AnalysisState('measure pitch','')
        try:
            cloud_agent.run_cloud_turn(cfg,state,execute_action=lambda *_:None,cancel=threading.Event(),runtime=Broken())
        except Exception as error: self.fail('Runtime exception must become a safe report: '+type(error).__name__)
        self.assertEqual(state.status,'partial'); self.assertNotIn('secret',state.report)

    def test_reuses_same_loop_and_model_then_replaces_changed_identity(self):
        runtime_type=getattr(cloud_agent,'CloudRuntime',None)
        self.assertTrue(callable(runtime_type), 'Missing loop-safe client reuse')
        made=[]
        class Client:
            closed=False
            async def close(self): self.closed=True
        def factory(cfg):
            model=SimpleNamespace(client=Client()); made.append(model); return model
        runtime=runtime_type(model_factory=factory)
        async def operation(model): return (id(model),id(asyncio.get_running_loop()),threading.get_ident())
        try:
            cfg=config()
            first=runtime.run(cfg,operation)
            self.assertEqual(runtime.run(cfg,operation),first)
            cfg.api.api_key='private-test-key'
            second=runtime.run(cfg,operation)
            self.assertNotEqual(second[0],first[0]); self.assertEqual(second[1:],first[1:])
            self.assertTrue(made[0].client.closed)
            cfg.api.model='fixture-model-2'; runtime.run(cfg,operation)
            cfg.api.request_timeout_sec=25; runtime.run(cfg,operation)
            self.assertEqual(len(made),4)
        finally: runtime.close(wait=True)
        self.assertTrue(made[-1].client.closed)
        self.assertFalse(runtime.thread.is_alive())


if __name__ == '__main__': unittest.main()
