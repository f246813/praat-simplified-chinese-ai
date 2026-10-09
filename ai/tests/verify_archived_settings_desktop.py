"""Production WebView2 archive-settings acceptance with isolated SQLite data."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
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
    def capture_target(self,text):raise AssertionError('Unexpected Praat capture')
    def run(self,**kwargs):raise AssertionError('Unexpected executor call')

result=dict(realWebView2=True,productionAssets=True,isolatedData=True,checks=[])
with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary);config=root/'config.json';config.write_text('{"fixture":"archived-settings"}',encoding='utf8')
    app=ModernApplication(root/'modern',config,executor=NoExecution())
    active=app.store.new_session('保留的当前会话')['id']
    section=app.store.organization.create('归档研究')['id']
    archived=app.store.organization.create_session('归档的声学分析',section)['id']
    remote=app.store.new_session('远程历史样例')['id']
    app.store.put_message(archived,dict(id='archive-user',role='user',content='保留的原始问题'))
    app.store.view(archived,draft='原始草稿',scroll=88,anchor=dict(messageId='archive-user',offset=3))
    # Imported remote origin fixture, never a live remote connection.
    with app.store.connect() as db:
        db.execute('UPDATE sessions SET project_path=?,connection_id=?,connection_label=? WHERE id=?',('/srv/prosody','ssh:fixture','实验室主机',remote))
    app.store.organization.archive([archived,remote],True)
    before=app.store.get(archived)
    calls=[];original_rpc=app.rpc
    def rpc(method,params):
        calls.append(dict(method=method,params=params))
        return original_rpc(method,params)
    app.rpc=rpc
    window,assets=create_window(app,hidden=True)
    def check():
        def js(code):return window.evaluate_js(code)
        def wait(code):
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                if js(code):return
                time.sleep(.1)
            raise AssertionError('Timed out: '+code)
        def click(selector):js('document.querySelector('+json.dumps(selector,ensure_ascii=False)+').click()')
        def button(text):js('[...document.querySelectorAll(".settings-nav>button")].find(el=>el.textContent==='+json.dumps(text,ensure_ascii=False)+').click()')
        def open_archives():
            wait('document.querySelector("[aria-label=打开设置]")');click('[aria-label="打开设置"]');button('已归档会话')
            wait('document.querySelector(".settings-main h1")?.textContent==="已归档的聊天"')
        try:
            wait('document.querySelector("[aria-label=展开会话侧栏]")');click('[aria-label="展开会话侧栏"]')
            wait('document.querySelectorAll(".session-row").length===1')
            assert not js('document.querySelector("[aria-label=查看已归档会话]")')
            open_archives();wait('document.querySelectorAll(".archived-session-row").length===2')
            assert 'prosody · 实验室主机' in js('document.querySelector('+json.dumps('[data-archived-session-id="'+remote+'"]')+').closest(".archived-group").querySelector(".archived-group-name").textContent')
            assert js('[...document.querySelectorAll(".archived-session-row")].every(el=>el.querySelector("time[datetime]")&&el.querySelector(".archived-session-restore"))')
            result['checks'].append('entry is settings-only; archived rows show date, preserved project/connection context and Unarchive')
            click('[data-archived-session-id="'+archived+'"] .archived-session-restore');wait('document.querySelectorAll(".archived-session-row").length===1')
            restored=app.store.get(archived)
            assert not restored['session']['archived'] and restored['session']['sectionId']==section
            assert restored['messages']==before['messages']
            assert all(restored['session'][key]==before['session'][key] for key in ['draft','scroll','anchor','created','updated'])
            assert sum(call.get('method')=='sessions.archive' for call in calls)==1
            assert js('document.querySelector(".settings-main h1").textContent')=='已归档的聊天'
            result['checks'].append('one host restore; settings stay open; original section/messages/draft/reading position remain unchanged')
            js('location.reload()');wait('document.querySelector("[aria-label=展开会话侧栏]")');open_archives()
            wait('document.querySelectorAll(".archived-session-row").length===1')
            click('[data-archived-session-id="'+remote+'"] .archived-session-title');wait('document.querySelector(".archived-conversation")')
            assert not js('document.querySelector("[aria-label=消息输入]")')
            assert app.store.get(remote)['session']['archived']
            open_archives();click('[data-archived-session-id="'+remote+'"] .archived-session-restore')
            wait('document.querySelector(".archived-sessions-empty")?.textContent==="暂无已归档会话"')
            button('返回聊天');wait('document.querySelector("[aria-label=消息输入]")')
            assert not app.store.get(remote)['session']['archived']
            # Reuse the restored metadata and add an explicit legacy fixture to
            # exercise all deletion scopes against real production host RPC.
            legacy=root/'legacy.sqlite3'
            with closing(sqlite3.connect(legacy)) as db, db:
                db.executescript('CREATE TABLE sessions(id TEXT PRIMARY KEY,created TEXT);CREATE TABLE events(id INTEGER PRIMARY KEY,session TEXT,kind TEXT,payload TEXT);')
                db.execute('INSERT INTO sessions VALUES (?,?)',('old','2020-01-01'))
                db.execute('INSERT INTO events VALUES (?,?,?,?)',(1,'old','user',json.dumps(dict(prompt='保留旧库的归档样例'))))
            original_legacy=legacy.read_bytes();app.store.legacy=legacy
            app.store.put_message(remote,dict(id='search-body',role='user',content='只在正文中的归档检索词'))
            app.store.organization.archive([archived,remote,'legacy:old'],True)
            js('location.reload()');wait('document.querySelector("[aria-label=展开会话侧栏]")');open_archives();wait('document.querySelectorAll(".archived-session-row").length===3')
            assert '无项目' in js('[...document.querySelectorAll(".archived-group-name")].map(el=>el.textContent)')
            def search(value):
                js('(()=>{const el=document.querySelector("[aria-label=搜索已归档的聊天]");Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value").set.call(el,'+json.dumps(value,ensure_ascii=False)+');el.dispatchEvent(new Event("input",{bubbles:true}));})()')
            before_search=sum(call.get('method')=='sessions.search' for call in calls)
            search('只在正文中的归档检索词');wait('document.querySelectorAll(".archived-session-row").length===1')
            assert sum(call.get('method')=='sessions.search' for call in calls)==before_search+1
            click('[data-archived-session-id="'+remote+'"] .archived-session-delete');wait('document.querySelector("dialog[open]")')
            click('dialog[open] [aria-label="确认删除归档会话"]');wait('!document.querySelector("dialog[open]")')
            assert remote not in [s['id'] for s in app.store.sessions()]
            search('');wait('document.querySelectorAll(".archived-session-row").length===2')
            click('[aria-label="归档分组操作 归档研究"]');wait('document.querySelector("[data-context-menu-item=delete-group]")')
            click('[data-context-menu-item="delete-group"]');wait('document.querySelector("dialog[open]")');click('dialog[open] [aria-label="确认删除归档会话"]');wait('document.querySelectorAll(".archived-session-row").length===1')
            wait('!document.querySelector("[aria-label=全部删除]").disabled')
            click('[aria-label="全部删除"]');wait('document.querySelector("dialog[open]")');click('dialog[open] [aria-label="确认删除归档会话"]');wait('document.querySelector(".archived-sessions-empty")')
            js('location.reload()');wait('document.querySelector("[aria-label=展开会话侧栏]")');open_archives();wait('document.querySelector(".archived-sessions-empty")')
            assert legacy.read_bytes()==original_legacy and [s['id'] for s in app.store.sessions()]==[active]
            assert any(s['id']==section for s in app.store.organization.sections())
            result['checks'].append('body-only search uses one compact RPC; row/group/global deletion persists; active chats/section/legacy source remain intact')
            assert not app.tasks and json.loads(config.read_text(encoding='utf8'))=={'fixture':'archived-settings'}
            result['checks'].append('restore persists across production reload; opening archives is read-only until restored; empty state works')
            result.update(passed=True,userAgent=js('navigator.userAgent'))
        except Exception as error:
            result.update(passed=False,error=repr(error),diagnostic=js('({settings:document.querySelector(".settings-main h1")?.textContent,rows:document.querySelectorAll(".archived-session-row").length,alerts:[...document.querySelectorAll("[role=alert]")].map(el=>el.textContent)})'))
        finally:window.destroy()
    with patch.object(budget,'text_request',side_effect=AssertionError('Unexpected model request')) as provider:
        try:
            webview.start(check,gui='edgechromium',private_mode=True,storage_path=str(root/'profile'));assert provider.call_count==0
        finally:app.close();assets.close()
output=Path(__file__).resolve().parents[2]/'test-records/frontend/archived-settings-desktop-result.json'
output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(0 if result.get('passed') else 1)
