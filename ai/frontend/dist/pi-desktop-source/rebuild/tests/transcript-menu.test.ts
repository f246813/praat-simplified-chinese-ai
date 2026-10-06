import { expect, it } from 'vitest';
import {
  collectEvidence, conversationMenuEntries, copyPayload, evidencePayload,
  messageMenuEntries, transcriptText, type EvidenceEntry,
} from '../src/transcript-menu';
import type { Activity } from '../src/types';

const activity = (over: Partial<Activity>): Activity => ({id: 'a', type: 'tool', ...over});

it('offers only what this host can honestly do', () => {
  expect(messageMenuEntries({text: '答案', hasEvidence: false}).map(entry => entry.id)).toEqual(['copy-message', 'select-message']);
  expect(conversationMenuEntries({hasMessages: true}).map(entry => entry.id)).toEqual(['copy-conversation', 'select-conversation', 'scroll-top', 'scroll-bottom']);
  // Message mutation, regenerate and branch have no RPC behind them, so they are not offered.
  const ids = [...messageMenuEntries({text: 'x', hasEvidence: true}), ...conversationMenuEntries({hasMessages: true})].map(entry => entry.id);
  for (const missing of ['edit', 'delete', 'regenerate', 'branch', 'revision-next']) expect(ids).not.toContain(missing);
});

it('does not paint a leading separator and never opens an empty menu', () => {
  expect(messageMenuEntries({text: '', hasEvidence: false})).toEqual([]);
  expect(messageMenuEntries({text: '   ', hasEvidence: false})).toEqual([]);
  const evidenceOnly = messageMenuEntries({text: '', hasEvidence: true});
  expect(evidenceOnly.map(entry => entry.id)).toEqual(['copy-evidence']);
  expect(evidenceOnly[0].separatorBefore).toBeFalsy();
  const both = messageMenuEntries({text: '答案', hasEvidence: true});
  expect(both.map(entry => entry.id)).toEqual(['copy-message', 'select-message', 'copy-evidence']);
  expect(both[2].separatorBefore).toBe(true);
  expect(conversationMenuEntries({hasMessages: false})[0]).toMatchObject({id: 'copy-conversation', disabled: true});
});

it('keeps evidence separate from model prose, and only for delivered tool results', () => {
  const entries = collectEvidence([
    activity({id: 'thinking', type: 'thinking', text: '不是证据'}),
    activity({id: 'pending', type: 'tool', name: '时长', status: 'running'}),
    activity({id: 'done', type: 'tool', name: '时长', args: {object: 'Sound'}, result: ['15 ms'], status: 'success', execution: 'delivered'}),
    activity({id: 'compression', type: 'compression', text: '压缩'}),
  ]);
  expect(entries).toEqual([{name: '时长', status: 'success', execution: 'delivered', args: {object: 'Sound'}, result: ['15 ms']}]);
  expect(JSON.parse(evidencePayload(entries))).toEqual({name: '时长', status: 'success', execution: 'delivered', args: {object: 'Sound'}, result: ['15 ms']});
  const many: EvidenceEntry[] = [...entries, {name: '强度', result: 1}];
  expect(JSON.parse(evidencePayload(many))).toHaveLength(2);
});

it('prefers an in-row selection over the whole message, and trims nothing away by accident', () => {
  expect(copyPayload('选中的一句', '整条消息')).toBe('选中的一句');
  expect(copyPayload('   ', '整条消息')).toBe('整条消息');
  expect(copyPayload(undefined, '  整条消息  ')).toBe('整条消息');
  expect(copyPayload(undefined, '   ')).toBe('');
});

it('labels a copied conversation by speaker and skips empty rows', () => {
  expect(transcriptText([{role: 'user', content: '你好'}, {role: 'assistant', content: ''}, {role: 'assistant', content: ' 在 '}])).toBe('你：\n你好\n\n声学助手：\n在');
});
