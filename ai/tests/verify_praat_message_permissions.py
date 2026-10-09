"""Check native -> Python token inheritance and Message.txt access without writes."""
import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def integrity_level():
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    security = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    security.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    security.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)]
    security.GetSidSubAuthorityCount.argtypes = [w.LPVOID]
    security.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
    security.GetSidSubAuthority.argtypes = [w.LPVOID, w.DWORD]
    security.GetSidSubAuthority.restype = ctypes.POINTER(w.DWORD)
    token = w.HANDLE()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        size = w.DWORD()
        security.GetTokenInformation(token, 25, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        if not security.GetTokenInformation(token, 25, buffer, size, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        sid = ctypes.cast(buffer, ctypes.POINTER(w.LPVOID))[0]
        return security.GetSidSubAuthority(sid, security.GetSidSubAuthorityCount(sid)[0] - 1)[0]
    finally:
        kernel.CloseHandle(token)


def probe(output):
    from praat_ai.sendpraat import message_file_path
    result = dict(pid=os.getpid(), parent_pid=os.getppid(), integrity=integrity_level())
    try:
        # Opening with write access checks MIC/DACL without changing any bytes.
        with message_file_path().open('r+b'):
            pass
        result['message_write_access'] = True
    except OSError as error:
        result.update(message_write_access=False, error=str(error))
    Path(output).write_text(json.dumps(result, ensure_ascii=False), encoding='utf8')


def main():
    if sys.argv[1] == '--probe':
        probe(sys.argv[2])
        return 0
    root = Path(__file__).resolve().parents[2]
    results = []
    with tempfile.TemporaryDirectory(prefix='message-permissions-', dir=root/'installer'/'verification') as temporary:
        directory = Path(temporary)
        for name in sys.argv[2:]:
            executable = (root/name).resolve()
            output = directory/'probe.json'
            output.unlink(missing_ok=True)
            command = subprocess.list2cmdline([sys.executable, str(Path(__file__).resolve()), '--probe', str(output)])
            script = directory/'probe.praat'
            script.write_text('runSystem: "' + command.replace('"', '""') + '"\n', encoding='utf8')
            completed = subprocess.run([str(executable), '--FULL-TRUST', '--no-plugins', '--no-pref-files', '--run', str(script)],
                                       cwd=root, capture_output=True, timeout=20)
            if completed.returncode or not output.is_file():
                raise RuntimeError(f'{name}: native probe failed: {completed.stderr!r}')
            result = json.loads(output.read_text(encoding='utf8'))
            results.append(dict(executable=name, **result))
    report = root/'test-records'/'installer'/('message-permissions-'+sys.argv[1]+'.json')
    report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf8')
    print(report)
    for result in results:
        print(json.dumps(result, ensure_ascii=False))
    return 0 if all(r['integrity'] >= 0x2000 and r['message_write_access'] for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
