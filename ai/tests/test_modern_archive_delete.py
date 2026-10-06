"""Archive removal preserves the legacy read-only database boundary."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from praat_ai.modern_store import ModernStore

class ArchiveDeleteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.legacy=self.root/'legacy.sqlite3'
        with closing(sqlite3.connect(self.legacy)) as db, db:
            db.executescript('CREATE TABLE sessions(id TEXT PRIMARY KEY,created TEXT);CREATE TABLE events(id INTEGER PRIMARY KEY,session TEXT,kind TEXT,payload TEXT);')
            db.execute('INSERT INTO sessions VALUES (?,?)',('old','2020-01-01'))
            db.execute('INSERT INTO events VALUES (?,?,?,?)',(1,'old','user',json.dumps(dict(prompt='archived legacy needle'))))
        self.original=self.legacy.read_bytes();self.path=self.root/'modern.sqlite3';self.store=ModernStore(self.path,self.legacy)
    def tearDown(self):self.temp.cleanup()

    def test_unarchived_legacy_can_be_removed_and_never_returns_after_reload(self):
        self.store.delete('legacy:old')
        self.assertNotIn('legacy:old',[s['id'] for s in self.store.sessions()])
        self.assertEqual(self.store.search('needle',True)['sessionIds'],[])
        self.assertEqual(self.store.search('needle',False)['sessionIds'],[])
        with self.assertRaises(ValueError):self.store.get('legacy:old')
        self.store=ModernStore(self.path,self.legacy)
        self.assertNotIn('legacy:old',[s['id'] for s in self.store.sessions()])
        self.assertEqual(self.legacy.read_bytes(),self.original)

    def test_modern_delete_cascades_history_but_retains_section_and_active_chats(self):
        section=self.store.organization.create('研究')['id']
        archived=self.store.organization.create_session('归档',section)['id'];active=self.store.new_session('保留')['id']
        self.store.put_message(archived,dict(id='q',role='user',content='original'))
        self.store.save_evidence(archived,'old-task',dict(rows=['saved']))
        self.store.organization.archive([archived],True);self.store.delete(archived)
        self.assertIn(active,[s['id'] for s in self.store.sessions()])
        self.assertIn(section,[s['id'] for s in self.store.organization.sections()])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM messages WHERE session=?',(archived,)).fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM evidence WHERE session=?',(archived,)).fetchone()[0],0)

    def test_group_detach_and_delete_include_legacy_without_writing_its_source(self):
        modern=self.store.new_session('same group')['id']
        keep=self.store.new_session('other group')['id']
        self.store.organization.group_action(['legacy:old',modern],'detach')
        self.assertTrue(self.store.get('legacy:old')['session']['timeGroupDetached'])
        self.assertFalse(self.store.get(keep)['session']['timeGroupDetached'])
        self.store.organization.group_action(['legacy:old',modern],'delete')
        self.store=ModernStore(self.path,self.legacy)
        self.assertEqual([s['id'] for s in self.store.sessions()],[keep])
        self.assertEqual(self.legacy.read_bytes(),self.original)

    def test_additive_metadata_upgrade_keeps_original_membership_and_archive_state(self):
        old=self.root/'old-modern.sqlite3'
        with closing(sqlite3.connect(old)) as db, db:
            db.executescript('CREATE TABLE history_metadata(session TEXT PRIMARY KEY,section TEXT,section_position INTEGER,archived INTEGER NOT NULL DEFAULT 0,forked_from TEXT,forked_from_title TEXT);')
            db.execute('INSERT INTO history_metadata(session,archived) VALUES (?,1)',('legacy:old',))
        upgraded=ModernStore(old,self.legacy)
        self.assertTrue(upgraded.get('legacy:old')['session']['archived'])
        upgraded.delete('legacy:old');upgraded=ModernStore(old,self.legacy)
        self.assertEqual(upgraded.sessions(),[]);self.assertEqual(self.legacy.read_bytes(),self.original)

if __name__=='__main__':unittest.main()
