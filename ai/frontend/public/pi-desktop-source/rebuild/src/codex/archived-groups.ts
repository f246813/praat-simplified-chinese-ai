// Public Codex section/cwd/sourceKinds semantics, adapted to existing host
// metadata. Pi's project-name/path functions remain the single path adapter.
import {readOnly,type HistorySection,type Session} from '../types';
import type {ThreadSourceKind} from './protocol/ThreadSourceKind';
import {folderNameFromPath} from '../pi/sidebar/project-name';
import {normalizeProjectPath} from '../pi/sidebar/sidebar-session-groups';

export const archiveSources:{value:'all'|ThreadSourceKind;label:string}[]=[
  {value:'all',label:'全部聊天'},{value:'appServer',label:'桌面聊天'},{value:'unknown',label:'旧版聊天'},
];
export const archiveSource=(session:Session):ThreadSourceKind=>readOnly(session)?'unknown':'appServer';
export type ArchivedGroup={id:string;name:string;detail:string;appearance?:HistorySection['appearance'];sessions:Session[]};
export function archivedGroups(rows:readonly Session[],sections:readonly HistorySection[]):ArchivedGroup[]{
  const sectionById=new Map(sections.map(section=>[section.id,section]));
  const groups=new Map<string,ArchivedGroup>();
  for(const session of rows){
    const section=session.sectionId?sectionById.get(session.sectionId):undefined;
    const path=normalizeProjectPath(session.projectPath)||'';
    const connection=session.connectionId||'local';
    const remote=connection!=='local'?(session.connectionLabel||connection):'';
    const id=section?`section:${section.id}`:path?`project:${JSON.stringify([connection,path])}`:'no-project';
    const name=section?section.name:path?[folderNameFromPath(path),remote].filter(Boolean).join(' · '):'无项目';
    const group=groups.get(id)||{id,name,detail:section?section.name:path||'无项目',appearance:section?.appearance,sessions:[]};
    group.sessions.push(session);groups.set(id,group);
  }
  // Retain the sidebar's section order, then projects, with the ungrouped bucket last.
  const order=new Map(sections.map((s,index)=>[`section:${s.id}`,index]));
  return [...groups.values()].sort((a,b)=>{
    if(a.id==='no-project'||b.id==='no-project')return a.id===b.id?0:a.id==='no-project'?1:-1;
    return (order.get(a.id)??sections.length)-(order.get(b.id)??sections.length)||a.name.localeCompare(b.name);
  });
}
