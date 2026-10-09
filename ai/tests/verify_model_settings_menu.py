"""Native API menu -> real WebView2 Model page; completely isolated runtime."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from PIL import ImageGrab
from verify_path_settings_live import children, text, class_name, command, press, user32, wait, windows
from ctypes import wintypes
import ctypes
from verify_frontend_menu_layout import user32  # shared native mouse/DPI signatures


# Test-only instrumentation runs inside the real host, reads its actual DOM and
# executes fixture UI actions. No browser demo, no production test RPC added.
PROBE_RUNNER = '''
import json, threading, time
from pathlib import Path
from praat_ai import modern_host
root = Path(__file__).resolve().parent / 'runtime'
original = modern_host.create_window
def create_window(*args, **kwargs):
    window, server = original(*args, **kwargs)
    stopped = threading.Event()
    window.events.closed += stopped.set
    def probe():
        previous = ''
        while not stopped.is_set():
            try:
                action = root / 'probe-action.json'
                if action.exists():
                    raw = json.loads(action.read_text(encoding='utf8'))
                    if raw['id'] != previous:
                        window.evaluate_js(raw['script'])
                        previous = raw['id']
                result = window.evaluate_js("""(()=>({
                    heading:document.querySelector('.settings-main h1')?.textContent,
                    category:document.querySelector('.settings-nav [aria-current=page]')?.textContent,
                    api:Array.from(document.querySelectorAll('.segmented button')).find(b=>b.textContent==='云端 API')?.getAttribute('aria-pressed'),
                    model:document.querySelector('input[aria-label=模型名]')?.value,
                    chat:!document.querySelector('.settings-dashboard')&&!!document.querySelector('.app'),
                    action:""" + json.dumps(previous) + """
                }))()""")
                from praat_ai.desktop_launch import write_record
                write_record(root / 'probe.json', result)
            except Exception:
                pass
            time.sleep(.15)
    window.events.loaded += lambda: threading.Thread(target=probe, daemon=True).start()
    return window, server
modern_host.create_window = create_window
raise SystemExit(modern_host.main())
'''


def main():
    project = Path(__file__).resolve().parents[2]
    executable = Path(sys.argv[1]).resolve()
    report = dict(executable=str(executable), checks=[])
    output = project/'test-records'/'installer'
    # WebView2 may retain its working-directory handle briefly after the host
    # closes; this must not turn completed UI assertions into a test failure.
    with tempfile.TemporaryDirectory(prefix='model-menu-',dir=output,ignore_cleanup_errors=True) as directory:
        root = Path(directory); ai = root/'ai'; ai.mkdir()
        (ai/'runtime').mkdir()
        for path in (project/'ai').glob('*.py'): shutil.copy2(path, ai/path.name)
        shutil.copytree(project/'ai'/'praat_ai', ai/'praat_ai', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(project/'ai'/'frontend'/'dist', ai/'frontend'/'dist')
        (ai/'run_ai_chat.py').write_text(PROBE_RUNNER, encoding='utf8')
        profile = root/'profile'; profile.mkdir()
        (profile/'Preferences.txt').write_text('Python.executablePath: '+sys.executable+
            '\nAI.projectDirectory: '+str(ai)+'\n', encoding='utf8')
        config = root/'config.json'; config.write_text(json.dumps(dict(
            api=dict(enabled=True, base_url='https://example.invalid/v1', model='no-network-fixture'))))
        before = config.read_bytes()
        script = root/'editor.praat'
        script.write_text('Create Sound from formula: "model-settings-test", 1, 0, 0.2, 44100, ~0\nView & Edit\n')
        env = dict(os.environ, PRAAT_AI_PROJECT_DIR=str(ai), PRAAT_AI_CONFIG_PATH=str(config),
            PRAAT_PYTHON_EXECUTABLE=sys.executable, PYTHONPATH=str(ai))
        process = subprocess.Popen([str(executable), '--new-send', '--no-plugins', '--no-pref-files',
            '--pref-dir='+str(profile), str(script)], env=env, cwd=root)
        desktop = None
        try:
            editor = wait(lambda:next((w for w in windows() if w[1]==process.pid and 'model-settings-test' in w[2]), None), 'isolated editor')
            number = command(editor[0], ('API 设置', 'API 配置'))
            report['command_id'] = number
            def click_api():
                bar=user32.GetMenu(editor[0])
                for index in range(user32.GetMenuItemCount(bar)):
                    sub=user32.GetSubMenu(bar,index)
                    for item in range(user32.GetMenuItemCount(sub)) if sub else ():
                        if user32.GetMenuItemID(sub,item)==number: break
                    else: continue
                    break
                user32.SetWindowPos(editor[0],wintypes.HWND(-1),0,0,0,0,0x43)
                user32.SetForegroundWindow(editor[0])
                rect=wintypes.RECT();assert user32.GetMenuItemRect(editor[0],bar,index,ctypes.byref(rect))
                user32.SetCursorPos((rect.left+rect.right)//2,(rect.top+rect.bottom)//2);time.sleep(.15)
                user32.mouse_event(2,0,0,0,0);user32.mouse_event(4,0,0,0,0)
                wait(lambda:any(w[1]==process.pid and class_name(w[0])=='#32768' for w in windows()),'frontend popup')
                assert user32.GetMenuItemRect(editor[0],sub,item,ctypes.byref(rect))
                report['menu_state']=user32.GetMenuState(sub,item,0x400)
                user32.SetCursorPos((rect.left+rect.right)//2,(rect.top+rect.bottom)//2);time.sleep(.15)
                user32.mouse_event(2,0,0,0,0);user32.mouse_event(4,0,0,0,0)
                user32.SetWindowPos(editor[0],wintypes.HWND(-2),0,0,0,0,0x43)
            click_api()
            runtime = ai/'runtime'; probe = runtime/'probe.json'
            def snapshot():
                try: return json.loads(probe.read_text(encoding='utf8'))
                except (OSError, ValueError): return {}
            def model_page():
                messages=[w for w in windows() if w[1]==process.pid and w[2] in ('Message','Information','Praat Info')]
                if messages:
                    raise AssertionError([text(c) for w in messages for c in children(w[0]) if text(c)])
                data = snapshot()
                return data if data.get('heading')=='模型' and data.get('category')=='模型' and data.get('api')=='true' else None
            wait(model_page, 'first API click opens Model/API page', 40)
            record = json.loads((runtime/'chat-process.json').read_text(encoding='utf8'))
            desktop = wait(lambda:next((w for w in windows() if w[1]==record['pid'] and w[2]=='AIPraat · AI 工作台'),None), 'desktop')
            report['checks'].append('closed_desktop_native_API_menu_opens_model_API_page')
            assert not any(class_name(w[0])=='TkTopLevel' for w in windows() if w[1]==record['pid'])
            report['checks'].append('no_standalone_API_window')
            def action(name, js):
                (runtime/'probe-action.json').write_text(json.dumps(dict(id=name,script=js)),encoding='utf8')
                wait(lambda:snapshot().get('action')==name,name)
            action('back', "Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='返回聊天').click()")
            wait(lambda:snapshot().get('chat'),'returned to chat')
            click_api(); wait(model_page,'existing desktop returns to Model')
            assert json.loads((runtime/'chat-process.json').read_text())['pid']==record['pid']
            report['checks'].append('existing_desktop_reused_after_returning_to_chat')
            action('draft', "(()=>{const input=document.querySelector('input[aria-label=模型名]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'unsaved-model');input.dispatchEvent(new Event('input',{bubbles:true}));Array.from(document.querySelectorAll('.settings-nav button')).find(b=>b.textContent==='外观与交互').click()})()")
            wait(lambda:snapshot().get('heading')=='外观与交互','other settings page')
            click_api(); wait(model_page,'repeat API click switches settings page')
            assert snapshot()['model']=='unsaved-model'
            report['checks'].append('repeated_API_menu_restores_model_page_preserving_unsaved_edit')
            assert len([w for w in windows() if w[1]==record['pid'] and w[2]=='AIPraat · AI 工作台'])==1
            assert config.read_bytes()==before
            report['checks'].append('single_desktop_and_saved_configuration_unchanged')
            user32.ShowWindow(desktop[0],9); user32.SetForegroundWindow(desktop[0]);time.sleep(.4)
            rect=wintypes.RECT(); user32.GetWindowRect(desktop[0],ctypes.byref(rect))
            ImageGrab.grab((rect.left,rect.top,rect.right,rect.bottom)).save(output/'model-settings-menu.png')
            process.terminate(); process.wait(timeout=5)
            wait(lambda:not any(w[0]==desktop[0] for w in windows()),'test parent closes bound desktop',15)
            report['checks'].append('bound_test_desktop_closes_with_its_Praat_parent')
        except Exception as error:
            report['error']=str(error)
            report['probe']=snapshot() if 'snapshot' in locals() else None
            report['windows']=[dict(pid=w[1],title=w[2],cls=class_name(w[0])) for w in windows()]
            for p in (ai/'runtime').glob('*error*.json'): report[p.name]=p.read_text(encoding='utf8')
            for p in (ai/'runtime').glob('*.txt'): report[p.name]=p.read_text(encoding='utf8')
            report['runtime_files']=[p.name for p in (ai/'runtime').glob('*')]
            raise
        finally:
            if process.poll() is None: process.terminate(); process.wait(timeout=5)
            if desktop:
                user32.PostMessageW(desktop[0],0x10,0,0)
                time.sleep(1.5)
            (output/'model-settings-menu.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
