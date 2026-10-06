"""Search must not hydrate histories or write either conversation database."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from praat_ai.conversation_store import ConversationStore
from praat_ai.modern_app import ModernApplication
from praat_ai.modern_store import ModernStore


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.legacy = ConversationStore(self.root / 'legacy.sqlite3')
        self.old = self.legacy.new_session()
        self.legacy.append(self.old, 'user', dict(prompt='旧问题'))
        self.legacy.append(self.old, 'turn', dict(report='日本語 needle.* 旧答案', attempts=[dict(tool='hidden-tool')]))
        self.store = ModernStore(self.root / 'modern.sqlite3', self.legacy.path)
        self.first = self.store.new_session('Title ONLY')['id']
        self.second = self.store.new_session('ordinary')['id']
        self.store.put_message(self.second, dict(id='m', role='assistant', content='日本語 NEEDLE.* ответ', activities=[dict(text='hidden-tool')]))

    def tearDown(self):
        self.temp.cleanup()

    def test_batch_search_reads_only_conversation_text_and_returns_ids(self):
        before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.store.path, self.legacy.path)]
        with patch.object(self.store, 'get', side_effect=AssertionError('Full history load')), patch.object(self.store, 'sessions', side_effect=AssertionError('N+1 session enumeration')):
            self.assertEqual(set(self.store.search('needle.*')['sessionIds']), {self.second, 'legacy:' + self.old})
            self.assertEqual(self.store.search('title only')['sessionIds'], [self.first])
            self.assertEqual(set(self.store.search('日本語')['sessionIds']), {self.second, 'legacy:' + self.old})
            self.assertEqual(self.store.search('hidden-tool')['sessionIds'], [])
            self.assertEqual(self.store.search('NEEDLEZZ')['sessionIds'], [])
        self.assertEqual(before, [hashlib.sha256(p.read_bytes()).hexdigest() for p in (self.store.path, self.legacy.path)])

    def test_updates_deletes_archives_and_legacy_visibility_are_current(self):
        self.store.organization.archive([self.second, 'legacy:' + self.old], True)
        self.assertEqual(self.store.search('needle.*')['sessionIds'], [])
        self.assertEqual(set(self.store.search('needle.*', True)['sessionIds']), {self.second, 'legacy:' + self.old})
        self.store.organization.archive([self.second], False)
        self.store.put_message(self.second, dict(id='m', role='assistant', content='replaced'))
        self.assertEqual(self.store.search('needle.*')['sessionIds'], [])
        self.assertEqual(self.store.search('replaced')['sessionIds'], [self.second])
        self.store.rename(self.first, 'new name')
        self.assertEqual(self.store.search('title only')['sessionIds'], [])
        self.store.delete(self.second)
        self.assertEqual(self.store.search('replaced')['sessionIds'], [])

    def test_literal_unicode_and_validation(self):
        self.store.put_message(self.first, dict(id='unicode', role='user', content='ÉCOLE 中文 "quoted" 100% _wildcard_'))
        for query in ['école', '中文', '"quoted"', '100%', '_wildcard_']:
            self.assertEqual(self.store.search(query)['sessionIds'], [self.first])
        self.assertEqual(self.store.search('  ')['sessionIds'], [])
        for query in [None, {}, 'x' * 1025]:
            with self.assertRaises(ValueError): self.store.search(query)
        with self.assertRaises(ValueError): self.store.search('x', 'false')

    def test_rpc_includes_unflushed_live_text_without_executor_or_settings(self):
        config = self.root / 'config.json'
        config.write_text('{}', encoding='utf8')
        app = ModernApplication(self.root / 'app', config, executor=object())
        try:
            sid = app.store.new_session('live')['id']
            app.tasks['running'] = dict(sessionId=sid, status='running', message=dict(id='live-message', role='assistant', content='unflushed-stream'))
            with patch.object(app.settings, 'candidate', side_effect=AssertionError('Config read')), patch.object(app.store, 'get', side_effect=AssertionError('Full history load')):
                self.assertEqual(app.rpc('sessions.search', dict(searchTerm='unflushed-stream', archived=False))['sessionIds'], [sid])
            self.assertEqual(app.tasks['running']['message']['content'], 'unflushed-stream')
        finally:
            app.tasks.clear()
            app.close()


if __name__ == '__main__': unittest.main()
