import { createContext, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { AssistantRuntimeProvider, useExternalStoreRuntime, useAuiState, ThreadPrimitive, MessagePrimitive, type AssistantRuntime, type AttachmentAdapter, type ThreadMessageLike } from '@assistant-ui/react';
import { ArrowDown, AudioLines, Brain, CheckCircle2, CircleAlert, Copy, FileText, LoaderCircle, RefreshCw, Shield, Wrench } from 'lucide-react';
import { Markdown } from './Markdown';
import { Composer, AttachmentPreview, attachmentDescriptor } from './Composer';
import { importFile } from './bridge';
import { ChatStore, useChatState } from './store';
import { knownModel, readOnly, type Activity, type Message, type Preview, type Session } from './types';
import { IconButton, Json, statusLabel } from './ui';
const Context = createContext<{store: ChatStore; smooth: boolean}>(null!);
export function convertMessage(message: Message): ThreadMessageLike {
  const status = message.status === 'running' ? {type: 'running' as const} : message.status === 'failed' ? {type: 'incomplete' as const, reason: 'error' as const} : ['partial','cancelled','interrupted'].includes(message.status || '') ? {type: 'incomplete' as const, reason: 'cancelled' as const} : {type: 'complete' as const, reason: 'stop' as const};
  return {id: message.id, role: message.role, content: message.content, ...(message.role === 'assistant' ? {status} : {}), metadata: {custom: {host: message}}, ...(message.role === 'user' ? {attachments: message.attachments?.map(a => ({...attachmentDescriptor(a), status: {type: 'complete' as const}}))} : {})};
}
function ActivityCard({activity}: {activity: Activity}) {
  const {store} = useContext(Context);
  const tool = activity.type === 'tool'; const thinking = activity.type === 'thinking';
  const Icon = tool ? Wrench : thinking ? Brain : activity.type === 'compression' ? RefreshCw : LoaderCircle;
  if (thinking && !activity.text) return null;
  return <details className={`activity ${tool ? 'tool-card' : ''}`}><summary><Icon size={15}/><span>{tool ? activity.name || '工具执行' : thinking ? '模型思考' : activity.type === 'compression' ? '上下文压缩' : '执行进度'}</span><span className={`badge ${activity.status === 'failed' ? 'bad' : ''}`}>{statusLabel(activity.status)}</span></summary><div className="activity-body">{activity.execution && <p className="execution-fact"><Shield size={14}/>投递 / 执行事实：<strong>{activity.execution}</strong></p>}{activity.text && <Markdown text={activity.text} rpc={store.rpc} onError={store.report}/>} {activity.args !== undefined && <><h5>参数</h5><Json value={activity.args}/></>}{activity.result !== undefined && <><h5>结果 / 结构化证据</h5><Json value={activity.result}/></>}{tool && !activity.execution && <p className="muted">宿主未提供投递事实。成功或取消状态不等于已执行或撤销。</p>}</div></details>;
}
function MessageCard() {
  const {store, smooth} = useContext(Context); const m = useAuiState(s => s.message);
  const host = m.metadata.custom.host as Message | undefined;
  const text = host?.content ?? m.content.filter(p => p.type === 'text').map(p => p.text).join('');
  const [preview, setPreview] = useState<Preview>();
  const user = m.role === 'user';
  return <MessagePrimitive.Root className={`message ${user ? 'user' : 'assistant'}`} data-message-id={m.id}><div className={`avatar ${user ? 'user-avatar' : ''}`}>{user ? '你' : <AudioLines size={20}/>}</div><div className="message-content"><div className="message-label"><strong>{user ? '你' : '声学助手'}</strong>{host?.status && host.status !== 'complete' && <span className={`badge ${host.status === 'failed' ? 'bad' : ''}`}>{statusLabel(host.status)}</span>}</div>{host?.activities?.length ? <div className="activities">{host.activities.map(a => <ActivityCard key={a.id} activity={a}/>)}</div> : null}<Markdown text={text} rpc={store.rpc} onError={store.report} smooth={smooth && host?.status === 'running'}/>{host?.status === 'running' && !text && <div className="actual-running"><LoaderCircle size={15}/>任务运行中，等待后端内容…</div>}{host?.attachments?.length ? <div className="attachment-list">{host.attachments.map(a => <button className="attachment-chip" key={a.id} onClick={() => void store.rpc('attachments.preview', {attachmentId: a.id}).then(setPreview).catch(store.report)}><FileText size={14}/>{a.name}<small>{(a.size / 1024).toFixed(1)} KB</small></button>)}</div> : null}{text && <div className="message-actions"><IconButton label="复制消息" onClick={() => void navigator.clipboard.writeText(text).catch(store.report)}><Copy size={14}/></IconButton>{host?.taskId && <small>任务 {host.taskId}</small>}</div>}</div>{preview && <AttachmentPreview preview={preview} onClose={() => setPreview(undefined)}/>}</MessagePrimitive.Root>;
}
export function Chat({store, session, onSettings}: {store: ChatStore; session: Session; onSettings: () => void}) {
  const state = useChatState(store); const runtimeRef = useRef<AssistantRuntime>(null); const viewport = useRef<HTMLDivElement>(null);
  const initialScroll = useRef(session.scroll); const [restored, setRestored] = useState(false);
  const savedAttachments = useRef([...(store.attachments.get(session.id) || [])]);
  const boot = state.boot!; const modelConfig = boot.settings.api.enabled ? boot.settings.api : boot.settings.local;
  const unknownAuto = modelConfig.token_mode === 'auto' && !knownModel(boot.models, modelConfig);
  const attachmentsAdapter = useMemo<AttachmentAdapter>(() => ({
    accept: '*',
    add: async ({file}) => { const a = await importFile(store.rpc, file); return {...attachmentDescriptor(a), file, status: {type: 'requires-action', reason: 'composer-send'}}; },
    remove: async () => { /* Contract has no deletion RPC: detach only; storage remains host-owned. */ },
    send: async a => ({...a, file: undefined, content: [], status: {type: 'complete'}}),
  }), [store]);
  const runtime = useExternalStoreRuntime<Message>({
    messages: state.messages[session.id] || [], convertMessage,
    isRunning: Boolean(store.running(session.id)), isLoading: Boolean(state.loading[session.id]),
    isDisabled: readOnly(session), isSendDisabled: !state.connected || Boolean(state.submitting[session.id]) || unknownAuto,
    adapters: {attachments: attachmentsAdapter},
    onNew: async message => {
      const text = message.content.filter(p => p.type === 'text').map(p => p.text).join('');
      try { await store.submit(session.id, text, (message.attachments || []).map(a => a.id)); }
      catch (e) {
        const composer = runtimeRef.current?.thread.composer;
        composer?.setText(text);
        for (const a of message.attachments || []) if (!composer?.getState().attachments.some(current => current.id === a.id)) await composer?.addAttachment({id: a.id, type: a.type, name: a.name, contentType: a.contentType, content: []});
        throw e;
      }
    },
    onCancel: () => store.cancel(session.id).catch(store.report),
  });
  runtimeRef.current = runtime;
  useEffect(() => {
    const initialAttachments = savedAttachments.current;
    runtime.thread.composer.setText(session.draft || '');
    for (const a of initialAttachments) void runtime.thread.composer.addAttachment(attachmentDescriptor(a)).catch(store.report);
    let lastText = runtime.thread.composer.getState().text;
    const unsubscribe = runtime.thread.composer.subscribe(() => {
      const text = runtime.thread.composer.getState().text;
      if (text !== lastText && !store.getSnapshot().submitting[session.id]) { lastText = text; store.view(session.id, {draft: text}); }
    });
    return () => { unsubscribe(); store.flushView(session.id); };
  }, [runtime, session.id, store]);
  useLayoutEffect(() => {
    if (state.loading[session.id] || restored || !viewport.current) return;
    const node = viewport.current; node.scrollTop = initialScroll.current;
    const frame = requestAnimationFrame(() => { node.scrollTop = initialScroll.current; setRestored(true); });
    return () => cancelAnimationFrame(frame);
  }, [state.loading[session.id], restored]);
  const running = store.running(session.id);
  return <Context.Provider value={{store, smooth: Boolean(boot.settings.preferences.smooth_stream)}}><AssistantRuntimeProvider runtime={runtime}><ThreadPrimitive.Root className="thread"><header className="chat-header"><div><h1>{session.title || '新会话'}{readOnly(session) && <span className="badge">旧记录 · 只读</span>}</h1><p><span className={`connection-dot ${state.connected ? '' : 'offline'}`}/>{running ? `${statusLabel(running.status)} · ${running.model}` : String(modelConfig.model || '尚未配置模型')}{running && <span className="muted"> · 切换会话不会中断</span>}</p></div><div className="actions"><IconButton label="刷新当前会话" onClick={() => void store.load(session.id).catch(store.report)}><RefreshCw size={17}/></IconButton><button className="model-button" onClick={onSettings}>模型设置</button></div></header>{unknownAuto && <div className="capability-banner"><CircleAlert size={16}/><span>模型窗口未知，自动预算不能猜测。</span><button onClick={onSettings}>配置真实窗口 / 手动预算</button></div>}<ThreadPrimitive.Viewport ref={viewport} className="transcript" autoScroll={restored} scrollToBottomOnInitialize={false} scrollToBottomOnThreadSwitch={false} scrollToBottomOnRunStart={false} onScroll={e => { if (restored) store.view(session.id, {scroll: e.currentTarget.scrollTop}); }} aria-label="会话消息">
    <ThreadPrimitive.Empty><div className="welcome"><div className="welcome-mark"><AudioLines size={32}/></div><span className="eyebrow">PRAAT · 专业声学工作空间</span><h2>从一个声音，开始探索。</h2><p>描述目标，上传材料，让分析过程与专业证据<br/>在同一处清晰呈现。</p><div className="welcome-cards">{['分析音高与时长','比较语音特征','解释测量结果'].map(text => <button key={text} onClick={() => { runtime.thread.composer.setText(text); }}>{text}</button>)}</div><small><CheckCircle2 size={13}/>只展示真实模型输出与工具结果</small></div></ThreadPrimitive.Empty><div className="transcript-content"><ThreadPrimitive.Messages components={{Message: MessageCard}}/></div>
  </ThreadPrimitive.Viewport><div className="jump-wrap"><ThreadPrimitive.ScrollToBottom className="jump-button" aria-label="回到最新消息"><ArrowDown size={16}/>回到最新</ThreadPrimitive.ScrollToBottom></div><Composer store={store} session={session} composer={runtime.thread.composer} onSettings={onSettings}/></ThreadPrimitive.Root></AssistantRuntimeProvider></Context.Provider>;
}
