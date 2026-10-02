"""Real Windows integrity-level regression for Praat's native Python workspace."""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPILER = ROOT / '.build-tools/msys/clang64/bin/clang++.exe'

HARNESS = r'''
#include <filesystem>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
#include <windows.h>
#include <shlobj.h>
static HRESULT checked_known_folder (REFKNOWNFOLDERID id, DWORD flags, HANDLE token, PWSTR *folder) {
    if (GetEnvironmentVariableW (L"PRAAT_WORKSPACE_TEST_CHECK_COM", nullptr, 0)) {
        APTTYPE type; APTTYPEQUALIFIER qualifier;
        const HRESULT state = CoGetApartmentType (&type, &qualifier);
        if (FAILED (state)) return state;
    }
    return SHGetKnownFolderPath (id, flags, token, folder);
}
#if __has_include("praat_python_workspace.h")
#define SHGetKnownFolderPath checked_known_folder
#include "praat_python_workspace.h"
#undef SHGetKnownFolderPath
#endif
WORKSPACE_FUNCTION
static DWORD integrity () {
    HANDLE token = nullptr;
    if (! OpenProcessToken (GetCurrentProcess (), TOKEN_QUERY, &token)) return 0;
    DWORD size = 0;
    GetTokenInformation (token, TokenIntegrityLevel, nullptr, 0, &size);
    std::vector<BYTE> bytes (size);
    if (! GetTokenInformation (token, TokenIntegrityLevel, bytes.data (), size, &size)) {
        CloseHandle (token); return 0;
    }
    auto *label = reinterpret_cast<TOKEN_MANDATORY_LABEL *> (bytes.data ());
    DWORD rid = *GetSidSubAuthority (label->Label.Sid, *GetSidSubAuthorityCount (label->Label.Sid) - 1);
    CloseHandle (token);
    return rid;
}
static int low_child (const wchar_t *result) {
    HANDLE source = nullptr, token = nullptr;
    if (! OpenProcessToken (GetCurrentProcess (), TOKEN_DUPLICATE | TOKEN_QUERY, &source)) return 90;
    if (! DuplicateTokenEx (source, TOKEN_ALL_ACCESS, nullptr, SecurityImpersonation, TokenPrimary, &token)) return 91;
    CloseHandle (source);
    SID_IDENTIFIER_AUTHORITY authority = SECURITY_MANDATORY_LABEL_AUTHORITY;
    PSID sid = nullptr;
    if (! AllocateAndInitializeSid (&authority, 1, SECURITY_MANDATORY_LOW_RID, 0,0,0,0,0,0,0, &sid)) return 92;
    TOKEN_MANDATORY_LABEL label { { sid, SE_GROUP_INTEGRITY } };
    if (! SetTokenInformation (token, TokenIntegrityLevel, &label, sizeof (label) + GetLengthSid (sid))) return 93;
    FreeSid (sid);
    wchar_t executable [32768];
    GetModuleFileNameW (nullptr, executable, 32768);
    std::wstring command = L"\"" + std::wstring (executable) + L"\" --probe \"" + result + L"\"";
    STARTUPINFOW startup { }; startup.cb = sizeof (startup);
    PROCESS_INFORMATION process { };
    if (! CreateProcessAsUserW (token, executable, command.data (), nullptr, nullptr, FALSE,
            CREATE_NO_WINDOW, nullptr, nullptr, &startup, &process)) {
        std::cerr << "low launch error=" << GetLastError () << "\n";
        CloseHandle (token); return 94;
    }
    CloseHandle (token); CloseHandle (process.hThread);
    if (WaitForSingleObject (process.hProcess, 30000) != WAIT_OBJECT_0) {
        TerminateProcess (process.hProcess, 95);
        WaitForSingleObject (process.hProcess, 5000);
        CloseHandle (process.hProcess);
        return 95;
    }
    DWORD exitCode = 0; GetExitCodeProcess (process.hProcess, &exitCode);
    CloseHandle (process.hProcess);
    return static_cast<int> (exitCode);
}
int wmain (int argc, wchar_t **argv) {
    if (argc != 3) return 98;
    if (std::wstring (argv [1]) == L"--low") return low_child (argv [2]);
    std::filesystem::path workspace;
    int error = 0;
    const bool initializedMta = GetEnvironmentVariableW (L"PRAAT_WORKSPACE_TEST_MTA", nullptr, 0) != 0;
    if (initializedMta && FAILED (CoInitializeEx (nullptr, COINIT_MULTITHREADED))) return 97;
    try {
        workspace = get_process_workspace ();
        std::filesystem::create_directories (workspace);
        const auto marker = workspace / ("probe-" + std::to_string (GetCurrentProcessId ()) + ".txt");
        std::ofstream data (marker);
        data << "python workspace write succeeded";
        data.close ();
        if (! data) error = 5;
        std::error_code ignored;
        std::filesystem::remove (marker, ignored);
        std::filesystem::remove (workspace, ignored); // Empty directory only.
    } catch (const std::system_error &failure) {
        error = failure.code ().value ();
    }
    APTTYPE apartment; APTTYPEQUALIFIER qualifier;
    const HRESULT comState = CoGetApartmentType (&apartment, &qualifier);
    if (initializedMta) CoUninitialize ();
    std::ofstream result { std::filesystem::path (argv [2]) };
    result << integrity () << "\n" << error << "\n" << workspace.u8string () << "\n"
        << static_cast<int> (comState) << "\n" << (SUCCEEDED (comState) ? static_cast<int> (apartment) : -1) << "\n";
    return result ? 0 : 99;
}
'''


class PythonWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.low_root = Path(os.environ['USERPROFILE']) / 'AppData/LocalLow' / ('praat-native-test-' + uuid.uuid4().hex)
        cls.low_root.mkdir()
        cls.build = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.build.cleanup)
        cls.addClassCleanup(cls.cleanup_low_root)
        source = (ROOT / 'sys/praat_python.cpp').read_text(encoding='utf-8')
        function = re.search(r'static std::filesystem::path get_process_workspace \(\) \{.*?\n\}', source, re.S)
        if function is None:
            raise AssertionError('Production workspace function not found')
        path = Path(cls.build.name) / 'probe.cpp'
        path.write_text(HARNESS.replace('WORKSPACE_FUNCTION', function.group()), encoding='utf-8')
        # A low process can read the test executable, and writes only into LocalLow.
        cls.executable = cls.low_root / 'workspace-test.exe'
        result = subprocess.run([str(COMPILER), '-std=gnu++17', '-municode', '-static', '-I' + str(ROOT / 'sys'),
                                 str(path), '-o', str(cls.executable), '-ladvapi32', '-lshell32', '-lole32', '-luuid'], capture_output=True)
        if result.returncode:
            raise AssertionError(result.stderr.decode('utf-8', errors='replace'))

    @classmethod
    def cleanup_low_root(cls):
        # Only this test's exact LocalLow child directory is removed.
        assert cls.low_root.parent == Path(os.environ['USERPROFILE']) / 'AppData/LocalLow'
        if cls.low_root.exists():
            shutil.rmtree(cls.low_root)

    def probe(self, low=False, env=None):
        record = self.low_root / ('result-' + uuid.uuid4().hex + '.txt')
        completed = subprocess.run([str(self.executable), '--low' if low else '--probe', str(record)],
                                   env=env, capture_output=True, timeout=40)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        lines = record.read_text(encoding='utf-8').splitlines()
        self.last_com_state = (int(lines[3]), int(lines[4]))
        return int(lines[0]), int(lines[1]), Path(lines[2])

    def test_normal_process_keeps_standard_temp(self):
        level, error, workspace = self.probe()
        self.assertGreaterEqual(level, 8192)
        self.assertEqual(error, 0)
        self.assertEqual(workspace.parent, Path(os.environ['TEMP']))

    def test_low_process_can_create_and_write_workspace(self):
        level, error, workspace = self.probe(low=True)
        self.assertEqual(level, 4096)
        self.assertEqual(error, 0, f'Low process could not write {workspace}; Win32 error={error}')
        self.assertTrue(workspace.is_relative_to(Path(os.environ['USERPROFILE']) / 'AppData/LocalLow'))

    def test_low_process_does_not_depend_on_inaccessible_temp(self):
        env = dict(os.environ, TEMP=str(Path(self.build.name) / '不可写 TEMP 目录'), TMP=str(Path(self.build.name) / '不可写 TEMP 目录'))
        level, error, workspace = self.probe(low=True, env=env)
        self.assertEqual(level, 4096)
        self.assertEqual(error, 0, f'Low process used unavailable temp: {workspace}')
        self.assertTrue(workspace.is_relative_to(Path(os.environ['USERPROFILE']) / 'AppData/LocalLow'))

    def test_low_process_initializes_and_balances_com(self):
        level, error, workspace = self.probe(low=True, env=dict(os.environ, PRAAT_WORKSPACE_TEST_CHECK_COM='1'))
        self.assertEqual(level, 4096)
        self.assertEqual(error, 0, f'Known folder query called without COM initialization: {workspace}')
        self.assertEqual(self.last_com_state[0], -2147221008)  # CO_E_NOTINITIALIZED after balanced release.

    def test_low_process_preserves_existing_mta(self):
        level, error, _ = self.probe(low=True, env=dict(os.environ, PRAAT_WORKSPACE_TEST_CHECK_COM='1', PRAAT_WORKSPACE_TEST_MTA='1'))
        self.assertEqual(level, 4096)
        self.assertEqual(error, 0)
        self.assertEqual(self.last_com_state, (0, 1))  # Existing MTA remains initialized.


if __name__ == '__main__':
    unittest.main(verbosity=2)
