"""Isolated production pywebview/WebView2 history organization acceptance.

Run from the project root after rebuilding ai/frontend/dist. No model/Praat calls.
"""
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf8',errors='replace')
sys.path.insert(0,str(Path.cwd()/'ai'))
import webview
from praat_ai.modern_app import ModernApplication
from praat_ai.modern_host import create_window
from praat_ai import modern_budget as budget


class NoExecution:
    def capture_target(self,text):raise AssertionError('Unexpected Praat capture')
    def run(self,**kwargs):raise AssertionError('Unexpected executor call')


result=dict(realWebView2=True,productionAssets=True,isolatedData=True,checks=[])
with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary);config=root/'config.json';config.write_text('{"fixture":"history-organization"}',encoding='utf8')
    app=ModernApplication(root/'modern',config,executor=NoExecution())
    parent=app.store.new_session('生产分区验收')['id'];other=app.store.new_session('普通历史保留')['id']
    app.store.put_message(parent,dict(id='source-user',role='user',content='独立分叉的原始问题'))
    app.store.put_message(parent,dict(id='source-answer',role='assistant',content='历史结果，不执行工具',status='complete',taskId='historical-task'))
    app.store.save_evidence(parent,'historical-task',dict(source='isolated fixture',executed=False))
    app.store.view(parent,draft='父会话草稿',scroll=88)
    before=app.get_session(parent)
    window,assets=create_window(app,hidden=True)

    def check():
        def js(code):return window.evaluate_js(code)
        def wait(code):
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                if js(code):return
                time.sleep(.1)
            raise AssertionError('Timed out: '+code)
        def click(selector):js('document.querySelector('+json.dumps(selector)+').click()')
        def wait_selector(selector,present=True):wait(('' if present else '!')+'document.querySelector('+json.dumps(selector,ensure_ascii=False)+')')
        def menu(label):
            wait('Boolean([...document.querySelectorAll("[role=menuitem]")].find(el=>el.textContent.trim().replace(/›$/," ").trim()==='+json.dumps(label,ensure_ascii=False)+'))')
            js('[...document.querySelectorAll("[role=menuitem]")].find(el=>el.textContent.trim().replace(/›$/," ").trim()==='+json.dumps(label,ensure_ascii=False)+').click()')
        def input(label,value):
            js('(()=>{const input=document.querySelector('+json.dumps('[aria-label="'+label+'"]',ensure_ascii=False)+');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value").set.call(input,'+json.dumps(value,ensure_ascii=False)+');input.dispatchEvent(new Event("input",{bubbles:true}));})()')
        try:
            wait('document.querySelector("[aria-label=展开会话侧栏]")');click('[aria-label="展开会话侧栏"]');wait('document.querySelectorAll(".session-row").length===2')
            assert js('Object.keys(window.pywebview.api)')==['rpc'];result['userAgent']=js('navigator.userAgent')
            click('[aria-label="新建分区"]');wait('document.querySelector("[aria-label=分区名称]")');input('分区名称','声学研究');input('分区图标','🎵');click('[aria-label="保存分区"]')
            wait_selector('[aria-label="折叠分区 声学研究"]')
            section=next(s['id'] for s in app.store.organization.sections() if s['name']=='声学研究')
            click('[aria-label="会话操作 生产分区验收"]');menu('分区');menu('声学研究')
            wait('document.querySelector('+json.dumps('[data-history-section="'+section+'"] [data-session-id="'+parent+'"]')+')')
            click('[aria-label="分区操作 声学研究"]');menu('编辑分区');wait_selector('[aria-label="分区名称"]');input('分区名称','共振峰研究');click('[aria-label="保存分区"]');wait_selector('[aria-label="折叠分区 共振峰研究"]')
            assert app.store.get(parent)['session']['sectionId']==section
            result['checks'].append('native menus create/edit section and move session; rename preserves stable membership')
            js('document.querySelector('+json.dumps('[data-session-id="'+parent+'"]')+').dispatchEvent(new MouseEvent("contextmenu",{bubbles:true,clientX:140,clientY:160}))');menu('分叉会话')
            wait('document.querySelector(".chat-header h1")?.textContent.includes("分叉")')
            fork=next(s['id'] for s in app.store.sessions() if s['forkedFrom']==parent)
            copied=app.store.get(fork);assert [m['content'] for m in copied['messages']]==[m['content'] for m in before['messages']]
            assert set(m['id'] for m in copied['messages']).isdisjoint(m['id'] for m in before['messages'])
            assert copied['session']['draft']=='' and copied['session']['scroll']==0 and not app.tasks
            assert app.store.context(fork)[1]==app.store.context(parent)[1]
            assert app.store.get(parent)=={k:v for k,v in before.items() if k!='cursor'}|{'session':{**before['session'],'sectionId':section,'sectionPosition':1000000}}
            result['checks'].append('right-click forks independent message identities and evidence; parent draft/history unchanged; no tasks')
            click('[aria-label="分区操作 共振峰研究"]');menu('新建会话');wait('document.querySelectorAll(".session-row").length===4')
            assert len(app.store.organization.members(section))==3
            click('[aria-label="分区操作 共振峰研究"]');menu('归档分区');wait('document.querySelector("[aria-label=确认归档分区]")');click('[aria-label="确认归档分区"]');wait('document.querySelectorAll(".session-row").length===1')
            assert sum(s['archived'] for s in app.store.sessions())==3 and not app.store.get(other)['session']['archived']
            js('location.reload()');wait('document.querySelector("[aria-label=展开会话侧栏]")');click('[aria-label="展开会话侧栏"]');wait('document.querySelectorAll(".session-row").length===1')
            assert not js('document.querySelector("[aria-label=查看已归档会话]")')
            click('[aria-label="打开设置"]');js('[...document.querySelectorAll(".settings-nav>button")].find(el=>el.textContent==="已归档会话").click()');wait('document.querySelectorAll(".archived-session-row").length===3')
            assert js('[...document.querySelectorAll(".archived-session-row")].every(el=>el.querySelector("time[datetime]")&&el.closest(".archived-group").querySelector(".archived-group-name")?.textContent)')
            click('[data-archived-session-id="'+parent+'"] .archived-session-title');wait('document.querySelector(".archived-conversation")');assert not js('document.querySelector("[aria-label=消息输入]")')
            click('[aria-label="分区操作 共振峰研究"]');menu('恢复分区会话');wait('document.querySelector("[aria-label=确认恢复分区]")');click('[aria-label="确认恢复分区"]');wait('document.querySelectorAll(".session-row").length===4')
            result['checks'].append('create within section; bulk archive persists across production reload; restore retains all membership/history')
            click('[aria-label="分区操作 共振峰研究"]');menu('移除分区');wait_selector('[aria-label="确认移除分区"]');click('[aria-label="确认移除分区"]');wait_selector('[aria-label="折叠分区 共振峰研究"]',False)
            assert len(app.store.sessions())==4 and app.store.get(parent)['messages']==before['messages']
            assert all(s['sectionId'] is None for s in app.store.sessions())
            assert js('getComputedStyle(document.querySelector(".session-list"),"::-webkit-scrollbar-thumb").minHeight')=='68px'
            assert js('getComputedStyle(document.querySelector(".session-list"),"::-webkit-scrollbar").width')=='14px'
            result['checks'].append('remove section detaches only; original messages preserved; 14px lane and 68px minimum unchanged')
            assert json.loads(config.read_text(encoding='utf8'))=={'fixture':'history-organization'}
            result['checks'].append('isolated database/config only; no model, executor or Praat calls')
            result['passed']=True
        except Exception as error:
            result.update(passed=False,error=repr(error),diagnostic=js('({title:document.querySelector(".chat-header h1")?.textContent,menus:[...document.querySelectorAll("[role=menuitem]")].map(e=>e.textContent),alerts:[...document.querySelectorAll("[role=alert]")].map(e=>e.textContent)})'))
        finally:window.destroy()

    with patch.object(budget,'text_request',side_effect=AssertionError('Unexpected model request')) as request:
        try:
            webview.start(check,gui='edgechromium',debug=False,private_mode=True,storage_path=str(root/'profile'))
            assert request.call_count==0
        finally:app.close();assets.close()
output=Path.cwd()/'docs/ai-frontend/verification/codex-history-desktop-result.json'
output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(0 if result.get('passed') else 1)
