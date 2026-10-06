import { describe, expect, it } from 'vitest';
import { getSchema } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import { InputHistory, markdownParser, markdownSerializer, shouldSend } from '../src/editor';
const key = {key:'Enter',shiftKey:false,ctrlKey:false,metaKey:false,altKey:false};
describe('IME-safe single submission policy', () => {
  it.each([{isComposing:true},{keyCode:229}])('never sends IME candidate %#', flags => expect(shouldSend({...key,...flags},'enter',false,false)).toBe(false));
  it('guards tracked composition and commit cooldown', () => {expect(shouldSend(key,'enter',true,false)).toBe(false);expect(shouldSend(key,'enter',false,true)).toBe(false);});
  it('Enter sends; Shift+Enter and Alt+Enter never send', () => {expect(shouldSend(key,'enter',false,false)).toBe(true);expect(shouldSend({...key,shiftKey:true},'enter',false,false)).toBe(false);expect(shouldSend({...key,altKey:true},'enter',false,false)).toBe(false);});
  it('Ctrl/Command mode keeps ordinary Enter as newline', () => {expect(shouldSend(key,'ctrl-enter',false,false)).toBe(false);expect(shouldSend({...key,ctrlKey:true},'ctrl-enter',false,false)).toBe(true);expect(shouldSend({...key,metaKey:true},'ctrl-enter',false,false)).toBe(true);});
});
describe('mature ProseMirror Markdown adaptation', () => {
  const schema = getSchema([StarterKit.configure({underline:false,link:{openOnClick:false,autolink:false}})]);
  const parser = markdownParser(schema);
  it('round-trips rich marks, CJK, lists, fenced code and hard breaks', () => {
    const source='**中文** *解释* ~~修订~~ `token`\n\n3. 三\n4. 四\n\n```python\nprint("声音")\n```\n\n第一行\\\n第二行';
    const doc=parser.parse(source);const out=markdownSerializer.serialize(doc);
    expect(out).toContain('**中文**');expect(out).toContain('~~修订~~');expect(out).toContain('3. 三');expect(out).toContain('```python');expect(out).toContain('第一行\\\n第二行');expect(parser.parse(out).eq(doc)).toBe(true);
  });
  it('does not turn pasted HTML into an active document', () => {const out=markdownSerializer.serialize(parser.parse('<script>alert(1)</script>'));expect(out).toContain('script');expect(parser.parse(out).textContent).toContain('<script>');});
  it('uses safe longer fences if content includes backticks', () => {const doc=schema.node('doc',{},[schema.node('codeBlock',{language:'txt'},[schema.text('```')])]);expect(markdownSerializer.serialize(doc)).toMatch(/^````txt/);});
});
describe('per-session input history', () => {
  it('restores the original draft after browsing', () => {const h=new InputHistory();expect(h.navigate('older','草稿',['最近','更早'])).toBe('最近');expect(h.navigate('older','最近',['最近','更早'])).toBe('更早');expect(h.navigate('newer','更早',['最近','更早'])).toBe('最近');expect(h.navigate('newer','最近',['最近','更早'])).toBe('草稿');});
  it('editing a recalled value resets history snapshot', () => {const h=new InputHistory();h.navigate('older','原稿',['最近']);expect(h.navigate('older','修改后',['最近'])).toBe('最近');expect(h.navigate('newer','最近',['最近'])).toBe('修改后');});
});
