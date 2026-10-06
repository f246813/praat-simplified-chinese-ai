"""Real Pydantic AI / OpenAI SDK against an isolated local HTTP endpoint."""
import base64
import json
import tempfile
import threading
import unittest
import wave
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from praat_ai.config import AppConfig, apply_api_to_qwen
from praat_ai.escape_policy import AnalysisState
from praat_ai.materials import TaskMaterials
from praat_ai.cloud_agent import run_cloud_turn


@contextmanager
def endpoint(reject_audio=False, reject_reasoning=False, always_rate_limit=False):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(request)
            audio = any(isinstance(m.get('content'), list) and any(p.get('type') == 'input_audio' for p in m['content']) for m in request['messages'])
            error = ('This model does not support audio input' if reject_audio and audio else
                     'Unknown parameter reasoning_effort' if reject_reasoning and 'reasoning_effort' in request else
                     'Rate limited' if always_rate_limit else '')
            if error:
                payload = json.dumps({'error':{'message':error, 'type':'invalid_request_error', 'code':'bad_request'}}).encode()
                self.send_response(429 if always_rate_limit else 400)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            content = json.dumps({'analysis':'原始材料提供了模型音频分析依据；定性判断需要结合专业测量，当前报告解释原目标并明确未完成部分。',
                       'coverage':[{'item':'直接听原始音频', 'status':'partial', 'explanation':'音频定性分析可用，缺少专业参考测量。'}]}, ensure_ascii=False)
            if request.get('stream'):
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                chunks = [dict(id='test', object='chat.completion.chunk', created=1, model=request['model'], choices=[{'index':0,'delta':{'role':'assistant','content':content},'finish_reason':None}]),
                          dict(id='test', object='chat.completion.chunk', created=1, model=request['model'], choices=[{'index':0,'delta':{},'finish_reason':'stop'}]),
                          dict(id='test', object='chat.completion.chunk', created=1, model=request['model'], choices=[], usage={'prompt_tokens':300,'completion_tokens':100,'total_tokens':400})]
                for chunk in chunks:
                    self.wfile.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
                self.wfile.write(b'data: [DONE]\n\n')
            else:
                payload = json.dumps({'id':'test','object':'chat.completion','created':1,'model':request['model'],
                           'choices':[{'index':0,'message':{'role':'assistant','content':content},'finish_reason':'stop'}],
                           'usage':{'prompt_tokens':300,'completion_tokens':100,'total_tokens':400}}).encode()
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', requests
    finally:
        server.shutdown()
        server.server_close()
        worker.join()


class ProtocolTests(unittest.TestCase):
    def run_audio(self, base, model='qwen3.8-omni-flash', **kwargs):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source.wav'
            with wave.open(str(source),'wb') as wav:
                wav.setparams((1,2,16000,0,'NONE','not compressed'))
                wav.writeframes(b'\0\0' * 1600)
            material = TaskMaterials(Path(directory) / 'tasks')
            material.snapshot_wav(source)
            config = AppConfig()
            config.api.enabled = True
            config.api.base_url, config.api.model = base, model
            config.api.api_key = 'test-placeholder'
            config.api.audio_input_enabled = True
            config.api.thinking_level = 'medium'
            apply_api_to_qwen(config)
            state = AnalysisState('直接听原始音频', '')
            corrections = []
            run_cloud_turn(config,state,execute_action=lambda *_:self.fail('No Praat operation required'),
                           cancel=threading.Event(), materials=material,
                           correct_audio=corrections.append, **kwargs)
            material.close()
            return state, corrections

    def test_qwen_stream_uri_and_text_output(self):
        with endpoint() as (base, requests):
            state, _ = self.run_audio(base)
        self.assertTrue(state.audio_received, state.reason)
        self.assertEqual(state.mode,'L3')
        self.assertEqual(len(requests),1)
        request = requests[0]
        self.assertTrue(request['stream'])
        self.assertEqual(request['modalities'],['text'])
        self.assertEqual(request['reasoning_effort'],'medium')
        audio = [p for m in request['messages'] if isinstance(m['content'],list) for p in m['content'] if p['type']=='input_audio'][0]
        self.assertTrue(audio['input_audio']['data'].startswith('data:'))
        self.assertTrue(base64.b64decode(audio['input_audio']['data'].split(',')[1]).startswith(b'RIFF'))

    def test_audio_rejection_redirects_once_without_audio(self):
        with endpoint(reject_audio=True) as (base, requests):
            state, corrections = self.run_audio(base)
        self.assertEqual(len(requests),2, state.reason)
        self.assertEqual(len(corrections),1)
        self.assertEqual(state.mode,'L2')
        self.assertFalse(state.audio_received)
        self.assertFalse(any(isinstance(m.get('content'), list) and any(p.get('type') == 'input_audio'
                         for p in m['content']) for m in requests[1]['messages']))
        self.assertTrue(state.metrics.get('report_verified'), state.reason)
        self.assertTrue(state.report)

    def test_reasoning_rejected_field_retry(self):
        with endpoint(reject_reasoning=True) as (base, requests):
            state, _ = self.run_audio(base, model='gemini-3.8-flash')
        self.assertEqual(len(requests),2)
        self.assertTrue(state.audio_received, state.reason)
        self.assertNotIn('reasoning_effort',requests[1])

    def test_rate_limit_does_not_correct_capability_or_loop(self):
        with endpoint(always_rate_limit=True) as (base, requests):
            state, corrections = self.run_audio(base, model='gemini-3.8-flash')
        self.assertEqual(len(requests),2)
        self.assertEqual(corrections,[])
        self.assertTrue(state.report)


if __name__ == '__main__':
    unittest.main()
