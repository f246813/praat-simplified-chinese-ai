import { expect, it } from 'vitest';
import {
  availableCommands, COMMANDS, completionRange, detectCompletion, matchCommands, stripCompletion,
} from '../src/completions';

it('opens only on a leading slash token', () => {
  expect(detectCompletion('/')).toEqual({query: '', start: 0, end: 1});
  expect(detectCompletion('/新建')).toEqual({query: '新建', start: 0, end: 3});
  expect(detectCompletion('看一下 /设置')).toEqual({query: '设置', start: 4, end: 7});
  expect(detectCompletion('/新建', 2)).toEqual({query: '新', start: 0, end: 2});
  // A slash inside a value or a word is ordinary text, not a trigger.
  expect(detectCompletion('2026/10')).toBeNull();
  expect(detectCompletion('a/b')).toBeNull();
  expect(detectCompletion('https://example.com')).toBeNull();
  // Once the token is closed the list must not come back.
  expect(detectCompletion('/新建 参数')).toBeNull();
  expect(detectCompletion('前面 /后面 空格')).toBeNull();
  expect(detectCompletion('', 0)).toBeNull();
});

it('offers only commands whose action exists right now', () => {
  expect(availableCommands(false, true).map(command => command.id)).toEqual(['new', 'settings', 'attach']);
  expect(availableCommands(true, true).map(command => command.id)).toEqual(['new', 'settings', 'stop', 'attach']);
  // A read-only record has no running task to cancel and gets no list at all.
  expect(availableCommands(true, false)).toEqual([]);
  expect(COMMANDS.map(command => command.id)).toEqual(['new', 'settings', 'stop', 'attach']);
});

it('matches by name prefix in either script and by label', () => {
  const commands = availableCommands(true, true);
  expect(matchCommands(commands, '').map(command => command.id)).toEqual(['new', 'settings', 'stop', 'attach']);
  expect(matchCommands(commands, '新').map(command => command.id)).toEqual(['new']);
  expect(matchCommands(commands, 's').map(command => command.id)).toEqual(['settings', 'stop']);
  expect(matchCommands(commands, '附件').map(command => command.id)).toEqual(['attach']);
  expect(matchCommands(commands, '取消本会话').map(command => command.id)).toEqual(['stop']);
  expect(matchCommands(commands, 'nope')).toEqual([]);
});

it('removes exactly the typed token and nothing else', () => {
  const detection = detectCompletion('看一下 /设置')!;
  expect(stripCompletion('看一下 /设置', detection)).toEqual({text: '看一下 ', caret: 4});
  expect(stripCompletion('/设置 其余', detectCompletion('/设置')!)).toEqual({text: ' 其余', caret: 0});
  const whole = detectCompletion('/新建')!;
  expect(stripCompletion('/新建', whole)).toEqual({text: '', caret: 0});
  // The document range deletes the same characters the strip rule removes.
  expect(completionRange(whole, 4)).toEqual({from: 1, to: 4});
});
