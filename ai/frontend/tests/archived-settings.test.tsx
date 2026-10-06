import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ArchivedSessions} from '../src/codex/ArchivedSessions';
import {ChatStore,useChatState} from '../src/store';
import {createDemoAdapter} from '../src/demo';
import type {Methods,Rpc} from '../src/types';

afterEach(cleanup);
function ArchivePage({store}:{store:ChatStore}){
  const state=useChatState(store);
  return <ArchivedSessions store={store} sessions={state.sessions} busy={Boolean(state.organizationBusy)} onOpen={()=>{}}/>;
}
it('failed restore keeps history visible, reports the error and permits a successful retry',async()=>{
  const demo=createDemoAdapter();let fail=false;
  const rpc=vi.fn(async(method:string,params:any)=>{
    if(method==='sessions.archive'&&!params.archived&&fail)throw new Error('宿主暂不可用');
    return demo(method as keyof Methods,params);
  }) as unknown as Rpc;
  const store=new ChatStore(rpc);await store.initialize();await store.archive('demo-1',true);fail=true;
  render(<ArchivePage store={store}/>);
  fireEvent.click(screen.getByRole('button',{name:'取消归档 新的分析'}));
  expect((await screen.findByRole('alert')).textContent).toContain('宿主暂不可用');
  expect(store.getSnapshot().sessions.find(s=>s.id==='demo-1')?.archived).toBe(true);
  fail=false;fireEvent.click(screen.getByRole('button',{name:'取消归档 新的分析'}));
  expect(await screen.findByText('暂无已归档会话')).not.toBeNull();
  expect(store.getSnapshot().sessions.find(s=>s.id==='demo-1')?.archived).toBe(false);
  expect(screen.queryByRole('alert')).toBeNull();store.stop();
});
it('one pending restore cannot dispatch duplicates and keyboard focus moves to the remaining row',async()=>{
  const demo=createDemoAdapter();let release!:()=>void,block=false;
  const gate=new Promise<void>(resolve=>{release=resolve;});
  const rpc=vi.fn(async(method:string,params:any)=>{
    if(method==='sessions.archive'&&!params.archived&&block)await gate;
    return demo(method as keyof Methods,params);
  }) as unknown as Rpc;
  const store=new ChatStore(rpc);await store.initialize();await store.archive('demo-1',true);await store.archive('demo-history',true);block=true;
  render(<ArchivePage store={store}/>);
  const restore=screen.getByRole('button',{name:'取消归档 新的分析'});restore.focus();fireEvent.click(restore);fireEvent.click(restore);
  expect((restore as HTMLButtonElement).disabled).toBe(true);
  await act(async()=>{release();});
  await waitFor(()=>expect(document.activeElement).toBe(screen.getByRole('button',{name:'取消归档 长历史与渲染夹具'})));
  expect((rpc as unknown as ReturnType<typeof vi.fn>).mock.calls.filter(([method,params])=>method==='sessions.archive'&&!params.archived)).toHaveLength(1);store.stop();
});
