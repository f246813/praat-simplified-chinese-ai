/**
 * Conversation minimap: the long-history navigation rail.
 *
 * Interaction ported from PI-Desktop (`components/ConversationMinimap.tsx`,
 * `lib/conversation-minimap.ts`, fixed revision
 * `0d47d26769ecbeca1c3ab56fa83b58a91de8190e`, LGPL-3.0), adapted to this data model:
 * PI merges each assistant turn's stream fragments into one marker, while here the host
 * already delivers one settled message per turn, so a marker is simply a non-empty row.
 *
 * Two deliberate differences, both because of the mount window this project added:
 * the rail describes **only mounted rows** (a dash for a withheld row would jump nowhere),
 * and the "earlier history" dash reveals the next page instead of loading an older one.
 */

export const CONVERSATION_MINIMAP_PREVIEW_MAX_CHARS = 280;
/** A rail shorter than its content only appears once the transcript actually overflows. */
export const OVERFLOW_EPSILON_PX = 1;
export const MINIMAP_MAGNIFY_RADIUS = 46;
export const MINIMAP_MAGNIFY_BOOST = 1.3;
export const MINIMAP_POPOVER_SNAP = 24;
export const MINIMAP_POPOVER_HEIGHT = 132;
/** Where the "you are reading here" line sits inside the viewport. */
export const MINIMAP_ANCHOR_RATIO = 0.3;
export const MINIMAP_JUMP_OFFSET_PX = 24;

export type ConversationMarker = {id: string; role: 'user' | 'assistant'; preview: string};

export const conversationMarkers = (messages: {id: string; role: string; content: string}[]): ConversationMarker[] =>
  messages
    .filter(message => (message.role === 'user' || message.role === 'assistant') && message.content.trim())
    .map(message => ({id: message.id, role: message.role as 'user' | 'assistant', preview: message.content.trim().slice(0, CONVERSATION_MINIMAP_PREVIEW_MAX_CHARS)}));

export function shouldRenderMinimap({markerCount, overflows, hasEarlier}: {markerCount: number; overflows: boolean; hasEarlier: boolean}): boolean {
  return hasEarlier || (markerCount >= 2 && overflows);
}

/** Cosine falloff across the rail, so the dash under the pointer widens and its neighbours follow. */
export function magnifyScale(distance: number | null): number {
  if (distance === null || !Number.isFinite(distance) || Math.abs(distance) >= MINIMAP_MAGNIFY_RADIUS) return 1;
  return 1 + MINIMAP_MAGNIFY_BOOST * Math.cos((Math.abs(distance) / MINIMAP_MAGNIFY_RADIUS) * (Math.PI / 2));
}

/** The preview bubbles stay inside the rail and leave a readable gap above the nearest dash. */
export const popoverTop = (center: number, railHeight: number): number =>
  Math.round(Math.min(Math.max(center - 36, 0), Math.max(railHeight - MINIMAP_POPOVER_HEIGHT, 0)));

/**
 * The dash the reading line sits on: the last row whose content top is at or above it.
 * `tops` is in the same order as the markers, so the index is directly usable.
 */
export function activeMarkerIndex(tops: number[], anchorLine: number): number {
  let low = 0; let high = tops.length - 1; let found = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (tops[mid] <= anchorLine) { found = mid; low = mid + 1; } else high = mid - 1;
  }
  return found === -1 ? 0 : found;
}

/** The rail's gap shrinks as the rail fills up, so a dense history never overflows the rail. */
export const markerGap = (count: number): number => Math.min(2, Math.max(0, 4 - count * 0.05));

export const prefersReducedMotion = (): boolean =>
  typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
