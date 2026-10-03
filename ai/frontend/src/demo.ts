// Explicit browser-only development/test fixtures. Never selected as a host fallback.
import { activeTask, type Attachment, type Bootstrap, type HostEvent, type Message, type Methods, type Rpc, type Session, type Task } from './types';
export function createDemoAdapter(): Rpc {
  if (window.pywebview) throw new Error('测试适配器不能在桌面宿主中运行');
  const now = new Date().toISOString(); let seq = 0; let nextId = 0;
  const sessions: Session[] = [{id:'demo-1',title:'新的分析',created:now,updated:now,readOnly:false,draft:'',scroll:0},{id:'legacy:fixture',title:'演示旧记录（只读）',created:now,updated:now,readOnly:true,draft:'',scroll:0},{id:'demo-history',title:'长历史与渲染夹具',created:now,updated:now,readOnly:false,draft:'',scroll:0}];
  const messages: Record<string,Message[]> = {
    'demo-1': [],
    'legacy:fixture': [{id:'legacy-user',role:'user',content:'这是一条只读旧记录（测试夹具）'},{id:'legacy-answer',role:'assistant',content:'旧记录只展示，不恢复 Praat 操作。',status:'complete'}],
    'demo-history': Array.from({length:120},(_,i) => ({id:`history-${i}`,role:i%2 ? 'assistant' : 'user',content:i%2 ? `## 第 ${i+1} 条夹具\n\n这不是实际测量结果。公式：$f_0 = 1/T$。\n\n| 来源 | 证据 |\n|---|---|\n| 演示 | 未执行 |\n\n\`\`\`python\nprint(\"仅离线渲染测试\")\n\`\`\`` : `演示历史问题 ${i+1}`,status:'complete'} as Message)),
  };
  messages['demo-history'].push({id:'diagram-fixture',role:'assistant',content:'```mermaid\nflowchart LR\n A[材料] --> B[宿主校验]\n B --> C[结构化证据]\n```',status:'complete',activities:[{id:'fixture-thinking',type:'thinking',text:'仅测试夹具提供的思考文本，不是真实模型思考。',status:'complete'},{id:'fixture-tool',type:'tool',name:'Praat 测试卡片',args:{object:'fixture',scope:[0,1]},result:{source:'fixture',measured:false},status:'failed',execution:'未投递（演示夹具）'}]});
  const tasks = new Map<string,Task>(); const events: HostEvent[] = []; const attachments = new Map<string, Attachment>(); const previews = new Map<string,string>();
  const boot: Bootstrap = {sessions,settings:{api:{enabled:false,locked:false,label:'',base_url:'',model:'',has_api_key:true,request_timeout_sec:120,stop_local_service:true,use_world_knowledge:true,audio_input_enabled:false,token_mode:'auto'},local:{base_url:'http://127.0.0.1:8000/v1',model:'browser-fixture',token_mode:'manual',max_context_tokens:32768,plan_max_tokens:4096},preferences:{theme:'system',font_size:15,send_key:'enter',smooth_stream:true},analysis:{default_error_threshold:1.25,minimum_error_duration_sec:0.04,maximum_errors_per_phone:3},alignment:{backend:'auto',agreement_threshold_sec:0.04,minimum_confidence:0.45,mfa:{enabled:false,executable:'mfa',beam:10,retry_beam:40}}},tasks:[],host:{name:'浏览器测试夹具',version:'1',cloudAllowed:false},providers:[],models:[]};
  const emit = (task: Task, type: HostEvent['type'], payload: unknown) => events.push({seq:++seq,sessionId:task.sessionId,taskId:task.id,type,payload:structuredClone(payload)});
  return (async (method: keyof Methods, params: any) => {
    if (window.pywebview) throw new Error('测试适配器已禁用：检测到桌面宿主，请移除 demo 参数并刷新');
    const session = sessions.find(s => s.id === params.sessionId);
    switch (method) {
      case 'bootstrap': return structuredClone({...boot,tasks:[...tasks.values()]});
      case 'sessions.get': if (!session) throw new Error('会话不存在'); return structuredClone({session,messages:messages[session.id]});
      case 'sessions.create': { const s: Session = {id:`demo-new-${++nextId}`,title:params.title || '新会话',created:now,updated:now,readOnly:false,draft:'',scroll:0}; sessions.unshift(s); messages[s.id]=[]; return structuredClone(s); }
      case 'sessions.rename': if (!session || session.readOnly) throw new Error('记录只读'); session.title=params.title; return {ok:true};
      case 'sessions.pin': {
        if (!session || session.readOnly || typeof params.pinned !== 'boolean') throw new Error('记录只读或参数无效');
        session.pinned = params.pinned;
        sessions.sort((a,b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)) || b.updated.localeCompare(a.updated));
        return structuredClone(session);
      }
      case 'sessions.delete': if (!session || session.readOnly || [...tasks.values()].some(t => t.sessionId === session.id && activeTask(t))) throw new Error('会话不能删除'); sessions.splice(sessions.indexOf(session),1); delete messages[session.id]; return {ok:true};
      case 'sessions.view': if (session) { if (params.draft !== undefined) session.draft=params.draft; if (params.scroll !== undefined) session.scroll=params.scroll; } return {ok:true};
      case 'sessions.context': {
        if (!session) throw new Error('会话不存在');
        const config = boot.settings.api.enabled ? boot.settings.api : boot.settings.local;
        const overheadTokens = 1200;
        const content = messages[session.id].filter(m => m.status !== 'running').map(m => m.content).join('') + params.text + (params.attachmentIds || []).map((id: string) => previews.get(id) || '').join('');
        const inputTokens = overheadTokens + Math.ceil(content.length / 2);
        const contextWindow = config.token_mode === 'manual' ? Number(config.max_context_tokens) || null : null;
        const reservedTokens = contextWindow ? Number(config.plan_max_tokens) || 4096 : null;
        return {sessionId: session.id, model: String(config.model), estimated: true, inputTokens, overheadTokens, contextWindow, reservedTokens, availableTokens: contextWindow ? contextWindow - inputTokens - reservedTokens! : null, percent: contextWindow ? inputTokens / contextWindow * 100 : null, tokenMode: String(config.token_mode), windowSource: contextWindow ? 'configured' : 'unknown', reason: '显式浏览器演示夹具，非真实宿主用量', exclusions: ['Praat 对象与范围', '音频／图片编码', '正在生成的正文']};
      }
      case 'tasks.submit': {
        if (!session || session.readOnly) throw new Error('只读记录不能提交');
        if ([...tasks.values()].some(t => t.sessionId === session.id && activeTask(t))) throw new Error('本会话正在运行');
        const task: Task = {id:`demo-task-${++nextId}`,sessionId:session.id,status:'running',model:'browser-fixture',created:now}; tasks.set(task.id,task); emit(task,'task',task);
        const user: Message = {id:`${task.id}-user`,role:'user',content:params.text,taskId:task.id,attachments:(params.attachmentIds || []).map((id:string) => attachments.get(id)).filter(Boolean)};
        const answer: Message = {id:`${task.id}-assistant`,role:'assistant',content:'',taskId:task.id,status:'running'};
        messages[session.id].push(user,answer); emit(task,'message',user); emit(task,'message',answer);
        const response = '这是一条**浏览器测试响应**，没有调用模型、云端或 Praat。\n\n可以切换会话观察事件隔离，使用停止按钮取消当前夹具任务。\n\n- Markdown 与公式 $f_0 = 1/T$\n- 附件只有演示元数据\n- 所有数字都不是专业测量结果';
        let offset=0;
        const timer = setInterval(() => {
          if (!activeTask(task)) { clearInterval(timer); return; }
          const chunk=response.slice(offset,offset+5); offset+=5; answer.content+=chunk; emit(task,'delta',{messageId:answer.id,text:chunk});
          if (offset >= response.length) { clearInterval(timer); task.status='complete'; answer.status='complete'; emit(task,'message',answer); emit(task,'task',task); }
        },130);
        return structuredClone(task);
      }
      case 'tasks.cancel': { const t=tasks.get(params.taskId); if (t) { t.status='cancelled'; const m=messages[t.sessionId].find(m => m.taskId===t.id && m.role==='assistant'); if(m){m.status='cancelled';emit(t,'message',m);} emit(t,'task',t); } return {ok:true}; }
      case 'events.poll': return {events:structuredClone(events.filter(e => e.seq > params.after)),cursor:seq};
      case 'settings.get': return structuredClone(boot.settings);
      case 'settings.save': {
        for (const section of ['api','local','preferences','analysis','alignment'] as const) {
          if (params.settings[section]) boot.settings[section] = {...boot.settings[section], ...structuredClone(params.settings[section])};
        }
        boot.settings.api.api_key=''; boot.settings.local.api_key=''; return structuredClone(boot.settings);
      }
      case 'settings.test': return {status:'demo-not-verified',reason:`${params.kind === 'audio' ? '音频' : '文字'}测试仅返回显式夹具；没有网络请求，不能视为验证通过。`,details:{adapter:'browser-test',realRequest:false}};
      case 'attachments.choose': { const a={id:`demo-file-${++nextId}`,name:'演示材料.txt',mime:'text/plain',size:24}; attachments.set(a.id,a); previews.set(a.id,'这是演示选择器夹具，不是真实文件。'); return [a]; }
      case 'attachments.import': { const a={id:`demo-file-${++nextId}`,name:params.name,mime:params.mime,size:Math.floor(params.data.length*3/4)}; attachments.set(a.id,a); if(params.mime.startsWith('text/')) previews.set(a.id,new TextDecoder().decode(Uint8Array.from(atob(params.data),(s:string)=>s.charCodeAt(0)))); return a; }
      case 'attachments.preview': {const a=attachments.get(params.attachmentId);if(!a) throw new Error('附件不存在');return {...a,text:previews.get(a.id)};}
      case 'links.open': throw new Error('浏览器测试适配器不打开外部链接');
      default: throw new Error(`测试适配器不支持 ${method}`);
    }
  }) as Rpc;
}
