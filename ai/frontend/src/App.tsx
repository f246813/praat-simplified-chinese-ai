import { useEffect, useState } from 'react';
import { AudioLines, ChevronLeft, ChevronRight, CircleAlert, Plus, Search, Settings, X, LoaderCircle } from 'lucide-react';
import { ChatStore, useChatState } from './store';
import { HostBridge } from './bridge';
import { Chat } from './Chat';
import { SettingsDashboard } from './Settings';
import { activeTask, readOnly, type Session } from './types';
import { IconButton, Modal, statusLabel } from './ui';
import { SessionRow } from './SessionRow';
export function App({bridge, store, demo = false}: {bridge: HostBridge; store: ChatStore; demo?: boolean}) {
  const state = useChatState(store); const [sidebar, setSidebar] = useState(false); const [settings, setSettings] = useState(false);
  const [query, setQuery] = useState(''); const [searching, setSearching] = useState(false); const [starting, setStarting] = useState(true);
  const [edit, setEdit] = useState<{session: Session; action: 'rename'|'delete'}>(); const [title, setTitle] = useState(''); const [busy, setBusy] = useState(false); const [taskPanel, setTaskPanel] = useState(false);
  const initialize = async () => { setStarting(true); store.clearError(); try { await bridge.wait(); await store.initialize(); store.start(); } catch (e) { store.report(e); } finally { setStarting(false); } };
  useEffect(() => { void initialize(); const flush = () => { for (const s of store.getSnapshot().sessions) store.flushView(s.id); }; window.addEventListener('pagehide', flush); return () => { window.removeEventListener('pagehide', flush); store.stop(); }; }, [store, bridge]);
  useEffect(() => {
    const prefs = state.boot?.settings.preferences;
    const media = matchMedia('(prefers-color-scheme: dark)');
    const setTheme = () => { document.documentElement.dataset.theme = prefs?.theme === 'dark' || (!prefs?.theme || prefs.theme === 'system') && media.matches ? 'dark' : 'light'; document.documentElement.style.setProperty('--chat-font-size', `${Number(prefs?.font_size) || 15}px`); };
    setTheme(); media.addEventListener('change', setTheme); return () => media.removeEventListener('change', setTheme);
  }, [state.boot?.settings.preferences]);
  useEffect(() => {
    if (!query.trim() || !state.boot) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      setSearching(true);
      // Contract has no full-text-search RPC: index host snapshots on explicit search,
      // including legacy read-only records, without changing current selection.
      try { for (const s of store.getSnapshot().sessions) if (!store.getSnapshot().messages[s.id] && !cancelled) await store.load(s.id); }
      catch (e) { store.report(e); } finally { if (!cancelled) setSearching(false); }
    }, 300);
    return () => { cancelled = true; clearTimeout(timer); setSearching(false); };
  }, [query, store, Boolean(state.boot)]);
  const tasks = Object.values(state.tasks).filter(activeTask);
  const selected = state.sessions.find(s => s.id === state.selected);
  const filtered = state.sessions.filter(s => !query.trim() || `${s.title}\n${(state.messages[s.id] || []).map(m => m.content).join('\n')}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  if (!state.boot) return <main className="host-screen"><div className="welcome-mark"><AudioLines size={32}/></div><h1>Praat 声学助手</h1><p>{starting ? '正在等待桌面宿主…' : '需要桌面宿主连接'}</p>{state.error && <div role="alert" className="warning">{state.error}</div>}<p className="muted">只接受 pywebview.api.rpc。此页面不会假装有模型、会话或工具服务。</p><button className="primary" disabled={starting} onClick={() => void initialize()}>重新连接宿主</button></main>;
  return <div className={`app ${sidebar ? 'sidebar-expanded' : ''}`}>
    {demo && <div className="demo-banner" role="status">浏览器测试适配器 · 全部内容为明确的演示夹具 · 没有模型、Praat 或网络验证</div>}
    {!settings && <aside className="sidebar" aria-label="会话侧栏">
      <div className="sidebar-top"><div className="brand"><AudioLines size={24}/>{sidebar && <strong>Praat<span>声学助手</span></strong>}</div><IconButton label={sidebar ? '折叠会话侧栏' : '展开会话侧栏'} aria-expanded={sidebar} onClick={() => setSidebar(s => !s)}>{sidebar ? <ChevronLeft size={18}/> : <ChevronRight size={18}/>}</IconButton></div>
      <button className="new-session" title="新建会话" aria-label="新建会话" onClick={() => void store.create().catch(store.report)}><Plus size={19}/>{sidebar && '新建会话'}</button>
      {sidebar && <label className="session-search"><Search size={15}/><input aria-label="搜索会话与消息" placeholder="搜索会话与消息" value={query} onChange={e => setQuery(e.target.value)}/>{query && <IconButton label="清除搜索" onClick={() => setQuery('')}><X size={13}/></IconButton>}</label>}
      <div className="session-list">{sidebar ? <>
        {searching && <small className="search-status">正在搜索宿主历史…</small>}
        {filtered.map(s => <SessionRow key={s.id} store={store} session={s} selected={selected?.id === s.id} onRename={session => { setEdit({session,action:'rename'}); setTitle(session.title); }} onDelete={session => setEdit({session,action:'delete'})}/>)}
        {!filtered.length && <p className="muted">{query ? '没有匹配记录' : '暂无会话，创建一个开始探索'}</p>}
      </> : <IconButton label="搜索 / 浏览历史会话" onClick={() => setSidebar(true)}><Search size={18}/></IconButton>}</div>
      <div className="sidebar-bottom"><button className="task-entry" title="后台任务" aria-label="后台任务" onClick={() => setTaskPanel(true)}><LoaderCircle size={17}/>{sidebar && '后台任务'}<span className="task-count">{tasks.length}</span></button><button className="settings-entry" title="设置" aria-label="打开设置" onClick={() => setSettings(true)}><Settings size={20}/>{sidebar && '设置'}</button>{sidebar && <small className="sidebar-footnote">本地工作空间 · 证据优先</small>}</div>
    </aside>}
    <main className="main-surface">{state.error && <div className="error-banner" role="alert"><CircleAlert size={16}/><span>{state.error}</span><button onClick={() => void store.initialize().catch(store.report)}>刷新核对</button><IconButton label="关闭错误提示" onClick={store.clearError}><X size={16}/></IconButton></div>}{settings ? <SettingsDashboard store={store} onClose={() => setSettings(false)}/> : selected ? <Chat key={selected.id} store={store} session={selected} onSettings={() => setSettings(true)}/> : <div className="host-screen"><AudioLines size={38}/><h1>准备开始新的分析</h1><p className="muted">创建会话，保存目标与证据；旧记录不会被修改。</p><button className="primary" onClick={() => void store.create().catch(store.report)}>新建会话</button></div>}</main>
    {edit && <Modal title={edit.action === 'rename' ? '重命名会话' : '删除会话'} onClose={() => !busy && setEdit(undefined)}>{edit.action === 'rename' ? <label className="field"><span>会话名称</span><input autoFocus value={title} onChange={e => setTitle(e.target.value)} maxLength={200}/></label> : <p>确认删除“{edit.session.title}”？此操作不能撤销，不会重放或撤销已经执行的 Praat 操作。</p>}<div className="actions"><button disabled={busy} onClick={() => setEdit(undefined)}>取消</button><button className={edit.action === 'delete' ? 'danger' : 'primary'} disabled={busy || (edit.action === 'rename' && !title.trim())} onClick={() => { setBusy(true); void (edit.action === 'rename' ? store.rename(edit.session.id,title) : store.delete(edit.session.id)).then(() => setEdit(undefined)).catch(store.report).finally(() => setBusy(false)); }}>{busy ? '处理中…' : '确认'}</button></div></Modal>}
    {taskPanel && <Modal title="后台任务" onClose={() => setTaskPanel(false)}><p className="muted">切换会话不取消任务。取消按 taskId 隔离，不表示撤销已执行操作。</p>{tasks.length ? tasks.map(t => <div className="task-row" key={t.id}><div><strong>{state.sessions.find(s => s.id === t.sessionId)?.title || t.sessionId}</strong><small>{statusLabel(t.status)} · {t.model}<br/>{t.id}</small></div><button onClick={() => { setTaskPanel(false); void store.select(t.sessionId).catch(store.report); }}>查看</button><button onClick={() => void store.rpc('tasks.cancel',{taskId:t.id}).catch(store.report)}>取消任务</button></div>) : <p>没有运行中的任务。</p>}</Modal>}
  </div>;
}
