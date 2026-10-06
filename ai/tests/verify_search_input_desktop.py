"""Production WebView2 search composition acceptance with isolated host data."""
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
sys.path.insert(0,str(Path.cwd()/'ai'))
import webview
from praat_ai.modern_app import ModernApplication
from praat_ai.modern_host import create_window
from praat_ai import modern_budget as budget

class NoExecution:
    def capture_target(self,text):raise AssertionError('Unexpected Praat capture')
    def run(self,**kwargs):raise AssertionError('Unexpected executor call')

result=dict(realWebView2=True,productionAssets=True,checks=[])
with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary);config=root/'config.json';config.write_text('{}',encoding='utf8')
    app=ModernApplication(root/'modern',config,executor=NoExecution());app.store.new_session('输入法搜索验收')
    window,assets=create_window(app,hidden=True)
    def check():
        from System import Func,Object
        def js(code):return window.evaluate_js(code)
        def wait(code):
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                if js(code):return
                time.sleep(.1)
            raise AssertionError('Timed out: '+code)
        def cdp(method,params):
            task=window.native.Invoke(Func[Object](lambda:window.native.webview.CoreWebView2.CallDevToolsProtocolMethodAsync(method,json.dumps(params))))
            return str(task.Result)
        def sample(selector):
            js('(()=>{window.testInput=document.querySelector('+json.dumps(selector)+');testInput.focus();window.compositionEvents=[];for(const name of ["compositionstart","compositionupdate","compositionend"])testInput.addEventListener(name,event=>compositionEvents.push({type:event.type,data:event.data}));})()')
            assert js('getComputedStyle(testInput).outlineStyle')=='none'
            cdp('Input.imeSetComposition',dict(text='nihon',selectionStart=0,selectionEnd=5))
            cdp('Input.insertText',dict(text='日本'))
            wait('testInput.value==="日本"')
            assert js('testInput.isConnected&&document.activeElement===testInput')
            events=js('compositionEvents');assert any(e['type']=='compositionstart' for e in events) and any(e['type']=='compositionend' for e in events),events
            return dict(value=js('testInput.value'),events=events,outline=js('getComputedStyle(testInput).outlineStyle'))
        try:
            wait('document.querySelector("[aria-label=展开会话侧栏]")');js('document.querySelector("[aria-label=展开会话侧栏]").click()');wait('document.querySelector(".session-search input")')
            result['sidebar']=sample('.session-search input')
            js('document.querySelector('+json.dumps('[aria-label="在会话中查找（Ctrl / Cmd + K）"]',ensure_ascii=False)+').click()')
            wait('document.querySelector(".chat-search-input")');result['find']=sample('.chat-search-input')
            for key in ['Enter','Escape']:
                assert not js('(()=>{const event=new KeyboardEvent("keydown",{key:'+json.dumps(key)+',bubbles:true,cancelable:true,isComposing:true});testInput.dispatchEvent(event);return event.defaultPrevented;})()')
                assert js('testInput.isConnected&&document.activeElement===testInput')
            result['imeMode']=str(window.native.webview.ImeMode)
            assert result['imeMode']!='Disable',result['imeMode']
            assert not app.tasks
            result.update(passed=True,userAgent=js('navigator.userAgent'))
            result['checks']=['focused search inputs have no green outline','WebView2 native composition/start/update/end commits Japanese text in both inputs','focused input identity survives composition and filtering','composing Enter/Escape are not prevented or used to close search','WebView2 IME mode is not Disable; no language-switch or executor calls']
        except Exception as error:result.update(passed=False,error=repr(error))
        finally:window.destroy()
    with patch.object(budget,'text_request',side_effect=AssertionError('Unexpected model request')) as request:
        try:
            webview.start(check,gui='edgechromium',private_mode=True,storage_path=str(root/'profile'));assert request.call_count==0
        finally:app.close();assets.close()
output=Path.cwd()/'docs/ai-frontend/verification/search-input-desktop-result.json';output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(result,indent=2));raise SystemExit(0 if result.get('passed') else 1)
