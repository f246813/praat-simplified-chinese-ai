"""SDK/SSE over localhost, including actual Qwen fields and TCP reuse."""
import json
import threading
import time
import unittest
import asyncio
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from praat_ai.cloud_agent import CloudRuntime, run_dialogue_turn
from praat_ai.escape_policy import AnalysisState
from test_dialogue_stream import config


@contextmanager
def endpoint(reject=False, finish='stop', tail_delay=0, disconnect=False, chunk_delay=0.2,
             finish_sequence=None, bodies=None, reject_output_at=0,
             reject_output_message='max_tokens is too large: this model supports at most 8192 output tokens'):
    requests=[]; ports=[]
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*_): pass
        def handle(self):
            try: super().handle()
            except ConnectionError: pass  # Expected for cancellation/tail timeout.
        def do_POST(self):
            payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(payload); ports.append(self.client_address[1])
            index=len(requests)
            if reject:
                body=json.dumps({'error':{'message':'Unknown parameter enable_thinking','type':'invalid_request_error'}}).encode()
                self.send_response(400); self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
            if reject_output_at and index == reject_output_at:
                body=json.dumps({'error':{'message':reject_output_message,'type':'invalid_request_error'}}).encode()
                self.send_response(400); self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
            def chunk(delta,finish=None):
                return {'id':'fixture','object':'chat.completion.chunk','created':1,'model':payload['model'],
                    'choices':[{'index':0,'delta':delta,'finish_reason':finish}]}
            current_finish=(finish_sequence[index-1] if finish_sequence and index-1 < len(finish_sequence)
                            else finish)
            if bodies and index-1 < len(bodies):
                text=[chunk({'role':'assistant','content':bodies[index-1]}),chunk({},current_finish)]
            else:
                text=[chunk({'role':'assistant','content':'您好！'}),chunk({'content':'我可以介绍功能。'}),
                      chunk({},current_finish)]
            chunks=text+[{'id':'fixture','object':'chat.completion.chunk','created':1,'model':payload['model'],'choices':[],
                     'usage':{'prompt_tokens':30,'completion_tokens':15,'total_tokens':45,
                              'completion_tokens_details':{'reasoning_tokens':7}}}]
            data=[('data: '+json.dumps(item)+'\n\n').encode() for item in chunks]+[b'data: [DONE]\n\n']
            tail=b'\n' if tail_delay else b''
            self.send_response(200); self.send_header('Content-Type','text/event-stream')
            self.send_header('Content-Length',str(sum(map(len,data))+len(tail))); self.end_headers()
            for index,item in enumerate(data):
                try: self.wfile.write(item); self.wfile.flush()
                except OSError: return
                if index==0: time.sleep(chunk_delay)
                if disconnect:
                    self.close_connection=True
                    return
            if tail:
                time.sleep(tail_delay)
                try: self.wfile.write(tail); self.wfile.flush()
                except OSError: pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}/v1',requests,ports
    finally: server.shutdown(); server.server_close(); thread.join()


