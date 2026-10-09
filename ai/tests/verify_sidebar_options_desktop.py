"""Real production WebView2 menu/origin acceptance using isolated history only."""
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
from praat_ai.modern_settings import SettingsService
from praat_ai import modern_budget as budget

class NoExecution:
    def capture_target(self,text):raise AssertionError('Unexpected Praat capture')
    def run(self,**kwargs):raise AssertionError('Unexpected executor call')

result=dict(realWebView2=True,productionAssets=True,isolatedData=True,checks=[])
output=Path(__file__).resolve().parents[2]/'test-records/frontend/sidebar-options-desktop-result.json'
with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary);config=root/'config.json';config.write_text('{"fixture":"sidebar-options"}',encoding='utf8')
    app=ModernApplication(root/'modern',config,executor=NoExecution())
    local=app.store.new_session('本地分析')['id']
    remote=app.store.new_session('远程来源样例')['id']
    section=app.store.organization.create('保留的研究分区')['id']
    member=app.store.organization.create_session('分区原有会话',section)['id']
    # Explicit fixture of a preserved origin; this does not connect to SSH.
    with app.store.connect() as db:
        db.execute('UPDATE sessions SET project_path=?,connection_id=?,connection_label=? WHERE id=?',('/srv/audio','ssh:fixture','实验室主机（验收样例）',remote))
    window,assets=create_window(app,hidden=True)

    def check():
        def js(code):return window.evaluate_js(code)
        def wait(code):
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                if js(code):return
                time.sleep(.05)
            raise AssertionError('Timed out: '+code)
        def click(selector):
            # A hidden WebView2 does not deliver CDP mouse clicks. Dispatch the
            # production pointer handler; browser acceptance uses real input.
            js('(()=>{const e=document.querySelector('+json.dumps(selector,ensure_ascii=False)+');e.dispatchEvent(new PointerEvent("pointerdown",{bubbles:true,pointerType:"mouse",button:0,buttons:1}));e.click();e.dispatchEvent(new PointerEvent("pointerup",{bubbles:true,pointerType:"mouse",button:0}));})()')
        def hover_menu(label):
            wait('Boolean([...document.querySelectorAll("[role=menuitem]")].find(e=>e.textContent.trim()==='+json.dumps(label,ensure_ascii=False)+'))')
            js('(()=>{let e=[...document.querySelectorAll("[role=menuitem]")].find(e=>e.textContent.trim()==='+json.dumps(label,ensure_ascii=False)+');let r=e.getBoundingClientRect();e.dispatchEvent(new PointerEvent("pointermove",{bubbles:true,pointerType:"mouse",clientX:r.x+r.width/2,clientY:r.y+r.height/2}));})()')
            wait('document.querySelector('+json.dumps('[role="menu"][aria-label="'+label+'"]',ensure_ascii=False)+')')
        def choose(menu,label):
            click('[aria-label="会话历史选项"][type="button"]');hover_menu(menu)
            js('[...document.querySelectorAll("[role=menuitemradio]")].find(e=>e.textContent.trim()==='+json.dumps(label,ensure_ascii=False)+').click()')
            wait('!document.querySelector("[role=menu]")')
        try:
            result['stage']='bootstrap';print('Production WebView2: bootstrap',flush=True)
            wait('document.querySelector("[aria-label=展开会话侧栏]")')
            assert js('!document.querySelector('+json.dumps('[aria-label="搜索 / 浏览历史会话"]',ensure_ascii=False)+')')
            click('[aria-label="打开设置"]')
            wait('document.querySelector(".settings-main h1")?.textContent==="会话与存储"')
            assert js('document.querySelector(".settings-nav [aria-current=page]")?.textContent')=='会话与存储'
            js('[...document.querySelectorAll("button")].find(e=>e.textContent.trim()==="返回聊天").click()')
            wait('document.querySelector(".model-button")');click('.model-button')
            wait('document.querySelector(".settings-main h1")?.textContent==="模型"')
            js('[...document.querySelectorAll("button")].find(e=>e.textContent.trim()==="返回聊天").click()')
            wait('document.querySelector("[aria-label=展开会话侧栏]")')
            click('[aria-label="展开会话侧栏"]');wait('document.querySelectorAll(".session-row").length===3')
            click('[aria-label="打开设置"]')
            wait('document.querySelector(".settings-main h1")?.textContent==="会话与存储"')
            js('[...document.querySelectorAll("button")].find(e=>e.textContent.trim()==="返回聊天").click()')
            wait('document.querySelectorAll(".session-row").length===3')
            result['checks'].append('collapsed search shortcut removed; collapsed/expanded gear opens storage category; model settings still opens model category')
            assert js('Object.keys(window.pywebview.api)')==['rpc']
            assert js('document.querySelectorAll(".sidebar-origin-group").length')==2
            result['stage']='menu';print('Production WebView2: menu',flush=True)
            click('[aria-label="会话历史选项"][type="button"]')
            wait('document.querySelectorAll("[role=menuitem]").length===2')
            hover_menu('聊天排序方式')
            labels=js('[...document.querySelectorAll("[role=menuitemradio]")].map(e=>e.textContent.trim())')
            assert labels==['最近更新','最早创建','按名称','最近创建'],labels
            assert js('!document.querySelector("[aria-label=会话排序]")')
            # Drive the production handler in this hidden native renderer.
            # Browser acceptance separately verifies actual keyboard input.
            js('document.activeElement.dispatchEvent(new KeyboardEvent("keydown",{bubbles:true,key:"Escape",code:"Escape"}))')
            wait('!document.querySelector("[role=menu]")')
            wait('document.activeElement?.getAttribute("aria-label")==="会话历史选项"')
            result['checks'].append('production pointer/keyboard handlers open sort flyout and restore focus; four choices once each')
            result['stage']='grouping';print('Production WebView2: grouping',flush=True)
            choose('聊天排序方式','按名称')
            wait('document.querySelectorAll(".sidebar-time-group-header").length===0')
            assert SettingsService(config).get()['preferences']['sidebar_sort']=='name'
            choose('整理侧边栏','按远程连接')
            wait('document.querySelectorAll(".sidebar-origin-group").length===2&&[...document.querySelectorAll(".sidebar-origin-group")].every(e=>e.dataset.sidebarOrigin.startsWith("connection:"))')
            labels=js('[...document.querySelectorAll(".sidebar-origin-name")].map(e=>e.textContent)')
            assert set(labels)=={'本地','实验室主机（验收样例）'},labels
            assert app.store.get(member)['session']['sectionId']==section
            result['checks'].append('connection groups use local and explicitly seeded remote origins; custom section membership stays intact')
            choose('整理侧边栏','在一个列表中')
            wait('document.querySelectorAll(".sidebar-origin-group").length===0')
            js('location.reload()');wait('document.querySelector("[aria-label=展开会话侧栏]")');click('[aria-label="展开会话侧栏"]');wait('document.querySelectorAll(".session-row").length===3')
            assert js('document.querySelectorAll(".sidebar-origin-group").length')==0
            assert SettingsService(config).get()['preferences']['sidebar_grouping']=='list'
            choose('整理侧边栏','按项目')
            wait('document.querySelectorAll(".sidebar-origin-group").length===2')
            assert app.store.get(local)['session']['projectPath']==str(Path(__file__).resolve().parents[2])
            assert app.store.get(member)['session']['sectionId']==section
            assert js('getComputedStyle(document.querySelector(".session-list"),"::-webkit-scrollbar-thumb").minHeight')=='68px'
            assert js('getComputedStyle(document.querySelector(".session-list"),"::-webkit-scrollbar").width')=='14px'
            result['checks'].append('project/connection/list change real groups and persist across production reload; original thumb/lane unchanged')
            assert not app.tasks and json.loads(config.read_text(encoding='utf8'))['fixture']=='sidebar-options'
            result.update(passed=True,stage='complete',userAgent=js('navigator.userAgent'))
        except Exception as error:
            result.update(passed=False,error=repr(error),diagnostic=js('({rows:document.querySelectorAll(".session-row").length,expanded:document.querySelector("[aria-label=折叠会话侧栏]")!==null,viewport:[innerWidth,innerHeight],buttons:[...document.querySelectorAll(".sidebar button")].map(e=>e.getAttribute("aria-label")),menus:[...document.querySelectorAll("[role=menu]")].map(e=>e.textContent),alerts:[...document.querySelectorAll("[role=alert]")].map(e=>e.textContent)})'))
        finally:window.destroy()

    with patch.object(budget,'text_request',side_effect=AssertionError('Unexpected model request')) as provider:
        try:
            webview.start(check,gui='edgechromium',private_mode=True,storage_path=str(root/'profile'))
            assert provider.call_count==0
        finally:app.close();assets.close()
output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(0 if result.get('passed') else 1)
