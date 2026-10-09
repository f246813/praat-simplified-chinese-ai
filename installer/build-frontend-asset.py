"""按显式文件名单构建可选前端附件。

运行：python installer/build-frontend-asset.py。
名单不含用户配置、runtime、logs、缓存、安装器载荷或文档；打包检查敏感凭据。
安装器由 installer/build.ps1 构建。附件文件名由 OUTPUT 常量决定。
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'AIPraat-frontend-fix-20261002.zip'

FILES = [
    'ai/praat_ai/delivery.py',
    'ai/praat_ai/chat.py',
    'ai/praat_ai/cloud_workflow.py',
    'ai/praat_ai/cloud_agent.py',
    'ai/tests/test_delivery_state.py',
    'ai/tests/verify_delivery_live.py',
    'ai/tests/verify_delivery_live_cloud.py',
    'ai/tools/launch_praat_medium.py',
    'installer/build.ps1',
    'installer/publish-release.ps1',
    'installer/verification/verify-delivery-package.py',
    'test-records/installer/delivery-artifacts.json',
    'test-records/installer/delivery-package-check.log',
    'test-records/project/verify-delivery-live.json',
    'test-records/project/verify-delivery-live-cloud.json',
    'test-records/project/verify-delivery-state-suite.log',
]


def main() -> int:
    secrets = []
    config = json.loads((ROOT / 'ai' / 'ai_config.json').read_text(encoding='utf-8'))
    for section in ('api', 'qwen'):
        key = str(config.get(section, {}).get('api_key', '') or '')
        if key and key != 'EMPTY':
            secrets.append(key)

    missing = [name for name in FILES if not (ROOT / name).is_file()]
    if missing:
        raise SystemExit('missing files: ' + ', '.join(missing))

    with zipfile.ZipFile(OUTPUT, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            data = (ROOT / name).read_bytes()
            text = data.decode('utf-8', errors='replace')
            for secret in secrets:
                if secret in text:
                    raise SystemExit(f'SECRET LEAK in {name}')
            archive.writestr(name, data)

    with zipfile.ZipFile(OUTPUT) as archive:
        unpacked = sum(item.file_size for item in archive.infolist())
        print(f'{OUTPUT.name}: {len(archive.infolist())} files, {OUTPUT.stat().st_size} bytes'
              f' (unpacked {unpacked})')
        for item in archive.infolist():
            print(f'  {item.file_size:>8}  {item.filename}')
    print('API key check:', 'not present in any archived file' if secrets else '(no key in config)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
