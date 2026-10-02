"""Append-only viewing records, not workflow checkpoints. No media bytes."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager


class ConversationStore:
    def __init__(self, path: Path, *, secrets=()):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.secrets = tuple(value for value in secrets if value and value != 'EMPTY')
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session TEXT NOT NULL, created TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_session ON events(session, id);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def new_session(self) -> str:
        identity = uuid.uuid4().hex
        with self.connect() as db:
            db.execute('INSERT INTO sessions VALUES (?,?)', (identity, datetime.now(timezone.utc).isoformat()))
        return identity

    def clean(self, value):
        if isinstance(value, bytes):
            return '[音频/二进制材料不保存]'
        if isinstance(value, dict):
            return {key:self.clean(item) for key, item in value.items()
                    if not any(word in key.casefold() for word in ('api_key', 'authorization', 'credential', 'base64'))}
        if isinstance(value, (list, tuple)):
            return [self.clean(item) for item in value]
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, '[凭据已隐藏]')
            return re.sub(r'data:audio/[^\s"]+', '[音频数据不保存]', value)
        return value

    def append(self, session: str, kind: str, payload):
        with self.connect() as db:
            db.execute('INSERT INTO events(session,created,kind,payload) VALUES (?,?,?,?)',
                       (session, datetime.now(timezone.utc).isoformat(), kind,
                        json.dumps(self.clean(payload), ensure_ascii=False)))

    def sessions(self):
        with self.connect() as db:
            return db.execute('SELECT id,created FROM sessions ORDER BY created DESC').fetchall()

    def records(self, session: str):
        with self.connect() as db:
            rows = db.execute('SELECT created,kind,payload FROM events WHERE session=? ORDER BY id', (session,)).fetchall()
        return [{'created':created, 'kind':kind, 'payload':json.loads(payload)} for created, kind, payload in rows]
