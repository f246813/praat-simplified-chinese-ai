import { useCallback, useMemo, useRef, useState, type MouseEvent } from 'react';
import { LoaderCircle, MessageSquare, MoreHorizontal, Pencil, Pin, PinOff, Trash2 } from 'lucide-react';
import { ChatStore, useChatState } from './store';
import { readOnly, type Session } from './types';
import { statusLabel } from './ui';
import { ContextMenu, type ContextMenuState } from './pi/ContextMenu';

export function SessionRow({store, session, selected, onRename, onDelete}: {store: ChatStore; session: Session; selected: boolean; onRename: (session: Session) => void; onDelete: (session: Session) => void}) {
  const state = useChatState(store);
  const trigger = useRef<HTMLButtonElement>(null);
  const [menu, setMenu] = useState<Pick<ContextMenuState, 'point' | 'trigger'> | null>(null);
  const [pinning, setPinning] = useState(false);
  const close = useCallback(() => setMenu(null), []);
  const readonly = readOnly(session); const running = store.running(session.id);
  const cannotDelete = readonly || Boolean(running) || Boolean(state.submitting[session.id]);
  const menuState = useMemo<ContextMenuState | null>(() => menu ? {
    ...menu, label: `会话操作 ${session.title}`,
    items: [
      {id:'rename-session', label:'重命名', icon:<Pencil size={14}/>, disabled:readonly, onSelect:() => onRename(session)},
      {id:'toggle-session-pin', label:session.pinned ? '取消置顶' : '置顶', icon:session.pinned ? <PinOff size={14}/> : <Pin size={14}/>, disabled:readonly || pinning || !state.connected, onSelect:() => {
        setPinning(true); void store.pin(session.id, !session.pinned).catch(store.report).finally(() => setPinning(false));
      }},
      {id:'delete-session', label:'删除', icon:<Trash2 size={14}/>, danger:true, separatorBefore:true, disabled:cannotDelete, onSelect:() => onDelete(session)},
    ],
  } : null, [menu, session.id, session.title, session.pinned, readonly, cannotDelete, pinning, state.connected, store, onRename, onDelete]);
  function open(event: MouseEvent<HTMLElement>, pointer = false) {
    event.preventDefault(); event.stopPropagation();
    if (!pointer && menu) { close(); return; }
    const rect = trigger.current?.getBoundingClientRect() || event.currentTarget.getBoundingClientRect();
    // PI-Desktop Sidebar.tsx: left-click starts beside the trigger; right-click at the pointer.
    setMenu({point:pointer && (event.clientX || event.clientY) ? {x:event.clientX + 4,y:event.clientY + 4} : {x:rect.right + 4,y:rect.bottom + 4}, trigger:trigger.current});
  }
  return <div className={`session-row ${selected ? 'selected' : ''} ${menu ? 'menu-open' : ''}`} data-session-id={session.id} data-pinned={Boolean(session.pinned)} onContextMenu={event => open(event, true)}>
    <button className="session-select" onClick={() => void store.select(session.id).catch(store.report)}>
      <MessageSquare size={15}/><span><strong>{session.title || '未命名会话'}</strong><small>{readonly ? '旧记录 · 只读' : running ? `${statusLabel(running.status)} · 后台保留` : '可恢复续聊'}</small></span>
      {session.pinned && <Pin className="session-pin" size={12} aria-label="已置顶"/>}{running && <LoaderCircle className="spin" size={13}/>}
    </button>
    <button ref={trigger} type="button" className="session-more icon-button" aria-label={`会话操作 ${session.title}`} title={readonly ? '旧记录只读' : '会话操作'} aria-haspopup="menu" aria-expanded={Boolean(menu)} onClick={event => open(event)}><MoreHorizontal size={15}/></button>
    <ContextMenu state={menuState} onClose={close}/>
  </div>;
}
