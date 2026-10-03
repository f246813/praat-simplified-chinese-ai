"""UI-free turn adapter. The host owns cloud permission and local model leases.

Bridge files still belong to chat's native runtime, not to runtime_directory
(which owns task materials). Never change chat globals or process environment.
All modern executors share one dispatcher gate; unknown delivery is restart-only.
Legacy Tk dispatchers in another process do not participate in this gate.
"""
from __future__ import annotations

import copy
import json
import re
import threading
import time
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from types import FunctionType
from typing import Callable

from . import chat, delivery, model_capabilities as caps, qwen, tools
from .cloud_agent import run_cloud_turn, run_dialogue_turn
from .cloud_runtime import CloudRuntime
from .cloud_workflow import (explicit_range, explicit_wav, object_context_text,
                             renamed_context, target_context)
from .config import AppConfig, api_is_active
from .dialogue_policy import dialogue_kind, direct_measurement, force_high
from .escape_policy import AnalysisState, BranchExit, Budget, Evidence
from .materials import TaskMaterials
from .process import identities_match, process_identity

PRAAT_LOCK = threading.RLock()
_POISON = ''  # Never cleared by a new task/executor or close().
_IDENTITY_PREFIX = '# modern-process='
_MAX_TEXT_BYTES = 1024 * 1024


def _gate(cancel: threading.Event) -> None:
    if _POISON:
        raise BranchExit('Praat dispatcher blocked until desktop restart/reconciliation: ' + _POISON)
    if cancel.is_set():
        raise BranchExit('已取消，未投递 Praat 操作')


def _send(executable: str, pid: int, script: str, cancel: threading.Event):
    """Caller owns PRAAT_LOCK, including subsequent result reads."""
    global _POISON
    facts: list[str] = []
    try:
        ok, note = chat._send_script(executable, script, process_id=pid,
                                     cancel=cancel, outcome=facts)
    except Exception as error:
        note = str(error)
        ok = False
        # An exception after handoff (or without a declared fact) is ambiguous.
    fact = delivery.DELIVERED if ok else (
        delivery.NOT_DELIVERED if facts and facts[-1] == delivery.NOT_DELIVERED
        else delivery.EXECUTION_UNKNOWN)
    if fact == delivery.EXECUTION_UNKNOWN:
        _POISON = note or 'completion not confirmed'
    if not ok:
        return False, [], note, fact
    try:
        failure = chat._read_failure()
        return not bool(failure), chat._read_results(), failure, fact
    except OSError as error:
        return False, [], '完成已确认，但结果读取失败：' + str(error), fact


def _refresh(executable: str, pid: int, cancel: threading.Event, facts=None) -> str:
    _gate(cancel)
    # refresh_object_context's old-PID shortcut and bool-only failure lose
    # delivery facts. Use its real ping, explicitly addressed, through our gate.
    ok, _, note, fact = _send(executable, pid, chat.context_ping_script(), cancel)
    if facts is not None:
        facts.append(fact)
    if not ok:
        error = BranchExit('Praat 状态无法确认；未使用旧快照：' + note)
        error.execution = delivery.EXECUTION_UNKNOWN if _POISON else delivery.NOT_DELIVERED
        raise error
    text = chat.object_context()
    if not text.startswith('id\tclass\tname\tselected'):
        raise BranchExit('没有读到完整对象快照；未使用旧快照')
    marker = chat.context_pid(text)
    if marker and marker != pid:
        raise BranchExit('对象快照来自不同 Praat 进程')
    # A successful explicitly addressed ping validates legacy markerless output.
    if not marker:
        text = text.rstrip() + f'\n# praat-pid={pid}\n'
    return text


def _snapshot_wav(materials: TaskMaterials, path: Path, selection):
    # Bound source bytes before TaskMaterials decodes/allocates PCM frames.
    if not path.is_file() or path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError('WAV 源文件必须为真实文件且不超过 20 MiB')
    materials.snapshot_wav(path, selection)


