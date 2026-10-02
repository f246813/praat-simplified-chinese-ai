"""校验重新打包后的安装包：内嵌载荷 / 清单 / 当前源码三者逐项一致。

    python installer/verification/verify-delivery-package.py

与上一轮的 ``verify-staircase-package.py`` 同样的思路，针对 2026-10-02 夜这次的
「投递事实」修复：

1. 从 ``AIPraat-install.exe`` 里取出内嵌的 ``AIPraat.Payload.zip``（按 Zip 的
   中央目录定位，不依赖资源名），与 ``installer/build/payload.zip`` 逐字节比对；
2. 载荷里的每个条目都要与 ``payload-manifest.json`` 以及**当前源码/生成物**的
   SHA256 一致；
3. 不含用户配置、runtime、logs、tests、__pycache__、音频或数据库；
4. 记录本次三个二进制的体积与哈希；``Praat.exe`` 必须与**重打包前**记录的哈希一致
   （本轮没有重编原生程序）。
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / 'installer' / 'build'
VERIFICATION = ROOT / 'installer' / 'verification'
BACKUP = ROOT / 'backups' / 'installer-before-repack-20261002-delivery-fix'
EMBEDDED = VERIFICATION / 'delivery-embedded-payload.zip'

#: 载荷里不是「源码原样拷贝」的条目 → 它们对应的真实来源。
SPECIAL = {
    'AIPraat.exe': BUILD / 'AIPraat.exe',
    'AIPraat-使用说明.md': ROOT / 'installer' / 'README.zh-CN.md',
    'ai/ai_config.example.json': BUILD / 'ai_config.example.json',
    'AIPraat-paths.exe': ROOT / 'AIPraat-paths.exe',
}
FORBIDDEN = re.compile(r'(^|/)(?:ai_config\.json|runtime|logs|tests|__pycache__)(/|$)|\.(?:pyc|wav|mp3|sqlite|db)$', re.I)
NEW_FILES = ('ai/praat_ai/delivery.py', 'ai/tools/launch_praat_medium.py')


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def embedded_payload(executable: Path) -> bytes:
    """按 Zip 结尾记录定位内嵌载荷；载荷里也含 ``PK\\x05\\x06`` 字节，所以逐个候选试。"""

    data = executable.read_bytes()
    position = len(data)
    while True:
        position = data.rfind(b'PK\x05\x06', 0, position)
        if position < 0:
            raise SystemExit('在 exe 里找不到 Zip 结尾记录')
        comment = int.from_bytes(data[position + 20:position + 22], 'little')
        size = int.from_bytes(data[position + 12:position + 16], 'little')
        offset = int.from_bytes(data[position + 16:position + 20], 'little')
        start = position - size - offset
        if start >= 0 and data[start:start + 4] == b'PK\x03\x04':
            candidate = data[start:position + 22 + comment]
            try:
                with zipfile.ZipFile(io.BytesIO(candidate)) as archive:
                    if 'payload-manifest.json' in archive.namelist():
                        return candidate
            except zipfile.BadZipFile:
                pass


def main() -> int:
    manifest = json.loads((BUILD / 'payload-manifest.json').read_text(encoding='utf-8-sig'))
    report = json.loads((BUILD / 'build-report.json').read_text(encoding='utf-8-sig'))
    payload = (BUILD / 'payload.zip').read_bytes()
    embedded = embedded_payload(ROOT / 'AIPraat-install.exe')
    assert digest(embedded) == digest(payload), 'exe 内嵌载荷与构建出的 payload.zip 不一致'
    EMBEDDED.write_bytes(embedded)

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        entries = archive.namelist()
        assert len(entries) == len(set(entries)), '载荷里有重名条目'
        assert set(entries) == set(manifest) | {'payload-manifest.json'}, '载荷条目与清单不一致'
        assert json.loads(archive.read('payload-manifest.json')) == manifest, '载荷内清单与外部清单不一致'
        checked = 0
        for name, expected in manifest.items():
            assert not FORBIDDEN.search(name), '载荷里混进了不该有的文件: ' + name
            assert digest(archive.read(name)) == expected, '载荷内容与清单不一致: ' + name
            source = SPECIAL.get(name, ROOT / name)
            assert source.is_file(), '找不到对应源文件: ' + name
            assert digest(source.read_bytes()) == expected, '载荷与当前源码不一致: ' + name
            checked += 1
    for name in NEW_FILES:
        assert name in manifest, '本次新增文件没进载荷: ' + name
    assert not any(item.startswith('ai/tests/') for item in manifest), '载荷里不该有测试'

    binaries = {}
    for name in ('AIPraat-install.exe', 'AIPraat-paths.exe', 'Praat.exe'):
        data = (ROOT / name).read_bytes()
        binaries[name] = {'bytes': len(data), 'sha256': digest(data)}
    assert report['sha256'].lower() == binaries['AIPraat-install.exe']['sha256'], '构建报告与安装包不一致'
    assert report['praat_sha256'] == binaries['Praat.exe']['sha256'], '构建报告里的 Praat 哈希不一致'
    before = json.loads((BACKUP / 'payload-manifest.json').read_text(encoding='utf-8'))
    assert before['Praat.exe'] == binaries['Praat.exe']['sha256'], '本轮不该改动 Praat.exe'
    before_report = json.loads((BACKUP / 'build-report.json').read_text(encoding='utf-8-sig'))
    changed = sorted(name for name in set(manifest) | set(before)
                     if manifest.get(name) != before.get(name))

    result = {
        'installer': str(ROOT / 'AIPraat-install.exe'),
        'size': binaries['AIPraat-install.exe']['bytes'],
        'sha256': binaries['AIPraat-install.exe']['sha256'],
        'payload_files': len(entries),
        'hashes_verified': checked,
        'embedded_payload_matches': True,
        'current_sources_match': True,
        'no_user_config_audio_runtime': True,
        'praat_unchanged_since_last_pack': True,
        'previous_installer_sha256': before_report['sha256'],
        'changed_or_new_entries': changed,
        'binaries': binaries,
    }
    (VERIFICATION / 'delivery-artifacts.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (VERIFICATION / 'delivery-package-check.log').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
