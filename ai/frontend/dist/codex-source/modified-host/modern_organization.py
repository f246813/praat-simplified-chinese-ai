"""Codex thread-section semantics adapted to Praat's SQLite conversation store.

Stable identities, one membership, append/before ordering and detach-on-delete
follow openai/codex ab452649 (Apache-2.0). Archive and snapshot fork use the
existing local host; no Codex engine, task replay or legacy database writes.
"""
import copy
import json
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .modern_store import ModernStore

PINNED_SECTION='01984de2-8f74-7c91-a3b2-5c5e937cf318'
POSITION_GAP=1000000


class HistoryOrganization:
    def __init__(self, store: 'ModernStore'):
        self.store=store
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS history_sections(
                  id TEXT PRIMARY KEY,name TEXT NOT NULL,appearance TEXT,position INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS history_metadata(
                  session TEXT PRIMARY KEY,section TEXT REFERENCES history_sections(id) ON DELETE SET NULL,
                  section_position INTEGER,archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
                  forked_from TEXT,forked_from_title TEXT);
                CREATE INDEX IF NOT EXISTS history_section_order ON history_metadata(section,section_position,session);
            ''')
            if 'deleted' not in {column[1] for column in db.execute('PRAGMA table_info(history_metadata)')}:
                db.execute('ALTER TABLE history_metadata ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0 CHECK(deleted IN (0,1))')
            if 'time_group_detached' not in {column[1] for column in db.execute('PRAGMA table_info(history_metadata)')}:
                db.execute('ALTER TABLE history_metadata ADD COLUMN time_group_detached INTEGER NOT NULL DEFAULT 0 CHECK(time_group_detached IN (0,1))')
            db.execute('INSERT OR IGNORE INTO history_sections(id,name,position) VALUES (?,?,0)',(PINNED_SECTION,'置顶'))
            # Additive upgrade: existing pin membership remains discoverable.
            for index,row in enumerate(db.execute('SELECT session FROM session_pins ORDER BY session').fetchall()):
                db.execute('INSERT INTO history_metadata(session,section,section_position) VALUES (?,?,?) ON CONFLICT(session) DO UPDATE SET section=excluded.section,section_position=COALESCE(history_metadata.section_position,excluded.section_position)',(row['session'],PINNED_SECTION,(index+1)*POSITION_GAP))

    @staticmethod
    def name(value):
        if not isinstance(value,str) or not value.strip() or len(value.strip())>100:
            raise ValueError('分区名称须为 1–100 个字符')
        return value.strip()

    @staticmethod
    def appearance(value):
        if value is None:return None
        if not isinstance(value,dict):raise ValueError('分区外观参数无效')
        result={}
        for key in ('icon','color'):
            field=value.get(key)
            if field is not None and (not isinstance(field,str) or len(field.encode('utf8'))>64):
                raise ValueError('分区图标和颜色不能超过 64 字节')
            result[key]=field
        return result

    def sections(self):
        with self.store.connect() as db:
            return [dict(id=r['id'],name=r['name'],appearance=json.loads(r['appearance']) if r['appearance'] else None,builtin=r['id']==PINNED_SECTION) for r in db.execute('SELECT * FROM history_sections ORDER BY position,id')]

    def project(self, sessions):
        with self.store.connect() as db:
            metadata={r['session']:r for r in db.execute('SELECT * FROM history_metadata')}
        result=[]
        for session in sessions:
            row=metadata.get(session['id'])
            if row and row['deleted']:continue
            result.append({**session,'sectionId':row['section'] if row else None,'sectionPosition':row['section_position'] if row else None,'archived':bool(row['archived']) if row else False,
                           'forkedFrom':row['forked_from'] if row else None,'forkedFromTitle':row['forked_from_title'] if row else None,
                           'timeGroupDetached':bool(row['time_group_detached']) if row else False})
        return result

    def snapshot(self):return dict(sessions=self.store.sessions(),sections=self.sections())

    def group_action(self, ids, action):
        if action not in ('delete','detach','archive'):
            raise ValueError('分组操作无效')
        if not isinstance(ids,list) or not ids or any(not isinstance(sid,str) or not sid.strip() for sid in ids):
            raise ValueError('分组会话标识无效')
        ids=list(dict.fromkeys(ids))
        for sid in ids:self.store.get(sid)
        if action=='archive':return self.archive(ids,True)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for sid in ids:
                if action=='detach':
                    db.execute('INSERT INTO history_metadata(session,time_group_detached) VALUES (?,1) ON CONFLICT(session) DO UPDATE SET time_group_detached=1',(sid,))
                elif sid.startswith('legacy:'):
                    db.execute('INSERT INTO history_metadata(session,deleted) VALUES (?,1) ON CONFLICT(session) DO UPDATE SET deleted=1',(sid,))
                else:
                    db.execute('DELETE FROM history_metadata WHERE session=?',(sid,))
                    db.execute('DELETE FROM sessions WHERE id=?',(sid,))
        return self.snapshot()

    @staticmethod
    def require_section(db, section):
        if not isinstance(section,str) or not section.strip() or not db.execute('SELECT 1 FROM history_sections WHERE id=?',(section,)).fetchone():
            raise ValueError('分区不存在')

    def create(self, name, appearance=None):
        from .modern_store import identity
        name=self.name(name);appearance=self.appearance(appearance);sid=identity()
        with self.store.connect() as db:
            position=db.execute('SELECT COALESCE(MAX(position),0)+? FROM history_sections',(POSITION_GAP,)).fetchone()[0]
            db.execute('INSERT INTO history_sections VALUES (?,?,?,?)',(sid,self.store.clean(name),self.store.encode(appearance) if appearance is not None else None,position))
        return next(s for s in self.sections() if s['id']==sid)

    def update(self, section, name, appearance=...):
        name=self.name(name)
        if section==PINNED_SECTION:raise ValueError('内置置顶分区不能编辑')
        if appearance is not ...:appearance=self.appearance(appearance)
        with self.store.connect() as db:
            self.require_section(db,section)
            if appearance is ...:db.execute('UPDATE history_sections SET name=? WHERE id=?',(self.store.clean(name),section))
            else:db.execute('UPDATE history_sections SET name=?,appearance=? WHERE id=?',(self.store.clean(name),self.store.encode(appearance) if appearance is not None else None,section))
        return next(s for s in self.sections() if s['id']==section)

    def delete(self, section):
        if section==PINNED_SECTION:raise ValueError('内置置顶分区不能移除')
        with self.store.connect() as db:
            self.require_section(db,section)
            db.execute('UPDATE history_metadata SET section_position=NULL WHERE section=?',(section,))
            db.execute('DELETE FROM history_sections WHERE id=?',(section,))
        return self.snapshot()

    def move(self, sid, section, before=None):
        session=self.store.get(sid)['session']
        if section is None and before is not None:raise ValueError('移出分区时不能指定前置会话')
        if section==PINNED_SECTION and session['readOnly']:raise ValueError('旧记录不能置顶')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if section is not None:self.require_section(db,section)
            order=[r[0] for r in db.execute('SELECT session FROM history_metadata WHERE section=? AND session<>? ORDER BY section_position,session',(section,sid))] if section else []
            if before==sid:raise ValueError('不能插入自身之前')
            if before is not None and before not in order:raise ValueError('前置会话不在目标分区')
            if section:
                order.insert(order.index(before) if before else len(order),sid)
            db.execute('INSERT INTO history_metadata(session,section,section_position) VALUES (?,?,NULL) ON CONFLICT(session) DO UPDATE SET section=excluded.section,section_position=NULL',(sid,section))
            for index,item in enumerate(order):db.execute('UPDATE history_metadata SET section_position=? WHERE session=?',((index+1)*POSITION_GAP,item))
            if section==PINNED_SECTION:db.execute('INSERT OR IGNORE INTO session_pins(session) VALUES (?)',(sid,))
            else:db.execute('DELETE FROM session_pins WHERE session=?',(sid,))
        return self.snapshot()

    def members(self, section):
        if section is not None:
            with self.store.connect() as db:self.require_section(db,section)
        return [s['id'] for s in self.store.sessions() if s['sectionId']==section]

    def archive(self, ids, archived):
        if type(archived) is not bool:raise ValueError('归档状态必须是布尔值')
        for sid in ids:self.store.get(sid)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for sid in ids:db.execute('INSERT INTO history_metadata(session,archived) VALUES (?,?) ON CONFLICT(session) DO UPDATE SET archived=excluded.archived',(sid,int(archived)))
        return self.snapshot()

    def create_session(self, title='新会话', section=None):
        if section is not None:
            with self.store.connect() as db:self.require_section(db,section)
        session=self.store.new_session(title)
        if section is not None:self.move(session['id'],section)
        return self.store.get(session['id'])['session']

    def fork(self, snapshot):
        from .modern_store import identity, now
        source=snapshot['session'];sid=identity();stamp=now()
        section=source.get('sectionId')
        if section==PINNED_SECTION:section=None
        connection=source.get('connectionId') or 'local'
        project=source.get('projectPath')
        if project is None and connection=='local':project=self.store.project_path
        connection_label=source.get('connectionLabel') or ('本地' if connection=='local' else connection)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO sessions(id,title,created,updated,project_path,connection_id,connection_label) VALUES (?,?,?,?,?,?,?)',(sid,self.store.clean((source['title']+' · 分叉')[:100]),stamp,stamp,project,connection,connection_label))
            original=db.execute('SELECT summary,summarized FROM sessions WHERE id=?',(source['id'],)).fetchone()
            sequence={r['id']:r['seq'] for r in db.execute('SELECT id,seq FROM messages WHERE session=?',(source['id'],))}
            summarized=0
            for value in snapshot['messages']:
                message=copy.deepcopy(value);old_id=message['id'];message['id']=identity();message.pop('taskId',None)
                if message.get('status')=='running':message['status']='interrupted'
                for activity in message.get('activities',[]):
                    activity['id']=identity()
                    if activity.get('status')=='running':activity['status']='interrupted'
                cursor=db.execute('INSERT INTO messages(id,session,payload) VALUES (?,?,?)',(message['id'],sid,self.store.encode(message)))
                if original and sequence.get(old_id,float('inf'))<=original['summarized']:summarized=cursor.lastrowid
            if original:db.execute('UPDATE sessions SET summary=?,summarized=? WHERE id=?',(original['summary'],summarized,sid))
            db.execute('INSERT INTO evidence(session,task,payload) SELECT ?,task,payload FROM evidence WHERE session=?',(sid,source['id']))
            position=None
            if section:
                self.require_section(db,section)
                position=db.execute('SELECT COALESCE(MAX(section_position),0)+? FROM history_metadata WHERE section=?',(POSITION_GAP,section)).fetchone()[0]
            db.execute('INSERT INTO history_metadata(session,section,section_position,forked_from,forked_from_title) VALUES (?,?,?,?,?)',(sid,section,position,source['id'],source['title']))
        return self.store.get(sid)['session']
