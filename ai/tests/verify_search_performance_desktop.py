"""Production pywebview search on 500 isolated histories, with RPC accounting."""
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import webview
from praat_ai.modern_app import ModernApplication
from praat_ai.modern_host import create_window
from praat_ai import modern_budget as budget
from verify_search_performance import seed

class NoExecution:
    def capture_target(self,text):raise AssertionError('Unexpected Praat capture')
    def run(self,**kwargs):raise AssertionError('Unexpected executor call')

result=dict(realWebView2=True,productionAssets=True,isolatedData=True,sessions=500,messages=6000)
with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary);config=root/'config.json';config.write_text('{}',encoding='utf8')
    app=ModernApplication(root/'modern',config,executor=NoExecution());seed(app.store)
    calls=[];original=app.rpc
    def rpc(method,params=None):
        started=time.perf_counter();response=original(method,params)
        if method in {'sessions.get','sessions.search'}:calls.append(dict(method=method,ms=round((time.perf_counter()-started)*1000,2),bytes=len(json.dumps(response,ensure_ascii=False).encode('utf8'))))
        return response
    app.rpc=rpc
    window,assets=create_window(app,hidden=True)
    def check():
        from System import Func,Object
        def js(code):return window.evaluate_js(code)
        def wait(code):
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                if js(code):return
                time.sleep(.02)
            raise AssertionError('Timed out: '+code)
        def insert(text):
            task=window.native.Invoke(Func[Object](lambda:window.native.webview.CoreWebView2.CallDevToolsProtocolMethodAsync('Input.insertText',json.dumps(dict(text=text)))))
            return str(task.Result)
        try:
            wait('document.querySelector("[aria-label=展开会话侧栏]")');js('document.querySelector("[aria-label=展开会话侧栏]").click()')
            wait('document.querySelectorAll(".session-row").length===500')
            wait('document.querySelectorAll(".message").length>0')
            initial_get=sum(c['method']=='sessions.get' for c in calls)
            js('window.searchInput=document.querySelector(".session-search input");searchInput.focus()')
            started=time.perf_counter();insert('needle-499')
            wait('document.querySelectorAll(".session-row").length===1&&document.querySelector(".session-row").dataset.sessionId==="s499"&&!document.querySelector(".search-status")')
            result['inputToResultMilliseconds']=round((time.perf_counter()-started)*1000,2)
            result['fullHistoryRequestsDuringSearch']=sum(c['method']=='sessions.get' for c in calls)-initial_get
            searches=[c for c in calls if c['method']=='sessions.search'];result['searchRequests']=len(searches);result['searchRPC']=searches
            assert result['fullHistoryRequestsDuringSearch']==0 and len(searches)==1,calls
            assert js('document.activeElement===searchInput&&searchInput.isConnected')
            assert js('getComputedStyle(searchInput).outlineStyle')=='none'
            assert not app.tasks
            result.update(passed=True,userAgent=js('navigator.userAgent'))
        except Exception as error:result.update(passed=False,error=repr(error))
        finally:window.destroy()
    with patch.object(budget,'text_request',side_effect=AssertionError('Unexpected model request')) as provider:
        try:
            webview.start(check,gui='edgechromium',private_mode=True,storage_path=str(root/'profile'));assert provider.call_count==0
        finally:app.close();assets.close()
output=Path(__file__).resolve().parents[2]/'docs/ai-frontend/verification/search-performance-desktop-result.json'
output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(0 if result.get('passed') else 1)