class DialogueProtocolTests(unittest.TestCase):
    def test_clean_http_eof_without_a_completion_marker_is_partial(self):
        import httpx2
        from openai import AsyncOpenAI
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider
        from praat_ai.cloud_stream import enable_stream_reuse
        payload={'id':'fixture','object':'chat.completion.chunk','created':1,'model':'fixture',
                 'choices':[{'index':0,'delta':{'content':'unfinished answer'},'finish_reason':None}]}
        body=('data: '+json.dumps(payload)+'\n\n').encode()
        def transport(request):
            return httpx2.Response(200,headers={'content-type':'text/event-stream'},content=body)
        client=AsyncOpenAI(api_key='fixture',http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(transport)))
        enable_stream_reuse(client)
        model=OpenAIChatModel('fixture',provider=OpenAIProvider(openai_client=client))
        state=AnalysisState('hello',''); chunks=[]
        try:
            run_dialogue_turn(config(),state,kind='conversation',cancel=threading.Event(),on_text=chunks.append,model=model)
        finally: asyncio.run(client.close())
        self.assertEqual(state.requests,1)
        self.assertEqual(state.status,'partial')
        self.assertIn('未完成',state.report)

    def run_text(self,cfg,runtime=None,request_limit=None,text='what can u do for me?',kind='conversation'):
        state=AnalysisState(text,''); chunks=[]; started=time.monotonic()
        if request_limit is not None: state.budget.request_limit=request_limit
        run_dialogue_turn(cfg,state,kind=kind,cancel=threading.Event(),
                          on_text=lambda delta:chunks.append((time.monotonic()-started,delta)),runtime=runtime)
        return state,chunks

    def redirect(self,base):
        from openai import AsyncOpenAI, DefaultAsyncHttpxClient
        # Local protocol fixtures must reach the server directly. Product clients
        # still honor the user's proxy settings.
        return patch('openai.AsyncOpenAI',side_effect=lambda **kwargs:AsyncOpenAI(
            **{**kwargs,'base_url':base,'http_client':DefaultAsyncHttpxClient(trust_env=False)}))

    def test_truncated_reply_is_continued_once_and_merged(self):
        with endpoint(finish_sequence=('length','stop'),bodies=('前半段。','后半段。')) as (base,requests,ports),\
                self.redirect(base):
            state,chunks=self.run_text(config())
        # 第一次被 length 截断 → 自动续写一次（有界）；两段都逐段显示，最终合起来才算完成。
        self.assertEqual(len(requests),2)
        self.assertEqual(state.status,'complete',state.reason)
        written=''.join(text for _,text in chunks)
        self.assertEqual(state.report,written)
        self.assertIn('前半段',state.report); self.assertIn('后半段',state.report)
        # 续写请求要带上已写内容，让模型接着写而不是重写。
        self.assertIn('前半段',json.dumps(requests[1],ensure_ascii=False))

    def test_truncated_reply_keeps_the_written_text_when_continuation_truncates(self):
        with endpoint(finish='length') as (base,requests,ports),self.redirect(base):
            state,chunks=self.run_text(config())
        # 续写又被截断：有界重试到此为止，已经流出的正文必须留在最终消息里，并标未完成。
        self.assertEqual(len(requests),2)
        self.assertTrue(chunks)
        self.assertEqual(state.status,'partial')
        written=''.join(text for _,text in chunks)
        self.assertTrue(state.report.startswith(written))
        self.assertNotEqual(state.report,written)
        self.assertIn('未完成',state.report)
        self.assertIn('长度上限',state.report)

    def test_truncated_reply_is_not_continued_when_the_request_budget_is_spent(self):
        with endpoint(finish='length') as (base,requests,ports),self.redirect(base):
            state,chunks=self.run_text(config(),request_limit=1)
        self.assertEqual(len(requests),1)
        self.assertTrue(chunks)
        self.assertEqual(state.status,'partial')
        self.assertTrue(state.report.startswith(''.join(text for _,text in chunks)))

    def test_rejected_output_limit_is_lowered_once_instead_of_failing_the_turn(self):
        with endpoint(reject_output_at=1,
                      reject_output_message='max_tokens is too large: this model supports at most 256 output tokens'
                      ) as (base,requests,ports),self.redirect(base):
            state,chunks=self.run_text(config())
        self.assertEqual(len(requests),2)
        self.assertEqual(state.status,'complete',state.reason)
        cap=lambda payload:payload.get('max_completion_tokens',payload.get('max_tokens'))
        self.assertIsNotNone(cap(requests[0]))
        self.assertLessEqual(cap(requests[1]),256)
        self.assertTrue(chunks)

    def test_provider_output_cap_also_bounds_the_reasoning_allowance(self):
        # 概念对话 + 最高思考档：正文 2048 + 推理 8192 = 10240，超过百炼/DeepSeek 的 8192。
        # 只砍正文修不好（推理仍在），所以重试必须让「正文 + 推理」一起落回上限内。
        with endpoint(reject_output_at=1) as (base,requests,ports),self.redirect(base):
            state,chunks=self.run_text(config(),text='什么是HNR',kind='concept')
        self.assertEqual(len(requests),2)
        self.assertEqual(state.status,'complete',state.reason)
        cap=lambda payload:payload.get('max_completion_tokens',payload.get('max_tokens'))
        self.assertGreater(cap(requests[0]),8192)
        self.assertLessEqual(cap(requests[1]),8192)
        self.assertTrue(chunks)

    def test_provider_without_a_named_limit_drops_the_reasoning_allowance(self):
        with endpoint(reject_output_at=1,reject_output_message='max_tokens is not supported by this model'
                      ) as (base,requests,ports),self.redirect(base):
            state,chunks=self.run_text(config(),text='什么是HNR',kind='concept')
        self.assertEqual(len(requests),2)
        self.assertEqual(state.status,'complete',state.reason)
        cap=lambda payload:payload.get('max_completion_tokens',payload.get('max_tokens'))
        # 读不出上限：先让掉这次新增的推理额度，正文维持原样（= 旧版本的请求形状）。
        # 正文 = min(预算 1500, dialogue_max_tokens 2048)，推理不再额外留。
        self.assertEqual(cap(requests[1]),1500)
        self.assertTrue(chunks)

    def test_optional_protocol_tail_is_bounded_after_done(self):
        with endpoint(tail_delay=1.0) as (base,requests,ports),self.redirect(base):
            started=time.monotonic(); state,_=self.run_text(config())
            elapsed=time.monotonic()-started
        self.assertEqual(state.status,'complete',state.reason)
        self.assertLess(elapsed,0.85)

    def test_disconnect_after_first_text_is_not_retried_or_saved_as_complete(self):
        with endpoint(disconnect=True) as (base,requests,ports),self.redirect(base):
            state,chunks=self.run_text(config())
        self.assertTrue(chunks)
        self.assertEqual(len(requests),1)
        self.assertEqual(state.status,'partial')

    def test_cancelled_socket_does_not_break_the_next_turn(self):
        runtime=CloudRuntime(); cfg=config(); cancel=threading.Event()
        state=AnalysisState('hello','')
        with endpoint() as (base,requests,ports),self.redirect(base):
            try:
                run_dialogue_turn(cfg,state,kind='conversation',cancel=cancel,
                                  on_text=lambda _:cancel.set(),runtime=runtime)
                next_state,_=self.run_text(cfg,runtime)
            finally: runtime.close(wait=True)
        self.assertEqual(state.status,'cancelled')
        self.assertEqual(next_state.status,'complete',next_state.reason)
        self.assertEqual(len(requests),2)

    def test_qwen_off_is_in_actual_request_and_first_text_precedes_finish(self):
        with endpoint() as (base,requests,ports),self.redirect(base):
            state,chunks=self.run_text(config())
        self.assertEqual(len(requests),1); self.assertEqual(state.status,'complete',state.reason)
        payload=requests[0]
        self.assertTrue(payload['stream']); self.assertFalse(payload['enable_thinking'])
        self.assertNotIn('reasoning_effort',payload); self.assertFalse(payload.get('tools'))
        self.assertEqual(state.report,''.join(text for _,text in chunks))
        self.assertLess(chunks[0][0]+0.08,state.metrics['total_seconds'])
        self.assertEqual(state.metrics['reasoning_tokens'],7)

    def test_same_socket_reused_and_changed_force_setting_applies_immediately(self):
        runtime=CloudRuntime(); cfg=config()
        with endpoint() as (base,requests,ports),self.redirect(base):
            try:
                self.run_text(cfg,runtime); self.run_text(cfg,runtime)
                cfg.api.force_deep_thinking=True; self.run_text(cfg,runtime)
            finally: runtime.close(wait=True)
        self.assertEqual(len(set(ports)),1)
        self.assertEqual([p['enable_thinking'] for p in requests],[False,False,True])

    def test_rejected_forced_high_is_not_silently_disabled_and_retried(self):
        cfg=config(); cfg.api.force_deep_thinking=True
        with endpoint(reject=True) as (base,requests,ports),self.redirect(base):
            state,_=self.run_text(cfg)
        self.assertEqual(len(requests),1)
        self.assertTrue(requests[0]['enable_thinking'])
        self.assertEqual(state.status,'partial'); self.assertIn('未完成',state.report)


if __name__=='__main__': unittest.main()
