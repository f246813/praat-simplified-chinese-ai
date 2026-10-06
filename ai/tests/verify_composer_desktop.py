"""Visible production React/WebView2 composer acceptance with isolated settings/data.
No model, network verification, or Praat execution. Test-only executor refuses calls.
Run with the desktop Python: python ai/tests/verify_composer_desktop.py --output <scratch>/result.json
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from praat_ai.modern_app import ModernApplication
from praat_ai.modern_host import create_window
from praat_ai import modern_budget as budget


class NoExecution:
    def capture_target(self, text):
        raise AssertionError('Composer preview must not capture a Praat target')
    def run(self, **kwargs):
        raise AssertionError('Composer preview must not start execution')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import webview
    for key in list(os.environ):
        if key.startswith('PRAAT_AI_'): os.environ.pop(key)
    result = dict(checks=[], realWebView2=True, productionAssets=True,
                  isolatedSettings=True, realModelRequest=False, realPraat=False)
    with tempfile.TemporaryDirectory(dir=os.environ.get('PI_SCRATCH_DIR')) as temporary:
        root = Path(temporary)
        config = root / 'config.json'
        config.write_text(json.dumps(dict(api=dict(enabled=True, locked=False,
            base_url='http://127.0.0.1:8999/v1', model='fixture-model', api_key='isolated-secret',
            token_mode='manual', max_context_tokens=32768, plan_max_tokens=1000,
            stop_local_service=False), qwen=dict(model='preserved-local'), custom=dict(keep=True))), encoding='utf8')
        app = ModernApplication(root / 'modern', config, executor=NoExecution())
        sid = app.store.new_session('输入框隔离验收')['id']
        window, assets = create_window(app)
        def check():
            def js(code): return window.evaluate_js(code)
            def wait(code):
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if js(code): return
                    time.sleep(.1)
                raise AssertionError('Condition timed out: ' + code)
            def click(label):
                js("document.querySelector('[aria-label=" + json.dumps(label, ensure_ascii=False) + "]').click()")
            def passed(name): result['checks'].append(name)
            try:
                wait("document.querySelector('.composer-context-trigger')?.textContent.includes('%')")
                assert js('Object.keys(window.pywebview.api)') == ['rpc']
                assert not js("document.querySelector('.editor-toolbar small') || document.querySelector('.composer-actions>small')")
                assert '浏览器测试适配器' not in js('document.body.innerText')
                result['userAgent'] = js('navigator.userAgent')
                result['context'] = app.context_status(sid)
                click('上下文用量')
                wait("document.querySelector('.context-popover').matches(':popover-open')")
                wait("document.querySelector('.context-popover').getBoundingClientRect().bottom < document.querySelector('.composer-context-trigger').getBoundingClientRect().top")
                value = js("document.querySelector('.context-values dd').textContent.replaceAll(',','')")
                assert int(value) == result['context']['inputTokens']
                assert '估算' in js("document.querySelector('.context-popover').textContent")
                passed('host-backed-estimated-context-numbers-and-above-composer-popover')
                click('关闭上下文详情')
                click('切换模型与推理强度')
                wait("document.querySelector('.model-popover').matches(':popover-open')")
                js("Array.from(document.querySelectorAll('.quick-thinking button')).find(e=>e.title==='high').click()")
                wait("document.querySelector('.composer-model-trigger').textContent.includes(' · high')")
                # React controlled input through the native setter + bubbling event.
                js("const input=document.querySelector('.model-search input'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'next-fixture'); input.dispatchEvent(new Event('input',{bubbles:true}));")
                wait("document.querySelector('.quick-model-list').textContent.includes('next-fixture')")
                js("Array.from(document.querySelectorAll('.quick-model-list button')).find(e=>e.textContent.includes('next-fixture')).click()")
                wait("document.querySelector('.composer-model-trigger').textContent.includes('next-fixture · high')")
                raw = json.loads(config.read_text(encoding='utf8'))
                assert raw['api']['api_key'] == 'isolated-secret'
                assert raw['api']['base_url'] == 'http://127.0.0.1:8999/v1'
                assert raw['qwen']['model'] == 'preserved-local' and raw['custom']['keep']
                passed('quick-model-and-strength-persist-minimal-fields-with-key-and-endpoint-preserved')
                click('关闭模型选择')
                app.settings.save(dict(api=dict(token_mode='auto')))
                js('location.reload()')
                wait("document.querySelector('.composer-context-trigger')?.textContent==='—'")
                click('上下文用量')
                wait("document.querySelector('.context-popover').textContent.includes('窗口未知')")
                passed('unknown-window-without-fabricated-percentage')
                assert not app.tasks
                assert 'isolated-secret' not in js('document.body.innerText')
                passed('no-task-no-Praat-execution-no-credential-exposure')
                result['passed'] = True
            except Exception as error:
                result['passed'] = False
                result['error'] = str(error).replace('isolated-secret', '[redacted]')
            finally:
                window.destroy()
        with patch.object(budget, 'text_request', side_effect=AssertionError('No model requests allowed')) as request:
            try:
                webview.start(check, gui='edgechromium', debug=False, private_mode=True, storage_path=str(root / 'profile'))
                assert request.call_count == 0
            finally:
                app.close(); assets.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
