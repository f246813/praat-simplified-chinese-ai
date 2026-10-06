"""Verify fixed Codex source and the exact shipped replacement source/assets."""
from pathlib import Path
import hashlib
import json
import re
import shutil

root=Path.cwd();dist=root/'ai/frontend/dist';source=root/'ai/third_party/codex'
manifest=json.loads((source/'SOURCE.json').read_text(encoding='utf8'));checks=[]
for item in manifest['verifiedFiles']:
    relative=Path('upstream')/item['path'];data=(dist/'codex-source'/relative).read_bytes()
    assert hashlib.sha256(data).hexdigest()==item['sha256'],relative
checks.append('14 pinned original files in production match Git-verified SHA-256')
for filename in ['LICENSE','NOTICE.md','UPSTREAM-NOTICE','SOURCE.json']:
    assert (source/filename).read_bytes()==(dist/'codex-source'/filename).read_bytes(),filename
checks.append('Apache license, original notice, modification notice and provenance manifest shipped unchanged')
for filename in ['modern_organization.py','modern_store.py','modern_app.py']:
    assert (root/'ai/praat_ai'/filename).read_bytes()==(dist/'codex-source/modified-host'/filename).read_bytes(),filename
for filename in ['ThreadSection.ts','ThreadSectionAppearance.ts']:
    assert (root/'ai/frontend/src/codex/protocol'/filename).read_bytes()==(dist/'codex-source/modified/protocol'/filename).read_bytes(),filename
for path in (root/'ai/frontend/src').rglob('*'):
    if path.is_file():assert path.read_bytes()==(dist/'pi-desktop-source/rebuild/src'/path.relative_to(root/'ai/frontend/src')).read_bytes(),path
checks.append('current exact frontend rebuild inputs, raw section types and modified host source shipped')
scroll=root/'ai/frontend/src/pi/sidebar/styles.css';baseline=root/'.aipraat-backups/codex-sections-20261004/before/src/pi/sidebar/styles.css'
assert scroll.read_bytes()==baseline.read_bytes()
checks.append('sidebar scrollbar/style file is byte-for-byte unchanged from this feature baseline')
html=(dist/'index.html').read_text(encoding='utf8');assets=re.findall(r'(?:src|href)="((?:\./|/)assets/[^\"]+)"',html)
asset_paths=[name.removeprefix('./').removeprefix('/') for name in assets]
assert asset_paths and all((dist/name).is_file() for name in asset_paths)
checks.append('production index references existing freshly built assets')
notices=(dist/'THIRD-PARTY-NOTICES.txt').read_text(encoding='utf8');assert all(s in notices for s in ['Codex public thread-section','Apache','PI-Desktop','LGPL'])
result=dict(passed=True,revision=manifest['revision'],checks=checks,productionAssets=[dict(path=p,sha256=hashlib.sha256((dist/p).read_bytes()).hexdigest()) for p in asset_paths])
output=root/'docs/ai-frontend/verification/codex-history-source-result.json'
output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
screenshot=root/'.aipraat-backups/codex-sections-20261004/codex-section-menu.png'
if screenshot.exists():shutil.copyfile(screenshot,output.with_name('codex-history-section-menu.png'))
print(json.dumps(result,indent=2))
