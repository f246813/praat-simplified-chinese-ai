import {act, cleanup, fireEvent, render, screen} from '@testing-library/react';
import {afterEach, expect, it, vi} from 'vitest';
import {SessionSidebar} from '../src/pi/sidebar/Sidebar';
import {ChatStore} from '../src/store';
import {createDemoAdapter} from '../src/demo';
import type {Methods,Rpc} from '../src/types';

afterEach(()=>{cleanup();vi.useRealTimers();});

const mount=async(search?:(query:string)=>Promise<{sessionIds:string[]}>)=>{
  const demo=createDemoAdapter();
  const rpc=vi.fn(async(method:string,params:any)=>method==='sessions.search'&&search?search(params.searchTerm):demo(method as keyof Methods,params)) as unknown as Rpc;
  const store=new ChatStore(rpc);await store.initialize();
  render(<SessionSidebar store={store} expanded width={272} maxWidth={520} onToggle={()=>{}} onPreviewWidth={()=>{}} onCommitWidth={()=>{}} onTasks={()=>{}} onSettings={()=>{}} onRename={()=>{}} onDelete={()=>{}}/>);
  return {store,rpc:rpc as unknown as ReturnType<typeof vi.fn>,input:screen.getByRole('textbox',{name:'搜索会话与消息'})};
};

it('searches unopened messages with one compact host request and no full history hydration',async()=>{
  vi.useFakeTimers();
  const {store,rpc,input}=await mount(async()=>({sessionIds:['demo-history']}));
  try {
    fireEvent.change(input,{target:{value:'宿主正文'}});
    await act(async()=>{await vi.advanceTimersByTimeAsync(2000);});
    expect(rpc.mock.calls.filter(([method])=>method==='sessions.get')).toHaveLength(1);
    expect(rpc.mock.calls.filter(([method])=>method==='sessions.search')).toHaveLength(1);
    expect(document.querySelectorAll('.session-row')).toHaveLength(1);
    expect(document.querySelector('.session-row')?.getAttribute('data-session-id')).toBe('demo-history');
    expect(store.getSnapshot().messages['demo-history']).toBeUndefined();
  } finally {store.stop();}
});

it('discards old responses and clears pending search without changing the input or active chat',async()=>{
  vi.useFakeTimers();let old!:(value:{sessionIds:string[]})=>void;
  const {store,input}=await mount(query=>query==='old'?new Promise(resolve=>{old=resolve;}):Promise.resolve({sessionIds:['demo-history']}));
  try {
    fireEvent.change(input,{target:{value:'old'}});await act(async()=>{await vi.advanceTimersByTimeAsync(110);});
    fireEvent.change(input,{target:{value:'new'}});await act(async()=>{await vi.advanceTimersByTimeAsync(110);});
    expect(document.querySelector('.session-row')?.getAttribute('data-session-id')).toBe('demo-history');
    await act(async()=>{old({sessionIds:['legacy:fixture']});});
    expect(document.querySelector('.session-row')?.getAttribute('data-session-id')).toBe('demo-history');
    expect(store.getSnapshot().selected).toBe('demo-1');
    fireEvent.change(input,{target:{value:''}});
    expect(document.querySelectorAll('.session-row')).toHaveLength(3);
    expect(screen.getByRole('textbox',{name:'搜索会话与消息'})).toBe(input);
  } finally {store.stop();}
});

it('keeps body search results mounted while reading position and draft change',async()=>{
  vi.useFakeTimers();
  const {store,rpc,input}=await mount(async()=>({sessionIds:['demo-history']}));
  try {
    fireEvent.change(input,{target:{value:'宿主正文'}});
    await act(async()=>{await vi.advanceTimersByTimeAsync(110);});
    const row=document.querySelector('.session-row');expect(row).not.toBeNull();
    act(()=>store.view('demo-1',{scroll:480,anchor:{messageId:'read-anchor',offset:12}}));
    expect(document.querySelector('.session-row')).toBe(row);
    act(()=>store.view('demo-1',{scroll:160,draft:'尚未发送的内容'}));
    await act(async()=>{await vi.advanceTimersByTimeAsync(1000);});
    expect(document.querySelector('.session-row')).toBe(row);
    expect(rpc.mock.calls.filter(([method])=>method==='sessions.search')).toHaveLength(1);
    expect(store.getSnapshot().sessions.find(s=>s.id==='demo-1')?.scroll).toBe(160);
  } finally {store.stop();}
});

it('loads a matching row preview without clearing results or searching again',async()=>{
  vi.useFakeTimers();
  const {store,rpc,input}=await mount(async()=>({sessionIds:['demo-history']}));
  try {
    fireEvent.change(input,{target:{value:'宿主正文'}});
    await act(async()=>{await vi.advanceTimersByTimeAsync(110);});
    const row=document.querySelector('.session-row');expect(row).not.toBeNull();
    fireEvent.pointerEnter(row!.querySelector('.session-select')!);
    await act(async()=>{await vi.advanceTimersByTimeAsync(140);});
    expect(store.getSnapshot().messages['demo-history']?.length).toBeGreaterThan(0);
    expect(document.querySelector('.session-row')).toBe(row);
    await act(async()=>{await vi.advanceTimersByTimeAsync(1000);});
    expect(rpc.mock.calls.filter(([method])=>method==='sessions.search')).toHaveLength(1);
    expect(store.getSnapshot().selected).toBe('demo-1');
  } finally {store.stop();}
});

it('refreshes actual search matches when a conversation is renamed',async()=>{
  vi.useFakeTimers();const {store,rpc,input}=await mount();
  try {
    fireEvent.change(input,{target:{value:'新的分析'}});
    await act(async()=>{await vi.advanceTimersByTimeAsync(110);});
    expect(document.querySelector('.session-row')?.getAttribute('data-session-id')).toBe('demo-1');
    await act(async()=>{await store.rename('demo-1','声学研究');await vi.advanceTimersByTimeAsync(110);});
    expect(document.querySelectorAll('.session-row')).toHaveLength(0);
    expect(rpc.mock.calls.filter(([method])=>method==='sessions.search')).toHaveLength(2);
  } finally {store.stop();}
});
