// SPDX-License-Identifier: Apache-2.0
// openai/codex ab452649: tui/src/task_mentions.rs::spawn_search.
// Rust -> React adaptation: same 100ms debounce and generation checks before
// dispatch and after reply. Connect to Praat's SQLite RPC; keep its sidebar UI.
import {useEffect,useMemo,useRef,useState} from 'react';
import type {ChatStore} from '../store';
import type {Session} from '../types';

export function useSessionSearch(store:ChatStore,query:string,archived:boolean,sessions:readonly Session[]) {
  const generation=useRef(0);
  const [result,setResult]=useState<{query:string;archived:boolean;ids:Set<string>;loading:boolean}|null>(null);
  const term=query.trim();
  // Host updates/persisted text invalidate search; reading, draft, hover loads,
  // section order and new array identities do not. Sort identities so pinning
  // or reordering the same history cannot invalidate an unchanged query.
  const revision=useMemo(()=>JSON.stringify([...sessions].sort((a,b)=>a.id.localeCompare(b.id)).map(s=>[s.id,s.title,s.updated,Boolean(s.archived)])),[sessions]);
  useEffect(()=>{
    const requestGeneration=++generation.current;
    if(!term){setResult(null);return;}
    setResult({query:term,archived,ids:new Set(),loading:true});
    const timer=setTimeout(async()=>{
      if(generation.current!==requestGeneration)return;
      try {
        const response=await store.rpc('sessions.search',{searchTerm:term,archived});
        if(generation.current!==requestGeneration)return;
        setResult({query:term,archived,ids:new Set(response.sessionIds),loading:false});
      } catch(error) {
        if(generation.current!==requestGeneration)return;
        setResult({query:term,archived,ids:new Set(),loading:false});
        store.report(error);
      }
    },100);
    return()=>{clearTimeout(timer);generation.current++;};
  },[store,term,archived,revision]);
  return result?.query===term&&result.archived===archived?result:null;
}
