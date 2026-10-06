/**
 * In-conversation search and hit highlighting.
 *
 * Highlight interaction ported from PI-Desktop (`components/SearchDialog.tsx`,
 * `lib/transcript-search-highlight.ts`, `hooks/use-transcript-search-focus.ts`, fixed revision
 * `0d47d26769ecbeca1c3ab56fa83b58a91de8190e`, LGPL-3.0), with one deliberate divergence:
 *
 * PI searches in the **host** (SQLite, one row per hit) and then re-matches inside the DOM to
 * paint that one message. Sidebar history now uses the Codex host search RPC; this panel's
 * searchable set remains the **rendered transcript**: every
 * hit that is counted is a hit that can be highlighted and aligned to. Matches that exist only
 * in Markdown source (or only in withheld rows) are not counted — the UI offers to reveal the
 * hidden page instead of inventing a number it cannot point at.
 *
 * The highlight itself is the CSS Custom Highlight API, exactly as PI uses it, because it
 * paints text without rewriting the DOM that React owns.
 * Literal matching comes from Codex LiteralMatcher, translated to UTF-16 DOM offsets.
 */
import {literalMatchRanges} from './codex/literal-matcher';

export type SearchHit = {range: Range; messageId: string};

/** Chrome that is not message prose: chrome labels, code/mermaid copy buttons, hidden decorations. */
export const SEARCH_NON_CONTENT = 'button, textarea, input, select, [aria-hidden="true"], .minimap-rail, .history-reveal';

type Segment = {node: Text; start: number; end: number};

/** Visible text nodes in document order, skipping non-content chrome. */
export function searchSegments(root: HTMLElement): Segment[] {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => {
      const value = node.nodeValue;
      if (!value || !value.trim()) return NodeFilter.FILTER_REJECT;
      const parent = (node as Text).parentElement;
      if (!parent || parent.closest(SEARCH_NON_CONTENT)) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const segments: Segment[] = [];
  let at = 0;
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node as Text;
    segments.push({node: text, start: at, end: at + (text.nodeValue?.length ?? 0)});
    at += text.nodeValue?.length ?? 0;
  }
  return segments;
}

/**
 * Codex LiteralMatcher supplies literal hit offsets, including expanded lowercase
 * Unicode. Map these to DOM segments with the same linear two-pointer method.
 */
export function searchRanges(root: HTMLElement, query: string, limit = 500): Range[] {
  const needle = query.trim();
  if (!needle) return [];
  const segments = searchSegments(root);
  if (!segments.length) return [];
  const text = segments.map(segment => segment.node.nodeValue ?? '').join('');
  const ranges: Range[] = [];
  let first=0,last=0;
  for(const [start,end] of literalMatchRanges(text,needle,limit)){
    while(segments[first].end<=start)first++;
    while(segments[last].end<end)last++;
    const range=document.createRange();
    range.setStart(segments[first].node,start-segments[first].start);
    range.setEnd(segments[last].node,end-segments[last].start);
    ranges.push(range);
  }
  return ranges;
}

/** Which message row a hit belongs to, so the UI can name it and grow the window for it. */
export function messageIdOf(node: Node | null, root: HTMLElement): string | null {
  const element = node instanceof Element ? node : node?.parentElement ?? null;
  const row = element?.closest<HTMLElement>('[data-message-id]') ?? null;
  return row && root.contains(row) ? row.dataset.messageId ?? null : null;
}

/** PI places a hit about a third down the viewport, moving the scroller by at most 160px. */
export function alignScrollTop({targetTop, viewportTop, scrollTop, clientHeight}: {targetTop: number; viewportTop: number; scrollTop: number; clientHeight: number}): number {
  return Math.max(0, Math.round(scrollTop + targetTop - viewportTop - Math.min(160, clientHeight / 3)));
}

/** Wrapping match navigation, so Enter past the last hit returns to the first. */
export const stepMatch = (current: number, delta: number, total: number): number =>
  total <= 0 ? 0 : ((current + delta) % total + total) % total;

export const matchSummary = (active: number, total: number): string => (total ? `${active + 1}/${total}` : '无匹配');

/**
 * Whether a lowercased literal query appears in the source of any of these messages.
 * Used only to decide whether to offer revealing the hidden page — never to claim a count.
 */
export function sourceHasMatch(messages: {content: string}[], query: string): boolean {
  const needle = query.trim().toLocaleLowerCase();
  return Boolean(needle) && messages.some(message => message.content.toLocaleLowerCase().includes(needle));
}

export const supportsHighlightApi = (): boolean =>
  typeof CSS !== 'undefined' && 'highlights' in CSS && typeof (globalThis as {Highlight?: unknown}).Highlight === 'function';

export const SEARCH_HIGHLIGHT = 'transcript-search';
export const SEARCH_ACTIVE_HIGHLIGHT = 'transcript-search-active';
