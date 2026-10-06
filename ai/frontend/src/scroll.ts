/**
 * Transcript disclosure anchoring.
 *
 * Interaction ported from PI-Desktop (fixed revision
 * `0d47d26769ecbeca1c3ab56fa83b58a91de8190e`, LGPL-3.0):
 * `lib/disclosure-anchor.ts` + `hooks/use-disclosure-anchor.ts`. The anchor is
 * the collapsed row's offset **from the scroller's top edge**, not a
 * `scrollTop`, so a height change anywhere above the row is compensated too.
 * Implementation is project-local; see `Scroll.tsx` for the wiring.
 */

/** Below this the browser already holds the row and a write would only emit a scroll event. */
export const DISCLOSURE_ANCHOR_TOLERANCE_PX = 0.5;

export type DisclosureAnchor = {offset: number};
export type DisclosureAnchorFrame = {elementOffset: number; scrollTop: number; scrollHeight: number; clientHeight: number};

export const disclosureAnchorOffset = (scrollerTop: number, elementTop: number): number => elementTop - scrollerTop;

/** The row's own content-space top: invariant under scrolling, moved by content above it. */
export const disclosureContentTop = (frame: DisclosureAnchorFrame): number => frame.elementOffset + frame.scrollTop;

/** `null` means the viewport already holds this anchor, so the scroller must not be written. */
export function resolveDisclosureAnchor(anchor: DisclosureAnchor, frame: DisclosureAnchorFrame): number | null {
  const maxScrollTop = Math.max(0, frame.scrollHeight - frame.clientHeight);
  const target = Math.min(maxScrollTop, Math.max(0, disclosureContentTop(frame) - anchor.offset));
  return Math.abs(target - frame.scrollTop) < DISCLOSURE_ANCHOR_TOLERANCE_PX ? null : target;
}

/** Re-adopt where the row actually landed: the boundary clamp is the browser's answer, not something to fight. */
export const adoptDisclosureAnchor = (frame: DisclosureAnchorFrame): DisclosureAnchor => ({offset: frame.elementOffset});

/** Reading keys must not release a hold: they are how the user reads the expanded content. */
export const SCROLL_READING_KEYS = new Set(['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End', ' ']);
