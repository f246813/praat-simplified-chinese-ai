"""Menu/desktop launch tests, isolated state, never a model request or real GUI."""
import ctypes
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import start_ai_chat
import start_installed_frontend
from praat_ai import desktop_launch as launch
from praat_ai import process
from praat_ai.modern_app import HostAPI


class DesktopLaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.getenv('PI_SCRATCH_DIR'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.environment = patch.dict(os.environ)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        for key in list(os.environ):
            if key.startswith('PRAAT_'): os.environ.pop(key)

    def test_native_menu_prepares_desktop_without_old_service_or_network(self):
        with patch.dict(os.environ, PRAAT_AI_CONTROL_COMMAND='start', PRAAT_AI_CONTROL_QUIET='1'), \
                patch.object(launch, 'runtime_directory', return_value=self.root), \
                patch.object(launch, 'check_desktop_dependencies'), \
                patch('praat_ai.control.main') as old, patch('socket.socket.connect', side_effect=AssertionError('network')):
            self.assertEqual(launch.menu_control_main([]), 0)
        old.assert_not_called()
        status = json.loads((self.root/'status.json').read_text())
        self.assertEqual(status['frontend_start_phase'], 'ready-to-launch')
        self.assertFalse(status['model_service_started'])
        self.assertEqual(status['frontend_model_source'], 'desktop')

    def test_explicit_service_cli_keeps_legacy_behavior(self):
        with patch.dict(os.environ, PRAAT_AI_CONTROL_COMMAND='start', PRAAT_AI_CONTROL_QUIET='1'), \
                patch('praat_ai.control.main', return_value=7) as old:
            self.assertEqual(launch.menu_control_main(['start']), 7)
        old.assert_called_once_with(['start'])

    def test_other_native_commands_keep_legacy_behavior(self):
        with patch.dict(os.environ, PRAAT_AI_CONTROL_COMMAND='status', PRAAT_AI_CONTROL_QUIET='1'), \
                patch('praat_ai.control.main', return_value=0) as old:
            self.assertEqual(launch.menu_control_main([]), 0)
        old.assert_called_once_with([])

    def test_missing_python_dependencies_fail_before_spawn(self):
        with patch.object(launch.importlib.util, 'find_spec', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'webview, clr'):
                launch.check_desktop_dependencies(self.root)

    def test_missing_assets_fail_before_spawn(self):
        with patch.object(launch.importlib.util, 'find_spec', return_value=object()):
            with self.assertRaisesRegex(RuntimeError, 'dist/index.html'):
                launch.check_desktop_dependencies(self.root)

    def test_launch_failure_is_visible_and_redacts_both_credentials(self):
        config = self.root/'config.json'
        config.write_text(json.dumps({'api':{'api_key':'cloud-private'},'qwen':{'api_key':'local-private'}}))
        with patch.object(ctypes.windll.user32, 'MessageBoxW', return_value=1) as dialog:
            self.assertEqual(launch.report_failure(RuntimeError('cloud-private local-private'),
                                                  runtime=self.root, config_path=config), 1)
        record = (self.root/'frontend-startup-error.json').read_text()
        self.assertNotIn('cloud-private', record)
        self.assertNotIn('local-private', record)
        self.assertIn('[REDACTED]', record)
        self.assertNotIn('cloud-private', str(dialog.call_args))
        self.assertIn('Python', str(dialog.call_args))

    def test_pythonw_with_no_stderr_still_displays_error(self):
        with patch.object(launch.sys, 'stderr', None), patch.object(ctypes.windll.user32, 'MessageBoxW', return_value=1) as dialog:
            self.assertEqual(launch.report_failure(RuntimeError('dependency failed'), runtime=self.root), 1)
        dialog.assert_called_once()

    def test_start_preflight_failure_has_no_child_and_reports(self):
        with patch.object(launch, 'check_desktop_dependencies', side_effect=RuntimeError('missing')), \
                patch.object(launch, 'report_failure', return_value=1) as error, \
                patch.object(start_ai_chat.subprocess, 'Popen') as spawn:
            self.assertEqual(start_ai_chat.main(self.root), 1)
        error.assert_called_once()
        spawn.assert_not_called()

    def test_alive_reused_pid_without_chat_window_or_identity_does_not_suppress_launch(self):
        (self.root/'chat.pid').write_text('4242')
        with patch.object(launch, 'check_desktop_dependencies'), \
                patch.object(start_ai_chat, 'process_alive', return_value=True), \
                patch.object(start_ai_chat, 'focus_existing_window', return_value=False), \
                patch.object(start_ai_chat, 'start_new_chat_window', return_value=0) as spawn:
            self.assertEqual(start_ai_chat.main(self.root), 0)
        spawn.assert_called_once()

    def test_identity_matched_process_still_starting_is_not_duplicated(self):
        identity = dict(executable='python.exe', started='creation')
        (self.root/'chat.pid').write_text('4242')
        (self.root/'chat-process.json').write_text(json.dumps(dict(pid=4242,identity=identity)))
        with patch.object(launch, 'check_desktop_dependencies'), \
                patch.object(start_ai_chat, 'process_alive', return_value=True), \
                patch.object(start_ai_chat, 'focus_existing_window', return_value=False), \
                patch.object(process, 'process_identity', return_value=identity), \
                patch.object(start_ai_chat, 'start_new_chat_window') as spawn:
            self.assertEqual(start_ai_chat.main(self.root), 0)
        spawn.assert_not_called()

    def test_snapshot_requires_bound_live_parent_and_matching_native_marker(self):
        path = str(self.root/'Praat.exe')
        (self.root/'chat_context.tsv').write_text('id\tclass\tname\tselected\tsel_start\tsel_end\n1\tSound\t合成声音\t1\t\t\n# praat-pid=123\n',encoding='utf8')
        with patch.dict(os.environ, PRAAT_AI_PRAAT_PID='123', PRAAT_AI_PRAAT_EXECUTABLE=path), \
                patch.object(launch, 'runtime_directory', return_value=self.root), \
                patch.object(process, 'process_identity', return_value=dict(executable=path,started='now')):
            self.assertEqual(launch.praat_snapshot()['objects'][0]['name'], '合成声音')
            with patch.dict(os.environ, PRAAT_AI_PRAAT_PID='124'):
                self.assertIsNone(launch.praat_snapshot())
            with patch.object(process, 'process_identity', return_value=None):
                self.assertIsNone(launch.praat_snapshot())

    def test_host_records_connection_once_without_exposing_an_extra_api(self):
        class App:
            def rpc(self, method, params): return {'host':'real-service-fixture'}
        api = HostAPI(App())
        calls = []
        api._on_connected = lambda: calls.append('connected')
        self.assertEqual([key for key in dir(api) if not key.startswith('_')], ['rpc'])
        api.rpc('bootstrap', {}); api.rpc('bootstrap', {})
        self.assertEqual(calls, ['connected'])

    def test_installed_entry_uses_same_desktop_launcher(self):
        with patch.object(start_ai_chat, 'main', return_value=0) as run:
            self.assertEqual(start_installed_frontend.main(), 0)
        run.assert_called_once_with()

    def test_cleanup_never_removes_someone_elses_pid(self):
        (self.root/'chat.pid').write_text('9999999')
        (self.root/'frontend-ready.json').write_text(json.dumps(dict(pid=os.getpid())))
        with patch.object(launch, 'runtime_directory', return_value=self.root):
            launch.clear_own_records()
        self.assertTrue((self.root/'chat.pid').is_file())
        self.assertFalse((self.root/'frontend-ready.json').exists())


if __name__ == '__main__': unittest.main()
