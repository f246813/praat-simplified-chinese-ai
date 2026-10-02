"""把工作目录同步到 public 镜像的 modern 分支（只动前端/文档/安装器，绝不覆盖原生 C++）。

    python installer/push-frontend.py            # dry run：列出将上传/将跳过的文件
    python installer/push-frontend.py --push     # 真的建 blob/tree/commit 并更新分支

为什么要这样写（2026-10-02 实测定下的规则）：

* 工作目录 `稳定早期版` 是从 `D:\\Praat-work` 导出的快照，和线上 `modern` **双向分叉**：
  - 前端（`ai/`）、文档、安装器侧：本地是新的；
  - 原生 C++ 侧：线上是新的（有 `PraatAiControl_addModelMenu`、`fon/SegmentAcoustic*`、
    `MelderFile_replaceAtomically`、`v_createExtraToolbarButtons` 等），本地快照没有。
    线上 `sys/praat_objectMenus.cpp` 会调用 `addModelMenu`，所以**照推本地原生文件会让原生树
    自相矛盾（链接不过），还会删掉上游的分段声学分析**。
* 因此：原生源文件与构建文件（`sys/`、`fon/`、`foned/`、`melder/`、`Makefile`、`meson.build`…）
  一律跳过，保持线上版本；只推 `ai/`、`docs/`、`installer/`、根目录文本与**新增文件**。
* 三道保险：①任何「本地版本会丢掉线上内容」（有删除行、没有新增行）的文件都跳过；
  ②建树时用 `base_tree = 线上树`，**不删除任何线上路径**；③上传前对每个字节做密钥扫描
  （GitHub token / API key / 私钥）。
* 只按路径查线上状态（`GET /contents/<path>`），**不拉递归树**：本机代理会把 1.7 MB 的
  递归树响应截断，非递归的小响应正常。

回退：把 `refs/heads/modern` 指回推送前记录的 SHA，或在提交页点 Revert。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = 'f246813/praat-simplified-chinese-ai'
BRANCH = 'modern'
TOKEN = os.environ.get('GITHUB_TOKEN', '')
ROOT = Path(__file__).resolve().parents[1]

EXCLUDE_DIRS = {'.build-tools', '.git', '__pycache__', 'backups', 'runtime', 'logs',
                'installer/build', 'ai/runtime', '.aipraat-backups'}
EXCLUDE_SUFFIX = {'.exe', '.dll', '.zip', '.gguf', '.wav', '.pyc', '.pyd', '.so', '.dylib',
                  '.lib', '.obj', '.pdb', '.msi', '.7z', '.tar', '.gz', '.bin', '.bak', '.a', '.o'}
EXCLUDE_NAMES = {'ai_config.json', 'ai_config.json.lock', 'chat.pid', 'conversations.sqlite3',
                 'payload.zip'}
EXCLUDE_PREFIX = ('installer/verification/python-live-', 'installer/verification/python_setup_',
                  'installer/verification/python-workspace-', 'installer/verification/installed')
MAX_FILE_BYTES = 8 * 1024 * 1024

NATIVE_SUFFIX = {'.cpp', '.h', '.hpp', '.c', '.cc', '.cxx', '.in', '.am', '.ac', '.m', '.mm', '.rc'}
NATIVE_NAMES = {'Makefile', 'makefile', 'meson.build', 'CMakeLists.txt'}

MESSAGE = """前端与文档同步：投递事实修复、对话优化、主菜单 UI 等

- ai/praat_ai：新增 delivery.py（DELIVERED / NOT_DELIVERED / EXECUTION_UNKNOWN /
  EXECUTION_BLOCKED）；chat.py / cloud_workflow.py / cloud_agent.py 按投递事实判断，
  「没送出去」不再被当成「执行状态不明」，失败原因进报告上下文（blocked_attempts），
  `audio_input=false` 不再被当成「无法测量」。
- ai/：对话 fastpath、思考链折叠区、IME、API 能力状态、分段/表格工具等此前几轮的改动，
  以及对应测试与模板。
- docs/、guide.md、README、BUILD_INFO 等主页面文档同步。
- installer/：build.ps1 补 UTF-8 BOM（避免 PowerShell 5.1 按 ANSI 读导致载荷中文文件名乱码）；
  新增 publish-release.ps1、build-frontend-asset.py、push-frontend.py、
  verification/verify-delivery-package.py。

说明：**原生 C++（sys/、fon/、foned/、melder/ 等）保持线上版本不变**——线上有本地快照没有的
模型菜单与分段声学分析，混合推送会破坏原生树。本次只同步 Python 前端、文档与安装器侧，
没有删除任何线上文件（新树以线上树为 base_tree）。

