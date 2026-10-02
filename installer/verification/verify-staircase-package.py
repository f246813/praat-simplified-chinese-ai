"""Verify current sources against the rebuilt and embedded installation payload."""
import hashlib
import json
import re
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
build = root / 'installer' / 'build'
verification = root / 'installer' / 'verification'


def digest(data):
    return hashlib.sha256(data).hexdigest()


manifest = json.loads((build / 'payload-manifest.json').read_text(encoding='utf-8-sig'))
special = {
    'AIPraat.exe':build / 'AIPraat.exe',
    'AIPraat-使用说明.md':root / 'installer' / 'README.zh-CN.md',
    'ai/ai_config.example.json':build / 'ai_config.example.json',
}
with zipfile.ZipFile(build / 'payload.zip') as archive:
    entries = archive.namelist()
    assert len(entries) == len(set(entries)), 'Duplicate archive paths'
    assert set(entries) == set(manifest) | {'payload-manifest.json'}, 'Unexpected payload files'
    assert json.loads(archive.read('payload-manifest.json')) == manifest
    for name, expected in manifest.items():
        assert not re.search(r'(^|/)(?:ai_config\.json|runtime|logs|tests|__pycache__)(/|$)|\.(?:pyc|wav|mp3|sqlite|db)$', name, re.I), name
        assert digest(archive.read(name)) == expected, 'Payload mismatch: ' + name
        source = special.get(name, root / name)
        assert digest(source.read_bytes()) == expected, 'Source mismatch: ' + name

embedded = verification / 'staircase-embedded-payload.zip'
assert digest(embedded.read_bytes()) == digest((build / 'payload.zip').read_bytes()), 'EXE embedded payload mismatch'
binaries = {}
for name in ('AIPraat-install.exe', 'AIPraat-paths.exe', 'Praat.exe'):
    path = root / name
    binaries[name] = {'bytes':path.stat().st_size, 'sha256':digest(path.read_bytes())}
report = json.loads((build / 'build-report.json').read_text(encoding='utf-8-sig'))
assert report['sha256'].lower() == binaries['AIPraat-install.exe']['sha256']
assert report['praat_sha256'] == binaries['Praat.exe']['sha256']
native_build = verification / 'python-workspace-native-build.json'
baseline_native = 'cca8ef9884ff6a6237ee78f6325df79689289656316d6fb5ec850433ab0324ee'
if native_build.exists():
    native_report = json.loads(native_build.read_text(encoding='utf-8-sig'))
    assert native_report['previous_native_sha256'] == baseline_native, 'Unexpected native build baseline'
    assert binaries['Praat.exe']['sha256'] == native_report['native_sha256'], 'Native build not synchronized'
    assert digest(Path(native_report['candidate']).read_bytes()) == native_report['native_sha256'], 'Native candidate mismatch'
    for name, expected in native_report['sources'].items():
        assert digest((root / name).read_bytes()) == expected, 'Native source changed after build: ' + name
else:
    assert binaries['Praat.exe']['sha256'] == baseline_native, 'Unexpected native Praat change'
wheel_closure = {}
for version in ('310', '314'):
    wheels = list((verification / ('staircase-wheels-py' + version)).glob('*.whl'))
    wheel_closure[version] = {'files':len(wheels), 'MiB':round(sum(path.stat().st_size for path in wheels) / (1024 * 1024), 2)}
result = {
    'payload_files':len(entries), 'hashes_verified':len(manifest),
    'embedded_payload_matches':True, 'current_sources_match':True,
    'no_user_config_audio_runtime':True, 'binaries':binaries,
    'wheel_closure':wheel_closure,
}
(verification / 'staircase-artifacts.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
