import {expect,it} from 'vitest';
import {archivedGroups,archiveSource} from '../src/codex/archived-groups';
import type {HistorySection,Session} from '../src/types';
const session=(id:string,patch:Partial<Session>={}):Session=>({id,title:id,readOnly:false,created:'',updated:'',draft:'',scroll:0,archived:true,...patch});
const sections:HistorySection[]=[{id:'s',name:'原分区',appearance:{icon:'🎵',color:'#26715f'}}];
it('keeps original section membership before project origins and does not group equal folder names from different hosts',()=>{
  const rows=[session('member',{sectionId:'s',projectPath:'/srv/audio'}),session('local',{projectPath:'/srv/audio'}),session('remote',{projectPath:'/srv/audio',connectionId:'ssh:fixture',connectionLabel:'实验室'}),session('legacy:old',{readOnly:true})];
  const groups=archivedGroups(rows,sections);
  expect(groups.map(group=>group.name)).toEqual(['原分区','audio','audio · 实验室','无项目']);
  expect(groups[0].sessions.map(s=>s.id)).toEqual(['member']);expect(groups[0].appearance?.icon).toBe('🎵');
  expect(new Set(groups.map(g=>g.id)).size).toBe(4);expect(rows[0].sectionId).toBe('s');
});
it('groups missing/deleted sections under the real project or no-project bucket without fabricating a source',()=>{
  const groups=archivedGroups([session('unknown',{sectionId:'missing'}),session('project',{sectionId:'missing',projectPath:'/real/work'})],[]);
  expect(groups.map(g=>g.name)).toEqual(['work','无项目']);
  expect(archiveSource(session('legacy:old'))).toBe('unknown');expect(archiveSource(session('modern'))).toBe('appServer');
});
