"""Visible Windows acceptance: real Praat file picker -> editor menu -> production host.

Run from project root with the desktop Python. No model requests or measurements.
Refuses to interfere with existing Praat/chat windows. Optional --observe-react
uses Playwright/CDP solely to inspect the real WebView2; never launches a mock host.
Temporary fixture/evidence go to PI_SCRATCH_DIR; --output persists sanitized results.
"""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes as w
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import wave

PROJECT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT / 'ai'), str(Path(__file__).resolve().parent)]
from praat_ai.process import process_alive
from praat_ai.sendpraat import list_windows
from verify_ai_menu_no_crash import find_menu_command

USER32 = ctypes.windll.user32
USER32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
USER32.SendMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
USER32.SendMessageW.restype = w.LPARAM
USER32.SendMessageTimeoutW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM, w.UINT, w.UINT, ctypes.POINTER(ctypes.c_size_t)]
USER32.SendMessageTimeoutW.restype = w.LPARAM
USER32.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
USER32.ShowWindow.argtypes = [w.HWND, ctypes.c_int]
USER32.IsIconic.argtypes = [w.HWND]
USER32.GetForegroundWindow.restype = w.HWND


def wait_for(predicate, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(.2)
    raise RuntimeError('Window/state timeout')


def children(hwnd):
    result = []
    @ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    def collect(handle, _):
        title = ctypes.create_unicode_buffer(1024)
        cls = ctypes.create_unicode_buffer(128)
        USER32.GetWindowTextW(handle, title, len(title))
        USER32.GetClassNameW(handle, cls, len(cls))
        result.append(dict(handle=handle, title=title.value, cls=cls.value,
                           visible=bool(USER32.IsWindowVisible(handle))))
        return True
    USER32.EnumChildWindows(hwnd, collect, 0)
    return result


def command(hwnd, label):
    number, path, labels = find_menu_command(hwnd, (label,))
    if not number:
        raise RuntimeError(f'Menu not found: {label}; {labels}')
    print('MENU:', path, flush=True)
    USER32.PostMessageW(hwnd, 0x111, number, 0)
    return path


def responsive(hwnd):
    result = ctypes.c_size_t()
    start = time.monotonic()
    if not USER32.SendMessageTimeoutW(hwnd, 0, 0, 0, 2, 1500, ctypes.byref(result)):
        raise RuntimeError('Praat did not respond to WM_NULL within 1.5s')
    return round(time.monotonic() - start, 3)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--observe-react', action='store_true')
    parser.add_argument('--node', default='node')
    args = parser.parse_args()
    os.chdir(PROJECT)
    scratch = Path(os.environ['PI_SCRATCH_DIR'])
    runtime = PROJECT / 'ai/runtime'
    title = 'AIPraat · AI 工作台'
    if any(x.visible and (x.title == title or x.title == 'Praat Objects') for x in list_windows()):
        raise RuntimeError('Close existing Praat/chat windows before isolated acceptance')
    audio = scratch / 'menu-isolated-synthetic.wav'
    with wave.open(str(audio), 'wb') as stream:
        stream.setparams((1, 2, 16000, 16000, 'NONE', 'not compressed'))
        stream.writeframes(b''.join(struct.pack('<h', int(4000 * math.sin(2 * math.pi * 220 * i / 16000))) for i in range(16000)))
    protected = ['Praat.exe', 'ai/ai_config.json', 'ai/runtime/conversations.sqlite3', 'ai/runtime/modern/sessions.sqlite3']
    before = {name: digest(PROJECT / name) for name in protected if (PROJECT / name).exists()}
    audio_hash = digest(audio)
    environment = dict(os.environ)
    # Ensure the default run does not rely on CDP or inherited diagnostic flags.
    environment.pop('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', None)
    if args.observe_react:
        environment['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = '--remote-debugging-port=9337'
    process = subprocess.Popen([str(PROJECT / 'Praat.exe')], cwd=PROJECT, env=environment)
    result = dict(praatPid=process.pid, before=before, reactObserved=args.observe_react)
    try:
        objects = wait_for(lambda: next((x for x in list_windows() if x.process_id == process.pid and x.visible and x.title == 'Praat Objects'), None))
        time.sleep(3)
        assert not any(x.visible and x.title == title for x in list_windows())
        result['noAutoLaunch'] = True
        command(objects.handle, '从文件读取')
        picker = wait_for(lambda: next((x for x in list_windows() if x.process_id == process.pid and x.visible and any(c['cls'] == 'Edit' and c['visible'] for c in children(x.handle))), None))
        edit = next(c for c in children(picker.handle) if c['cls'] == 'Edit' and c['visible'])
        buffer = ctypes.create_unicode_buffer(str(audio))
        USER32.SendMessageW(edit['handle'], 0xC, 0, ctypes.cast(buffer, ctypes.c_void_p).value)
        USER32.PostMessageW(picker.handle, 0x111, 1, 0)
        time.sleep(.7)
        view = next(c for c in children(objects.handle) if c['cls'] == 'Button' and '查看并编辑' in c['title'])
        USER32.PostMessageW(view['handle'], 0xF5, 0, 0)
        editor = wait_for(lambda: next((x for x in list_windows() if x.process_id == process.pid and x.visible and 'Sound' in x.title), None))
        result['editorTitle'] = editor.title
        start = time.monotonic()
        result['menu'] = command(editor.handle, '启动前端')
        chat = wait_for(lambda: next((x for x in list_windows() if x.visible and x.title == title), None), 45)
        def own_ready():
            path = runtime / 'frontend-ready.json'
            if not path.exists():
                return None
            record = json.loads(path.read_text(encoding='utf8'))
            return record if record.get('pid') == chat.process_id else None
        ready = wait_for(own_ready, 45)
        assert ready['praatPid'] == process.pid and ready['executor'] == 'ModernExecutor'
        result.update(ready=ready, startupSeconds=round(time.monotonic() - start, 2))
        if args.observe_react:
            observed = subprocess.run([args.node, str(Path(__file__).with_name('observe_modern_menu.cjs'))], cwd=PROJECT, env=environment, timeout=45, capture_output=True, text=True, encoding='utf8')
            if observed.returncode:
                raise RuntimeError(observed.stderr)
            data = json.loads(observed.stdout)
            assert data['api'] == ['rpc'] and not data['host']['cloudAllowed'] and data['taskCount'] == 0
            snapshot = data['host']['praat']
            assert snapshot['pid'] == process.pid
            assert any(o['className'] == 'Sound' and o['name'] == 'Sound menu-isolated-synthetic' and o['selected'] for o in snapshot['objects'])
            result['react'] = data
        result['responsiveSeconds'] = [responsive(objects.handle), responsive(editor.handle)]
        context = (runtime / 'chat_context.tsv').read_bytes()
        USER32.ShowWindow(chat.handle, 6)
        result['repeatMenu'] = command(editor.handle, '启动前端')
        time.sleep(3)
        chats = [x for x in list_windows() if x.visible and x.title == title]
        assert len(chats) == 1 and chats[0].process_id == chat.process_id
        assert not USER32.IsIconic(chat.handle)
        result.update(reusedPid=chat.process_id, restored=True, foregroundIsChat=USER32.GetForegroundWindow() == chat.handle)
        assert result['foregroundIsChat']
        result['responsiveAfterRepeat'] = [responsive(objects.handle), responsive(editor.handle)]
        assert context == (runtime / 'chat_context.tsv').read_bytes()
        assert digest(audio) == audio_hash
        result['audioUnchanged'] = True
        result['after'] = {name: digest(PROJECT / name) for name in before}
        assert result['after'] == before
        command(objects.handle, '退出 Praat')
        confirmation = wait_for(lambda: next((x for x in list_windows() if x.process_id == process.pid and x.visible and x.title == '确认退出'), None))
        exit_button = next(c for c in children(confirmation.handle) if c['cls'] == 'Button' and '退出' in c['title'])
        USER32.PostMessageW(exit_button['handle'], 0xF5, 0, 0)
        wait_for(lambda: not process_alive(process.pid))
        wait_for(lambda: not process_alive(chat.process_id), 15)
        result.update(parentCloseCleanup=True, passed=True)
    finally:
        if process.poll() is None:
            process.terminate()  # Only the isolated instance owned by this check.
            process.wait(timeout=10)
        output = args.output or scratch / 'modern-menu-result.json'
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
