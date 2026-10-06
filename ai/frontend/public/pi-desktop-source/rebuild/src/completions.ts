/**
 * Composer completion: a typed `/` trigger, a filtered list, and keyboard accept.
 *
 * Interaction ported from PI-Desktop (`features/chat/composer/slash-dispatch.ts`,
 * `ComposerAutocomplete.tsx`, fixed revision
 * `0d47d26769ecbeca1c3ab56fa83b58a91de8190e`, LGPL-3.0), reduced to what this host
 * can honestly offer:
 * - dropped the plugin groups and `@` file references: there is no plugin registry
 *   and no workspace/file RPC here, only a native picker.
 * - dropped control commands such as compaction or context clearing: the capture
 *   contract has no such RPC, and offering them would fake backend capabilities the
 *   design explicitly forbids.
 * Every remaining command performs an action the UI already has a control for.
 */

export type ComposerCommandId = 'new' | 'settings' | 'stop' | 'attach';

export type ComposerCommand = {
  id: ComposerCommandId;
  /** Typed names, Chinese first; matching is by prefix on any of them. */
  names: string[];
  label: string;
  hint: string;
};

export const COMMANDS: ComposerCommand[] = [
  {id: 'new', names: ['新建', 'new'], label: '新建会话', hint: '创建并切换到新会话'},
  {id: 'settings', names: ['设置', 'settings'], label: '打开设置', hint: '进入完整设置仪表盘'},
  {id: 'stop', names: ['取消', 'stop'], label: '取消本会话任务', hint: '只取消本会话，不影响其他会话'},
  {id: 'attach', names: ['附件', 'attach'], label: '添加附件', hint: '打开系统文件选择器'},
];

/** Cancelling needs something to cancel, and a read-only record has no running task to lose. */
export const availableCommands = (running: boolean, editable: boolean): ComposerCommand[] =>
  editable ? COMMANDS.filter(command => command.id !== 'stop' || running) : [];

export type CompletionDetection = {query: string; start: number; end: number};

/**
 * `/` only opens the list at the start of a word: a slash inside prose, or a line
 * like `2026/10`, must stay ordinary text.
 */
export function detectCompletion(before: string, cursor: number = before.length): CompletionDetection | null {
  if (cursor < 0 || cursor > before.length) return null;
  const head = before.slice(0, cursor);
  const start = Math.max(head.lastIndexOf('\n'), head.lastIndexOf(' '), head.lastIndexOf('\t')) + 1;
  if (head[start] !== '/') return null;
  const query = head.slice(start + 1);
  if (/\s/.test(query)) return null;
  return {query, start, end: cursor};
}

export function matchCommands(commands: ComposerCommand[], query: string): ComposerCommand[] {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) return commands;
  return commands.filter(command => command.names.some(name => name.toLocaleLowerCase().startsWith(needle)) || command.label.toLocaleLowerCase().includes(needle));
}

/** An accepted command is an action, so its typed token leaves the draft rather than lingering as text. */
export function stripCompletion(value: string, detection: CompletionDetection): {text: string; caret: number} {
  return {text: value.slice(0, detection.start) + value.slice(detection.end), caret: detection.start};
}

/** The document range that holds the typed token, given the caret's document position. */
export const completionRange = (detection: CompletionDetection, caret: number) =>
  ({from: caret - (detection.end - detection.start), to: caret});
