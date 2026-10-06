import { afterEach, expect, it } from 'vitest';
import {
  alignScrollTop, matchSummary, messageIdOf, searchRanges, searchSegments, sourceHasMatch,
  stepMatch, supportsHighlightApi,
} from '../src/search';

const mount = (html: string) => {
  const root = document.createElement('div');
  root.innerHTML = html;
  document.body.append(root);
  return root;
};
afterEach(() => { document.body.innerHTML = ''; });

it('reads only message prose, not the chrome around it', () => {
  const root = mount('<div data-message-id="m1"><p>Hello <strong>world</strong> hello</p><button>hello</button></div><div data-message-id="m2" aria-hidden="true">hello</div>');
  expect(searchSegments(root).map(segment => segment.node.nodeValue)).toEqual(['Hello ', 'world', ' hello']);
});

it('matches case-insensitively and across inline elements', () => {
  const root = mount('<div data-message-id="m1"><p>Hello <strong>world</strong> hello</p><button>hello</button></div><div data-message-id="m2" aria-hidden="true">hello</div>');
  expect(searchRanges(root, 'hello')).toHaveLength(2);
  expect(searchRanges(root, 'HELLO')).toHaveLength(2);
  expect(searchRanges(root, 'zzz')).toEqual([]);
  expect(searchRanges(root, '   ')).toEqual([]);
  // A hit that spans an inline element still resolves to one range.
  const spanning = searchRanges(root, 'o w');
  expect(spanning).toHaveLength(1);
  expect(spanning[0].toString()).toBe('o w');
  // Hits never overlap each other: "Hello world hello" holds five separate l's.
  expect(searchRanges(root, 'l')).toHaveLength(5);
  expect(searchRanges(root, 'l', 2)).toHaveLength(2);
});

it('maps case-expanded Unicode matches back to the original DOM offsets', () => {
  const root=mount('<p>İ <strong>hello</strong> İ</p>');
  const hits=searchRanges(root,'i\u0307');
  expect(hits.map(range=>range.toString())).toEqual(['İ','İ']);
});

it('attributes a hit to the row that owns it', () => {
  const root = mount('<div data-message-id="m1"><p>alpha</p></div><div data-message-id="m2"><p>beta</p></div>');
  const hits = searchRanges(root, 'beta');
  expect(messageIdOf(hits[0].startContainer, root)).toBe('m2');
  expect(messageIdOf(root, root)).toBeNull();
  expect(messageIdOf(null, root)).toBeNull();
});

it('places a hit about a third down the viewport, moving at most 160px', () => {
  // min(160, 900/3) = 160
  expect(alignScrollTop({targetTop: 500, viewportTop: 100, scrollTop: 1000, clientHeight: 900})).toBe(1240);
  // A short viewport uses its own third instead.
  expect(alignScrollTop({targetTop: 500, viewportTop: 100, scrollTop: 1000, clientHeight: 300})).toBe(1300);
  // Never scrolls above the top.
  expect(alignScrollTop({targetTop: 0, viewportTop: 500, scrollTop: 100, clientHeight: 900})).toBe(0);
});

it('wraps match navigation and reports it', () => {
  expect(stepMatch(0, 1, 3)).toBe(1);
  expect(stepMatch(2, 1, 3)).toBe(0);
  expect(stepMatch(0, -1, 3)).toBe(2);
  expect(stepMatch(5, 1, 0)).toBe(0);
  expect(matchSummary(0, 0)).toBe('无匹配');
  expect(matchSummary(1, 5)).toBe('2/5');
});

it('only offers the hidden page when the source actually holds a match', () => {
  const messages = [{content: '第 20 条夹具'}, {content: '另一条'}];
  expect(sourceHasMatch(messages, '夹具')).toBe(true);
  expect(sourceHasMatch(messages, '  第 20  ')).toBe(true);
  expect(sourceHasMatch(messages, '不存在')).toBe(false);
  expect(sourceHasMatch(messages, '   ')).toBe(false);
});

it('reports the highlight API as unavailable instead of throwing when it is missing', () => {
  // jsdom has no CSS.highlights, which is exactly the branch a host without it would take.
  expect(supportsHighlightApi()).toBe(false);
});
