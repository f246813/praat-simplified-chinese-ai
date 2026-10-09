"""Production WebView2 result-list scrolling/prefetch with real host requests.

Hidden WebView2 throttles animation frames and skips hover-card display. Actual
transcript scrolling/reading writes are covered by browser/unit acceptance.
"""
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf8',errors='replace')
import webview
from praat_ai.modern_app import ModernApplication
from praat_ai.modern_host import create_window
from praat_ai import modern_budget as budget

class NoExecution:
    def run(self,**kwargs):raise AssertionError('Unexpected executor call')
    def capture_target(self,text):raise AssertionError('Unexpected Praat capture')

result=dict(productionAssets=True,realWebView2=True,isolatedData=True,checks=[])
with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary);config=root/'config.json';config.write_text('{}',encoding='utf8')
    app=ModernApplication(root/'modern',config,executor=NoExecution())
    for index in range(80):
        sid=app.store.new_session(f'历史记录 {index:02d}')['id']
        app.store.put_message(sid,dict(id=f'body-{index}',role='user',content='needle-only 正文命中样例'))
    active=app.store.new_session('阅读中的长会话')['id']
    for index in range(120):
        app.store.put_message(active,dict(id=f'long-{index}',role='user' if index%2==0 else 'assistant',content=f'第 {index} 条阅读材料\n\n'+('声学阅读段落。'*30),status='complete'))
    calls=[];original_rpc=app.rpc
    def rpc(method,params=None):
        if method in {'sessions.search','sessions.get','sessions.view'}:calls.append(dict(method=method,sessionId=(params or {}).get('sessionId')))
        return original_rpc(method,params)
    app.rpc=rpc
    window,assets=create_window(app,hidden=True)
    def check():
        def js(code):return window.evaluate_js(code)
        def wait(code):
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                if js(code):return
                time.sleep(.05)
            raise AssertionError('Timed out: '+code)
        def click(selector):js('document.querySelector('+json.dumps(selector,ensure_ascii=False)+').click()')
        def search_calls():return sum(c['method']=='sessions.search' for c in calls)
        try:
            wait('document.querySelector("[aria-label=展开会话侧栏]")');click('[aria-label="展开会话侧栏"]')
            wait('document.querySelectorAll(".session-row").length===81&&document.querySelectorAll(".message").length>0')
            js('(()=>{const e=document.querySelector(".session-search input");Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value").set.call(e,"needle-only");e.dispatchEvent(new Event("input",{bubbles:true}));})()')
            wait('document.querySelectorAll(".session-row").length===80&&!document.querySelector(".search-status")')
            assert search_calls()==1
            js('window.rowsBefore=new Map([...document.querySelectorAll(".session-row")].map(e=>[e.dataset.sessionId,e]));window.searchReloads=0;new MutationObserver(records=>{for(const r of records)for(const n of r.addedNodes){if(n instanceof Element&&(n.matches(".search-status")||n.querySelector(".search-status")))window.searchReloads++;}}).observe(document.querySelector(".session-list"),{childList:true,subtree:true});')
            # Drive the production handlers in the hidden native renderer.
            js('(()=>{const list=document.querySelector(".session-list");list.scrollTop=420;list.dispatchEvent(new Event("scroll",{bubbles:true}));const e=document.querySelectorAll(".session-select")[18];e.dispatchEvent(new PointerEvent("pointerover",{bubbles:true,pointerType:"mouse"}));e.dispatchEvent(new MouseEvent("mouseover",{bubbles:true}));})()')
            # The row's actual prefetch still runs while the window is hidden.
            deadline=time.monotonic()+5
            while time.monotonic()<deadline and sum(c['method']=='sessions.get' for c in calls)<2:time.sleep(.05)
            assert sum(c['method']=='sessions.get' for c in calls)>1
            sidebar_top=js('document.querySelector(".session-list").scrollTop');assert sidebar_top>300
            js('(()=>{const list=document.querySelector(".session-list");list.scrollTop=260;list.dispatchEvent(new Event("scroll",{bubbles:true}));})()')
            sidebar_top=js('document.querySelector(".session-list").scrollTop');assert sidebar_top>200
            click('[aria-label="刷新当前会话"]');time.sleep(.7)
            assert search_calls()==1,calls
            assert js('window.searchReloads')==0
            assert js('[...document.querySelectorAll(".session-row")].every(e=>window.rowsBefore.get(e.dataset.sessionId)===e)')
            assert abs(js('document.querySelector(".session-list").scrollTop')-sidebar_top)<2
            result['checks'].append('80 body results keep the same DOM rows and scroll position while scrolling the result list, prefetching a preview and refreshing unchanged history')
            result['searchCallsDuringBrowsing']=search_calls()
            app.store.put_message(active,dict(id='new-match',role='user',content='needle-only 新增正文命中'))
            click('[aria-label="刷新当前会话"]')
            wait('document.querySelectorAll(".session-row").length===81&&!document.querySelector(".search-status")')
            assert search_calls()==2
            result['checks'].append('real persisted message update still invalidates search and adds the newly matching conversation')
            assert not app.tasks
            result.update(passed=True,searchCallsAfterContentChange=search_calls(),userAgent=js('navigator.userAgent'))
        except Exception as error:
            result.update(passed=False,error=repr(error),calls=calls,diagnostic=js('({rows:document.querySelectorAll(".session-row").length,messages:document.querySelectorAll(".message").length,title:document.querySelector(".chat-header h1")?.textContent,hidden:document.hidden,loading:Boolean(document.querySelector(".search-status")),reloads:window.searchReloads,scroll:document.querySelector(".session-list")?.scrollTop,alerts:[...document.querySelectorAll("[role=alert]")].map(e=>e.textContent)})'))
        finally:window.destroy()
    with patch.object(budget,'text_request',side_effect=AssertionError('Unexpected model request')) as provider:
        try:
            webview.start(check,gui='edgechromium',private_mode=True,storage_path=str(root/'profile'))
            assert provider.call_count==0
        finally:app.close();assets.close()
output=Path(__file__).resolve().parents[2]/'test-records/frontend/search-scroll-desktop-result.json'
output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(0 if result.get('passed') else 1)
