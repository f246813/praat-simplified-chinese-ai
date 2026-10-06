"""Same-model A/B on isolated sessions and real Praat batch fixtures.

No desktop selection, user recording, configuration or saved conversation is
modified. --send uses the configured API. Only counts/fingerprints are saved.
"""
from __future__ import annotations
import argparse
import asyncio
import copy
import json
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ap = argparse.ArgumentParser()
ap.add_argument('--send', action='store_true')
ap.add_argument('--variant', choices=['baseline', 'candidate'])
ap.add_argument('--group', choices=['dialogue','measurement','prosody','failure','compression'])
ap.add_argument('--repeat', type=int, default=0)
ap.add_argument('--rounds', type=int, default=2)
ap.add_argument('--suite', choices=['fullgraph','stage-fixtures'], default='stage-fixtures')
ap.add_argument('--out', default='context-cache-final.jsonl')
ap.add_argument('--thinking', default='off')
args = ap.parse_args()
if not args.send:
    print('Pass --send to measure the configured API against isolated test fixtures.')
    raise SystemExit(0)
if args.variant is None:
    output = ROOT / 'ai/logs' / args.out
    for repeat in range(args.rounds):
        for group in ((args.group,) if args.group else ('dialogue','measurement','prosody','failure','compression')):
            order = ('baseline','candidate') if repeat == 0 else ('candidate','baseline')
            for variant in order:
                command = [sys.executable, __file__, '--send', '--variant', variant,
                           '--group', group, '--repeat', str(repeat), '--suite', args.suite, '--thinking', args.thinking]
                run = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=300)
                if run.returncode:
                    print(group, variant, 'failed', run.stderr[-600:], flush=True)
                    continue
                record = json.loads(run.stdout)
                with output.open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + '\n')
                print(group, variant, repeat, 'requests', record['requests'], 'seconds', round(record['seconds'],2), flush=True)
    raise SystemExit(0)

package = ROOT / ('backups/pi-context-cache-20261006' if args.variant == 'baseline' else 'ai')
sys.path.insert(0, str(package))
from praat_ai.config import load_config, apply_api_to_qwen
from praat_ai import cloud_agent, cloud_stream, qwen, tools, chat
from praat_ai.escape_policy import AnalysisState, Budget
from praat_ai.cloud_runtime import CloudRuntime

cfg = load_config(ROOT / 'ai/ai_config.json')
cfg.api.token_mode = 'manual'
cfg.api.limit_tokens = True
cfg.api.plan_max_tokens = 4096
cfg.api.thinking_level = args.thinking
apply_api_to_qwen(cfg)
wire = []
current = {}
active_summary = False
original_factory = cloud_agent.create_model

def factory(config):
    model = original_factory(config)
    async def request_hook(request):
        payload = json.loads(request.content)
        import hashlib
        digest = lambda value: hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        current.clear()
        current.update(static=digest({k:v for k,v in payload.items() if k in ('model','tools','response_format')}
                         | {'system':[m for m in payload['messages'] if m['role']=='system']}),
                       messages=[digest(m) for m in payload['messages']],
                       bytes=len(request.content), started=time.monotonic(), cache_mode='implicit')
        current['phase'] = 'summary' if active_summary else ('dialogue' if args.group in {'dialogue','compression'} else
                                                           'planner' if payload.get('tools') else 'report')
        wire.append(current.copy())
    async def response_hook(response):
        if response.headers.get('content-type', '').startswith('application/json'):
            await response.aread()
            if wire:
                raw = response.json().get('usage', {})
                wire[-1].update(usage=raw, seconds=time.monotonic()-wire[-1]['started'])
    model.client._client.event_hooks['request'].append(request_hook)
    model.client._client.event_hooks['response'].append(response_hook)
    return model
cloud_agent.create_model = factory
original_events = cloud_stream.DrainingAsyncStream._iter_events
async def events(self):
    async for event in original_events(self):
        if not event.data.startswith('[DONE]'):
            raw = json.loads(event.data).get('usage')
            if raw and wire:
                wire[-1].update(usage=raw, seconds=time.monotonic()-wire[-1]['started'])
        yield event
cloud_stream.DrainingAsyncStream._iter_events = events

history = []
if args.group == 'compression':
    for i in range(20):
        history += [dict(role='user', content='请记住：讨论基频与响度的区别，并区分一般知识与测量证据。' * 34),
                    dict(role='assistant', content='基频与响度属于不同的声学维度；此处只有一般知识，没有本次录音测量。' * 10)]
runtime = CloudRuntime()
states = []
ctx = None
if args.variant == 'candidate':
    from praat_ai.session_context import PhaseContext
    ctx = PhaseContext()
