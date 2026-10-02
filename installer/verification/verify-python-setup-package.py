import hashlib
import json
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[2]
with zipfile.ZipFile(root / 'installer/build/payload.zip') as package:
    assert package.testzip() is None
    manifest = json.loads(package.read('payload-manifest.json'))
    for name, expected in manifest.items():
        assert hashlib.sha256(package.read(name)).hexdigest() == expected, name
    assert package.read('AIPraat-paths.exe') == (root / 'AIPraat-paths.exe').read_bytes()
    assert package.read('Praat.exe') == (root / 'Praat.exe').read_bytes()
    assert '运行Powershell命令一键配置'.encode() in package.read('AIPraat-使用说明.md')
    assert not any(name.endswith('ai_config.json') for name in package.namelist())
    print(f'PASS payload CRC, {len(manifest)} hashes, dialog binary and documentation')
backup = root / 'backups/python-setup-before-build-20261001-183035'
manifest = json.loads((backup / 'manifest.json').read_text(encoding='utf-8-sig'))
for item in manifest:
    assert hashlib.sha256((backup / item['path']).read_bytes()).hexdigest().upper() == item['sha256']
assert (backup / 'Praat.exe').read_bytes() == (root / 'Praat.exe').read_bytes()
assert (backup / 'AIPraat-paths.exe').read_bytes() != (root / 'AIPraat-paths.exe').read_bytes()
assert (backup / 'AIPraat-install.exe').read_bytes() != (root / 'AIPraat-install.exe').read_bytes()
print(f'PASS {len(manifest)} backup hashes; updated dialog/installer; Praat binary retained')
