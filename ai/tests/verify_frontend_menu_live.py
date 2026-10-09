"""Real Sound-editor menu, coloured dots and desktop lifecycle with isolated settings."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from PIL import ImageGrab
from verify_path_settings_live import class_name, command, menu, press, user32, wait, windows

user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
user32.GetMenuItemRect.argtypes = [wintypes.HWND, wintypes.HMENU, wintypes.UINT, ctypes.POINTER(wintypes.RECT)]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]


def main():
    project = Path(__file__).resolve().parents[2]
    executable = Path(sys.argv[1]).resolve()
    fixture = Path(sys.argv[2]).resolve()
    report = dict(checks=[], executable=str(executable), realCloud=False)
    runtime = project/'ai'/'runtime'
    record_names = ('status.json', 'chat.pid', 'chat-process.json', 'frontend-ready.json', 'chat_context.tsv')
    # Do not overwrite a running user's desktop records.
    sys.path.insert(0, str(project/'ai'))
    from praat_ai.frontend_status import desktop_running
    assert not desktop_running(runtime), 'A user desktop is running; use separate runtime before this test'
    saved = {name:(runtime/name).read_bytes() if (runtime/name).exists() else None for name in record_names}
    process = None
    with tempfile.TemporaryDirectory(prefix='praat-frontend-menu-') as directory:
        root = Path(directory)
        profile = root/'profile'; profile.mkdir()
        (profile/'Preferences.txt').write_text('Python.executablePath: '+sys.executable+
            '\nAI.projectDirectory: '+str(project/'ai')+'\n', encoding='utf8')
        gpu = root/'gpu.txt'; gpu.write_text('1536')
        config = root/'config.json'
        raw = dict(api=dict(enabled=True, locked=False, base_url='http://127.0.0.1:8999/v1',
                            model='no-network-fixture', stop_local_service=False),
                   alignment=dict(mfa=dict(dictionary_path='保留.dict', dictionary_paths=['保留.dict'])))
        def save(): config.write_text(json.dumps(raw), encoding='utf8')
        save()
        script = root/'editor.praat'
        script.write_text('Create Sound from formula: "frontend-menu-test", 1, 0, 0.2, 44100, ~0.01*sin(2*pi*220*x)\nView & Edit\n', encoding='utf8')
        environment = dict(os.environ, PRAAT_AI_PROJECT_DIR=str(project/'ai'), PRAAT_AI_CONFIG_PATH=str(config),
                           PRAAT_TEST_VRAM_FILE=str(gpu), PATH=str(fixture.parent)+os.pathsep+os.environ['PATH'])
        before = {w[0] for w in windows()}
        try:
            process = subprocess.Popen([str(executable),'--new-send','--no-plugins','--pref-dir='+str(profile),str(script)],env=environment)
            editor = wait(lambda: next((w for w in windows() if w[1]==process.pid and 'frontend-menu-test' in w[2]),None),'Sound editor')
            def labels(): return [s for group in menu(editor[0]) for s,_ in group]
            def expect(label): wait(lambda: label in labels(),label,20)
            expect('模型: 云端API模式'); expect('状态: 已停止')
            report['checks'].append('cloud_label_and_configured_stopped')

            # GPU warning colours apply to local inference only.
            model = root/'模型.gguf'; model.touch()
            server = root/'llama-server.exe'; server.touch()
            raw['server']=dict(model_path=str(model),llama_server=str(server),active_preset='fixture',
                presets=[dict(id='fixture',label='本地显存验收',model_path=str(model))])
            raw['api']['enabled']=False; save(); expect('模型: 本地显存验收')

            def capture_dot(free, name, rgb):
                gpu.write_text(str(free))
                snapshot = runtime/('frontend-menu-'+str(process.pid)+'.json')
                wait(lambda: snapshot.exists() and json.loads(snapshot.read_text(encoding='utf8')).get('vram_warning')==name, name+' sampler',20)
                # One further native timer reads the finished snapshot.
                time.sleep(2.2)
                bar = user32.GetMenu(editor[0]); index = None
                for i in range(user32.GetMenuItemCount(bar)):
                    label = ctypes.create_unicode_buffer(256)
                    user32.GetMenuStringW(bar,i,label,256,0x400)
                    if label.value=='前端': index=i; break
                assert index is not None
                rect = wintypes.RECT()
                assert user32.GetMenuItemRect(editor[0],bar,index,ctypes.byref(rect))
                user32.SetForegroundWindow(editor[0])
                user32.SetCursorPos((rect.left+rect.right)//2,(rect.top+rect.bottom)//2)
                user32.mouse_event(2,0,0,0,0); user32.mouse_event(4,0,0,0,0)
                popup = wait(lambda: next((w for w in windows() if class_name(w[0])=='#32768'),None), 'frontend popup')
                time.sleep(.3)
                user32.GetWindowRect(popup[0],ctypes.byref(rect))
                shot = ImageGrab.grab((rect.left,rect.top,rect.right,rect.bottom))
                shot.save(project/'test-records'/'installer'/('frontend-menu-'+name+'.png'))
                count = sum(1 for pixel in shot.convert('RGB').get_flattened_data() if pixel==rgb)
                assert count>12, (name,count)
                # Close just the test popup, leaving the editor alive.
                user32.PostMessageW(editor[0],0x100,0x1B,0)
                wait(lambda: not any(class_name(w[0])=='#32768' for w in windows()),'popup closed')
                report['checks'].append(name+'_native_coloured_circle_at_'+str(free)+'MiB')
            capture_dot(511,'red',(220,38,38))
            capture_dot(512,'yellow',(234,179,8))
            capture_dot(1536,'green',(22,163,74))
            gpu.write_text('-1')
            expect('显存预警：不可用')
            report['checks'].append('unavailable_GPU_does_not_show_green')

            raw['api']['enabled']=True; save(); expect('模型: 云端API模式')

            press(editor[0],command(editor[0],('启动前端',)))
            desktop = wait(lambda: next((w for w in windows() if w[0] not in before and w[2]=='AIPraat · AI 工作台'),None),'real modern desktop',35)
            expect('状态: 运行中')
            report['checks'].append('real_connected_desktop_running')
            press(editor[0],command(editor[0],('停止前端',)))
            wait(lambda: not any(w[0]==desktop[0] for w in windows()),'normal desktop closure',25)
            expect('状态: 已停止')
            report['checks'].append('stop_menu_closes_desktop_and_reports_stopped')

            model = root/'模型.gguf'; model.touch()
            server = root/'llama-server.exe'; server.touch()
            raw['api']['enabled']=False
            raw['server']=dict(model_path=str(model),llama_server=str(server),active_preset='fixture',
                presets=[dict(id='fixture',label='中文 "预设" 🦜',model_path=str(model))])
            save(); expect('模型: 中文 "预设" 🦜'); expect('状态: 已停止')
            report['checks'].append('local_saved_Unicode_quoted_preset')
            model.unlink(); expect('状态: 未配置')
            report['checks'].append('missing_local_file_unconfigured')
            raw['api']['enabled']=True; raw['api']['model']=''; save()
            expect('模型: 云端API模式'); expect('状态: 未配置')
            report['checks'].append('incomplete_API_unconfigured')
            assert any('管理语音词典与模型'==label for label in labels())
            assert json.loads(config.read_text(encoding='utf8'))['alignment']==raw['alignment']
            report['checks'].append('dictionary_menu_and_selected_configuration_preserved')
            assert process.poll() is None
        except Exception as error:
            report['error']=str(error)
            report['windows']=windows()
            if process: report['labels']=locals().get('labels',lambda:[])()
            raise
        finally:
            if process and process.poll() is None: process.terminate(); process.wait(timeout=5)
            time.sleep(1.3)
            for name,value in saved.items():
                if value is None: (runtime/name).unlink(missing_ok=True)
                else: (runtime/name).write_bytes(value)
            (project/'test-records'/'installer'/'frontend-menu-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
