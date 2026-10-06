"""Desktop cloud activation regression; isolated config, no provider requests."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from praat_ai import modern_budget as budget, modern_host
from praat_ai.modern_app import ModernApplication


class NoExecution:
    def capture_target(self, text):
        raise AssertionError('Unexpected Praat capture')

    def run(self, **kwargs):
        raise AssertionError('Unexpected execution')


class DesktopCloudActivationTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        for key in list(os.environ):
            if key.startswith('PRAAT_AI_'):
                os.environ.pop(key)
        temporary = tempfile.TemporaryDirectory(dir=os.getenv('PI_SCRATCH_DIR'))
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / 'config.json'
        self.config.write_text(json.dumps(dict(
            api=dict(enabled=True, locked=False, base_url='https://gateway.example/v1',
                     model='custom-model', api_key='fixture-private-key', token_mode='manual',
                     max_context_tokens=32768, plan_max_tokens=1000, stop_local_service=False),
            qwen=dict(base_url='http://127.0.0.1:8999/v1', model='local', token_mode='manual'),
            custom=dict(preserve='yes'))), encoding='utf8')
        self.network = patch('socket.socket.connect', side_effect=AssertionError('Unexpected network'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def application(self, **options):
        app = ModernApplication(self.root / 'modern', self.config, executor=NoExecution(), **options)
        self.addCleanup(app.close)
        return app

    def test_normal_menu_entry_accepts_configured_api_without_cli_flag(self):
        app, window, server = MagicMock(), MagicMock(), MagicMock()
        with patch.object(modern_host, 'ModernApplication', return_value=app) as factory, \
                patch.object(modern_host, 'create_window', return_value=(window, server)), \
                patch.object(modern_host, 'service_transition_lock'), \
                patch('webview.start') as start, patch('praat_ai.desktop_launch.report_failure') as failure:
            self.assertEqual(modern_host.main(['--config', str(self.config), '--data-dir', str(self.root / 'modern')]), 0)
        self.assertTrue(factory.call_args.kwargs.get('configured_cloud', False))
        self.assertFalse(factory.call_args.kwargs['allow_cloud'])
        start.assert_called_once()
        failure.assert_not_called()
        app.close.assert_called_once()
        server.close.assert_called_once()

    def test_saved_api_is_prepared_on_desktop_without_network_or_key_exposure(self):
        app = self.application(configured_cloud=True)
        boot = app.bootstrap()
        self.assertTrue(boot['host']['cloudAllowed'])
        self.assertTrue(boot['settings']['api']['has_api_key'])
        self.assertNotIn('fixture-private-key', json.dumps(boot))
        self.assertEqual(app.prepared().qwen.base_url, 'https://gateway.example/v1')
        self.assertEqual(app.tasks, {})

    def test_enable_and_disable_api_take_effect_without_restart(self):
        app = self.application(configured_cloud=True)
        app.rpc('settings.save', dict(settings=dict(api=dict(enabled=False))))
        self.assertEqual(app.prepared().qwen.base_url, 'http://127.0.0.1:8999/v1')
        app.rpc('settings.save', dict(settings=dict(api=dict(enabled=True, api_key=''))))
        self.assertEqual(app.prepared().qwen.api_key, 'fixture-private-key')
        app.close()
        restarted = self.application(configured_cloud=True)
        self.assertEqual(restarted.prepared().qwen.base_url, 'https://gateway.example/v1')
        self.assertEqual(json.loads(self.config.read_text())['custom'], dict(preserve='yes'))

    def test_connection_test_uses_current_enabled_settings_only_after_click(self):
        app = self.application(configured_cloud=True)
        app.rpc('settings.save', dict(settings=dict(api=dict(enabled=False))))
        settings = app.settings.get()
        settings['api']['enabled'] = True
        before = self.config.read_bytes()
        with patch.object(budget, 'text_request', return_value='OK') as request:
            app.bootstrap()
            request.assert_not_called()
            result = app.rpc('settings.test', dict(kind='text', settings=settings))
        self.assertEqual(result['status'], 'verified')
        request.assert_called_once()
        self.assertEqual(request.call_args.args[0].qwen.base_url, 'https://gateway.example/v1')
        self.assertEqual(self.config.read_bytes(), before)

    def test_desktop_policy_does_not_authorize_remote_local_model(self):
        app = self.application(configured_cloud=True)
        app.rpc('settings.save', dict(settings=dict(api=dict(enabled=False), local=dict(base_url='https://local.example/v1'))))
        with self.assertRaises(PermissionError):
            app.prepared()

    def test_isolated_default_stays_restricted_and_explicit_flag_still_works(self):
        restricted = self.application()
        self.assertFalse(restricted.bootstrap()['host']['cloudAllowed'])
        with self.assertRaises(PermissionError):
            restricted.prepared()
        explicit = self.application(allow_cloud=True)
        self.assertTrue(explicit.bootstrap()['host']['cloudAllowed'])
        self.assertEqual(explicit.prepared().qwen.base_url, 'https://gateway.example/v1')

    def test_malformed_or_credential_endpoints_remain_rejected(self):
        app = self.application(configured_cloud=True)
        for url in ('file:///config.json', 'https://user:private@gateway.example/v1'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                app.prepared(dict(api=dict(base_url=url)))


if __name__ == '__main__':
    unittest.main()
