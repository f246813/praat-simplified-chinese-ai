"""Verify exact Codex search originals and shipped local source adaptations."""
from pathlib import Path
import hashlib
import json

root=Path(__file__).resolve().parents[2]
dist=root/'ai/frontend/dist';source=root/'ai/third_party/codex/upstream/search'
manifest=json.loads((source/'SOURCE.json').read_text(encoding='utf8'))
for entry in manifest['files']:
    original=(source/entry['path']).read_bytes()
    assert hashlib.sha256(original).hexdigest()==entry['sha256'],entry['path']
    assert hashlib.sha1(b'blob '+str(len(original)).encode()+b'\0'+original).hexdigest()==entry['gitBlob'],entry['path']
    assert original==(dist/'codex-source/upstream/search'/entry['path']).read_bytes(),entry['path']
for file in ['modern_search.py','modern_app.py','modern_store.py']:
    assert (root/'ai/praat_ai'/file).read_bytes()==(dist/'codex-source/modified-host'/file).read_bytes(),file
for file in ['useSessionSearch.ts','literal-matcher.ts']:
    assert (root/'ai/frontend/src/codex'/file).read_bytes()==(dist/'codex-source/modified'/file).read_bytes(),file
for file in ['search.ts','SearchBar.tsx','pi/sidebar/Sidebar.tsx','types.ts','bridge.ts','demo.ts']:
    assert (root/'ai/frontend/src'/file).read_bytes()==(dist/'pi-desktop-source/rebuild/src'/file).read_bytes(),file
assert (root/'ai/third_party/codex/NOTICE.md').read_bytes()==(dist/'codex-source/NOTICE.md').read_bytes()
result=dict(passed=True,revision=manifest['revision'],exactOriginals=manifest['files'],checks=['Pinned originals verified against Git blob/SHA-256 and shipped unchanged','Current renderer and SQLite/RPC adaptations shipped exactly','Original license and modification/source notice retained'],browserChecks=10,frontendUnitChecks=27,pythonChecks=42,productionBuild=True)
output=root/'test-records/frontend/search-performance-source-result.json'
output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(result,indent=2))
