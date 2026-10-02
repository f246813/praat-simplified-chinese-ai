"""Application policy only; graph and model execution live in cloud_agent."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any


class BranchExit(RuntimeError):
    pass


@dataclass
class Budget:
    context_tokens: int = 32768
    response_tokens: int = 1500
    request_limit: int = 12
    tool_limit: int = 20

    @property
    def reserve(self) -> int:
        return self.response_tokens + max(512, min(2048, self.context_tokens // 10)) + 512

    def should_close(self, input_tokens: int) -> bool:
        return self.context_tokens - input_tokens < self.reserve


@dataclass
class Evidence:
    tool: str
    arguments: dict[str, Any]
    rows: list[str]
    source: str
    kind: str = 'measurement'

    @property
    def signature(self) -> str:
        return json.dumps([self.tool, self.arguments, self.source], ensure_ascii=False, sort_keys=True)


@dataclass
class AnalysisState:
    goal: str
    context_text: str
    mode: str = 'L0'
    evidence: list[Evidence] = field(default_factory=list)
    failures: dict[str, int] = field(default_factory=dict)
    attempts: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    report: str = ''
    coverage: list[dict[str, Any]] = field(default_factory=list)
    deliveries: list[str] = field(default_factory=list)
    status: str = 'running'
    reason: str = ''
    requests: int = 0
    planning_rounds: int = 0
    tool_attempts: int = 0
    stagnant: int = 0
    last_progress: int = 0
    direction: str = ''
    visible_prompt: str = ''
    continuation: bool = False
    continuation_mode: str = ''
    can_continue: bool = False
    audio_sent: bool = False
    audio_received: bool = False
    audio_report_completed: bool = False
    audio_observations: list[dict[str, Any]] = field(default_factory=list)
    previous_report: str = ''
    previous_coverage: list[dict[str, Any]] = field(default_factory=list)
    dialogue_context: list[dict[str, str]] = field(default_factory=list)
    budget: Budget = field(default_factory=Budget)
    metrics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.deliveries:
            # Stable original delivery labels, passed verbatim to report validation.
            import re
            self.deliveries = [s.strip() for s in re.split(r'[\n；;]+', self.goal) if s.strip()] or [self.goal]

    def event(self, mode: str, reason: str) -> None:
        self.mode = mode
        self.events.append({'mode': mode, 'reason': reason})

    def failed(self, problem: str, reason: str, *, permanent: bool = False) -> None:
        self.failures[problem] = self.failures.get(problem, 0) + 1
        if permanent or self.failures[problem] >= 2:
            self.reason = reason
            raise BranchExit(reason)
        self.event('L1', reason + '；允许一次有区别的纠正')

    def add_evidence(self, evidence: Evidence) -> bool:
        if evidence.signature in {e.signature for e in self.evidence}:
            return False
        self.evidence.append(evidence)
        return True

    def finish_round(self) -> None:
        progress = len(self.evidence)
        self.stagnant = self.stagnant + 1 if progress == self.last_progress else 0
        self.last_progress = progress
        if self.stagnant >= 2:
            raise BranchExit('连续两轮没有新增有效证据，停止当前执行分支')

    def continued(self, direction: str, *, mode: str = '') -> AnalysisState:
        if not mode:
            import re
            mode = 'L4' if '一般' in direction else ('L3' if re.search(r'(直接.*(?:音频|录音|听)|原始(?:音频|录音)|听感)', direction) else 'L2')
        if mode not in {'L2', 'L3', 'L4'}:
            raise ValueError('继续分析需要明确的 L2/L3/L4 模式')
        state = AnalysisState(self.goal, self.context_text, evidence=copy.deepcopy(self.evidence),
                              failures=dict(self.failures), deliveries=list(self.deliveries),
                              dialogue_context=copy.deepcopy(self.dialogue_context),
                              audio_observations=copy.deepcopy(self.audio_observations),
                              previous_report=self.report, previous_coverage=copy.deepcopy(self.coverage),
                              reason=self.reason, continuation_mode=mode,
                              budget=copy.deepcopy(self.budget), direction=direction, continuation=True)
        state.visible_prompt = ('继续分析原始任务：' + self.goal + '\n沿用原目标材料和成功测量，重点：'
                                + direction + '。仅补充必要分析，交代新增证据与缺口。')
        state.events = [{'mode':'continue', 'reason':state.visible_prompt}]
        return state

    def fallback_report(self) -> str:
        rows = [f'原始目标：{self.goal}', '本轮仅交付阶段记录，目标分析尚未完成。']
        if self.evidence:
            rows.append('已取得的证据：')
            rows.extend(f'- {e.tool}（来源：{e.source}）：' + '；'.join(e.rows) for e in self.evidence)
        rows.append('缺口与影响：' + (self.reason or '模型未返回可验证的目标解释')
                    + '。现有记录不能据此确定录音的具体发音缺陷。')
        rows.append('可继续：沿用这些证据补充目标解释；精确数值需要相应测量，听感需要实际音频输入。')
        self.coverage = [{'item':item, 'status':'partial' if self.evidence else 'missing',
                          'explanation':'模型报告未完成，已保存现有证据与诊断'} for item in self.deliveries]
        return '\n\n'.join(rows)
