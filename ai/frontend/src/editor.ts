import { MarkdownParser, MarkdownSerializer, defaultMarkdownParser, defaultMarkdownSerializer } from 'prosemirror-markdown';
import type { Schema } from '@tiptap/pm/model';
const nodes = defaultMarkdownSerializer.nodes;
export const markdownSerializer = new MarkdownSerializer({
  paragraph: nodes.paragraph, text: nodes.text, heading: nodes.heading, blockquote: nodes.blockquote,
  bulletList: nodes.bullet_list, listItem: nodes.list_item,
  orderedList: (state, node) => {
    const start = node.attrs.start || 1; const width = String(start + node.childCount - 1).length;
    state.renderList(node, ' '.repeat(width + 2), i => `${String(start + i).padStart(width)}. `);
  },
  codeBlock: (state, node) => { const runs = node.textContent.match(/`+/g) || []; const fence = '`'.repeat(Math.max(3, ...runs.map(s => s.length + 1))); state.write(`${fence}${node.attrs.language || ''}\n`); state.text(node.textContent, false); state.write(`\n${fence}`); state.closeBlock(node); },
  horizontalRule: nodes.horizontal_rule,
  hardBreak: state => state.write('\\\n'),
}, {bold: defaultMarkdownSerializer.marks.strong, italic: defaultMarkdownSerializer.marks.em, code: defaultMarkdownSerializer.marks.code, link: defaultMarkdownSerializer.marks.link, strike: {open: '~~', close: '~~', mixable: true, expelEnclosingWhitespace: true}}, {hardBreakNodeName: 'hardBreak'});
export function markdownParser(schema: Schema) {
  const tokenizer = defaultMarkdownParser.tokenizer; tokenizer.enable('strikethrough');
  return new MarkdownParser(schema, tokenizer, {
    ...defaultMarkdownParser.tokens,
    list_item: {block: 'listItem'}, bullet_list: {block: 'bulletList'}, ordered_list: {block: 'orderedList', getAttrs: token => ({start: Number(token.attrGet('start') || 1)})},
    code_block: {block: 'codeBlock', noCloseToken: true}, fence: {block: 'codeBlock', getAttrs: token => ({language: token.info || null}), noCloseToken: true},
    hr: {node: 'horizontalRule'}, hardbreak: {node: 'hardBreak'}, em: {mark: 'italic'}, strong: {mark: 'bold'}, s: {mark: 'strike'},
    image: {ignore: true},
  });
}
export interface KeyInput {key: string; shiftKey: boolean; ctrlKey: boolean; metaKey: boolean; altKey: boolean; isComposing?: boolean; keyCode?: number}
export function shouldSend(event: KeyInput, mode: string, composing: boolean, cooldown: boolean) {
  if (composing || cooldown || event.isComposing || event.keyCode === 229) return false;
  if (event.key !== 'Enter' || event.shiftKey || event.altKey) return false;
  return mode === 'ctrl-enter' ? event.ctrlKey || event.metaKey : !event.ctrlKey && !event.metaKey;
}
export class InputHistory {
  private cursor = -1; private original = ''; private recalled = '';
  navigate(direction: 'older'|'newer', current: string, history: string[]) {
    if (this.cursor >= 0 && current !== this.recalled) this.cursor = -1;
    if (this.cursor < 0) { if (direction === 'newer' || !history.length) return; this.original = current; }
    const next = this.cursor + (direction === 'older' ? 1 : -1);
    if (next >= history.length) return this.recalled;
    this.cursor = next;
    this.recalled = next < 0 ? this.original : history[next];
    return this.recalled;
  }
}
