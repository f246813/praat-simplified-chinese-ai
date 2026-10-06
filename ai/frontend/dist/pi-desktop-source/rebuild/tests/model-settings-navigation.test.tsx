import {act,cleanup,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ChatStore} from '../src/store';
import {SettingsDashboard} from '../src/Settings';
import {createDemoAdapter} from '../src/demo';
import type {Rpc} from '../src/types';

afterEach(cleanup);
it('host navigation is independent of task events and survives event reset',async()=>{
  const demo=createDemoAdapter();let navigation=1;
  const rpc=(async(method:string,params:any)=>method==='events.poll'
    ?{events:[],cursor:0,reset:navigation===2,navigation:{id:String(navigation),category:'模型'}}
    :demo(method as any,params)) as Rpc;
  const store=new ChatStore(rpc);await store.initialize();
  const selected=store.getSnapshot().selected;
  await store.pollOnce();expect(store.getSnapshot().modelSettingsRequest).toBe('1');
  navigation=2;await store.pollOnce();expect(store.getSnapshot().modelSettingsRequest).toBe('2');
  expect(store.getSnapshot().selected).toBe(selected);store.stop();
});
it('repeated menu requests select Model/API and keep unsaved settings',async()=>{
  const rpc=vi.fn(createDemoAdapter()) as unknown as Rpc;
  const store=new ChatStore(rpc);await store.initialize();
  const view=render(<SettingsDashboard store={store} onClose={()=>{}} initialCategory="外观与交互"/>);
  expect(screen.getByRole('heading',{name:'外观与交互'})).toBeTruthy();
  view.rerender(<SettingsDashboard store={store} onClose={()=>{}} modelSettingsRequest="first"/>);
  expect(screen.getByRole('heading',{name:'模型'})).toBeTruthy();
  fireEvent.change(screen.getByLabelText('模型名'),{target:{value:'unsaved-model'}});
  fireEvent.click(screen.getByRole('button',{name:'本地模型'}));
  fireEvent.click(screen.getByRole('button',{name:'外观与交互'}));
  await act(async()=>view.rerender(<SettingsDashboard store={store} onClose={()=>{}} modelSettingsRequest="second"/>));
  expect(screen.getByRole('heading',{name:'模型'})).toBeTruthy();
  expect(screen.getByRole('button',{name:'云端 API'}).getAttribute('aria-pressed')).toBe('true');
  expect((screen.getByLabelText('模型名') as HTMLInputElement).value).toBe('unsaved-model');
  expect((rpc as any).mock.calls.some(([method]:[string])=>['tasks.submit','settings.save','settings.test'].includes(method))).toBe(false);
  store.stop();
});
