"""Codex host search adapted to the existing SQLite storage boundary.

openai/codex ab452649, Apache-2.0: rollout/src/search.rs uses an escaped,
case-insensitive literal matcher and only user/assistant conversation text;
thread-store/local/search_threads.rs returns matches rather than full histories.
The originals are shipped in third_party/codex/upstream/search/. JSONL/rg storage
is replaced by SQLite JSON extraction, without a second engine or search index.
"""
import re


def literal_matcher(search_term, archived=False):
    if not isinstance(search_term, str) or len(search_term) > 1024:
        raise ValueError('搜索文本须为不超过 1024 字符的字符串')
    if type(archived) is not bool:
        raise ValueError('archived 必须是布尔值')
    # Translation of Codex case_insensitive_literal_regex (regex::escape).
    term = search_term.strip()
    return re.compile(re.escape(term), re.IGNORECASE) if term else None


def search_sessions(store, search_term, archived=False):
    matcher = literal_matcher(search_term, archived)
    if matcher is None:
        return dict(sessionIds=[])
    def matches(text):
        return int(bool(text and matcher.search(store.clean(text))))
    with store.connect() as db:
        db.create_function('codex_matches', 1, matches, deterministic=True)
        # A single host query; the existing (session,seq) index serves EXISTS.
        # Extract content, never tool payloads, attachments or evidence.
        result = [row[0] for row in db.execute('''
            SELECT s.id FROM sessions AS s
            LEFT JOIN history_metadata AS h ON h.session=s.id
            WHERE COALESCE(h.archived,0)=? AND (
                codex_matches(s.title) OR EXISTS (
                    SELECT 1 FROM messages AS m WHERE m.session=s.id
                    AND json_extract(m.payload,'$.role') IN ('user','assistant')
                    AND codex_matches(json_extract(m.payload,'$.content'))
                )
            ) ORDER BY s.updated DESC,s.id
        ''', (int(archived),))]
        legacy_archived = {row[0] for row in db.execute("SELECT session FROM history_metadata WHERE archived=1 AND session LIKE 'legacy:%'")}
        legacy_deleted = {row[0] for row in db.execute("SELECT session FROM history_metadata WHERE deleted=1 AND session LIKE 'legacy:%'")}
    with store.legacy_connect() as db:
        if db:
            db.create_function('codex_matches', 1, matches, deterministic=True)
            for row in db.execute('''
                SELECT s.id FROM sessions AS s WHERE
                codex_matches('旧记录 · '||s.created) OR EXISTS (
                    SELECT 1 FROM events AS e WHERE e.session=s.id
                    AND codex_matches(CASE e.kind
                        WHEN 'user' THEN json_extract(e.payload,'$.prompt')
                        WHEN 'turn' THEN json_extract(e.payload,'$.report') END)
                ) ORDER BY s.created DESC,s.id
            '''):
                sid = 'legacy:' + row[0]
                if sid not in legacy_deleted and (sid in legacy_archived) == archived:
                    result.append(sid)
    return dict(sessionIds=result)
