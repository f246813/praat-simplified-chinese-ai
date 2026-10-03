export type Config = Record<string, unknown>;
export interface Settings { api: Config; local: Config; preferences: Config; analysis: Config; alignment: Config; [key: string]: unknown }
export interface Session { id: string; title: string; created: string; updated: string; readOnly: boolean; pinned?: boolean; draft: string; scroll: number }
export interface Attachment { id: string; name: string; mime: string; size: number }
export interface Activity { id: string; type: 'progress' | 'thinking' | 'tool' | 'compression'; text?: string; name?: string; args?: object; result?: unknown; status?: string; execution?: string }
export interface Message { id: string; role: 'user' | 'assistant'; content: string; status?: 'running' | 'complete' | 'partial' | 'cancelled' | 'failed' | 'interrupted'; taskId?: string; attachments?: Attachment[]; activities?: Activity[] }
export interface Task { id: string; sessionId: string; status: string; model: string; created: string }
export interface HostEvent { seq: number; sessionId: string; taskId: string; type: 'task' | 'delta' | 'activity' | 'message'; payload: unknown }
export interface PraatSnapshot { pid: number; objects: {id: number; className: string; name: string; selected: boolean}[] }
export interface Bootstrap { sessions: Session[]; settings: Settings; tasks: Task[]; host: {name: string; version: string; cloudAllowed: boolean; praat?: PraatSnapshot | null}; providers: {label: string; base_url: string; model: string; hint: string}[]; models: {id: string; contextWindow: number; maxTokens: number}[] }
export interface TestResult { status: string; reason: string; details?: unknown; identity?: unknown }
export interface Preview { name: string; mime: string; text?: string; dataUrl?: string }
export interface ContextStatus { sessionId: string; model: string; estimated: true; inputTokens: number; overheadTokens: number; contextWindow: number | null; reservedTokens: number | null; availableTokens: number | null; percent: number | null; tokenMode: string; windowSource: 'metadata' | 'configured' | 'unknown'; reason: string; exclusions: string[] }
export interface Methods {
  bootstrap: [{}, Bootstrap];
  'sessions.create': [{title?: string}, Session];
  'sessions.get': [{sessionId: string}, {session: Session; messages: Message[]; cursor?: number}];
  'sessions.context': [{sessionId: string; text: string; attachmentIds?: string[]}, ContextStatus];
  'sessions.rename': [{sessionId: string; title: string}, {ok: true}];
  'sessions.pin': [{sessionId: string; pinned: boolean}, Session];
  'sessions.delete': [{sessionId: string}, {ok: true}];
  'sessions.view': [{sessionId: string; draft?: string; scroll?: number}, {ok: true}];
  'tasks.submit': [{sessionId: string; text: string; attachmentIds?: string[]}, Task];
  'tasks.cancel': [{taskId: string}, {ok: true}];
  'events.poll': [{after: number}, {events: HostEvent[]; cursor: number; reset?: boolean}];
  'settings.get': [{}, Settings];
  'settings.save': [{settings: Partial<Settings>}, Settings];
  'settings.test': [{kind: 'text' | 'audio'; settings: Settings}, TestResult];
  'attachments.choose': [{}, Attachment[]];
  'attachments.import': [{name: string; mime: string; data: string}, Attachment];
  'attachments.preview': [{attachmentId: string}, Preview];
  'links.open': [{url: string}, {ok: true}];
}
export type Rpc = <M extends keyof Methods>(method: M, params: Methods[M][0]) => Promise<Methods[M][1]>;
export const readOnly = (session: Session) => session.readOnly || session.id.startsWith('legacy:');
export const activeTask = (task: Task) => ['queued', 'running', 'cancelling', 'pending', 'submitted'].includes(task.status);
export function knownModel(models: Bootstrap['models'], config: Config) {
  try {
    if (new URL(String(config.base_url || '')).hostname.toLowerCase() !== 'api.openai.com') return undefined;
  } catch { return undefined; }
  return models.find(m => m.id === config.model);
}
