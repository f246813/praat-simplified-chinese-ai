"""Offline asset origin and cross-process desktop gate checks."""
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from praat_ai.modern_host import AssetServer
from praat_ai.service_lock import service_transition_lock


class ModernHostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.getenv('PI_SCRATCH_DIR'))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_offline_assets_origin_headers_and_no_directory_listing(self):
        assets = self.root / 'assets'
        assets.mkdir()
        (assets / 'index.html').write_text('<h1>offline</h1>', encoding='utf8')
        (assets / 'subdir').mkdir()
        server = AssetServer(assets)
        self.addCleanup(server.close)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(server.url) as response:
            self.assertIn(b'offline', response.read())
            self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
            self.assertIn("connect-src 'self'", response.headers['Content-Security-Policy'])
        for url, headers in [(server.url, {'Host':'untrusted.example'}),
                             (server.url.replace('index.html', 'subdir/'), {})]:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                opener.open(urllib.request.Request(url, headers=headers))
            self.assertEqual(caught.exception.code, 403)

    def test_shared_gate_excludes_another_process_and_releases(self):
        lock = self.root / 'frontend.lock'
        code = (f'import sys; sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r}); '
                'from pathlib import Path; from praat_ai.service_lock import service_transition_lock; '
                f'gate=service_transition_lock(Path({str(lock)!r}),timeout=0.1); '
                'gate.__enter__(); gate.__exit__(None,None,None)')
        with service_transition_lock(lock, timeout=.1):
            result = subprocess.run([sys.executable, '-c', code], capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'Timed out', result.stderr)
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_modern_model_request_never_follows_redirect(self):
        from praat_ai import qwen
        from praat_ai.config import QwenConfig
        hits = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                hits.append(self.path)
                self.send_response(302)
                self.send_header('Location', f'http://localhost:{self.server.server_port}/escaped')
                self.end_headers()
            def do_GET(self):
                if self.path != '/escaped':
                    return self.do_POST()
                hits.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"choices":[]}')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            config = QwenConfig(base_url=f'http://127.0.0.1:{server.server_port}/v1',
                                token_mode='manual', api_key='test-only-secret')
            with self.assertRaisesRegex(qwen.QwenError, 'HTTP 302'):
                qwen.QwenClient(config)._post({'messages':[]})
            self.assertEqual(hits, ['/v1/chat/completions'])
            from praat_ai.server import endpoint_available, server_model_state
            self.assertFalse(endpoint_available(config.base_url, opener=qwen._open_no_redirect))
            self.assertIsNone(server_model_state(config.base_url, 'model', opener=qwen._open_no_redirect))
            self.assertNotIn('/escaped', hits)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    def test_legacy_direct_entry_uses_same_gate(self):
        from praat_ai import chat
        seen = []
        class Gate:
            def __enter__(self): seen.append('locked')
            def __exit__(self, *args): seen.append('released')
        with patch.object(chat, 'runtime_dir', return_value=self.root), patch(
                'praat_ai.service_lock.service_transition_lock', return_value=Gate()) as gate, patch.object(chat, 'ChatWindow') as window:
            window.return_value.run.return_value = 0
            self.assertEqual(chat.main(), 0)
            gate.assert_called_once_with(self.root / 'frontend.lock', timeout=1)
        self.assertEqual(seen, ['locked', 'released'])

    def test_parent_watch_without_explicit_parent_does_not_guess(self):
        from praat_ai.modern_host import watch_native_parent
        from unittest.mock import MagicMock
        window = MagicMock()
        with patch('praat_ai.parent_watch.parent_pid', return_value=None), patch('praat_ai.process.process_identity') as identity:
            watch_native_parent(window)
        identity.assert_not_called()
        window.destroy.assert_not_called()

    def test_parent_watch_closes_on_replaced_process_identity(self):
        from praat_ai.modern_host import watch_native_parent
        from unittest.mock import MagicMock
        window = MagicMock()
        original = dict(executable='Praat.exe', started='first')
        replacement = dict(executable='Praat.exe', started='reused')
        with patch('praat_ai.parent_watch.parent_pid', return_value=123), patch('praat_ai.process.process_identity', side_effect=[original, replacement]), patch('praat_ai.modern_host.threading.Event') as event:
            event.return_value.wait.return_value = False
            watch_native_parent(window)
        window.destroy.assert_called_once_with()

    def test_parent_watch_stops_when_window_is_closed(self):
        from praat_ai.modern_host import watch_native_parent
        from unittest.mock import MagicMock
        window = MagicMock()
        with patch('praat_ai.parent_watch.parent_pid', return_value=123), patch('praat_ai.process.process_identity', return_value=dict(executable='Praat.exe', started='first')) as identity, patch('praat_ai.modern_host.threading.Event') as event:
            event.return_value.wait.return_value = True
            watch_native_parent(window)
        identity.assert_called_once_with(123)
        window.destroy.assert_not_called()



if __name__ == '__main__':
    unittest.main()
