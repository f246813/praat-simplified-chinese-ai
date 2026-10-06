"""Thin public Pydantic AI message adapter (Pi's append-only context boundary).

Reference: earendil-works/pi agent-loop.ts @28dcce2 (MIT). Protocol cleaning,
serialization and tool pairing are supplied by the locked SDK, not reimplemented.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from pydantic_ai.messages import (ModelMessagesTypeAdapter, ModelRequest, ModelResponse,
                                  SystemPromptPart, TextPart, UserPromptPart)


def native_history(history):
    result = []
    for item in history:
        text = str(item.get('content') or '')
        if item.get('status') in {'running', 'cancelled', 'interrupted', 'failed', 'partial'}:
            continue
        if item.get('role') == 'user':
            result.append(ModelRequest(parts=[UserPromptPart(text)]))
        elif item.get('role') == 'assistant':
            result.append(ModelResponse(parts=[TextPart(text)]))
        elif item.get('role') == 'system':
            result.append(ModelRequest(parts=[SystemPromptPart(text)]))
    return result


@dataclass
class PhaseContext:
    messages: list = field(default_factory=list)
    epoch: int = 0
    identity: str = ''
    loaded: set[str] = field(default_factory=set)
    projected: dict = field(default_factory=dict)
    formal_count: int = 0
    formal_hash: str = ''
    complete: bool = False
    archives: list = field(default_factory=list)
    calibration_start: int = 0

    def mark_formal(self, history):
        self.formal_count = len(history)
        self.formal_hash = self._formal_hash(history)

    @staticmethod
    def _formal_hash(history):
        return hashlib.sha256(json.dumps([{k: i[k] for k in ('role', 'content')} for i in history],
                                         ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def sync_formal(self, history):
        if not self.formal_hash:
            if not self.messages:
                self.messages = native_history(history)
        elif self._formal_hash(history[:self.formal_count]) == self.formal_hash:
            self.messages.extend(native_history(history[self.formal_count:]))
        else:
            self.messages = native_history(history)
            self.identity = ''
            self.epoch += 1
        self.mark_formal(history)

    def configure(self, system, identity='', baseline=None):
        key = hashlib.sha256((system + identity).encode()).hexdigest()
        if self.identity and self.identity != key:
            # Configuration changes use a formal baseline, never prior tools.
            self.messages = native_history(baseline or [])
            self.loaded.clear()
            self.projected.clear()
            self.epoch += 1
        self.identity = key
        if not any(isinstance(p, SystemPromptPart) for m in self.messages for p in m.parts):
            self.messages.insert(0, ModelRequest(parts=[SystemPromptPart(system)]))

    def append_guidance(self, key, text):
        if key not in self.loaded:
            self.messages.append(ModelRequest(parts=[UserPromptPart(text)]))
            self.loaded.add(key)

    def delta(self, values):
        """Append changed metadata only; original evidence remains in TaskState."""
        changed = {k: v for k, v in values.items() if self.projected.get(k) != v}
        for key in ('evidence', 'audio_observations'):
            previous, current = self.projected.get(key, []), values.get(key, [])
            if key in changed and previous and current[:len(previous)] == previous:
                changed[key] = current[len(previous):]
        self.projected.update(copy.deepcopy(values))
        return changed

    def payload(self):
        # Audio/attachments remain task-local: no expired bytes in SQLite/replay.
        if any(isinstance(p, UserPromptPart) and not isinstance(p.content, str)
               for m in self.messages for p in m.parts):
            return None
        return dict(protocol='pydantic-ai-2.52.0', epoch=self.epoch, identity=self.identity,
                    formal_count=self.formal_count, formal_hash=self.formal_hash,
                    calibration_start=self.calibration_start,
                    archives=[ModelMessagesTypeAdapter.dump_python(a, mode='json') for a in self.archives],
                    messages=ModelMessagesTypeAdapter.dump_python(self.messages, mode='json'))

    @classmethod
    def restore(cls, payload):
        if payload.get('protocol') != 'pydantic-ai-2.52.0':
            return None
        return cls(messages=ModelMessagesTypeAdapter.validate_python(payload['messages']),
                   epoch=payload['epoch'], identity=payload['identity'],
                   formal_count=payload.get('formal_count', 0), formal_hash=payload.get('formal_hash', ''),
                   calibration_start=payload.get('calibration_start', 0),
                   archives=[ModelMessagesTypeAdapter.validate_python(a) for a in payload.get('archives', [])])


def evidence_projection(records):
    """Full measurement values/provenance, compact delivery facts; no metrics/UI/scripts."""
    result, seen = [], set()
    for record in records:
        evidence = []
        for item in record.get('evidence', []):
            key = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if key not in seen:
                seen.add(key)
                evidence.append(item)
        attempts = [{k: item[k] for k in ('tool','arguments','status','execution','reason') if k in item}
                    for item in record.get('attempts', [])]
        # Empty dialogue turns contribute no new professional evidence.
        if evidence or attempts:
            result.append(dict(target=record.get('target', ''), evidence=evidence, attempts=attempts))
    return result
