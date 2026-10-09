"""Real popup regression: API has no GPU dot before/after hover or reopen."""
import ctypes
from ctypes import wintypes
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from PIL import ImageChops, ImageGrab
from verify_path_settings_live import class_name, menu, user32, wait, windows

user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
user32.GetMenuItemRect.argtypes = [wintypes.HWND, wintypes.HMENU, wintypes.UINT, ctypes.POINTER(wintypes.RECT)]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
user32.GetMenuState.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
COLOURS = {(220, 38, 38), (234, 179, 8), (22, 163, 74)}


def main():
    project = Path(__file__).resolve().parents[2]
    executable, fixture = (Path(p).resolve() for p in sys.argv[1:3])
    output = project / 'test-records' / 'installer'
    source_ai = project / 'ai'
    report = dict(executable=str(executable), checks=[], failures=[])
    with tempfile.TemporaryDirectory(prefix='api-vram-', dir=output) as directory:
        root = Path(directory); ai = root/'ai'; ai.mkdir(); (ai/'runtime').mkdir()
        for path in source_ai.glob('*.py'): shutil.copy2(path, ai/path.name)
        shutil.copytree(source_ai/'praat_ai', ai/'praat_ai', ignore=shutil.ignore_patterns('__pycache__'))
        profile = root / 'profile'; profile.mkdir()
        (profile / 'Preferences.txt').write_text('Python.executablePath: ' + sys.executable +
            '\nAI.projectDirectory: ' + str(ai) + '\n', encoding='utf8')
        model = root / 'model.gguf'; model.touch()
        server = root / 'llama-server.exe'; server.touch()
        raw = dict(api=dict(enabled=True, base_url='https://example.invalid/v1', model='cloud'),
            server=dict(model_path=str(model), llama_server=str(server), active_preset='fixture',
                presets=[dict(id='fixture', label='本地验收预设', model_path=str(model))]))
        config = root / 'config.json'
        def save(): config.write_text(json.dumps(raw), encoding='utf8')
        save()
        gpu = root / 'gpu.txt'; gpu.write_text('1536')
        script = root / 'editor.praat'
        script.write_text('Create Sound from formula: "api-vram-test", 1, 0, 0.2, 44100, ~0\nView & Edit\n')
        env = dict(os.environ, PRAAT_AI_PROJECT_DIR='ai', PRAAT_AI_CONFIG_PATH=str(config),
            PRAAT_TEST_VRAM_FILE=str(gpu), PYTHONPATH=str(ai), PRAAT_PYTHON_EXECUTABLE=Path(sys.executable).as_posix(),
            PATH=str(fixture.parent) + os.pathsep + os.environ['PATH'])
        process = subprocess.Popen([str(executable), '--new-send', '--no-plugins',
            '--no-pref-files', '--pref-dir=' + str(profile), str(script)], env=env, cwd=root)
        try:
            editor = wait(lambda: next((w for w in windows() if w[1] == process.pid and 'api-vram-test' in w[2]), None), 'editor')
            bar = user32.GetMenu(editor[0]); titles = []
            for i in range(user32.GetMenuItemCount(bar)):
                label = ctypes.create_unicode_buffer(128)
                user32.GetMenuStringW(bar, i, label, 128, 0x400); titles.append(label.value)
            index = titles.index('前端'); sub = user32.GetSubMenu(bar, index)
            popups = lambda: [w for w in windows() if w[1] == process.pid and class_name(w[0]) == '#32768']
            def fresh_model():
                label = '模型: ' + ('云端API模式' if raw['api']['enabled'] else '本地验收预设')
                wait(lambda: any(s == label for group in menu(editor[0]) for s, _ in group), label)
                time.sleep(2.2)
            def open_menu():
                user32.SetWindowPos(editor[0], wintypes.HWND(-1), 0, 0, 0, 0, 0x43)
                rect = wintypes.RECT(); assert user32.GetMenuItemRect(editor[0], bar, index, ctypes.byref(rect))
                user32.SetForegroundWindow(editor[0])
                user32.SetCursorPos((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
                time.sleep(.15)
                user32.mouse_event(2, 0, 0, 0, 0); user32.mouse_event(4, 0, 0, 0, 0)
                wait(popups, 'popup'); time.sleep(.3)
            def close_menu():
                user32.keybd_event(0x1B, 0, 0, 0); user32.keybd_event(0x1B, 0, 2, 0)
                wait(lambda: not popups(), 'popup closed')
            def capture(name, expected_dot=False):
                popup = popups(); assert len(popup) == 1, popup
                row = wintypes.RECT(); assert user32.GetMenuItemRect(editor[0], sub, 2, ctypes.byref(row))
                image = ImageGrab.grab((row.left, row.top, row.right, row.bottom)).convert('RGB')
                image.save(output / ('api-vram-' + name + '.png'))
                count = sum(pixel in COLOURS for pixel in image.get_flattened_data())
                if not (count > 12 if expected_dot else count == 0): report['failures'].append([name, count])
                states=[user32.GetMenuState(sub, i, 0x400) & 3 for i in range(3)]
                expected=[0,0,1 if raw['api']['enabled'] else 0]
                if states != expected: report['failures'].append([name, 'text_states', states, expected])
                report['checks'].append(name)
            def hover():
                row = wintypes.RECT(); assert user32.GetMenuItemRect(editor[0], sub, 2, ctypes.byref(row))
                user32.SetCursorPos((row.left + row.right) // 2, (row.top + row.bottom) // 2)
                time.sleep(.3)
            def sweep(name):
                # Keep the model row untouched while repeatedly selecting other
                # rows. Catch blank/changed frames outside the native hover row.
                row = wintypes.RECT(); user32.GetMenuItemRect(editor[0], sub, 0, ctypes.byref(row))
                bounds = (row.left + 3, row.top + 3, row.right - 3, row.bottom - 3)
                target = wintypes.RECT(); user32.GetMenuItemRect(editor[0], sub, 4, ctypes.byref(target))
                user32.SetCursorPos((target.left+target.right)//2, (target.top+target.bottom)//2)
                time.sleep(.2)
                reference = ImageGrab.grab(bounds).convert('RGB')
                changed = 0
                for i in range(48):
                    target = wintypes.RECT()
                    user32.GetMenuItemRect(editor[0], sub, (1,2,4,5,7,8)[i % 6], ctypes.byref(target))
                    user32.SetCursorPos((target.left+target.right)//2, (target.top+target.bottom)//2)
                    frame = ImageGrab.grab(bounds).convert('RGB')
                    changed += ImageChops.difference(reference, frame).getbbox() is not None
                if changed: report['failures'].append([name, 'unchanged_row_changed_frames', changed])
                report['checks'].append(name + '_48_mouse_moves_stable_model_row')
                hover(); capture(name + '_dot_after_motion', not raw['api']['enabled'])
            fresh_model()
            for i in range(3):
                open_menu(); capture('api_open_' + str(i))
                if i == 0: sweep('api')
                hover(); capture('api_hover_' + str(i)); close_menu()
            raw['api']['enabled'] = False; save(); fresh_model()
            open_menu(); capture('local_dot_restored', True)
            sweep('local')
            hover(); capture('local_hover_keeps_dot', True)
            close_menu(); open_menu(); capture('local_reopen_keeps_dot',True)
            # Change the saved mode while the same native popup remains open.
            raw['api']['enabled'] = True; save(); fresh_model()
            capture('local_to_api_removes_dot_in_open_popup')
            hover(); capture('switched_api_hover'); close_menu()
            open_menu(); capture('switched_api_reopen'); close_menu()
            snapshot = ai / 'runtime' / ('frontend-menu-' + str(process.pid) + '.json')
            report['snapshot'] = json.loads(snapshot.read_text(encoding='utf8'))
            assert report['snapshot']['vram_warning'] == 'unknown'
            assert report['snapshot']['vram_free_gb'] is None
        except Exception as error:
            report['error'] = str(error)
            report['menu'] = menu(editor[0])
            report['runtime']={p.name:p.read_text(encoding='utf8',errors='replace') for p in (ai/'runtime').glob('*') if p.is_file() and p.suffix in {'.txt','.json'}}
            raise
        finally:
            if process.poll() is None: process.terminate(); process.wait(timeout=5)
            time.sleep(.3)
            (output / 'menu-colours-repaint.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    assert not report['failures'], report['failures']


if __name__ == '__main__': main()
