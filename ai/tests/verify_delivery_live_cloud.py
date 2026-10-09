"""真机 + 真云端的阶梯验证：走 ``process_cloud`` 这条真实代码路径。

    python ai/tests/verify_delivery_live_cloud.py --goal "测量 ... 的 VOT" --send

**会真的发云端请求**（用当前 ``ai_config.json`` 里的模型与额度），所以默认不跑，要显式
``--send``；跑之前确认 Praat 正在运行、对象列表与 ``--goal`` 对得上。它是
``verify_delivery_live.py``（不碰云端、只验投递与测量）的补充：这条把云端模型、阶梯、
投递、报告整条链走一遍，并把过程提示、报告、证据、尝试记录和用量写成
``test-records/project/verify-delivery-live-cloud.json``。

注意：本机会话环境里 ``NO_PROXY`` 含 ``[::1]``，``httpx2`` 解析不了（``Invalid port:
':1]'``），连 ``AsyncOpenAI(...)`` 都构造不出来。脚本只在**自己这个进程**里把
``NO_PROXY`` 换成可解析的值；那是环境问题，不是产品行为。
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

# 见模块说明：只影响本验证进程。
for _key in list(os.environ):
    if _key.lower() == 'no_proxy':
        os.environ[_key] = 'localhost,127.0.0.1,192.168.31.246,.local'

from praat_ai import chat, cloud_workflow  # noqa: E402
from praat_ai.cloud_runtime import CloudRuntime  # noqa: E402
from praat_ai.conversation_store import ConversationStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--goal', default='测量选中这段的 vot')
    parser.add_argument('--send', action='store_true', help='真的发云端请求（会消耗额度）')
    args = parser.parse_args()

    config = chat.load_config(chat.config_path())
    executable = chat.praat_executable()
    process_ids = chat.praat_process_ids(executable) if executable else None
    print('模型:', config.api.model, '| 端点:', config.api.base_url)
    print('Praat:', executable, process_ids)
    print(chat.object_context())
    if not args.send:
        print('未加 --send：只做了只读检查，没有发请求。')
        return 0
    if not executable or not chat.praat_process_running_from(process_ids):
        print('没有运行中的 Praat，先启动一个能写消息文件的 Praat')
        return 1

    window = chat.ChatWindow.__new__(chat.ChatWindow)
    window.config = config
    window.messages = queue.Queue()
    window.history = []
    window.cancel_event = threading.Event()
    window.pending_analysis = None
    window.task_materials = []
    window.current_materials = None
    window.analysis_state = None
    window.cloud_runtime = CloudRuntime()
    window._closed = False
    window.store = ConversationStore(chat.runtime_dir() / 'conversations.sqlite3')
    window.session_id = window.store.new_session()

    started = time.monotonic()
    cloud_workflow.process_cloud(window, args.goal)
    elapsed = time.monotonic() - started

    hints, reply = [], ''
    while not window.messages.empty():
        kind, payload = window.messages.get()
        if kind == 'hint':
            hints.append(payload)
        elif kind == 'assistant':
            reply = payload
        else:
            hints.append(f'[{kind}] {payload}')

    state = window.analysis_state
    print('\n===== 过程提示 =====')
    for line in hints:
        print('-', line)
    print('\n===== 本轮报告 =====')
    print(reply[:4000])
    print('\n===== 结构化 =====')
    for item in state.coverage:
        print('覆盖:', json.dumps(item, ensure_ascii=False)[:300])
    for attempt in state.attempts:
        print('尝试:', attempt.get('tool'), attempt.get('status'), attempt.get('execution'),
              str(attempt.get('reason'))[:160])
    print('metrics:', json.dumps(state.metrics, ensure_ascii=False)[:400])
    print(f'state.status={state.status} requests={state.requests} 用时={elapsed:.1f}s')

    record = {
        'goal': args.goal, 'model': config.api.model, 'elapsed_seconds': elapsed,
        'reply': reply, 'coverage': state.coverage, 'status': state.status,
        'requests': state.requests, 'metrics': state.metrics, 'events': state.events, 'hints': hints,
        'evidence': [{'tool': e.tool, 'arguments': e.arguments, 'rows': e.rows} for e in state.evidence],
        'attempts': [{key: value for key, value in attempt.items() if key != 'script'}
                     for attempt in state.attempts],
    }
    destination = Path(__file__).resolve().parents[2] / 'test-records' / 'project' / 'verify-delivery-live-cloud.json'
    destination.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print('记录:', destination)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