class _Dispatcher:
    def __init__(self, target, cancel, activity, runtime_directory):
        self.target, self.cancel, self.activity = target, cancel, activity
        self.runtime_directory = runtime_directory
        self.context = tools.ToolContext(tools.parse_object_context(target),
                                         chat.result_path(), chat.state_path())
        self.pid = chat.context_pid(target)
        self.identity = None
        for line in target.splitlines():
            if line.startswith(_IDENTITY_PREFIX):
                self.identity = json.loads(line[len(_IDENTITY_PREFIX):])
        self.last_execution = ''
        self.attempts: list[dict] = []
        self.evidence: list[Evidence] = []
        self.segment_facts: list[str] = []
        self.refresh_facts: list[str] = []

    def ensure(self):
        _gate(self.cancel)
        executable = chat.praat_executable()
        ids = chat.praat_process_ids(executable) if executable else []
        if not self.pid or not self.identity:
            raise BranchExit('没有经过验证的原 Praat 目标，未替换为当前选择')
        if self.pid not in (ids or []) or not identities_match(self.identity, process_identity(self.pid)):
            raise BranchExit('原 Praat 进程/会话身份已改变，未使用新实例')
        if chat.sendpraat.send_mode() == chat.sendpraat.ARGV_MODE:
            raise BranchExit('argv 投递不能保证原进程绑定，未执行')
        fresh = _refresh(executable, self.pid, self.cancel, self.refresh_facts)
        current = {row.id: row for row in tools.parse_object_context(fresh)}
        # Conservative: validate every retained row, not just selected rows.
        # Explicit references to unselected originals are equally identity-bound.
        for row in self.context.objects:
            now = current.get(row.id)
            if now is None or (now.class_name, now.name) != (row.class_name, row.name):
                raise BranchExit(f'原对象 {row.id} 已消失或身份改变，未替换为当前选择')
        retained = {row.id for row in self.context.objects}
        self.context = replace(self.context, objects=self.context.objects + tuple(
            replace(row, selected=False) for row in current.values() if row.id not in retained))
        return executable

    def execute(self, script):
        with PRAAT_LOCK:
            try:
                _gate(self.cancel)
                # Within one LocalTool segment do not ping between sends: pings
                # clear the shared results, and intermediate objects may be temporary.
                executable = chat.praat_executable()
                if not identities_match(self.identity or {}, process_identity(self.pid)):
                    raise BranchExit('原 Praat 进程身份已改变')
            except BranchExit as error:
                fact = delivery.EXECUTION_BLOCKED if _POISON else delivery.NOT_DELIVERED
                self.segment_facts.append(fact)
                self.last_execution = delivery.EXECUTION_UNKNOWN if delivery.EXECUTION_UNKNOWN in self.segment_facts else fact
                return False, [], str(error)
            ok, rows, note, fact = _send(executable, self.pid, script, self.cancel)
            self.segment_facts.append(fact)
            self.last_execution = delivery.EXECUTION_UNKNOWN if delivery.EXECUTION_UNKNOWN in self.segment_facts else fact
            return ok, rows, note

    def action(self, action, index):
        global _POISON
        with PRAAT_LOCK:
            self.last_execution = ''
            self.segment_facts = []
            self.refresh_facts = []
            name, args = str(action.get('tool', '')), action.get('arguments') or {}
            try:
                executable = self.ensure()
                environment = tools.LocalEnvironment(self.execute, executable,
                    self.runtime_directory, self.cancel.is_set)
                # Lock spans render/select/every LocalTool send/read, not just sends.
                step = chat._execute_action(action, self.context, self.execute, index, environment)
                step.execution = self.last_execution
                if self.last_execution == delivery.EXECUTION_UNKNOWN:
                    step.ok, step.results = False, []
                    step.observation += '；执行状态不明：' + _POISON
                if step.ok and name == 'rename_object':
                    row = self.context.resolve_object(args.get('object'))
                    try:
                        fresh = _refresh(executable, self.pid, self.cancel, self.refresh_facts)
                        self.context = renamed_context(self.context, fresh, row.id)
                        self.target = object_context_text(self.context.objects, self.target)
                    except (BranchExit, tools.ToolError, OSError) as error:
                        _POISON = 'rename identity cannot be reconciled: ' + str(error)
                        # The rename's delivered fact remains delivered.
                        step.note = str(error)
            except BranchExit as error:
                step = chat.AgentStep(index, name, dict(args) if isinstance(args, dict) else {},
                                      False, str(error), execution=getattr(error, 'execution',
                                      delivery.EXECUTION_BLOCKED if _POISON else delivery.NOT_DELIVERED))
            status = 'success' if step.ok else (
                'unknown' if step.execution == delivery.EXECUTION_UNKNOWN else
                'not_executed' if step.execution in {delivery.NOT_DELIVERED, delivery.EXECUTION_BLOCKED}
                or not step.script else 'failed')
            record = {'tool':step.tool, 'arguments':step.arguments, 'status':status,
                      'execution':step.execution, 'reason':step.observation,
                      'script':step.script, 'rows':list(step.results), 'deliveries':list(self.segment_facts)}
            record['refresh_deliveries'] = list(self.refresh_facts)
            if step.note:
                record['note'] = step.note
            self.attempts.append(record)
            if step.ok and step.results:
                self.evidence.append(Evidence(step.tool, step.arguments, list(step.results), self.target,
                    'operation' if tools.is_mutating(step.tool) else 'measurement'))
            self.activity('tool', name=step.tool, args=step.arguments, result=list(step.results),
                          text=step.observation, status=status, execution=step.execution)
            return step

    def cloud_action(self, name, arguments, index):
        return self.action({'tool':name, 'arguments':arguments}, index)

    def refresh_context(self):
        with PRAAT_LOCK:
            try:
                self.ensure()
            except BranchExit as error:
                raise tools.ToolError(str(error)) from error
            self.target = object_context_text(self.context.objects, self.target)
            return self.target


