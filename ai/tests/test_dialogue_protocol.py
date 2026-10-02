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
def endpoint(reject=False, finish='stop', tail_delay=0, disconnect=False, chunk_delay=0.2):
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
            if reject:
                body=json.dumps({'error':{'message':'Unknown parameter enable_thinking','type':'invalid_request_error'}}).encode()
                self.send_response(400); self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
            def chunk(delta,finish=None):
                return {'id':'fixture','object':'chat.completion.chunk','created':1,'model':payload['model'],
                    'choices':[{'index':0,'delta':delta,'finish_reason':finish}]}
            chunks=[chunk({'role':'assistant','content':'您好！'}),chunk({'content':'我可以介绍功能。'}),chunk({},finish),
                    {'id':'fixture','object':'chat.completion.chunk','created':1,'model':payload['model'],'choices':[],
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

    def run_text(self,cfg,runtime=None):
        state=AnalysisState('what can u do for me?',''); chunks=[]; started=time.monotonic()
        run_dialogue_turn(cfg,state,kind='conversation',cancel=threading.Event(),
                          on_text=lambda text:chunks.append((time.monotonic()-started,text)),runtime=runtime)
        return state,chunks

    def redirect(self,base):
        from openai import AsyncOpenAI, DefaultAsyncHttpxClient
        # Local protocol fixtures must reach the server directly. Product clients
        # still honor the user's proxy settings.
        return patch('openai.AsyncOpenAI',side_effect=lambda **kwargs:AsyncOpenAI(
            **{**kwargs,'base_url':base,'http_client':DefaultAsyncHttpxClient(trust_env=False)}))

    def test_output_token_truncation_is_not_published_as_complete(self):
        with endpoint(finish='length') as (base,requests,ports),self.redirect(base):
            state,chunks=self.run_text(config())
        self.assertEqual(len(requests),1)
        self.assertTrue(chunks)
        self.assertEqual(state.status,'partial')
        self.assertIn('未完成',state.report)

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
