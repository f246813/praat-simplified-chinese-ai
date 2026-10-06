"""Production React + real WebView2 acceptance; isolated store, no execution/model calls."""
from __future__ import annotations
import argparse
import hashlib
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
from praat_ai.modern_store import ModernStore
from praat_ai import modern_budget as budget

class NoExecution:
    def capture_target(self, text): raise AssertionError('No Praat target capture allowed')
    def run(self, **kwargs): raise AssertionError('No execution allowed')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    import webview
    for key in list(os.environ):
        if key.startswith('PRAAT_AI_'): os.environ.pop(key)
    result=dict(checks=[],realWebView2=True,productionAssets=True,isolatedData=True,realModelRequest=False,realPraat=False)
    with tempfile.TemporaryDirectory(dir=os.environ.get('PI_SCRATCH_DIR')) as temporary:
        root=Path(temporary);config=root/'config.json'
        config.write_text(json.dumps(dict(qwen=dict(model='isolated-fixture',token_mode='manual',max_context_tokens=32768,plan_max_tokens=1000))),encoding='utf8')
        config_hash=hashlib.sha256(config.read_bytes()).hexdigest()
        app=ModernApplication(root/'modern',config,executor=NoExecution())
        older=app.store.new_session('待置顶会话')['id'];newer=app.store.new_session('较新会话')['id']
        app.store.view(older,draft='保留的草稿',scroll=42)
        before=app.store.get(older)
        window,assets=create_window(app)
        def check():
            def js(code):return window.evaluate_js(code)
            def wait(code):
                end=time.monotonic()+20
                while time.monotonic()<end:
                    if js(code):return
                    time.sleep(.1)
                raise AssertionError('Timed out: '+code)
            def click(label):js("document.querySelector('[aria-label="+json.dumps(label,ensure_ascii=False)+"]').click()")
            def item(name):js("document.querySelector('[data-context-menu-item="+json.dumps(name)+"]').click()")
            def passed(name):result['checks'].append(name)
            def first():return js("document.querySelector('.session-row')?.dataset.sessionId")
            try:
                wait("document.querySelector('.composer-context-trigger')")
                assert js('Object.keys(window.pywebview.api)')==['rpc']
                assert '浏览器测试适配器' not in js('document.body.innerText')
                result['userAgent']=js('navigator.userAgent');click('展开会话侧栏')
                wait("document.querySelectorAll('.session-row').length===2")
                assert first()==newer
                click('会话操作 待置顶会话');wait("document.querySelector('.context-menu.is-open')")
                assert js("Array.from(document.querySelectorAll('[role=menuitem]')).map(e=>e.textContent)")==['重命名','置顶','删除']
                item('toggle-session-pin');wait("document.querySelector('.session-row').dataset.pinned==='true'")
                assert first()==older and app.store.get(older)['session']['pinned']
                assert {k:v for k,v in app.store.get(older)['session'].items() if k!='pinned'}=={k:v for k,v in before['session'].items() if k!='pinned'}
                assert app.store.get(older)['messages']==before['messages']
                passed('left-click-menu-host-pin-order-and-original-dialogue-view-preserved')
                # Reopen the isolated SQLite service object, then reload the production page.
                app.store=ModernStore(app.store.path,secrets=())
                js('location.reload()');wait("document.querySelector('.composer-context-trigger')");click('展开会话侧栏')
                wait("document.querySelector('.session-row')?.dataset.pinned==='true'");assert first()==older
                passed('pin-survives-store-reopen-and-production-page-reload-not-OS-process-restart')
                click('会话操作 待置顶会话');wait("document.querySelector('.context-menu.is-open')");item('toggle-session-pin')
                wait("document.querySelector('.session-row')?.dataset.sessionId==="+json.dumps(newer))
                click('会话操作 待置顶会话');wait("document.querySelector('.context-menu.is-open')");item('rename-session')
                wait("document.querySelector('dialog[open] input')")
                js("const input=document.querySelector('dialog input'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'已重命名');input.dispatchEvent(new Event('input',{bubbles:true}));")
                js("Array.from(document.querySelectorAll('dialog button')).find(e=>e.textContent==='确认').click()")
                wait("document.querySelector('[aria-label=\"会话操作 已重命名\"]')")
                click('会话操作 已重命名');wait("document.querySelector('.context-menu.is-open')");item('delete-session');wait("document.querySelector('dialog[open]')")
                assert app.store.get(older)
                js("Array.from(document.querySelectorAll('dialog button')).find(e=>e.textContent==='取消').click()")
                wait("!document.querySelector('dialog[open]')");assert app.store.get(older)
                passed('unpin-and-rename-use-host-delete-requires-confirmation-cancel-preserves-record')
                result['scrollbar']=js("getComputedStyle(document.querySelector('.transcript'),'::-webkit-scrollbar').width")
                assert result['scrollbar']=='6px'
                js("document.querySelector('.transcript').dispatchEvent(new Event('scroll'))")
                assert js("document.querySelector('.transcript').hasAttribute('data-scrolling')")
                wait("!document.querySelector('.transcript').hasAttribute('data-scrolling')")
                assert hashlib.sha256(config.read_bytes()).hexdigest()==config_hash and not app.tasks
                passed('6px-production-scrollbar-reveal-and-no-config-task-model-or-Praat-operation')
                result['passed']=True
            except Exception as error:result.update(passed=False,error=str(error))
            finally:window.destroy()
        with patch.object(budget,'text_request',side_effect=AssertionError('No model request allowed')) as request:
            try:
                webview.start(check,gui='edgechromium',debug=False,private_mode=True,storage_path=str(root/'profile'))
                assert request.call_count==0
            finally:app.close();assets.close()
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(result,ensure_ascii=False));return 0 if result.get('passed') else 1
if __name__=='__main__':raise SystemExit(main())