def _rebind(function, namespace):
    """Task-private chat hooks without monkeypatching its process-global module.

    run_turn currently has no action callback. Rebind only its two pure function
    globals so the existing constraints/planners run unchanged, with atomic
    actions. Remove this shim if run_turn gains an execute_action parameter.
    """
    bound = FunctionType(function.__code__, namespace, function.__name__,
                         function.__defaults__, function.__closure__)
    bound.__kwdefaults__ = function.__kwdefaults__
    return bound


class ModernExecutor:
    def __init__(self, runtime_directory: Path, config_path: Path):
        self.runtime_directory, self.config_path = Path(runtime_directory), Path(config_path)
        self._guard = threading.Lock()
        self._closed = False
        self._active: set[threading.Event] = set()

    def capture_target(self, text: str) -> str:
        with self._guard:
            if self._closed:
                raise RuntimeError('Modern executor is closed')
        if dialogue_kind(text) is not None:
            return ''  # No process lookup, Tk window, model call or queue.
        with PRAAT_LOCK:
            _gate(threading.Event())
            executable = chat.praat_executable()
            ids = chat.praat_process_ids(executable) if executable else []
            if not ids:
                return ''  # Files/concepts can still be analysed; no stale fallback.
            if len(ids) != 1:
                raise BranchExit('多个 Praat 实例，原目标进程不明确')
            pid = ids[0]
            identity = process_identity(pid)
            if not identity:
                raise BranchExit('原 Praat 进程身份无法验证')
            if chat.sendpraat.send_mode() == chat.sendpraat.ARGV_MODE:
                raise BranchExit('argv 投递不能保证目标进程绑定')
            fresh = _refresh(executable, pid, threading.Event())
            if not identities_match(identity, process_identity(pid)):
                raise BranchExit('捕获目标时 Praat 进程身份改变')
            target = target_context(text, chat._request_context(fresh, text))
            return target.rstrip() + '\n' + _IDENTITY_PREFIX + json.dumps(identity) + '\n'

    def close(self):
        with self._guard:
            self._closed = True
            for cancel in self._active:
                cancel.set()
        # Task finally blocks close their own clients/materials; never reset poison.

    def run(self, *, config: AppConfig, text: str, history: list[dict], target: str,
            cancel: threading.Event, emit: Callable[[str, dict], None],
            attachments: list[dict] = []) -> dict:
        with self._guard:
            if self._closed:
                raise RuntimeError('Modern executor is closed')
            self._active.add(cancel)
        config = copy.deepcopy(config)  # Never mutate the externally prepared snapshot.
        expected_identity = caps.config_identity(config.api)
        started = time.monotonic()
        activities: list[dict] = []
        deltas: list[str] = []
        materials = runtime = dispatcher = None
        state = AnalysisState(text, target, budget=Budget(config.api.max_context_tokens,
                                                        config.api.plan_max_tokens))
        state.dialogue_context = copy.deepcopy(history)

        def activity(kind='progress', **payload):
            item = {'id':uuid.uuid4().hex, 'type':kind, **payload}
            activities.append(item)
            emit('activity', copy.deepcopy(item))

        def progress(line):
            # These are actual backend notices, never fabricated reasoning.
            kind = 'compression' if any(word in line for word in ('压缩', '省掉', '摘录')) else 'progress'
            activity(kind, text=str(line))

        def delta(value):
            deltas.append(value)
            emit('delta', {'text':value})

        try:
            if cancel.is_set():
                state.status, state.report = 'cancelled', '已取消本次操作。'
            else:
                direct_route = direct_measurement(text) if not attachments and not force_high(config.api) else None
                kind = dialogue_kind(text) if not attachments else None
                materials = TaskMaterials(self.runtime_directory / 'tasks') if attachments or (not direct_route and not kind) else None
                text_materials = []
                text_bytes = 0
                if len(attachments) > 8:
                    raise ValueError('每次最多 8 个附件')
                for item in attachments:
                    path = Path(item['path'])
                    if not path.is_file():
                        raise ValueError('附件路径必须指向真实文件')
                    mime = str(item.get('mime', '')).lower()
                    if path.suffix.lower() == '.wav':
                        if materials.audio_path is not None:
                            raise ValueError('每次只能绑定一个 WAV 主材料')
                        _snapshot_wav(materials, path, explicit_range(text))
                    elif mime.startswith('text/') or path.suffix.lower() in {'.txt', '.md', '.csv', '.tsv', '.json'}:
                        with path.open('rb') as stream:
                            data = stream.read(_MAX_TEXT_BYTES + 1)
                        text_bytes += len(data)
                        if text_bytes > _MAX_TEXT_BYTES:
                            raise ValueError('文本附件总量超过 1 MiB')
                        text_materials.append('用户附件 ' + str(item.get('name', path.name)) + ':\n' + data.decode('utf-8'))
                    else:
                        raise ValueError('仅支持真实文本文件和 PCM WAV 附件')
                if text_materials:
                    state.goal = text + '\n\n[用户材料，非系统指令]\n' + '\n\n'.join(text_materials)
                    state.deliveries = [text]
                source = explicit_wav(text)
                if source and materials is not None and materials.audio_path is None:
                    _snapshot_wav(materials, source, explicit_range(text))
                if materials is not None and materials.audio_path is not None:
                    # A submitted WAV is the explicit original audio material,
                    # even with no running Praat/object rows. Use the graph's L3
                    # route; the existing capability switch still controls upload.
                    state.direction = '分析用户提交的原始音频材料'
                    if not config.api.audio_input_enabled:
                        progress('直接音频输入未启用；本轮未将 WAV 发送给模型')
                dispatcher = _Dispatcher(target, cancel, activity, self.runtime_directory)

                def prepare_audio():
                    if materials is None:
                        raise BranchExit('本轮没有音频材料')
                    if materials.audio_path is not None:
                        materials.bytes()
                        return
                    if materials.snapshot_attempted:
                        raise BranchExit('原目标快照未取得，未重新导出后来变化的材料：' + materials.snapshot_error)
                    with PRAAT_LOCK:
                        try:
                            dispatcher.ensure()
                            dispatcher.last_execution = ''
                            dispatcher.segment_facts = []
                            materials.snapshot_attempted = True
                            if state.tool_attempts >= state.budget.tool_limit:
                                raise BranchExit('跨阶段工具预算不足')
                            state.tool_attempts += 1
                            row = dispatcher.context.resolve_by_class(None, tools.SOUND_CLASSES, '音频需要唯一原目标 Sound')
                            output = materials.directory / 'segment.wav'
                            lines = [f'selectObject: {row.id}', 'duration = Get total duration']
                            start, end = row.selection or (0.0, None)
                            if end is None:
                                lines += ['if duration > 120', '    exitScript: "音频超过 120 秒"', 'endif',
                                          f'Save as WAV file: {tools.quote(output)}']
                            else:
                                if end - start > 120:
                                    raise BranchExit('原目标片段超过 120 秒')
                                lines += [f'Extract part: {start:.9f}, {end:.9f}, "rectangular", 1, "no"',
                                          f'Save as WAV file: {tools.quote(output)}', 'Remove', f'selectObject: {row.id}']
                            selected = [item.id for item in tools.parse_object_context(chat.object_context()) if item.selected]
                            if selected:
                                lines += [f'selectObject: {selected[0]}'] + [f'plusObject: {identifier}' for identifier in selected[1:]]
                            script = tools._assemble(lines, dispatcher.context)
                            ok, rows, reason = dispatcher.execute(script)
                            status = 'success' if ok else ('unknown' if dispatcher.last_execution == delivery.EXECUTION_UNKNOWN
                                else 'not_executed' if dispatcher.last_execution in {delivery.NOT_DELIVERED, delivery.EXECUTION_BLOCKED} else 'failed')
                            record = {'tool':'export_original_audio', 'arguments':{}, 'status':status,
                                      'execution':dispatcher.last_execution, 'reason':reason, 'script':script, 'rows':rows,
                                      'deliveries':list(dispatcher.segment_facts)}
                            dispatcher.attempts.append(record)
                            activity('tool', name=record['tool'], result=rows, status=record['status'],
                                     execution=record['execution'], text=reason)
                            if not ok or not output.is_file():
                                raise BranchExit('原目标音频导出失败：' + reason)
                            materials.audio_path, materials.source, materials.range = output, row.label, row.selection
                            materials.source_kind = 'praat'
                            materials.bytes()
                        except (BranchExit, tools.ToolError, OSError, ValueError) as error:
                            materials.snapshot_attempted = True
                            materials.snapshot_error = str(error)
                            raise

                def correct_audio(reason):
                    saved = caps.correct_audio_setting(self.config_path, expected_identity, reason)
                    progress('当前 API 路径音频能力纠正已保存' if saved else '配置身份已改变，音频纠正仅用于本轮')

                def cloud_action(name, arguments, index):
                    step = dispatcher.cloud_action(name, arguments, index)
                    state.context_text = dispatcher.target
                    return step

                if api_is_active(config):
                    direct = direct_route
                    if direct:
                        step = dispatcher.cloud_action(direct['tool'], direct['arguments'], 1)
                        state.evidence = dispatcher.evidence
                        state.report = '\n'.join(step.results) if step.ok else '时长测量未完成：' + step.observation
                        state.status = 'complete' if step.ok and step.results else 'partial'
                        state.metrics = {'requests':0, 'route':'direct_measurement'}
                    else:
                        runtime = CloudRuntime()  # Config/model/client is task-local.
                        if kind:
                            run_dialogue_turn(config, state, kind=kind, cancel=cancel,
                                              progress=progress, on_text=delta, runtime=runtime)
                        else:
                            # Capture original audio before model/network work or mutations.
                            if (materials is not None and materials.audio_path is None
                                    and config.api.audio_input_enabled
                                    and re.search(r'(分析|发音|录音|选区|声音|选中|基频|共振峰)', text)
                                    and any(row.selected and row.class_name in tools.SOUND_CLASSES
                                            for row in dispatcher.context.objects)):
                                try:
                                    prepare_audio()
                                    progress('已建立原目标的任务临时音频快照')
                                except (BranchExit, tools.ToolError, OSError, ValueError) as error:
                                    progress('原目标音频快照未取得：' + str(error))
                            run_cloud_turn(config, state, execute_action=cloud_action,
                                cancel=cancel, progress=progress, materials=materials,
                                prepare_audio=prepare_audio, correct_audio=correct_audio, runtime=runtime)
                else:
                    if materials is not None and materials.audio_path is not None:
                        raise BranchExit('本地 turn 适配器不支持 WAV 模型输入；未发送或伪造音频证据')
                    namespace = dict(chat.run_turn.__globals__)
                    namespace['_execute_action'] = lambda action, context, execute, index, environment=None: dispatcher.action(action, index)
                    namespace['_run_agent_turn'] = _rebind(chat._run_agent_turn, namespace)
                    run_turn = _rebind(chat.run_turn, namespace)
                    outcome = run_turn(qwen.QwenClient(config.qwen), user_text=state.goal,
                        context_text=target, history=copy.deepcopy(history), context=dispatcher.context,
                        execute=dispatcher.execute, on_progress=progress,
                        refresh_context=dispatcher.refresh_context, cancel=cancel)
                    state.report, state.status = outcome.reply, 'partial' if outcome.failure else 'complete'
                    state.evidence = dispatcher.evidence
                    for note in outcome.notes:
                        progress(note)
                    state.metrics = {'route':'local'}
        except Exception as error:
            state.reason = caps.safe_error(error, config.api.api_key)
            if config.qwen.api_key and config.qwen.api_key != 'EMPTY':
                state.reason = state.reason.replace(config.qwen.api_key, '[redacted]')
            state.report = ''.join(deltas) or ('本次任务未完成：' + state.reason)
            state.status = 'partial' if deltas or (dispatcher and dispatcher.evidence) else 'failed'
            if dispatcher and not state.evidence:
                state.evidence = dispatcher.evidence
        finally:
            for resource in (runtime, materials):
                if resource is not None:
                    try:
                        resource.close(wait=True) if resource is runtime else resource.close()
                    except Exception as error:
                        state.metrics.setdefault('cleanup_errors', []).append(caps.safe_error(error, config.api.api_key))
            with self._guard:
                self._active.discard(cancel)
        if cancel.is_set():
            state.status = 'cancelled'  # Does not change delivered/unknown facts.
            if deltas:
                state.report = ''.join(deltas)
        if state.coverage:
            state.report += '\n\n交付项状态：\n' + '\n'.join(
                '- ' + item['item'] + '：' + item['status'] + '。' + item['explanation'] for item in state.coverage)
        if not deltas and state.report:
            delta(state.report)
        state.metrics.setdefault('total_seconds', time.monotonic() - started)
        state.metrics.update(audio_input=state.audio_sent, audio_received=state.audio_received,
                             audio_report_completed=state.audio_report_completed)
        attempts = list(dispatcher.attempts) if dispatcher else []
        # Graph-only schema/cache/policy refusals never reached the dispatcher.
        for item in state.attempts:
            if item.get('status') == 'not_executed' and not any(
                    item.get('tool') == a['tool'] and item.get('arguments') == a['arguments']
                    and item.get('reason') == a['reason'] for a in attempts):
                attempts.append(item)
                activity('tool', name=item.get('tool'), args=item.get('arguments', {}),
                         text=item.get('reason', ''), status='not_executed', execution=item.get('execution', ''))
        return {'content':state.report, 'status':state.status, 'activities':activities,
                'evidence':[asdict(item) for item in state.evidence], 'attempts':attempts,
                'target':dispatcher.target if dispatcher else target, 'metrics':state.metrics,
                'audio_observations':copy.deepcopy(state.audio_observations)}
