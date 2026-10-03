"""Resumable dialogue storage. Never an execution checkpoint or legacy migration."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .conversation_store import ConversationStore


def now():
    return datetime.now(timezone.utc).isoformat()


def identity():
    return uuid.uuid4().hex


class ModernStore:
    def __init__(self, path: Path, legacy: Path | None = None, *, secrets=()):
        self.path, self.legacy = Path(path), Path(legacy) if legacy else None
        if self.legacy and self.path.resolve() == self.legacy.resolve():
            raise ValueError('新会话库不能覆盖旧记录库')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cleaner = ConversationStore.__new__(ConversationStore)
        self.cleaner.secrets = tuple(v for v in secrets if v and v != 'EMPTY')
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sessions(
                  id TEXT PRIMARY KEY,title TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL,
                  draft TEXT NOT NULL DEFAULT '',scroll REAL NOT NULL DEFAULT 0,
                  summary TEXT NOT NULL DEFAULT '',summarized INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS session_pins(
                  session TEXT PRIMARY KEY NOT NULL REFERENCES sessions(id) ON DELETE CASCADE);
                CREATE TABLE IF NOT EXISTS messages(
                  seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,
                  session TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS messages_session ON messages(session,seq);
                CREATE TABLE IF NOT EXISTS evidence(
                  seq INTEGER PRIMARY KEY AUTOINCREMENT,session TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                  task TEXT NOT NULL,payload TEXT NOT NULL);
            ''')
            # Restart means no task is resumed. Preserve partial text and delivery facts.
            for mid, payload in db.execute('SELECT id,payload FROM messages').fetchall():
                message = json.loads(payload)
                if message.get('status') == 'running':
                    message['status'] = 'interrupted'
                    message['content'] += '\n\n[桌面进程已中断；未恢复或重放任何工具操作]'
                    db.execute('UPDATE messages SET payload=? WHERE id=?', (self.encode(message), mid))

    def clean(self, value):
        return self.cleaner.clean(value)

    def encode(self, value):
        return json.dumps(self.clean(value), ensure_ascii=False)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.execute('PRAGMA foreign_keys=ON')
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def legacy_connect(self):
        if not self.legacy or not self.legacy.is_file():
            yield None
            return
        db = sqlite3.connect(self.legacy.resolve().as_uri() + '?mode=ro', uri=True, timeout=10)
        try:
            yield db
        finally:
            db.close()

    def sessions(self):
        with self.connect() as db:
            result = [self.session_row(row) for row in db.execute('''
                SELECT sessions.*, session_pins.session IS NOT NULL AS pinned
                FROM sessions LEFT JOIN session_pins ON session_pins.session=sessions.id
                ORDER BY pinned DESC, sessions.updated DESC
            ''')]
        with self.legacy_connect() as db:
            if db:
                for sid, created in db.execute('SELECT id,created FROM sessions ORDER BY created DESC'):
                    title = '旧记录 · ' + created[:16]
                    row = db.execute("SELECT payload FROM events WHERE session=? AND kind='user' ORDER BY id LIMIT 1", (sid,)).fetchone()
                    if row:
                        title = '旧记录 · ' + str(json.loads(row[0]).get('prompt', title))[:40]
                    result.append(dict(id='legacy:' + sid, title=title, created=created, updated=created,
                                       readOnly=True, pinned=False, draft='', scroll=0))
        return self.clean(result)

    @staticmethod
    def session_row(row):
        return {**{key: row[key] for key in ('id', 'title', 'created', 'updated', 'draft', 'scroll')},
                'readOnly': False, 'pinned': bool(row['pinned'])}

    def new_session(self, title='新会话'):
        sid, stamp = identity(), now()
        with self.connect() as db:
            db.execute('INSERT INTO sessions(id,title,created,updated) VALUES (?,?,?,?)', (sid, self.clean(str(title)[:100]), stamp, stamp))
        return self.get(sid)['session']

    def writable(self, sid):
        if not isinstance(sid, str) or sid.startswith('legacy:'):
            raise ValueError('旧记录仅供只读查看')
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM sessions WHERE id=?', (sid,)).fetchone():
                raise ValueError('会话不存在')

    def get(self, sid):
        if sid.startswith('legacy:'):
            sessions = {s['id']: s for s in self.sessions()}
            if sid not in sessions:
                raise ValueError('旧会话不存在')
            messages = []
            with self.legacy_connect() as db:
                rows = db.execute('SELECT id,kind,payload FROM events WHERE session=? ORDER BY id', (sid[7:],)).fetchall()
            for seq, kind, raw in rows:
                value = json.loads(raw)
                if kind == 'user':
                    messages.append(dict(id='legacy-user-' + str(seq), role='user', content=value.get('prompt', '')))
                elif kind == 'turn':
                    activities = [dict(id=f'legacy-tool-{seq}-{i}', type='tool', name=a.get('tool'), args=a.get('arguments', {}),
                                       result=a.get('rows', a.get('reason', '')), status=a.get('status'), execution=a.get('execution', ''))
                                  for i, a in enumerate(value.get('attempts', []))]
                    messages.append(dict(id='legacy-assistant-' + str(seq), role='assistant', content=value.get('report', ''),
                                         status=value.get('status', 'complete'), activities=activities))
            return dict(session=sessions[sid], messages=self.clean(messages))
        self.writable(sid)
        with self.connect() as db:
            row = db.execute('''
                SELECT sessions.*, session_pins.session IS NOT NULL AS pinned
                FROM sessions LEFT JOIN session_pins ON session_pins.session=sessions.id
                WHERE sessions.id=?
            ''', (sid,)).fetchone()
            messages = [json.loads(row['payload']) for row in db.execute('SELECT payload FROM messages WHERE session=? ORDER BY seq', (sid,))]
        return dict(session=self.session_row(row), messages=messages)

    def pin(self, sid, pinned):
        if type(pinned) is not bool:
            raise ValueError('pinned 必须是布尔值')
        self.writable(sid)
        with self.connect() as db:
            if pinned:
                db.execute('INSERT INTO session_pins(session) VALUES (?) ON CONFLICT(session) DO NOTHING', (sid,))
            else:
                db.execute('DELETE FROM session_pins WHERE session=?', (sid,))
        return self.get(sid)['session']

    def rename(self, sid, title):
        self.writable(sid)
        if not str(title).strip():
            raise ValueError('会话名称不能为空')
        with self.connect() as db:
            db.execute('UPDATE sessions SET title=?,updated=? WHERE id=?', (self.clean(str(title).strip()[:100]), now(), sid))

    def delete(self, sid):
        self.writable(sid)
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE id=?', (sid,))

    def view(self, sid, *, draft=None, scroll=None):
        self.writable(sid)
        with self.connect() as db:
            if draft is not None:
                db.execute('UPDATE sessions SET draft=? WHERE id=?', (self.clean(str(draft)[:100000]), sid))
            if scroll is not None:
                db.execute('UPDATE sessions SET scroll=? WHERE id=?', (max(0, float(scroll)), sid))

    def put_message(self, sid, message):
        self.writable(sid)
        with self.connect() as db:
            existing = db.execute('SELECT session FROM messages WHERE id=?', (message['id'],)).fetchone()
            if existing and existing['session'] != sid:
                raise ValueError('消息归属不匹配')
            db.execute('INSERT INTO messages(id,session,payload) VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
                       (message['id'], sid, self.encode(message)))
            db.execute('UPDATE sessions SET updated=? WHERE id=?', (now(), sid))

    def save_evidence(self, sid, task_id, payload):
        self.writable(sid)
        with self.connect() as db:
            db.execute('INSERT INTO evidence(session,task,payload) VALUES (?,?,?)', (sid, task_id, self.encode(payload)))

    def context(self, sid):
        self.writable(sid)
        with self.connect() as db:
            session = db.execute('SELECT summary,summarized FROM sessions WHERE id=?', (sid,)).fetchone()
            rows = db.execute('SELECT seq,payload FROM messages WHERE session=? ORDER BY seq', (sid,)).fetchall()
            evidence = [json.loads(row[0]) for row in db.execute('SELECT payload FROM evidence WHERE session=? ORDER BY seq', (sid,))]
        history = []
        if session['summary']:
            history.append(dict(role='user', content='较早对话摘要（非测量证据）：\n' + session['summary']))
        for row in rows:
            message = json.loads(row['payload'])
            if row['seq'] > session['summarized'] and message.get('status') != 'running':
                history.append(dict(role=message['role'], content=message['content'], _seq=row['seq']))
        return history, evidence

    def summarize(self, sid, summary, through):
        # Original history/evidence are never replaced or deleted by compaction.
        self.writable(sid)
        with self.connect() as db:
            db.execute('UPDATE sessions SET summary=?,summarized=? WHERE id=?', (self.clean(summary), int(through), sid))
