"""真机验证：投递事实 + 真实 Praat 里的 VOT 测量（不调用模型、不发云端请求）。

    python ai/tests/verify_delivery_live.py [--audio <path>] [--from 0.437403] [--to 0.635206]

复现 2026-10-02 那次「测量选中这段的vot 没完成」的现场。**前提是有一台能写
``%APPDATA%\\Praat\\Message.txt`` 的 Praat**（即完整性级别 Medium）：仓库所在的
``稳定早期版`` 目录带 Low 完整性标签，从那里启动的 ``Praat.exe`` 会是 Low，写不了
消息文件——那种情况下本脚本会先在这一项上失败，正好指出现场原因。

脚本做的事：

1. 检查消息文件能不能写（那次就是这里 `[Errno 13]`）；
2. 真的投一条刷新对象列表的脚本（Message.txt + WM_APP）；
3. 造一个**已知 VOT 的合成声音**（0.030 秒宽带爆破 → 0.045 秒 120 Hz 浊音，真值 15 毫秒），
   按用户原话那条路（``from``/``to`` 自动估计）跑一遍，再按「两个时刻相减」跑一遍确定性算术；
4. 真的写不进消息文件时，投递事实必须是 ``NOT_DELIVERED``，而不是「执行状态不明」；
5. 报告上下文必须带上那条真实失败原因；
6. 收尾：删掉本次造出来的对象（含 vot 工具留下的派生对象）。

给了 ``--audio``（默认取同目录上两级的 ``あなた.wav``，存在才用）时，还会把那段真实录音
读回对象列表、按 ``--from``/``--to`` 跑同一条 vot，并把数值写进记录；那个 Sound 会保留。
记录写到 ``稳定早期版/test-records/project/verify-delivery-live.json``。不会动用户已有的对象和录音。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from unittest.mock import patch

from praat_ai import chat, delivery, sendpraat, tools
from praat_ai.cloud_agent import report_context
from praat_ai.escape_policy import AnalysisState

#: 合成声音：0–0.030 静音；0.030–0.045 宽带爆破；0.045 起 120 Hz 浊音（带 10 毫秒淡入，
#: 免得正弦的突然起始自己造出一个宽带瞬态，把爆破点判到浊音起点上）。
#: Praat 公式里没有 ``elif``，条件只能写 ``if … then … else … fi``。
FORMULA = ('~ if x < 0.03 then 0 else (if x < 0.045 then 0.6*randomGauss(0,1) '
           'else 0.5*sin(2*pi*120*x)*min(1,(x-0.045)/0.01) fi) fi')


def with_completion(body: str) -> str:
    """手写脚本必须自己写完成标记（工具脚本由 ``tools._assemble`` 补上）。"""

    return body + f'appendFileLine: {tools.quote(chat.state_path())}, "done"\n'


def drop_objects(executable: str, predicate) -> list[str]:
    """按条件删对象；一次删一个，且先删 id 最大的（Praat 删完会重编号）。"""

    removed: list[str] = []
    for _ in range(20):
        victims = [row for row in tools.parse_object_context(chat.object_context()) if predicate(row)]
        if not victims:
            break
        row = max(victims, key=lambda item: item.id)
        ok, _ = chat._send_script(executable, with_completion(f'selectObject: {row.id}\nRemove\n'))
        if not ok:
            break
        removed.append(f'{row.id} {row.class_name} {row.name}')
    return removed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--audio', default='', help='真实录音（可选）')
    parser.add_argument('--from', dest='start', type=float, default=0.437403)
    parser.add_argument('--to', dest='end', type=float, default=0.635206)
    args = parser.parse_args()

    executable = chat.praat_executable()
    process_ids = chat.praat_process_ids(executable) if executable else None
    if not executable or not chat.praat_process_running_from(process_ids):
        print('FAIL 没有运行中的 Praat；先启动一个能写消息文件的 Praat')
        return 1
    print(f'PASS 找到运行中的 Praat：{executable}（pid {process_ids}）')

    record: dict = {'praat': executable, 'pids': process_ids, 'checks': []}

    def check(name: str, ok: bool, detail: object = '') -> bool:
        record['checks'].append({'check': name, 'ok': bool(ok), 'detail': str(detail)[:600]})
        print(('PASS ' if ok else 'FAIL ') + name + (f'：{str(detail)[:400]}' if detail else ''))
        return bool(ok)

    message_path = sendpraat.message_file_path()
    try:
        assert message_path is not None
        message_path.parent.mkdir(parents=True, exist_ok=True)
        probe = message_path.with_name(message_path.name + '.delivery-probe')
        probe.write_text('probe', encoding='utf-8')
        probe.unlink()
        check('Praat 消息文件可写（2026-10-02 的故障点）', True, message_path)
    except (AssertionError, OSError) as error:
        check('Praat 消息文件可写（2026-10-02 的故障点）', False, f'{message_path}: {error}')

    ok, note = chat.refresh_object_context(executable, process_ids, assume_fresh=False)
    check('对象列表刷新（真实投递 Message.txt + WM_APP）', ok, note or '已刷新')

    user_wav = Path(args.audio) if args.audio else (Path(__file__).resolve().parents[3] / 'あなた.wav')
    if not user_wav.is_file():
        user_wav = None
    user_name = ''

    try:
        box: list[str] = []
        ok, note = chat._send_script(
            executable,
            with_completion(f'Create Sound from formula: "vot-live", 1, 0, 0.4, 44100, {FORMULA}\n'),
            outcome=box)
        check('投递成功时投递事实 = DELIVERED', ok and box == [delivery.DELIVERED],
              f'ok={ok} outcome={box} {note[:200]}')
        fresh = tools.parse_object_context(chat.object_context())
        created = [row for row in fresh if 'vot-live' in row.name]
        check('合成声音已建立并成为当前选择',
              bool(created) and any(row.selected for row in created),
              f'新对象 {[row.id for row in created]}')
        if not created:
            return 1
        context = tools.ToolContext(fresh, chat.result_path(), chat.state_path())

        # 用户原话那条路：给了 from/to，工具在范围内自动估计。
        script = tools.render('vot', {'object': created[-1].id, 'from': 0.0, 'to': 0.2}, context)
        box.clear()
        ok, note = chat._send_script(executable, script, outcome=box)
        failure = chat._read_failure()
        text = '；'.join(chat._read_results())
        match = re.search(r'（([\d.]+)\s*毫秒）', text)
        check('真实 Praat 里跑完 vot（from/to 自动估计）', ok and not failure and bool(match),
              (failure or text)[:400])
        if match:
            check('自动估计落在合理区间（合成真值 15 毫秒，允许 5–60 毫秒）',
                  5.0 <= float(match.group(1)) <= 60.0, match.group(1) + ' 毫秒')
        check('这一条调用的投递事实也是 DELIVERED', box == [delivery.DELIVERED], box)

        # 确定性算术：两个时刻相减必须是 15.0 毫秒。
        script = tools.render('vot', {'object': created[-1].id, 'burst': 0.03, 'voicing': 0.045},
                              context)
        box.clear()
        ok, note = chat._send_script(executable, script, outcome=box)
        text = '；'.join(chat._read_results())
        check('给出两个时刻时 VOT = 15.0 毫秒（0.045 − 0.030）', '15.0 毫秒' in text, text[:300])

        # 真的写不进消息文件：必须报「没投递」，不是「执行状态不明」。
        with patch.object(sendpraat, 'message_file_path', return_value=message_path.parent):
            box.clear()
            ok, note = chat._send_script(executable, 'a = 1\n', outcome=box)
        check('写不进消息文件 → NOT_DELIVERED（不是状态不明）',
              (not ok) and box == [delivery.NOT_DELIVERED], f'{box} {note[:300]}')

        state = AnalysisState('测量选中这段的vot', chat.object_context())
        state.attempts = [{'tool': 'export_original_audio', 'status': 'failed', 'reason': note}]
        context_text = json.dumps(report_context(state), ensure_ascii=False)
        check('报告上下文带上真实失败原因',
              json.dumps(note, ensure_ascii=False)[1:-1] in context_text, context_text[:300])

        # 真实录音：按用户当时的选区跑同一条 vot（可选）。
        if user_wav is not None:
            stem = user_wav.stem
            rows = tools.parse_object_context(chat.object_context())
            loaded = [row for row in rows if row.class_name == 'Sound' and stem in row.name]
            if not loaded:  # 已经读过就不再读一份（免得对象列表里堆同名 Sound）
                box.clear()
                ok, note = chat._send_script(
                    executable,
                    with_completion(f'Read from file: {tools.quote(str(user_wav))}\n'), outcome=box)
                check(f'把真实录音读回对象列表（{user_wav.name}）', ok, note or user_wav.name)
                rows = tools.parse_object_context(chat.object_context())
                loaded = [row for row in rows if row.class_name == 'Sound' and stem in row.name]
            if loaded:
                user_name = stem
                context = tools.ToolContext(rows, chat.result_path(), chat.state_path())
                script = tools.render('vot', {'object': loaded[-1].id, 'from': args.start, 'to': args.end},
                                      context)
                box.clear()
                ok, note = chat._send_script(executable, script, outcome=box)
                text = '；'.join(chat._read_results())
                record['user_vot'] = text
                check(f'按选区 {args.start}–{args.end} 秒跑同一条 vot（用户原话那条路）',
                      ok and 'VOT' in text, (note or text)[:400])
    finally:
        # 本次造出来的对象都清掉：合成声音，以及 vot 工具跑完后留下的派生对象
        # （工具删自己的临时 Sound/Intensity，但会留下一个 Harmonicity）。
        removed = drop_objects(executable, lambda row: 'vot-live' in row.name)
        if user_name:
            removed += drop_objects(executable, lambda row: row.class_name == 'Harmonicity'
                                    and user_name in row.name)
            # 同名 Sound 只留 id 最大的那一个，其余（早先验证留下的）删掉。
            sounds = [row for row in tools.parse_object_context(chat.object_context())
                      if row.class_name == 'Sound' and user_name in row.name]
            newest = max(sounds, key=lambda row: row.id).id if sounds else 0
            removed += drop_objects(executable, lambda row: row.class_name == 'Sound'
                                    and user_name in row.name and row.id != newest)
        print('收尾删除：' + ('、'.join(removed) if removed else '（无）'))
        remaining = tools.parse_object_context(chat.object_context())
        print('剩余对象：' + ('、'.join(f'{row.id} {row.class_name} {row.name}' for row in remaining)
                             or '（空）'))
        keep = [row for row in remaining
                if row.class_name == 'Sound' and user_name and user_name in row.name]
        if keep:
            chat._send_script(executable, with_completion(f'selectObject: {keep[0].id}\n'))

    record['ok'] = all(item['ok'] for item in record['checks'])
    destination = Path(__file__).resolve().parents[2] / 'test-records' / 'project' / 'verify-delivery-live.json'
    destination.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    passed = sum(1 for item in record['checks'] if item['ok'])
    print(f'{passed}/{len(record["checks"])} 项真机检查通过；记录：{destination}')
    return 0 if record['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
