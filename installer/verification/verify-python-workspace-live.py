"""Open the actual frontend from an isolated low-integrity native Praat process.

Only synthetic sound, private preferences/configuration and fixture processes are used.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes as W
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
LOW = Path(os.environ['USERPROFILE']) / 'AppData/LocalLow'
K = ctypes.WinDLL('kernel32', use_last_error=True)
A = ctypes.WinDLL('advapi32', use_last_error=True)
U = ctypes.WinDLL('user32', use_last_error=True)

class STARTUP(ctypes.Structure):
    _fields_ = [('cb', W.DWORD), ('reserved', W.LPWSTR), ('desktop', W.LPWSTR), ('title', W.LPWSTR),
                ('x', W.DWORD), ('y', W.DWORD), ('width', W.DWORD), ('height', W.DWORD),
                ('cols', W.DWORD), ('rows', W.DWORD), ('fill', W.DWORD), ('flags', W.DWORD),
                ('show', W.WORD), ('reserved_size', W.WORD), ('reserved_bytes', ctypes.c_void_p),
                ('input', W.HANDLE), ('output', W.HANDLE), ('error', W.HANDLE)]
class PROCESS(ctypes.Structure):
    _fields_ = [('process', W.HANDLE), ('thread', W.HANDLE), ('pid', W.DWORD), ('tid', W.DWORD)]
class SIDATTR(ctypes.Structure):
    _fields_ = [('sid', ctypes.c_void_p), ('attributes', W.DWORD)]
class LABEL(ctypes.Structure):
    _fields_ = [('label', SIDATTR)]

K.GetCurrentProcess.restype = W.HANDLE
K.CloseHandle.argtypes = [W.HANDLE]
K.LocalFree.argtypes = [ctypes.c_void_p]
K.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]; K.OpenProcess.restype = W.HANDLE
K.GetExitCodeProcess.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD)]
K.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
K.TerminateProcess.argtypes = [W.HANDLE, W.UINT]
A.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, ctypes.POINTER(W.HANDLE)]
A.DuplicateTokenEx.argtypes = [W.HANDLE, W.DWORD, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.POINTER(W.HANDLE)]
A.ConvertStringSidToSidW.argtypes = [W.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
A.GetLengthSid.argtypes = [ctypes.c_void_p]; A.GetLengthSid.restype = W.DWORD
A.SetTokenInformation.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD]
A.GetTokenInformation.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD, ctypes.POINTER(W.DWORD)]
A.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]; A.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
A.GetSidSubAuthority.argtypes = [ctypes.c_void_p, W.DWORD]; A.GetSidSubAuthority.restype = ctypes.POINTER(W.DWORD)
A.CreateProcessAsUserW.argtypes = [W.HANDLE, W.LPCWSTR, W.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                  W.BOOL, W.DWORD, ctypes.c_void_p, W.LPCWSTR, ctypes.POINTER(STARTUP), ctypes.POINTER(PROCESS)]
ENUM = ctypes.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
U.EnumWindows.argtypes = [ENUM, W.LPARAM]
U.EnumChildWindows.argtypes = [W.HWND, ENUM, W.LPARAM]
U.GetWindowThreadProcessId.argtypes = [W.HWND, ctypes.POINTER(W.DWORD)]
U.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, ctypes.c_int]
U.ShowWindow.argtypes = [W.HWND, ctypes.c_int]
U.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]

def checked(result):
    if not result: raise ctypes.WinError(ctypes.get_last_error())
    return result

def integrity(handle):
    token = W.HANDLE(); checked(A.OpenProcessToken(handle, 8, ctypes.byref(token)))
    try:
        size = W.DWORD(); A.GetTokenInformation(token, 25, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        checked(A.GetTokenInformation(token, 25, buffer, size.value, ctypes.byref(size)))
        label = ctypes.cast(buffer, ctypes.POINTER(LABEL)).contents
        return A.GetSidSubAuthority(label.label.sid, A.GetSidSubAuthorityCount(label.label.sid)[0]-1)[0]
    finally: K.CloseHandle(token)

def launch_low(arguments, environment, directory):
    source = W.HANDLE(); token = W.HANDLE(); sid = ctypes.c_void_p()
    try:
        checked(A.OpenProcessToken(K.GetCurrentProcess(), 10, ctypes.byref(source)))
        checked(A.DuplicateTokenEx(source, 0xF01FF, None, 2, 1, ctypes.byref(token)))
        checked(A.ConvertStringSidToSidW('S-1-16-4096', ctypes.byref(sid)))
        label = LABEL(SIDATTR(sid, 0x20))
        checked(A.SetTokenInformation(token, 25, ctypes.byref(label), ctypes.sizeof(label)+A.GetLengthSid(sid)))
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline(arguments))
        block = ctypes.create_unicode_buffer('\0'.join(k+'='+v for k,v in sorted(environment.items(), key=lambda pair: pair[0].upper()))+'\0\0')
        startup = STARTUP(); startup.cb = ctypes.sizeof(startup); startup.flags = 1; startup.show = 0
        process = PROCESS()
        checked(A.CreateProcessAsUserW(token, arguments[0], command, None, None, False, 0x400, block,
                                      str(directory), ctypes.byref(startup), ctypes.byref(process)))
        K.CloseHandle(process.thread)
        return process
    finally:
        if sid: K.LocalFree(sid)
        if token: K.CloseHandle(token)
        if source: K.CloseHandle(source)

def owned_windows(pids):
    found = []
    @ENUM
    def collect(hwnd, _):
        owner = W.DWORD(); U.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value in pids:
            title = ctypes.create_unicode_buffer(2048); U.GetWindowTextW(hwnd, title, len(title))
            found.append((int(hwnd), owner.value, title.value))
            U.ShowWindow(hwnd, 0)
        return True
    U.EnumWindows(collect, 0)
    return found

def wait(predicate, label, pids, timeout=30):
    end = time.monotonic()+timeout
    while time.monotonic()<end:
        value = predicate()
        if value: return value
        errors = [w for w in owned_windows(pids) if w[2] in ('Message','Warning')]
        if errors:
            details = []
            @ENUM
            def collect(hwnd, _):
                title = ctypes.create_unicode_buffer(8192); U.GetWindowTextW(hwnd,title,len(title))
                details.append(title.value); return True
            for error in errors: U.EnumChildWindows(error[0],collect,0)
            raise AssertionError('Native diagnostic dialog: '+str(details))
        time.sleep(.05)
    raise AssertionError('Timeout: '+label+'; windows='+str(owned_windows(pids)))

def stop_owned(handle):
    status = W.DWORD()
    if K.GetExitCodeProcess(handle, ctypes.byref(status)) and status.value == 259:
        K.TerminateProcess(handle, 0)
        K.WaitForSingleObject(handle, 5000)
    K.CloseHandle(handle)

def main():
    candidate = Path(sys.argv[1]).resolve()
    fixture = LOW / ('praat-frontend-test-'+uuid.uuid4().hex); fixture.mkdir()
    assert fixture.parent == LOW
    report = {'candidate_sha256': hashlib.sha256(candidate.read_bytes()).hexdigest(), 'checks': [], 'fixture':str(fixture)}
    process = None; chat_handle = None; workspace = None
    try:
        executable = fixture/'Praat.exe'; shutil.copy2(candidate, executable)
        ai = fixture/'ai'; ai.mkdir()
        shutil.copytree(ROOT/'ai/praat_ai', ai/'praat_ai', ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        for script in (ROOT/'ai').glob('*.py'): shutil.copy2(script, ai/script.name)
        profile = fixture/'home/AppData/Roaming/Praat'; profile.mkdir(parents=True)
        user_preferences = Path(os.environ['APPDATA'])/'Praat/Preferences.txt'
        raw = user_preferences.read_bytes()
        prefs = raw.decode('utf-16' if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8')
        python = next(line.split(': ',1)[1] for line in prefs.splitlines() if line.startswith('Python.executablePath: '))
        report['python_executable'] = python
        (profile/'Preferences.txt').write_text('Python.executablePath: '+python+'\nAI.projectDirectory: '+str(ai)+'\n', encoding='utf-8')
        configuration = {'api':{'enabled':True,'base_url':'https://test.invalid/v1','model':'fixture','api_key':'EMPTY','stop_local_service':False},
                         'server':{'auto_start':False}, 'qwen':{'vision_when_requested':False}}
        config = ai/'ai_config.json'; config.write_text(json.dumps(configuration), encoding='utf-8')
        script = fixture/'open-editor.praat'
        script.write_text('Create Sound from formula: "あなた", 1, 0, 0.2, 44100, ~0.1*sin(2*pi*220*x)\nView & Edit\n', encoding='utf-8')
        env = {k:v for k,v in os.environ.items() if not k.startswith('PRAAT_')}
        env.update(APPDATA=str(profile.parent), PRAAT_AI_PROJECT_DIR=str(ai), PRAAT_AI_CONFIG_PATH=str(config),
                   PRAAT_PYTHON_EXECUTABLE=python, PYTHONDONTWRITEBYTECODE='1')
        process = launch_low([str(executable), '--new-send', '--no-plugins', '--FULL-TRUST', '--pref-dir='+str(profile), str(script)],env,fixture)
        workspace = LOW/'Praat/Python'/('praat_py_workspace_'+str(process.pid))
        assert integrity(process.process)==4096
        pids = {process.pid}
        spec = importlib.util.spec_from_file_location('menu_helpers',ROOT/'ai/tests/verify_path_settings_live.py')
        helpers = importlib.util.module_from_spec(spec); spec.loader.exec_module(helpers)
        def ready_editor():
            for window in owned_windows(pids):
                if 'Sound あなた' not in window[2]: continue
                try: helpers.command(window[0], ('启动前端', 'Start frontend'))
                except AssertionError: continue
                return window
            return None
        editor = wait(ready_editor,'synthetic sound editor menu',pids)
        number = helpers.command(editor[0], ('启动前端', 'Start frontend'))
        checked(U.PostMessageW(editor[0],0x111,number,0))
        pid_file = ai/'runtime/chat.pid'
        chat_pid = wait(lambda:int(pid_file.read_text()) if pid_file.exists() and pid_file.read_text().strip() else None,'frontend child PID',pids)
        pids.add(chat_pid)
        chat_handle = checked(K.OpenProcess(0x101001,False,chat_pid))
        chat = wait(lambda:next((w for w in owned_windows(pids) if w[1]==chat_pid and w[2]=='Praat AI 对话'),None),'Tk frontend',pids)
        assert integrity(chat_handle)==4096
        workspace = LOW/'Praat/Python'/('praat_py_workspace_'+str(process.pid))
        context = json.loads((workspace/'praat_context.json').read_text(encoding='utf-8'))
        row = context['selected_objects'][0]
        assert row['name']=='Sound あなた' and row['class']=='Sound',row
        audio = Path(row['file']); assert audio.parent==workspace and audio.name=='1_Sound_あなた.wav'
        assert audio.read_bytes()[:4]==b'RIFF'
        status = json.loads((ai/'runtime/status.json').read_text(encoding='utf-8'))
        assert status['success'] and status['frontend_running'] and status['api_enabled'],status
        assert not any(w[2]=='Message' for w in owned_windows(pids))
        report.update(ok=True,praat_pid=process.pid,chat_pid=chat_pid,integrity=4096,workspace=str(workspace),
                      selected_object=row['name'],frontend_status=status['frontend_status'])
        report['checks'] = ['real_low_integrity_native_process','actual_editor_start_frontend_callback',
                            'selected_user_python_launcher','LocalLow_workspace_created_and_written',
                            'unicode_sound_export_RIFF','frontend_status_running','Tk_chat_window_low_integrity',
                            'private_preferences_configuration_and_runtime']
        print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    except Exception as failure:
        report.update(ok=False,error=str(failure)); raise
    finally:
        if chat_handle: stop_owned(chat_handle)
        if process: stop_owned(process.process)
        if workspace and workspace.exists() and workspace.parent==LOW/'Praat/Python' and workspace.name=='praat_py_workspace_'+str(process.pid):
            shutil.rmtree(workspace)
        # Keep private fixture for failed-run diagnostics; successful fixtures contain no user data.
        if report.get('ok'): shutil.rmtree(fixture)
        (ROOT/'test-records/installer/python-workspace-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0

if __name__=='__main__': raise SystemExit(main())