started = time.monotonic()
with tempfile.TemporaryDirectory(prefix='aipraat-cache-ab-') as tmp:
    work = Path(tmp)
    sound = ROOT / 'test/fon/examples/sounds/aaaa02.wav'
    import wave
    with wave.open(str(sound), 'rb') as audio:
        duration = audio.getnframes() / audio.getframerate()
    context = 'id\tclass\tname\tselected\n1\tSound\taaaa02\t1\n'
    tool_context = tools.ToolContext(tools.parse_object_context(context), work/'result.tsv', work/'state.txt')
    execution_count = 0
    def execute(script):
        global execution_count
        execution_count += 1
        if args.group == 'failure':
            return False, [], '缺少可用测试依赖，测量未执行'
        tool_context.result_path.unlink(missing_ok=True)
        tool_context.state_path.unlink(missing_ok=True)
        path = work / f'step-{execution_count}.praat'
        path.write_text(f'Read from file: "{sound.as_posix()}"\n' + script, encoding='utf-8')
        run = subprocess.run([str(ROOT/'Praat.exe'), '--no-pref-files', '--no-plugins', '--FULL-TRUST', '--run', str(path)],
                             capture_output=True, timeout=40)
        rows = tool_context.result_path.read_text(encoding='utf-8').splitlines() if tool_context.result_path.exists() else []
        return run.returncode == 0 and bool(rows), rows, '' if run.returncode == 0 else '测试批处理执行失败'
    def action(name, arguments, index):
        return chat._execute_action(dict(tool=name, arguments=arguments), tool_context, execute, index)
    fixture = []
    if args.suite == 'stage-fixtures' and args.group in {'measurement','prosody'}:
        parameters = ('mean_pitch','mean_intensity') if args.group == 'measurement' else ('pitch_start','pitch_end','pitch_slope')
        for parameter in parameters:
            arguments = {'object':1, 'parameter':parameter, 'from':0, 'to':duration}
            step = action('measure', arguments, len(fixture)+1)
            if not step.ok or not step.results:
                raise RuntimeError('Real Praat measurement fixture failed: ' + step.observation)
            from praat_ai.escape_policy import Evidence
            fixture.append(Evidence('measure', arguments, step.results, context))
    for i in range(3):
        if args.group in {'dialogue','compression'}:
            goal = ('什么是基频？用两句话回答。','基频与音高是什么关系？用两句话回答。','响度与基频有什么区别？用两句话回答。')[i]
            if args.group == 'compression':
                from praat_ai.modern_store import ModernStore
                from praat_ai.modern_budget import compact
                store = ModernStore(work/'history.sqlite3')
                sid = store.new_session()['id']
                active_summary = True
                try:
                    history = compact(store, sid, cfg, history, [], goal, '', cancel=threading.Event(), emit=lambda *_:None,
                                      **(dict(runtime=runtime) if args.variant == 'candidate' else {}))
                finally:
                    active_summary = False
            state = AnalysisState(goal, '', budget=Budget(cfg.api.max_context_tokens, cfg.api.plan_max_tokens))
            state.dialogue_context = copy.deepcopy(history)
            if ctx is not None:
                ctx.sync_formal(history)
                state.phase_context = ctx
            cloud_agent.run_dialogue_turn(cfg, state, kind='concept', cancel=threading.Event(), on_text=lambda _:None,
                                         runtime=runtime if args.variant == 'candidate' else None)
            if state.status == 'complete':
                history += [dict(role='user', content=goal), dict(role='assistant', content=state.report)]
            if ctx is not None:
                ctx.mark_formal(history)
        else:
            goal = ('测量整段的基频统计与强度统计并简短解释。' if args.group == 'measurement' else
                    '测量整段音高起点终点与斜率，解释语调走向。' if args.group == 'prosody' else
                    '测量整段音高并简短解释无法完成时的原因。')
            if args.suite == 'stage-fixtures':
                goal += '用两句话引用已提供证据回答；不要给参考阈值或额外数字。'
            state = AnalysisState(goal, context, budget=Budget(cfg.api.max_context_tokens,cfg.api.plan_max_tokens))
            state.dialogue_context = copy.deepcopy(history)
            if args.suite == 'stage-fixtures':
                # Isolate report/context overhead with the SAME verified batch
                # evidence. Full agent-loop regressions run separately offline.
                state.continuation, state.continuation_mode = True, 'L2'
                state.evidence = copy.deepcopy(fixture)
                if args.group == 'failure':
                    state.failures['measure'] = 2
                    state.reason = '隔离测试依赖不可用；没有执行测量，不能给出录音判断'
                    state.attempts = [dict(tool='measure', arguments={}, status='not_executed',
                                           reason=state.reason, execution='not_delivered')]
            schemas = [s for s in tools.tool_schemas() if s['function']['name']=='measure']
            prior_reason = state.reason
            cloud_agent.run_cloud_turn(cfg, state, execute_action=action, cancel=threading.Event(),
                                      tool_schemas=schemas, runtime=runtime if args.variant == 'candidate' else None)
            if state.status in {'complete','partial'} and state.reason == prior_reason:
                history += [dict(role='user', content=goal), dict(role='assistant', content=state.report)]
        states.append(dict(status=state.status, requests=state.requests, metrics=state.metrics,
                           evidence=len(state.evidence), attempts=len(state.attempts), reason=state.reason))
runtime.close(wait=True)
for item in wire:
    item.pop('started',None)
record = dict(variant=args.variant,group=args.group,repeat=args.repeat,model=cfg.api.model,
              thinking=cfg.api.thinking_level,output_tokens=cfg.api.plan_max_tokens,
              suite=args.suite, context_tokens=cfg.api.max_context_tokens,
              cache_state='uncontrolled observation; implicit; alternating isolated sessions',
              seconds=time.monotonic()-started,requests=len(wire),states=states,wire=wire)
print(json.dumps(record, ensure_ascii=True))
