"""History organization uses isolated stores and never calls an executor/model."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from praat_ai.modern_app import ModernApplication


class NoExecution:
    def capture_target(self, text): raise AssertionError('metadata operation executed Praat')
    def run(self, **kwargs): raise AssertionError('metadata operation called executor')


class HistoryOrganizationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.config=self.root/'config.json';self.config.write_text('{}',encoding='utf8')
        self.app=ModernApplication(self.root/'modern',self.config,executor=NoExecution())
    def tearDown(self):
        self.app.tasks.clear();self.app.close();self.temp.cleanup()
    def rpc(self, method, **params): return self.app.rpc(method,params)
    def session(self, title='source'): return self.rpc('sessions.create',title=title)['id']
    def section(self, name='研究'): return self.rpc('sections.create',name=name)['id']

    def test_time_group_detach_preserves_content_and_survives_reopening(self):
        a,b=self.session('a'),self.session('b')
        self.app.store.put_message(a,dict(id='original',role='user',content='keep original'))
        self.rpc('sessions.group',sessionIds=[a],action='detach')
        self.assertTrue(self.rpc('sessions.get',sessionId=a)['session']['timeGroupDetached'])
        self.assertFalse(self.rpc('sessions.get',sessionId=b)['session']['timeGroupDetached'])
        self.app.close();self.app=ModernApplication(self.root/'modern',self.config,executor=NoExecution())
        self.assertEqual(self.rpc('sessions.get',sessionId=a)['messages'][0]['content'],'keep original')
        self.assertTrue(self.rpc('sessions.get',sessionId=a)['session']['timeGroupDetached'])

    def test_time_group_bulk_archive_and_delete_touch_only_named_members(self):
        a,b,c=[self.session(name) for name in ['a','b','keep']]
        self.rpc('sessions.group',sessionIds=[a,b],action='archive')
        self.assertTrue(self.rpc('sessions.get',sessionId=a)['session']['archived'])
        self.assertFalse(self.rpc('sessions.get',sessionId=c)['session']['archived'])
        self.rpc('sessions.group',sessionIds=[a,b],action='delete')
        self.assertEqual([s['id'] for s in self.rpc('bootstrap')['sessions']],[c])

    def test_running_member_or_missing_id_prevents_partial_group_changes(self):
        a,b=self.session('a'),self.session('b')
        self.app.tasks['fixture']=dict(id='fixture',sessionId=b,status='running',model='fixture',created='2026-10-06')
        for action in ['archive','delete']:
            with self.assertRaises(ValueError):self.rpc('sessions.group',sessionIds=[a,b],action=action)
            self.assertEqual(len(self.rpc('bootstrap')['sessions']),2)
            self.assertFalse(self.rpc('sessions.get',sessionId=a)['session']['archived'])
        self.app.tasks.clear()
        with self.assertRaises(ValueError):self.rpc('sessions.group',sessionIds=[a,'missing'],action='delete')
        self.assertEqual(len(self.rpc('bootstrap')['sessions']),2)

    def test_sections_stable_identity_delete_only_membership_and_reopen(self):
        sid=self.session();section=self.section()
        self.app.store.put_message(sid,dict(id='original',role='user',content='original history'))
        self.rpc('sessions.section',sessionId=sid,sectionId=section)
        renamed=self.rpc('sections.update',sectionId=section,name='测量',appearance=dict(icon='🎵',color='#26715f'))
        self.assertEqual(renamed['id'],section)
        self.assertEqual(self.rpc('sessions.get',sessionId=sid)['session']['sectionId'],section)
        self.app.close();self.app=ModernApplication(self.root/'modern',self.config,executor=NoExecution())
        self.assertEqual(next(s for s in self.rpc('bootstrap')['sections'] if s['id']==section)['name'],'测量')
        self.rpc('sections.delete',sectionId=section)
        restored=self.rpc('sessions.get',sessionId=sid)
        self.assertIsNone(restored['session']['sectionId']);self.assertEqual(restored['messages'][0]['content'],'original history')

    def test_section_order_pin_exclusion_and_invalid_move_rollback(self):
        ids=[self.session(str(i)) for i in range(3)];section=self.section()
        for sid in ids:self.rpc('sessions.section',sessionId=sid,sectionId=section)
        self.rpc('sessions.section',sessionId=ids[2],sectionId=section,beforeSessionId=ids[0])
        ordered=sorted([s for s in self.rpc('bootstrap')['sessions'] if s['sectionId']==section],key=lambda s:s['sectionPosition'])
        self.assertEqual([s['id'] for s in ordered],[ids[2],ids[0],ids[1]])
        with self.assertRaises(ValueError):self.rpc('sessions.section',sessionId=ids[0],sectionId='missing')
        self.assertEqual(self.rpc('sessions.get',sessionId=ids[0])['session']['sectionId'],section)
        self.rpc('sessions.pin',sessionId=ids[0],pinned=True)
        pinned=next(s for s in self.rpc('bootstrap')['sections'] if s.get('builtin'))
        self.assertEqual(self.rpc('sessions.get',sessionId=ids[0])['session']['sectionId'],pinned['id'])
        with self.assertRaises(ValueError):self.rpc('sections.delete',sectionId=pinned['id'])
        with self.assertRaises(ValueError):self.rpc('sections.update',sectionId=pinned['id'],name='changed')
        self.rpc('sessions.section',sessionId=ids[0],sectionId=section)
        self.assertFalse(self.rpc('sessions.get',sessionId=ids[0])['session']['pinned'])

    def test_archive_section_is_atomic_for_running_members_and_restorable(self):
        a,b=self.session('a'),self.session('b');section=self.section()
        for sid in [a,b]:self.rpc('sessions.section',sessionId=sid,sectionId=section)
        self.app.tasks['fixture']=dict(id='fixture',sessionId=b,status='running')
        with self.assertRaises(ValueError):self.rpc('sections.archive',sectionId=section,archived=True)
        self.app.tasks.clear()
        self.assertFalse(self.rpc('sessions.get',sessionId=a)['session']['archived'])
        self.rpc('sections.archive',sectionId=section,archived=True)
        self.assertTrue(all(s['archived'] for s in self.rpc('bootstrap')['sessions']))
        self.assertTrue(any(s['id']==section for s in self.rpc('bootstrap')['sections']))
        self.rpc('sections.archive',sectionId=section,archived=False)
        self.assertTrue(all(not s['archived'] for s in self.rpc('bootstrap')['sessions']))
        self.assertEqual(json.loads(self.config.read_text()),{})

    def test_fork_copies_independent_ids_context_and_evidence_without_execution(self):
        sid=self.session();section=self.section();self.rpc('sessions.section',sessionId=sid,sectionId=section)
        self.app.store.put_message(sid,dict(id='q',role='user',content='saved question'))
        self.app.store.put_message(sid,dict(id='a',role='assistant',content='saved answer',status='complete',taskId='old-task',activities=[dict(id='tool',type='tool',execution='delivered')]))
        self.app.store.view(sid,draft='parent draft',scroll=88)
        self.app.store.save_evidence(sid,'old-task',dict(rows=['measured source'],execution='delivered'))
        original=self.rpc('sessions.get',sessionId=sid)
        fork=self.rpc('sessions.fork',sessionId=sid)['id'];copy=self.rpc('sessions.get',sessionId=fork)
        self.assertEqual(copy['session']['forkedFrom'],sid);self.assertEqual(copy['session']['sectionId'],section)
        self.assertEqual(copy['session']['draft'],'');self.assertEqual(copy['session']['scroll'],0)
        self.assertEqual([m['content'] for m in copy['messages']],['saved question','saved answer'])
        self.assertTrue(set(m['id'] for m in copy['messages']).isdisjoint(m['id'] for m in original['messages']))
        self.assertTrue(all('taskId' not in m for m in copy['messages']))
        history,evidence=self.app.store.context(fork);self.assertEqual(evidence[0]['rows'],['measured source'])
        self.assertEqual(self.rpc('sessions.get',sessionId=sid),original);self.assertEqual(self.app.tasks,{})
        self.rpc('sessions.delete',sessionId=sid)
        self.assertEqual(self.rpc('sessions.get',sessionId=fork)['messages'],copy['messages'])

    def test_fork_live_snapshot_does_not_attach_parent_task(self):
        sid=self.session();self.app.store.put_message(sid,dict(id='live',role='assistant',content='persisted',status='running'))
        self.app.tasks['fixture']=dict(id='fixture',sessionId=sid,status='running',message=dict(id='live',role='assistant',content='current live delta',status='running'))
        fork=self.rpc('sessions.fork',sessionId=sid)['id'];copy=self.rpc('sessions.get',sessionId=fork)
        self.assertEqual(copy['messages'][0]['content'],'current live delta');self.assertEqual(copy['messages'][0]['status'],'interrupted')
        self.assertFalse(any(t['sessionId']==fork for t in self.app.tasks.values()))

    def test_legacy_organization_and_fork_leave_old_database_unchanged(self):
        legacy=self.root/'legacy.sqlite'
        with sqlite3.connect(legacy) as db:
            db.executescript('CREATE TABLE sessions(id TEXT,created TEXT);CREATE TABLE events(id INTEGER,session TEXT,kind TEXT,payload TEXT);')
            db.execute('INSERT INTO sessions VALUES (?,?)',('old','2020-01-01'))
            db.execute('INSERT INTO events VALUES (?,?,?,?)',(1,'old','user',json.dumps(dict(prompt='legacy original'))))
        db.close()
        original=legacy.read_bytes();self.app.store.legacy=legacy;section=self.section()
        self.rpc('sessions.section',sessionId='legacy:old',sectionId=section)
        self.rpc('sessions.archive',sessionId='legacy:old',archived=True)
        fork=self.rpc('sessions.fork',sessionId='legacy:old')['id']
        self.assertFalse(self.rpc('sessions.get',sessionId=fork)['session']['readOnly'])
        self.assertEqual(self.rpc('sessions.get',sessionId=fork)['messages'][0]['content'],'legacy original')
        self.assertEqual(legacy.read_bytes(),original)

    def test_invalid_fields_rejected_before_mutation(self):
        for name in ['', '  ', None, [], 'x'*101]:
            with self.subTest(name=name),self.assertRaises(ValueError):self.rpc('sections.create',name=name)
        with self.assertRaises(ValueError):self.rpc('sections.create',name='ok',appearance=dict(icon='字'*30))
        section=self.section();sid=self.session()
        with self.assertRaises(ValueError):self.rpc('sessions.archive',sessionId=sid,archived='yes')
        with self.assertRaises(ValueError):self.rpc('sessions.section',sessionId=sid,sectionId=None,beforeSessionId=sid)
        self.assertIsNone(self.rpc('sessions.get',sessionId=sid)['session']['sectionId'])
        self.assertEqual(len([s for s in self.rpc('bootstrap')['sections'] if not s.get('builtin')]),1)

    def test_missing_destination_cannot_silently_detach_and_default_archive_is_scoped(self):
        a,b=self.session('ordinary'),self.session('section');section=self.section()
        self.rpc('sessions.section',sessionId=b,sectionId=section)
        with self.assertRaises(ValueError):self.rpc('sessions.section',sessionId=b)
        with self.assertRaises(ValueError):self.rpc('sections.archive',archived=True)
        self.assertEqual(self.rpc('sessions.get',sessionId=b)['session']['sectionId'],section)
        self.rpc('sections.archive',sectionId=None,archived=True)
        self.assertTrue(self.rpc('sessions.get',sessionId=a)['session']['archived'])
        self.assertFalse(self.rpc('sessions.get',sessionId=b)['session']['archived'])
        with self.assertRaises(ValueError):self.rpc('tasks.submit',sessionId=a,text='cannot execute')

    def test_fork_retains_compressed_context_cutoff_with_new_message_sequence(self):
        sid=self.session()
        for index in range(4):self.app.store.put_message(sid,dict(id=f'm{index}',role='user' if index%2==0 else 'assistant',content=f'content {index}',status='complete'))
        with self.app.store.connect() as db:
            cutoff=db.execute('SELECT seq FROM messages WHERE id=?',('m1',)).fetchone()[0]
        self.app.store.summarize(sid,'confirmed summary',cutoff)
        original=self.app.store.context(sid)
        fork=self.rpc('sessions.fork',sessionId=sid)['id']
        copied=self.app.store.context(fork)
        self.assertEqual([{k:v for k,v in m.items() if k!='_seq'} for m in copied[0]], [{k:v for k,v in m.items() if k!='_seq'} for m in original[0]])
        self.assertEqual(copied[1],original[1]);self.assertEqual(len(self.rpc('sessions.get',sessionId=fork)['messages']),4)


if __name__=='__main__':unittest.main()
