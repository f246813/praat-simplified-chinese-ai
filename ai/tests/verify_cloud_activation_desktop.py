"""Production WebView2 cloud settings regression; isolated data, MOCK requests."""
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf8', errors='replace')

import webview
from praat_ai import modern_budget as budget
from praat_ai.modern_app import ModernApplication
from praat_ai.modern_host import create_window


class MockExecutor:
    def __init__(self):
        self.calls = []

    def capture_target(self, text):
        return 'mock-target'

    def run(self, **values):
        self.calls.append(values)
        return dict(content='MOCK 完成（无云端请求）', status='complete', evidence=[], attempts=[])


result = dict(realWebView2=True, productionAssets=True, isolatedData=True, mockRequestsOnly=True, checks=[])
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    config = root / 'config.json'
    config.write_text(json.dumps(dict(
        api=dict(enabled=False, locked=False, base_url='https://gateway.example/v1', model='custom-model',
                 api_key='fixture-private-key', token_mode='manual', max_context_tokens=32768,
                 plan_max_tokens=1000, stop_local_service=False),
        qwen=dict(base_url='http://127.0.0.1:8999/v1', model='local', token_mode='manual'))), encoding='utf8')
    executor = MockExecutor()
    app = ModernApplication(root / 'modern', config, configured_cloud=True, executor=executor)
    session = app.store.new_session('云端启用离线夹具')['id']
    window, assets = create_window(app, hidden=True)

    def check():
        def js(code):
            return window.evaluate_js(code)

        def wait(code):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if js(code):
                    return
                time.sleep(.1)
            raise AssertionError('Timed out: ' + code)

        def click(selector):
            js('document.querySelector(' + json.dumps(selector, ensure_ascii=False) + ').click()')

        def button(text):
            js('[...document.querySelectorAll("button")].find(e=>e.textContent.trim()===' + json.dumps(text, ensure_ascii=False) + ').click()')

        try:
            wait('document.querySelector("[aria-label=打开设置]")')
            click('[aria-label="打开设置"]')
            button('模型')
            wait('document.querySelector("[aria-label=\\\"启用云端 API\\\"]")')
            result['userAgent'] = js('navigator.userAgent')
            assert app.bootstrap()['host']['cloudAllowed']
            assert not executor.calls
            assert not request.called
            assert not js('document.body.innerText.includes("--allow-cloud")')
            assert 'fixture-private-key' not in js('document.body.innerText')
            result['checks'].append('normal desktop policy enables settings test controls without CLI or startup requests')

            click('[aria-label="启用云端 API"]')
            button('保存更改')
            wait('document.querySelector("[role=status]")?.textContent.includes("设置已保存")')
            assert app.settings.candidate().api.enabled
            assert app.prepared().qwen.base_url == 'https://gateway.example/v1'
            assert not request.called and not executor.calls
            result['checks'].append('API enable/save takes effect in current desktop; saved key retained; no request on save')

            assert not js('[...document.querySelectorAll("button")].find(e=>e.textContent.trim()==="测试文字连接").disabled')
            button('测试文字连接')
            wait('document.querySelector("dialog[open]")?.textContent.includes("确认最小云端验证")')
            assert not request.called
            button('确认验证')
            wait('document.querySelector(".test-result .badge")?.textContent==="verified"')
            assert request.call_count == 1
            assert request.call_args.args[0].qwen.base_url == 'https://gateway.example/v1'
            assert 'fixture-private-key' not in js('document.body.innerText')
            result['checks'].append('test click retains confirmation and submits exactly one MOCK remote-config request')

            task = app.rpc('tasks.submit', dict(sessionId=session, text='离线发送夹具'))
            deadline = time.monotonic() + 10
            while app.tasks[task['id']]['status'] != 'complete' and time.monotonic() < deadline:
                time.sleep(.05)
            assert app.tasks[task['id']]['status'] == 'complete'
            assert len(executor.calls) == 1
            assert executor.calls[0]['config'].qwen.base_url == 'https://gateway.example/v1'
            result['checks'].append('normal task submit accepts enabled cloud configuration and uses MOCK executor')
            result['passed'] = True
        except Exception as error:
            result['passed'] = False
            result['error'] = repr(error)
            result['dom'] = js('document.body.innerText.slice(0,5000)')
        finally:
            app.close()
            output = Path(__file__).resolve().parents[2] / 'docs/ai-frontend/verification/cloud-api-activation-desktop-result.json'
            output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
            window.destroy()

    try:
        with patch.object(budget, 'text_request', return_value='MOCK OK（无云端请求）') as request, \
                patch('socket.socket.connect', side_effect=AssertionError('Unexpected network')):
            # Asset HTTP runs on loopback in WebView2, not this Python socket client.
            webview.start(check, gui='edgechromium', private_mode=True, storage_path=str(root / 'profile'))
    finally:
        app.close()
        assets.close()

print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(0 if result.get('passed') else 1)
