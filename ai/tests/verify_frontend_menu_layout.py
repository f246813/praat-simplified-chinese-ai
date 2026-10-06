"""Isolated native popup geometry, trailing dots, duplicate-menu and repaint checks."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from PIL import ImageChops, ImageGrab
from verify_path_settings_live import class_name, children, menu, text, user32, wait, windows

user32.SetProcessDpiAwarenessContext.argtypes=[ctypes.c_void_p]
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
user32.GetMenuItemRect.argtypes=[wintypes.HWND,wintypes.HMENU,wintypes.UINT,ctypes.POINTER(wintypes.RECT)]
user32.SetForegroundWindow.argtypes=[wintypes.HWND]
user32.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
user32.SetCursorPos.argtypes=[ctypes.c_int,ctypes.c_int]
user32.mouse_event.argtypes=[wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.c_size_t]
user32.keybd_event.argtypes=[wintypes.BYTE,wintypes.BYTE,wintypes.DWORD,ctypes.c_size_t]


def main():
    project=Path(__file__).resolve().parents[2]
    executable=Path(sys.argv[1]).resolve(); fixture=Path(sys.argv[2]).resolve()
    report=dict(checks=[],executable=str(executable))
    output=project/'installer'/'verification'
    with tempfile.TemporaryDirectory(prefix='praat-menu-layout-',dir=output) as directory:
        root=Path(directory); ai=project/'ai'
        context=ai/'runtime'/'chat_context.tsv'
        prior_context=context.read_bytes() if context.exists() else None
        profile=root/'profile';profile.mkdir()
        (profile/'Preferences.txt').write_text('Python.executablePath: '+sys.executable+
            '\nAI.projectDirectory: '+str(ai)+'\n',encoding='utf8')
        model=root/'model.gguf';model.touch()
        server=root/'llama-server.exe';server.touch()
        config=root/'config.json';config.write_text(json.dumps(dict(server=dict(
            model_path=str(model),llama_server=str(server),active_preset='fixture',
            presets=[dict(id='fixture',label='本地验收预设',model_path=str(model))]))))
        gpu=root/'gpu.txt';gpu.write_text('-1')
        script=root/'editor.praat';script.write_text('Create Sound from formula: "menu-layout-test", 1, 0, 0.2, 44100, ~0.01*sin(2*pi*220*x)\nView & Edit\n')
        env=dict(os.environ,PRAAT_AI_PROJECT_DIR=str(ai),PRAAT_AI_CONFIG_PATH=str(config),
            PRAAT_TEST_VRAM_FILE=str(gpu),PYTHONPATH=str(project/'ai'),
            PATH=str(fixture.parent)+os.pathsep+os.environ['PATH'])
        process=subprocess.Popen([str(executable),'--new-send','--no-plugins','--pref-dir='+str(profile),str(script)],env=env)
        try:
            editor=wait(lambda: next((w for w in windows() if w[1]==process.pid and 'menu-layout-test' in w[2]),None),'test editor')
            bar=user32.GetMenu(editor[0]);titles=[]
            for i in range(user32.GetMenuItemCount(bar)):
                title=ctypes.create_unicode_buffer(128);user32.GetMenuStringW(bar,i,title,128,0x400);titles.append(title.value)
            assert len(titles)==len(set(titles)), titles
            assert titles.count('前端')==1 and titles.count('对齐')==1
            assert not any(text(c) in ('前端','对齐') and class_name(c)=='Button' for c in children(editor[0]))
            report['checks'].append('single_native_menu_bar_and_unique_top_level_menus')
            index=titles.index('前端'); sub=user32.GetSubMenu(bar,index)
            popup_windows=lambda:[w for w in windows() if w[1]==process.pid and class_name(w[0])=='#32768']
            def grab():
                popup=popup_windows(); assert len(popup)==1,popup
                bounds=wintypes.RECT();user32.GetWindowRect(popup[0][0],ctypes.byref(bounds))
                image=ImageGrab.grab((bounds.left,bounds.top,bounds.right,bounds.bottom)).convert('RGB')
                rects=[]
                for i in range(user32.GetMenuItemCount(sub)):
                    rect=wintypes.RECT();assert user32.GetMenuItemRect(editor[0],sub,i,ctypes.byref(rect))
                    rects.append([rect.left-bounds.left,rect.top-bounds.top,rect.right-bounds.left,rect.bottom-bounds.top])
                return image,rects
            def show(free,colour):
                gpu.write_text(str(free));snapshot=ai/'runtime'/('frontend-menu-'+str(process.pid)+'.json')
                wait(lambda:snapshot.exists() and json.loads(snapshot.read_text(encoding='utf8'))['vram_warning']==colour,colour+' sample')
                time.sleep(2.2)
                wait(lambda:any(s=='模型: 本地验收预设' for group in menu(editor[0]) for s,_ in group),'fresh native menu')
                user32.SetWindowPos(editor[0],wintypes.HWND(-1),0,0,0,0,0x43)
                rect=wintypes.RECT();assert user32.GetMenuItemRect(editor[0],bar,index,ctypes.byref(rect))
                user32.SetForegroundWindow(editor[0]);user32.SetCursorPos((rect.left+rect.right)//2,(rect.top+rect.bottom)//2)
                time.sleep(.15)
                x=(rect.left+rect.right)//2;y=(rect.top+rect.bottom)//2
                user32.mouse_event(2,0,0,0,0);user32.mouse_event(4,0,0,0,0)
                wait(popup_windows,'popup');time.sleep(.3)
                return grab()
            def close():
                user32.keybd_event(0x1B,0,0,0);user32.keybd_event(0x1B,0,2,0)
                wait(lambda:not popup_windows(),'popup closed')
            def ink(image,rect):
                points=[]
                for y in range(rect[1]+3,rect[3]-3):
                    for x in range(rect[0]+3,rect[2]-3):
                        pixel=image.getpixel((x,y))
                        if max(pixel)<200 and max(pixel)-min(pixel)<8:points.append((x,y))
                assert points
                return min(x for x,y in points),max(x for x,y in points)
            baseline,baseline_rects=show(-1,'unknown');baseline.save(output/'frontend-layout-baseline.png');close()
            report['baseline_geometry']=baseline_rects
            for free,name,rgb in [(511,'red',(220,38,38)),(512,'yellow',(234,179,8)),(1536,'green',(22,163,74))]:
                image,rects=show(free,name);image.save(output/('frontend-layout-'+name+'.png'))
                report[name+'_geometry']=rects
                assert [r[3]-r[1] for r in rects]==[r[3]-r[1] for r in baseline_rects],('row_height_shift',rects,baseline_rects)
                assert rects==baseline_rects,('whole_menu_geometry_shift',rects,baseline_rects)
                left,right=ink(image,rects[2]);baseline_left,_=ink(baseline,baseline_rects[2])
                assert abs(left-baseline_left)<=1,('VRAM_text_indent',left,baseline_left)
                for item in (0,1,4,5,7,8,9,11):
                    assert ink(image,rects[item])[0]==ink(baseline,baseline_rects[item])[0],('other_text_shift',item)
                pixels=[(x,y) for y in range(rects[2][1],rects[2][3]) for x in range(image.width) if image.getpixel((x,y))==rgb]
                assert len(pixels)>12 and min(x for x,y in pixels)>right,('dot_must_follow_text',right,pixels[:3])
                report['checks'].append(name+'_trailing_dot_and_unchanged_menu_geometry')
                time.sleep(4.5)
                refreshed,after_rects=grab()
                assert rects==after_rects and ImageChops.difference(image,refreshed).getbbox() is None,'menu_changed_or_ghosted_during_refresh'
                report['checks'].append(name+'_single_popup_and_stable_repeated_refresh')
                close()
            # Ordinary menus should still open as one native popup each.
            for wanted in ('对齐','文件'):
                if wanted not in titles:continue
                rect=wintypes.RECT();user32.GetMenuItemRect(editor[0],bar,titles.index(wanted),ctypes.byref(rect))
                user32.SetCursorPos((rect.left+rect.right)//2,(rect.top+rect.bottom)//2)
                x=(rect.left+rect.right)//2;y=(rect.top+rect.bottom)//2
                user32.mouse_event(2,0,0,0,0);user32.mouse_event(4,0,0,0,0)
                wait(popup_windows,wanted+' popup');assert len(popup_windows())==1;close()
                report['checks'].append(wanted+'_single_popup')
        except Exception as error:
            report['error']=str(error)
            report['exitcode']=process.poll()
            report['windows']=[dict(hwnd=w[0],pid=w[1],title=w[2],cls=class_name(w[0])) for w in windows() if w[1]==process.pid or class_name(w[0])=='#32768']
            report['editor_bounds']=[rect.left,rect.top,rect.right,rect.bottom] if 'rect' in locals() else None
            report['snapshots']={p.name:p.read_text(encoding='utf8') for p in (ai/'runtime').glob('frontend-menu-*.json')}
            raise
        finally:
            if process.poll() is None:process.terminate();process.wait(timeout=5)
            time.sleep(.3)
            if prior_context is None:context.unlink(missing_ok=True)
            else:context.write_bytes(prior_context)
            (output/'frontend-menu-layout.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(checks=report['checks'],executable=report['executable']),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
