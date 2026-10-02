import hashlib
import json
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[2]
backup = root / 'backups/alignment-paths-before-build-20261001-192137'
with zipfile.ZipFile(root / 'installer/build/payload.zip') as package:
    assert package.testzip() is None
    manifest = json.loads(package.read('payload-manifest.json'))
    for name, expected in manifest.items():
        assert hashlib.sha256(package.read(name)).hexdigest() == expected, name
    for name in ('Praat.exe', 'AIPraat-paths.exe'):
        assert package.read(name) == (root / name).read_bytes()
    documentation = package.read('AIPraat-使用说明.md').decode('utf-8')
    for name in ('wav2vec2 模型', 'MFA 程序', 'MFA 声学模型', 'MFA 发音词典'):
        assert name in documentation
    assert not any(name.endswith('ai_config.json') for name in package.namelist())
    defaults = json.loads(package.read('ai/ai_config.example.json'))['alignment']
    assert not defaults['mfa']['enabled'] and not defaults['wav2vec2']['enabled']
    print(f'PASS payload CRC, {len(manifest)} hashes, current binaries, path documentation and optional defaults')
originals = json.loads((backup / 'manifest.json').read_text(encoding='utf-8-sig'))
for item in originals:
    assert hashlib.sha256((backup / item['path']).read_bytes()).hexdigest().upper() == item['sha256']
for name in ('Praat.exe', 'Praat-fixed.exe'):
    assert (backup / name).read_bytes() == (root / name).read_bytes()
for name in ('AIPraat-paths.exe', 'AIPraat-install.exe'):
    assert (backup / name).read_bytes() != (root / name).read_bytes()
report = json.loads((root / 'installer/build/build-report.json').read_text(encoding='utf-8-sig'))
assert hashlib.sha256((root / 'AIPraat-install.exe').read_bytes()).hexdigest().upper() == report['sha256']
print(f'PASS {len(originals)} backup hashes, updated dialog/installer and final build report')
