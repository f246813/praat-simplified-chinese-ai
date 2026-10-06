// Codex sidebar project/connection/list grouping attached to host origin data.
// Public ThreadListParams supplies cwd-based project filtering; desktop React
// grouping is not published. This adapter leaves custom sections independent.
import type {Session} from '../types';
import type {SidebarGrouping} from '../SidebarOptions';
import {normalizeProjectPath} from '../pi/sidebar/sidebar-session-groups';
import {folderNameFromPath} from '../pi/sidebar/project-name';
export function groupSidebarOrigins<T extends Session>(rows:T[],mode:SidebarGrouping):{id:string;label:string;detail:string;sessions:T[]}[]{
  if(mode==='list')return [];
  const groups=new Map<string,{id:string;label:string;detail:string;sessions:T[]}>();
  for(const session of rows){
    const connection=session.connectionId||'local';
    const connectionLabel=session.connectionLabel||(connection==='local'?'本地':connection);
    const path=normalizeProjectPath(session.projectPath)||'';
    const id=mode==='connection'?`connection:${connection}`:`project:${JSON.stringify([connection,path])}`;
    const label=mode==='connection'?connectionLabel:path?`${folderNameFromPath(path)}${connection==='local'?'':` · ${connectionLabel}`}`:'其他聊天';
    const group=groups.get(id)||{id,label,detail:mode==='connection'?connectionLabel:path,sessions:[]};
    group.sessions.push(session);groups.set(id,group);
  }
  return [...groups.values()];
}
