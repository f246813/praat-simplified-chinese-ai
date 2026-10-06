import { expect, it } from 'vitest';
import {
  activeMarkerIndex, conversationMarkers, magnifyScale, markerGap, popoverTop, shouldRenderMinimap,
  CONVERSATION_MINIMAP_PREVIEW_MAX_CHARS, MINIMAP_MAGNIFY_BOOST, MINIMAP_POPOVER_HEIGHT,
} from '../src/minimap';

it('gives every non-empty turn a marker and skips the placeholders', () => {
  const markers = conversationMarkers([
    {id: 'u1', role: 'user', content: '  第一个问题  '},
    {id: 'a1', role: 'assistant', content: ''},
    {id: 'a2', role: 'assistant', content: '回答'},
    {id: 'x', role: 'system', content: '不该出现'},
    {id: 'u2', role: 'user', content: '   '},
    {id: 'u3', role: 'user', content: 'x'.repeat(400)},
  ]);
  expect(markers.map(marker => marker.id)).toEqual(['u1', 'a2', 'u3']);
  expect(markers[0]).toEqual({id: 'u1', role: 'user', preview: '第一个问题'});
  expect(markers[2].preview).toHaveLength(CONVERSATION_MINIMAP_PREVIEW_MAX_CHARS);
  expect(conversationMarkers([])).toEqual([]);
});

it('hides the rail until the transcript actually overflows', () => {
  expect(shouldRenderMinimap({markerCount: 2, overflows: false, hasEarlier: false})).toBe(false);
  expect(shouldRenderMinimap({markerCount: 1, overflows: true, hasEarlier: false})).toBe(false);
  expect(shouldRenderMinimap({markerCount: 2, overflows: true, hasEarlier: false})).toBe(true);
  // A withheld page is navigable even when the mounted tail happens to fit.
  expect(shouldRenderMinimap({markerCount: 0, overflows: false, hasEarlier: true})).toBe(true);
});

it('falls off smoothly from the pointer and stops at the radius', () => {
  expect(magnifyScale(0)).toBeCloseTo(1 + MINIMAP_MAGNIFY_BOOST, 5);
  expect(magnifyScale(null)).toBe(1);
  expect(magnifyScale(Number.NaN)).toBe(1);
  expect(magnifyScale(46)).toBe(1);
  expect(magnifyScale(-46)).toBe(1);
  expect(magnifyScale(400)).toBe(1);
  // Symmetric, and monotonically smaller further away.
  expect(magnifyScale(-12)).toBeCloseTo(magnifyScale(12), 6);
  expect(magnifyScale(12)).toBeGreaterThan(magnifyScale(30));
});

it('keeps the preview bubble inside the rail', () => {
  expect(popoverTop(10, 400)).toBe(0);
  expect(popoverTop(200, 400)).toBe(164);
  expect(popoverTop(1000, 400)).toBe(400 - MINIMAP_POPOVER_HEIGHT);
  // A rail shorter than the bubble still yields a non-negative offset.
  expect(popoverTop(50, 100)).toBe(0);
});

it('marks the dash the reading line sits on', () => {
  const tops = [0, 500, 1000];
  expect(activeMarkerIndex(tops, 600)).toBe(1);
  expect(activeMarkerIndex(tops, 500)).toBe(1);
  expect(activeMarkerIndex(tops, 499)).toBe(0);
  expect(activeMarkerIndex(tops, -50)).toBe(0);
  expect(activeMarkerIndex(tops, 5000)).toBe(2);
  expect(activeMarkerIndex([], 10)).toBe(0);
});

it('tightens the rail gap as it fills up so a dense history never overflows', () => {
  expect(markerGap(0)).toBe(2);
  expect(markerGap(40)).toBe(2);
  expect(markerGap(60)).toBe(1);
  expect(markerGap(200)).toBe(0);
});
