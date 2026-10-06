import { expect, it } from 'vitest';
import {
  adoptDisclosureAnchor, disclosureAnchorOffset, disclosureContentTop, resolveDisclosureAnchor,
  SCROLL_READING_KEYS, DISCLOSURE_ANCHOR_TOLERANCE_PX,
} from '../src/scroll';

const frame = (elementOffset: number, scrollTop: number, scrollHeight = 5000, clientHeight = 800) => ({elementOffset, scrollTop, scrollHeight, clientHeight});

it('anchors a row by its offset from the scroller top, not by scrollTop', () => {
  expect(disclosureAnchorOffset(100, 260)).toBe(160);
  expect(disclosureAnchorOffset(100, 40)).toBe(-60);
  // content-space top = viewport offset + scrollTop, so it is invariant under scrolling.
  expect(disclosureContentTop(frame(160, 400))).toBe(560);
  expect(adoptDisclosureAnchor(frame(160, 400))).toEqual({offset: 160});
});

it('does not write the scroller when the viewport already holds the row', () => {
  expect(resolveDisclosureAnchor({offset: 160}, frame(160, 400))).toBeNull();
  expect(resolveDisclosureAnchor({offset: 160.4}, frame(160, 400))).toBeNull();
  // One full tolerance away is already a real move, not a rounding artefact.
  expect(resolveDisclosureAnchor({offset: 160 + DISCLOSURE_ANCHOR_TOLERANCE_PX}, frame(160, 400))).toBe(399.5);
});

it('compensates height that changed above the row', () => {
  // A card above collapsed by 100px: the row must move back up to its held offset.
  expect(resolveDisclosureAnchor({offset: 160}, frame(60, 400))).toBe(300);
  // A prepended page pushed the row down by 200px: scroll down to keep it in place.
  expect(resolveDisclosureAnchor({offset: 160}, frame(360, 400))).toBe(600);
  // The row is held above the viewport (negative offset) and content below shrank.
  expect(resolveDisclosureAnchor({offset: -120}, frame(-360, 900))).toBe(660);
});

it('clamps to the scrollable range instead of writing an impossible offset', () => {
  expect(resolveDisclosureAnchor({offset: 5000}, frame(0, 100, 5000, 800))).toBe(0);
  expect(resolveDisclosureAnchor({offset: -5000}, frame(0, 0, 5000, 800))).toBe(4200);
  // Nothing to scroll: the only reachable offset wins.
  expect(resolveDisclosureAnchor({offset: 10}, frame(300, 100, 800, 800))).toBe(0);
});

it('releases the hold on navigation keys but not on reading keys', () => {
  for (const key of ['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' ']) expect(SCROLL_READING_KEYS.has(key)).toBe(true);
  for (const key of ['Tab', 'Escape', 'a', 'Enter']) expect(SCROLL_READING_KEYS.has(key)).toBe(false);
});
