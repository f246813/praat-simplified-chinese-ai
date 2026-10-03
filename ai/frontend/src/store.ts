import { useSyncExternalStore } from 'react';
import { activeTask, readOnly, type Attachment, type Bootstrap, type HostEvent, type Message, type Rpc, type Session, type Settings, type Task } from './types';
export interface State { boot?: Bootstrap; sessions: Session[]; messages: Record<string, Message[]>; tasks: Record<string, Task>; selected?: string; loading: Record<string, boolean>; submitting: Record<string, boolean>; error?: string; connected: boolean }
export function applyEvent(state: State, event: HostEvent): State {
  const {sessionId, taskId, payload} = event;
  // Never infer attribution from the selected UI thread.
  const existing = state.tasks[taskId];
  if (existing && existing.sessionId !== sessionId) return state;
  if (event.type === 'task') {
    const task = payload as Task;
    if (task.id !== taskId || task.sessionId !== sessionId) return state;
    return {...state, tasks: {...state.tasks, [task.id]: task}};
  }
  const messages = [...(state.messages[sessionId] || [])];
  const p = payload as {messageId: string; text: string; activity: NonNullable<Message['activities']>[number]};
  const id = event.type === 'message' ? (payload as Message).id : p.messageId;
  let index = messages.findIndex(m => m.id === id);
  if (index !== -1 && messages[index].taskId && messages[index].taskId !== taskId) return state;
  if (event.type === 'message') {
    const message = payload as Message;
    if (message.taskId && message.taskId !== taskId) return state;
    if (index === -1) messages.push({...message, taskId});
    else messages[index] = {...message, taskId};
  } else {
    if (index === -1) { index = messages.length; messages.push({id, role: 'assistant', content: '', taskId, status: 'running'}); }
    const message = messages[index];
    if (event.type === 'delta') messages[index] = {...message, content: message.content + p.text};
    else if (event.type === 'activity') {
      const activities = [...(message.activities || [])];
      const ai = activities.findIndex(a => a.id === p.activity.id);
      if (ai === -1) activities.push(p.activity); else activities[ai] = p.activity;
      messages[index] = {...message, activities};
    }
  }
  return {...state, messages: {...state.messages, [sessionId]: messages}};
}
export const sortSessions = (sessions: Session[]) => [...sessions].sort((a, b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)) || Number(readOnly(a)) - Number(readOnly(b)) || b.updated.localeCompare(a.updated));
export class ChatStore {
  private state: State = {sessions: [], messages: {}, tasks: {}, loading: {}, submitting: {}, connected: false};
  private listeners = new Set<() => void>();
  private cursor = 0;
  private journal: HostEvent[] = [];
  private fetching = new Map<string, Promise<void>>();
  private snapshotStreams = new Set<string>();
  private watermarks = new Map<string, number>();
  private pinRevisions = new Map<string, number>();
  private stopped = true;
  private timer?: ReturnType<typeof setTimeout>;
  private views = new Map<string, {draft?: string; scroll?: number}>();
  private viewTimers = new Map<string, ReturnType<typeof setTimeout>>();
  private viewChains = new Map<string, Promise<void>>();
  readonly attachments = new Map<string, Attachment[]>(); // transient metadata only; bytes stay in host
  constructor(readonly rpc: Rpc) {}
  getSnapshot = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private update(next: State) { this.state = next; this.listeners.forEach(l => l()); }
  report = (error: unknown) => this.update({...this.state, error: error instanceof Error ? error.message : String(error)});
  clearError = () => this.update({...this.state, error: undefined});
  async initialize() {
    const revisions = new Map(this.pinRevisions);
    const boot = await this.rpc('bootstrap', {});
    const local = new Map(this.state.sessions.map(s => [s.id, s]));
    this.update({...this.state, boot, connected: true, sessions: sortSessions(boot.sessions.map(s => ({...s, ...this.views.get(s.id), ...(local.has(s.id) ? {draft: local.get(s.id)!.draft, scroll: local.get(s.id)!.scroll} : {}), ...(revisions.get(s.id) !== this.pinRevisions.get(s.id) ? {pinned: local.get(s.id)?.pinned} : {})}))), tasks: Object.fromEntries(boot.tasks.map(t => [t.id, t]))});
    if (!this.state.selected || !boot.sessions.some(s => s.id === this.state.selected)) {
      this.update({...this.state, selected: boot.sessions[0]?.id});
    }
    if (this.state.selected) await this.load(this.state.selected);
  }
  async load(id: string) {
    if (this.fetching.has(id)) return this.fetching.get(id);
    const start = this.cursor;
    const pinRevision = this.pinRevisions.get(id);
    this.update({...this.state, loading: {...this.state.loading, [id]: true}});
    const job = (async () => {
      try {
        const result = await this.rpc('sessions.get', {sessionId: id});
        const local = this.state.sessions.find(s => s.id === id);
        const watermark = result.cursor;
        if (watermark !== undefined) this.watermarks.set(id, watermark);
        else if (this.running(id) || result.messages.some(m => m.status === 'running')) this.snapshotStreams.add(id);
        let next = {...this.state, sessions: sortSessions(this.state.sessions.map(s => s.id === id ? {...result.session, ...(pinRevision !== this.pinRevisions.get(id) ? {pinned: s.pinned} : {}), draft: local?.draft ?? result.session.draft, scroll: local?.scroll ?? result.session.scroll} : s)), messages: {...this.state.messages, [id]: result.messages}};
        // Production snapshots and their event watermark are captured atomically.
        // Only replay later events; old message creation must not erase live text.
        // Legacy fixtures without a watermark retain invalidation-based reconciliation.
        for (const e of this.journal) if (e.seq > (watermark ?? start) && e.sessionId === id && (watermark !== undefined || e.type !== 'delta')) next = applyEvent(next, e);
        this.update(next);
      } finally {
        this.fetching.delete(id);
        this.update({...this.state, loading: {...this.state.loading, [id]: false}});
      }
    })();
    this.fetching.set(id, job); return job;
  }
  async select(id: string) {
    const old = this.state.selected;
    if (old) this.flushView(old);
    this.update({...this.state, selected: id});
    await this.load(id);
  }
  async create() {
    const session = await this.rpc('sessions.create', {});
    this.update({...this.state, sessions: sortSessions([session, ...this.state.sessions]), messages: {...this.state.messages, [session.id]: []}});
    await this.select(session.id);
  }
  async rename(id: string, title: string) {
    const session = this.state.sessions.find(s => s.id === id);
    if (!session || readOnly(session)) throw new Error('旧会话只读，不能重命名');
    const value = title.trim(); if (!value) throw new Error('请输入会话名称');
    await this.rpc('sessions.rename', {sessionId: id, title: value});
    this.update({...this.state, sessions: this.state.sessions.map(s => s.id === id ? {...s, title: value} : s)});
  }
  async pin(id: string, pinned: boolean) {
    const current = this.state.sessions.find(s => s.id === id);
    if (!current || readOnly(current)) throw new Error('旧会话只读，不能置顶');
    const result = await this.rpc('sessions.pin', {sessionId: id, pinned});
    this.pinRevisions.set(id, (this.pinRevisions.get(id) || 0) + 1);
    // Authoritative metadata only; never replace local draft, reading position or messages.
    this.update({...this.state, sessions: sortSessions(this.state.sessions.map(s => s.id === id ? {...s, pinned: result.pinned} : s))});
  }
  async delete(id: string) {
    const session = this.state.sessions.find(s => s.id === id);
    if (!session || readOnly(session) || this.running(id) || this.state.submitting[id]) throw new Error('只读或运行中的会话不能删除');
    await this.rpc('sessions.delete', {sessionId: id});
    clearTimeout(this.viewTimers.get(id)); this.views.delete(id); this.attachments.delete(id);
    const messages = {...this.state.messages}; delete messages[id];
    const sessions = this.state.sessions.filter(s => s.id !== id);
    this.update({...this.state, messages, sessions, selected: this.state.selected === id ? sessions[0]?.id : this.state.selected});
    if (this.state.selected) await this.load(this.state.selected);
  }
  running(id: string) { return Object.values(this.state.tasks).find(t => t.sessionId === id && activeTask(t)); }
  view(id: string, patch: {draft?: string; scroll?: number}) {
    const session = this.state.sessions.find(s => s.id === id);
    if (!session) return;
    if (readOnly(session)) {
      if (patch.scroll !== undefined) this.update({...this.state, sessions: this.state.sessions.map(s => s.id === id ? {...s, scroll: patch.scroll!} : s)});
      return; // Legacy database stays read-only, including viewing metadata.
    }
    this.views.set(id, {...this.views.get(id), ...patch});
    this.update({...this.state, sessions: this.state.sessions.map(s => s.id === id ? {...s, ...patch} : s)});
    clearTimeout(this.viewTimers.get(id));
    this.viewTimers.set(id, setTimeout(() => this.flushView(id), 450));
  }
  flushView(id: string) {
    clearTimeout(this.viewTimers.get(id));
    const patch = this.views.get(id); if (!patch) return;
    this.views.delete(id);
    const chain = (this.viewChains.get(id) || Promise.resolve()).then(async () => { await this.rpc('sessions.view', {sessionId: id, ...patch}); }).catch(this.report);
    this.viewChains.set(id, chain);
  }
  async submit(id: string, text: string, attachmentIds: string[]) {
    const session = this.state.sessions.find(s => s.id === id);
    if (!session || readOnly(session)) throw new Error('旧记录只能查看，请新建会话');
    if (this.running(id) || this.state.submitting[id]) throw new Error('本会话任务尚未结束；可以在其他会话继续工作');
    if (!text.trim() && !attachmentIds.length) return;
    this.update({...this.state, submitting: {...this.state.submitting, [id]: true}});
    try {
      const task = await this.rpc('tasks.submit', {sessionId: id, text, attachmentIds});
      // A terminal event can arrive before the submit RPC resolves.
      const current = this.state.tasks[task.id];
      this.update({...this.state, tasks: {...this.state.tasks, [task.id]: current || task}});
      this.attachments.delete(id); this.view(id, {draft: ''});
      await this.load(id);
    } catch (e) {
      this.view(id, {draft: text});
      this.report(new Error(`${e instanceof Error ? e.message : String(e)}。未自动重试：请先刷新核对任务及投递状态。`));
      throw e;
    } finally { this.update({...this.state, submitting: {...this.state.submitting, [id]: false}}); }
  }
  async cancel(id: string) { const task = this.running(id); if (task) await this.rpc('tasks.cancel', {taskId: task.id}); }
  async save(settings: Partial<Settings>) {
    const result = await this.rpc('settings.save', {settings});
    this.update({...this.state, boot: this.state.boot ? {...this.state.boot, settings: result} : undefined}); return result;
  }
  start() { if (!this.stopped) return; this.stopped = false; void this.poll(); }
  stop() { this.stopped = true; clearTimeout(this.timer); for (const id of this.views.keys()) this.flushView(id); }
  async pollOnce() {
    const result = await this.rpc('events.poll', {after: this.cursor});
    if (result.reset) {
      this.cursor = result.cursor; this.journal = []; this.watermarks.clear(); this.snapshotStreams.clear();
      await this.initialize();
      for (const id of Object.keys(this.state.messages)) if (id !== this.state.selected && this.state.sessions.some(s => s.id === id)) await this.load(id);
      return;
    }
    const finished = new Set<string>(); const dirtyStreams = new Set<string>();
    let state = this.state;
    for (const event of result.events) {
      if (event.seq <= this.cursor) continue;
      if (event.type !== 'task' && event.seq <= (this.watermarks.get(event.sessionId) ?? -1)) continue;
      // Contract v1 snapshots have no cursor watermark. Once a live stream was
      // snapshotted, use delta events as invalidations rather than double-appending
      // bytes already present in that snapshot. Fetch once per polling batch.
      if (event.type === 'delta' && this.snapshotStreams.has(event.sessionId)) dirtyStreams.add(event.sessionId);
      else state = applyEvent(state, event);
      this.journal.push(event);
      if (event.type === 'task' && !activeTask(event.payload as Task)) finished.add(event.sessionId);
    }
    this.cursor = result.cursor;
    this.journal = this.journal.slice(-2000);
    this.update({...state, connected: true});
    for (const id of new Set([...dirtyStreams, ...finished])) if (this.state.messages[id] && this.state.sessions.some(s => s.id === id)) {
      await this.load(id);
      if (finished.has(id) && !this.running(id)) this.snapshotStreams.delete(id);
    }
  }
  private async poll() {
    try { await this.pollOnce(); } catch (e) { this.update({...this.state, connected: false}); this.report(e); }
    if (!this.stopped) this.timer = setTimeout(() => void this.poll(), 220);
  }
}
export const useChatState = (store: ChatStore) => useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
