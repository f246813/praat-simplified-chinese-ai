"""Origin metadata is additive, durable and never turns a model API into SSH."""
import json
from pathlib import Path
import tempfile
import unittest
from praat_ai.modern_store import ModernStore


class OriginTests(unittest.TestCase):
    def test_real_project_origin_survives_reopen_and_keeps_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'sessions.sqlite3'
            store=ModernStore(path,project_path='C:/projects/Acoustics')
            sid=store.new_session('analysis')['id']
            store.put_message(sid,dict(id='m',role='user',content='preserved'))
            row=store.get(sid)['session']
            self.assertEqual((row['projectPath'],row['connectionId'],row['connectionLabel']),('C:/projects/Acoustics','local','本地'))
            reopened=ModernStore(path,project_path='C:/different/Host')
            self.assertEqual(reopened.get(sid)['session']['projectPath'],'C:/projects/Acoustics')
            self.assertEqual(reopened.get(sid)['messages'][0]['content'],'preserved')
            self.assertEqual(reopened.sessions()[0]['connectionId'],'local')

    def test_fork_retains_source_project_and_connection_origin(self):
        with tempfile.TemporaryDirectory() as temporary:
            store=ModernStore(Path(temporary)/'sessions.sqlite3',project_path='C:/local/Praat')
            source=store.new_session('recorded remote')['id']
            store.put_message(source,dict(id='original',role='user',content='retained history'))
            with store.connect() as db:
                db.execute('UPDATE sessions SET project_path=?,connection_id=?,connection_label=? WHERE id=?',('/srv/audio','ssh:lab','实验室主机',source))
            fork=store.organization.fork(store.get(source))
            self.assertEqual((fork['projectPath'],fork['connectionId'],fork['connectionLabel']),('/srv/audio','ssh:lab','实验室主机'))
            self.assertEqual(store.get(fork['id'])['messages'][0]['content'],'retained history')

    def test_existing_sessions_upgrade_without_overwriting_known_remote_origin(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'sessions.sqlite3';store=ModernStore(path)
            first=store.new_session('existing')['id'];remote=store.new_session('imported')['id']
            with store.connect() as db:
                db.execute('UPDATE sessions SET project_path=?,connection_id=?,connection_label=? WHERE id=?',('/srv/audio','ssh:lab','实验室主机',remote))
            upgraded=ModernStore(path,project_path='C:/local/Praat')
            rows={s['id']:s for s in upgraded.sessions()}
            self.assertEqual(rows[first]['projectPath'],'C:/local/Praat')
            self.assertEqual(rows[remote]['projectPath'],'/srv/audio')
            self.assertEqual(rows[remote]['connectionLabel'],'实验室主机')

if __name__=='__main__':unittest.main()
