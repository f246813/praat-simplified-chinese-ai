"""Summarize the count-only A/B log without making cache/latency assumptions."""
import hashlib
import json
import statistics
from pathlib import Path

root = Path(__file__).resolve().parents[2]
records = [json.loads(line) for line in (root/'ai/logs/context-cache-final.jsonl').read_text(encoding='utf-8').splitlines()]
assert len(records) == 20
summary = {}
failure_reason = '隔离测试依赖不可用；没有执行测量，不能给出录音判断'
for group in ('dialogue','measurement','prosody','failure','compression'):
    summary[group] = {}
    for variant in ('baseline','candidate'):
        cases = [r for r in records if r['group']==group and r['variant']==variant]
        assert len(cases)==2
        assert all(r['thinking']=='off' and r['output_tokens']==4096 and r['context_tokens']==32768 for r in cases)
        wire = [w for r in cases for w in r['wire']]
        states = [s for r in cases for s in r['states']]
        total = sum(w['usage']['prompt_tokens'] for w in wire)
        cached = sum(w['usage']['prompt_tokens_details']['cached_tokens'] for w in wire)
        output = sum(w['usage']['completion_tokens'] for w in wire)
        first_text = [s['metrics']['first_text_seconds'] for s in states if s['metrics'].get('first_text_seconds') is not None]
        accepted = sum(s['status']=='complete' if group in {'dialogue','compression'} else
                       s['reason']==(failure_reason if group=='failure' else '') for s in states)
        phases = {}
        for phase in sorted({w['phase'] for w in wire}):
            entries = [w for w in wire if w['phase']==phase]
            phases[phase] = dict(requests=len(entries), input_tokens=sum(w['usage']['prompt_tokens'] for w in entries),
                                cache_read_tokens=sum(w['usage']['prompt_tokens_details']['cached_tokens'] for w in entries),
                                cache_write_tokens=None)
        elapsed = [r['seconds'] for r in cases]
        summary[group][variant] = dict(
            repeats=2, turns=6, requests=len(wire), extra_requests=len(wire)-(8 if group=='compression' else 6),
            input_tokens=total, output_tokens=output, cache_read_tokens=cached, cache_write_tokens=None,
            cache_coverage=cached/total, elapsed_median=statistics.median(elapsed), elapsed_range=[min(elapsed),max(elapsed)],
            first_text_median=statistics.median(first_text) if first_text else None,
            accepted_reports=accepted, guard_blocks=sum(sum(s['metrics'].get('guard_blocks',{}).values()) for s in states),
            guard_repairs=sum(sum(s['metrics'].get('guard_repairs',{}).values()) for s in states), phases=phases,
            tariff_estimate_cny=(.2*(total-.8*cached)+.8*output)/1_000_000)
    a,b = summary[group]['baseline'],summary[group]['candidate']
    summary[group]['observed_change'] = dict(input_reduction=1-b['input_tokens']/a['input_tokens'],
                                            time_reduction=1-b['elapsed_median']/a['elapsed_median'],
                                            tariff_reduction=1-b['tariff_estimate_cny']/a['tariff_estimate_cny'])
manifest = {}
for relative in ('cloud_agent.py','cloud_metrics.py','session_context.py','skill_registry.py','modern_budget.py',
                 'modern_store.py','modern_execution.py','modern_app.py','materials.py','cloud_stream.py'):
    manifest[relative] = hashlib.sha256((root/'ai/praat_ai'/relative).read_bytes()).hexdigest()
artifact = dict(model=records[0]['model'], provider_host='dashscope.aliyuncs.com',
                cache_state='implicit, uncontrolled; no prewarm', summary=summary, final_source_sha256=manifest,
                pricing=dict(date='2026-10-06',region='China Beijing',currency='CNY',input_per_million=.2,
                             output_per_million=.8,implicit_read_multiplier=.2,
                             sources=['https://help.aliyun.com/en/model-studio/model-pricing',
                                      'https://help.aliyun.com/zh/model-studio/context-cache'],
                             basis='public tariff estimate from observed usage, not an account bill'))
(root/'ai/logs/context-cache-summary.json').write_text(json.dumps(artifact,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
for group, data in summary.items():
    print(group,json.dumps(data,ensure_ascii=False))
