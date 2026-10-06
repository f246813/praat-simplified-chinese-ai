import {expect,it} from 'vitest';
import {groupSidebarOrigins} from '../src/codex/sidebar-origins';
import type {Session} from '../src/types';
const session=(id:string,projectPath:string|null,connectionId='local',connectionLabel='本地')=>({id,title:id,projectPath,connectionId,connectionLabel,created:'',updated:'',readOnly:false,draft:'',scroll:0}) as Session;
it('groups by real project paths and separates identical paths on distinct connections',()=>{
  const rows=[session('a','C:/one/audio'),session('b','C:/one/audio'),session('c','C:/two/audio'),session('d','C:/one/audio','ssh:lab','实验室'),session('e',null)];
  const groups=groupSidebarOrigins(rows,'project');
  expect(groups.map(g=>g.sessions.map(s=>s.id))).toEqual([['a','b'],['c'],['d'],['e']]);
  expect(groups.map(g=>g.label)).toEqual(['audio','audio','audio · 实验室','其他聊天']);
  expect(groupSidebarOrigins([session('extended','\\\\?\\C:\\one\\audio\\'),session('plain','C:/one/audio')],'project')).toHaveLength(1);
});
it('groups by the originating connection, retaining local and unknown legacy records',()=>{
  const rows=[session('a','C:/a'),session('b','/srv/project','ssh:lab','实验室'),session('c',null),session('d','/different','ssh:lab','实验室')];
  expect(groupSidebarOrigins(rows,'connection').map(g=>({label:g.label,ids:g.sessions.map(s=>s.id)}))).toEqual([{label:'本地',ids:['a','c']},{label:'实验室',ids:['b','d']}]);
  expect(groupSidebarOrigins(rows,'list')).toEqual([]);
});
