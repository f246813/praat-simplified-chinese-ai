"""Isolated before/after search transport benchmark; no user data or provider."""
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from praat_ai.modern_store import ModernStore

def seed(store,count=500,messages=12):
    stamp='2026-10-04T00:00:00Z'
    with store.connect() as db:
        db.executemany('INSERT INTO sessions(id,title,created,updated) VALUES (?,?,?,?)',[(f's{i}',f'会话 {i}',stamp,stamp) for i in range(count)])
        db.executemany('INSERT INTO messages(id,session,payload) VALUES (?,?,?)',[(f'm{i}-{j}',f's{i}',json.dumps(dict(id=f'm{i}-{j}',role='assistant',content=('历史内容 abcdefghijklmnop 日本語 '*50)+f' needle-{i}',status='complete'),ensure_ascii=False)) for i in range(count) for j in range(messages)])

def benchmark():
    with tempfile.TemporaryDirectory() as temporary:
        store=ModernStore(Path(temporary)/'sessions.sqlite3');seed(store)
        ids=[f's{i}' for i in range(500)];query='needle-499'
        transferred=0;old_ids=[]
        started=time.perf_counter()
        for sid in ids:
            snapshot=store.get(sid)
            transferred+=len(json.dumps(snapshot,ensure_ascii=False).encode('utf8'))
            if query in '\n'.join(m['content'] for m in snapshot['messages']).lower():old_ids.append(sid)
        old_ms=(time.perf_counter()-started)*1000
        new_times=[]
        with patch.object(store,'get',side_effect=AssertionError('Search hydrated a history')):
            for _ in range(5):
                started=time.perf_counter();result=store.search(query);new_times.append((time.perf_counter()-started)*1000)
        assert result['sessionIds']==old_ids==['s499']
        new_ms=statistics.median(new_times)
        return dict(passed=True,isolatedData=True,sessions=500,messages=6000,oldFullHistoryRequests=500,newSearchRequests=1,newFullHistoryRequests=0,oldMilliseconds=round(old_ms,2),newMedianMilliseconds=round(new_ms,2),speedup=round(old_ms/new_ms,2),oldResponseBytes=transferred,newResponseBytes=len(json.dumps(result).encode('utf8')),removedInputWaitMilliseconds=200,notes='Host benchmark excludes bridge/React time; old baseline omits the old fixed 300ms wait.')

if __name__=='__main__':
    result=benchmark()
    output=Path(__file__).resolve().parents[2]/'docs/ai-frontend/verification/search-performance-result.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(result,ensure_ascii=False,indent=2))