验证：Python 套件 798 项 0 failures（5 个环境性 error）；真机 Praat 12/12；真云端一轮
VOT=38.0 毫秒；安装包内嵌载荷 73 项哈希与源码逐项一致。
"""


class ApiError(RuntimeError):
    pass


def api(method: str, path: str, payload=None, attempts: int = 6):
    """带重试的 API 调用：本机代理偶发截断响应、TLS 握手失败。404 返回 None。"""

    data = json.dumps(payload).encode() if payload is not None else None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                'https://api.github.com' + path, data=data, method=method,
                headers={'Authorization': 'Bearer ' + TOKEN, 'Accept': 'application/vnd.github+json',
                         'Content-Type': 'application/json', 'User-Agent': 'aipraat-push',
                         'X-GitHub-Api-Version': '2022-11-28'})
            with urllib.request.urlopen(request, timeout=600) as response:
                chunks = []
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                return json.loads(b''.join(chunks))
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            detail = error.read().decode('utf-8', 'replace')[:300]
            if error.code in (500, 502, 503, 504) and attempt < attempts - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise ApiError(f'HTTP {error.code} on {method} {path}: {detail}')
        except (urllib.error.URLError, OSError, http.client.IncompleteRead,
                json.JSONDecodeError, ValueError) as error:
            if attempt == attempts - 1:
                raise ApiError(f'network failed on {method} {path}: {error!r}')
            time.sleep(2 * (attempt + 1))


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


def is_native(relative: str) -> bool:
    if relative.startswith('ai/'):
        return False
    name = relative.rsplit('/', 1)[-1]
    return name in NATIVE_NAMES or Path(name).suffix.lower() in NATIVE_SUFFIX


def excluded(relative: str) -> bool:
    parts = relative.split('/')
    if any(part in EXCLUDE_DIRS for part in parts[:-1]):
        return True
    if relative.startswith(EXCLUDE_PREFIX):
        return True
    if parts[-1] in EXCLUDE_NAMES:
        return True
    return Path(parts[-1]).suffix.lower() in EXCLUDE_SUFFIX


def secret_patterns() -> list[re.Pattern]:
    patterns = [re.compile(r'ghp_[A-Za-z0-9]{20,}'), re.compile(r'github_pat_[A-Za-z0-9_]{20,}'),
                re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')]
    config_path = ROOT / 'ai' / 'ai_config.json'
    if config_path.is_file():
        config = json.loads(config_path.read_text(encoding='utf-8'))
        for section in ('api', 'qwen'):
            key = str(config.get(section, {}).get('api_key', '') or '')
            if key and key != 'EMPTY':
                patterns.append(re.compile(re.escape(key)))
    return patterns


class Remote:
    """线上某一分支的「路径 → blob sha / mode」。

    不拉递归树：本机代理会把 1.7 MB 的递归树响应截断。改成从根树开始**逐层拉非递归树**
    （每个响应都小，`docs/manual` 那 2000 个文件也只是一个 250 KB 的响应），并把结果缓存到
    系统临时目录（按提交 sha 区分），重复运行不再重拉。
    """

    def __init__(self, ref: str, base_tree: str):
        self.ref = ref
        self.base_tree = base_tree
        self.map = self._load()

    def _cache_path(self) -> Path:
        temp = os.environ.get('TEMP') or os.environ.get('TMP') or str(Path.home())
        return Path(temp) / f'aipraat-remote-{self.ref}-{self.base_tree[:12]}.json'

    def _load(self) -> dict[str, dict]:
        cache = self._cache_path()
        if cache.is_file():
            try:
                return json.loads(cache.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                pass
        items: dict[str, dict] = {}
        queue = [('', self.base_tree)]
        while queue:
            prefix, sha = queue.pop()
            tree = api('GET', f'/repos/{REPO}/git/trees/{sha}')
            if tree is None:
                continue
            for entry in tree['tree']:
                path = prefix + entry['path']
                if entry['type'] == 'blob':
                    items[path] = {'sha': entry['sha'], 'mode': entry.get('mode', '100644')}
                elif entry['type'] == 'tree':
                    queue.append((path + '/', entry['sha']))
        try:
            cache.write_text(json.dumps(items, ensure_ascii=False), encoding='utf-8')
        except OSError:
            pass
        return items

    def info(self, relative: str) -> dict | None:
        return self.map.get(relative)


def collect(remote: Remote) -> tuple[dict[str, bytes], dict[str, str], dict[str, list[str]], dict[str, int]]:
    """挑出「该推、且推了不会丢线上内容」的文件。"""

    upload: dict[str, bytes] = {}
    modes: dict[str, str] = {}
    skipped: dict[str, list[str]] = {'native': [], 'pure_loss': [], 'binary': [], 'too_big': []}
    counts = {'added': 0, 'modified': 0}
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if excluded(relative):
            continue
        if is_native(relative) and not relative.startswith('docs/'):
            skipped['native'].append(relative)
            continue
        data = path.read_bytes()
        if len(data) > MAX_FILE_BYTES:
            skipped['too_big'].append(relative)
            continue
        try:
            data.decode('utf-8')
        except UnicodeDecodeError:
            skipped['binary'].append(relative)
            continue
        sha = blob_sha(data)
        info = remote.info(relative)
        if info is not None and info['sha'] == sha:
            continue                                        # 线上已经是这份内容
        if info is not None:
            blob = api('GET', f"/repos/{REPO}/git/blobs/{info['sha']}")
            old = base64.b64decode(blob['content']).decode('utf-8', 'replace').splitlines()
            new = data.decode('utf-8').splitlines()
            old_set, new_set = set(old), set(new)
            lost = [line for line in old if line.strip() and line not in new_set]
            gained = [line for line in new if line.strip() and line not in old_set]
            if lost and not gained:
                skipped['pure_loss'].append(relative)
                continue
            counts['modified'] += 1
            modes[relative] = '100755' if info.get('mode') == '100755' else '100644'
        else:
            counts['added'] += 1
            modes[relative] = '100644'
        upload[relative] = data
    return upload, modes, skipped, counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--push', action='store_true')
    parser.add_argument('-m', '--message', default='', help='覆盖提交信息（默认见 MESSAGE）')
    args = parser.parse_args()
    if not TOKEN:
        raise SystemExit('先设置 GITHUB_TOKEN（classic token 只需 public_repo，用完 revoke）')

    try:
        ref = api('GET', f'/repos/{REPO}/git/ref/heads/{BRANCH}')
        head = ref['object']['sha']
        commit = api('GET', f'/repos/{REPO}/git/commits/{head}')
        remote = Remote(BRANCH, commit['tree']['sha'])
        upload, modes, skipped, counts = collect(remote)
    except ApiError as error:
        raise SystemExit(str(error))

    total = sum(len(value) for value in upload.values())
    print(f'线上 HEAD {head[:12]} | 新增 {counts["added"]} | 修改 {counts["modified"]} | '
          f'待上传 {len(upload)} 个文件 / {total/1024/1024:.2f} MiB')
    print(f'跳过：原生 {len(skipped["native"])}，会丢线上内容 {len(skipped["pure_loss"])}，'
          f'非文本 {len(skipped["binary"])}，超大 {len(skipped["too_big"])}')
    for relative in skipped['pure_loss']:
        print('   会丢线上内容:', relative)
    if not args.push:
        print('（dry run，没有写任何东西；加 --push 才推送）')
        return 0

    patterns = secret_patterns()
    for relative, data in upload.items():
        text = data.decode('utf-8', 'replace')
        for pattern in patterns:
            if pattern.search(text):
                raise SystemExit(f'发现疑似密钥，已停止：{relative}')
    print('密钥扫描通过 ✓')

    try:
        entries = []
        for index, (relative, data) in enumerate(sorted(upload.items()), 1):
            blob = api('POST', f'/repos/{REPO}/git/blobs',
                       {'content': base64.b64encode(data).decode(), 'encoding': 'base64'})
            entries.append({'path': relative, 'mode': modes[relative], 'type': 'blob',
                            'sha': blob['sha']})
            if index % 40 == 0 or index == len(upload):
                print(f'   {index}/{len(upload)}')
        new_tree = api('POST', f'/repos/{REPO}/git/trees',
                       {'base_tree': remote.base_tree, 'tree': entries})
        new_commit = api('POST', f'/repos/{REPO}/git/commits',
                         {'message': args.message or MESSAGE, 'tree': new_tree['sha'],
                          'parents': [head]})
        api('PATCH', f'/repos/{REPO}/git/refs/heads/{BRANCH}',
            {'sha': new_commit['sha'], 'force': False})
    except ApiError as error:
        raise SystemExit(str(error))
    print(f"已推送 {head[:12]} -> {new_commit['sha'][:12]}")
    print(f"提交：https://github.com/{REPO}/commit/{new_commit['sha']}")
    print(f'回退：refs/heads/{BRANCH} 指回 {head}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
