"""Real popup regression: API has no GPU dot before/after hover or reopen."""
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
from verify_path_settings_live import class_name, menu, user32, wait, windows

user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
user32.GetMenuItemRect.argtypes = [wintypes.HWND, wintypes.HMENU, wintypes.UINT, ctypes.POINTER(wintypes.RECT)]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
COLOURS = {(220, 38, 38), (234, 179, 8), (22, 163, 74)}


def main():
    project = Path(__file__).resolve().parents[2]
    executable, fixture = (Path(p).resolve() for p in sys.argv[1:3])
    output = project / 'installer' / 'verification'
    ai = project / 'ai'; context = ai / 'runtime' / 'chat_context.tsv'
    prior_context = context.read_bytes() if context.exists() else None
    report = dict(executable=str(executable), checks=[])
    with tempfile.TemporaryDirectory(prefix='api-vram-', dir=output) as directory:
        root = Path(directory); profile = root / 'profile'; profile.mkdir()
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
        env = dict(os.environ, PRAAT_AI_PROJECT_DIR=str(ai), PRAAT_AI_CONFIG_PATH=str(config),
            PRAAT_TEST_VRAM_FILE=str(gpu), PYTHONPATH=str(ai),
            PATH=str(fixture.parent) + os.pathsep + os.environ['PATH'])
        process = subprocess.Popen([str(executable), '--new-send', '--no-plugins',
            '--pref-dir=' + str(profile), str(script)], env=env)
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
                assert (count > 12 if expected_dot else count == 0), (name, count)
                report['checks'].append(name)
            def hover():
                row = wintypes.RECT(); assert user32.GetMenuItemRect(editor[0], sub, 2, ctypes.byref(row))
                user32.SetCursorPos((row.left + row.right) // 2, (row.top + row.bottom) // 2)
                time.sleep(.3)
            fresh_model()
            for i in range(3):
                open_menu(); capture('api_open_' + str(i))
                hover(); capture('api_hover_' + str(i)); close_menu()
            raw['api']['enabled'] = False; save(); fresh_model()
            open_menu(); capture('local_dot_restored', True)
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
            raise
        finally:
            if process.poll() is None: process.terminate(); process.wait(timeout=5)
            time.sleep(.3)
            if prior_context is None: context.unlink(missing_ok=True)
            else: context.write_bytes(prior_context)
            (output / 'api-vram-menu.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
