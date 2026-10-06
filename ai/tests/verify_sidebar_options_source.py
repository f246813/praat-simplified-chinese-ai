"""Verify shipped menu reuse, pinned originals and exact replaceable sources."""
import hashlib
import json
from pathlib import Path
import re

root=Path(__file__).resolve().parents[2];frontend=root/'ai/frontend';dist=frontend/'dist';checks=[]
for library in ['codex','pi-desktop']:
    directory=root/'ai/third_party'/library/'upstream/sidebar-options'
    manifest=json.loads((directory/'SOURCE.json').read_text(encoding='utf8'))
    for item in manifest['files']:
        original=directory/item['path'];data=original.read_bytes()
        assert hashlib.sha256(data).hexdigest()==item['sha256'],original
        assert data==(dist/f'{library}-source/upstream/sidebar-options'/item['path']).read_bytes(),original
    assert (directory/'SOURCE.json').read_bytes()==(dist/f'{library}-source/upstream/sidebar-options/SOURCE.json').read_bytes()
checks.append('3 Codex and 1 Pi pinned original files/hashes shipped unchanged')
for name in ['ThreadSortKey.ts','SortDirection.ts']:
    upstream=root/'ai/third_party/codex/upstream/sidebar-options/codex-rs/app-server-protocol/schema/typescript/v2'/name
    assert upstream.read_bytes()==(frontend/'src/codex/protocol'/name).read_bytes()
    assert upstream.read_bytes()==(dist/'codex-source/modified/protocol'/name).read_bytes()
pi_original=(root/'ai/third_party/pi-desktop/upstream/sidebar-options/apps/desktop/src/lib/project-name.ts').read_text(encoding='utf8')
pi_excerpt=(frontend/'src/pi/sidebar/project-name.ts').read_text(encoding='utf8').split('export function',1)[1]
assert ('export function'+pi_excerpt).strip() in pi_original
checks.append('2 Codex types and exact Pi folderNameFromPath extraction reused')
package=json.loads((frontend/'package.json').read_text(encoding='utf8'))
lock=json.loads((frontend/'package-lock.json').read_text(encoding='utf8'))
assert package['dependencies']['@radix-ui/react-dropdown-menu']=='2.1.24'
assert lock['packages']['']['dependencies']['@radix-ui/react-dropdown-menu']=='2.1.24'
assert lock['packages']['node_modules/@radix-ui/react-dropdown-menu']['version']=='2.1.24'
assert (frontend/'src/SidebarOptions.tsx').read_bytes()==(dist/'codex-source/modified/SidebarOptions.tsx').read_bytes()
for name in ['modern_settings.py','modern_store.py','modern_app.py','modern_organization.py']:
    assert (root/'ai/praat_ai'/name).read_bytes()==(dist/'codex-source/modified-host'/name).read_bytes()
for file in (frontend/'src').rglob('*'):
    if file.is_file():assert file.read_bytes()==(dist/'pi-desktop-source/rebuild/src'/file.relative_to(frontend/'src')).read_bytes(),file
checks.append('Radix 2.1.24 pinned; exact current menu/frontend/host adaptations distributed')
for directory,source in [('codex-source','codex'),('pi-desktop-source','pi-desktop')]:
    assert (root/'ai/third_party'/source/'NOTICE.md').read_bytes()==(dist/directory/'NOTICE.md').read_bytes()
notices=(dist/'THIRD-PARTY-NOTICES.txt').read_text(encoding='utf8')
assert '@radix-ui/react-dropdown-menu 2.1.24' in notices and 'MIT' in notices
baseline=root/'.aipraat-backups/codex-sections-20261004/before/src/pi/sidebar/styles.css'
assert (frontend/'src/pi/sidebar/styles.css').read_bytes()==baseline.read_bytes()
html=(dist/'index.html').read_text(encoding='utf8')
assets=[p.removeprefix('./').removeprefix('/') for p in re.findall(r'(?:src|href)="((?:\./|/)assets/[^\"]+)"',html)]
assert assets and all((dist/p).is_file() for p in assets)
checks.append('licenses/notices supplied; scrollbar unchanged; production assets resolve')
result=dict(passed=True,checks=checks,assets=[dict(path=p,sha256=hashlib.sha256((dist/p).read_bytes()).hexdigest()) for p in assets])
output=root/'docs/ai-frontend/verification/sidebar-options-source-result.json'
output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(result,ensure_ascii=False,indent=2))
