// SPDX-License-Identifier: LGPL-3.0
// Exact independent functions from Pi features/sessions/session-collaboration-view.ts.
// Original and provenance: ../../../../third_party/pi-desktop/upstream/sidebar/.
export function sessionPreview(value: string | undefined, limit = 300): string {
  const text = (value ?? '').replace(/\s+/g, ' ').trim();
  return text.length > limit ? `${text.slice(0, limit).trimEnd()}…` : text;
}
export function positionSessionHoverCard(
  anchor: { top: number; bottom: number; left: number; right: number },
  card: { width: number; height: number },
  viewport: { width: number; height: number },
) {
  const padding = 8;
  const gap = 6;
  const maxLeft = Math.max(padding, viewport.width - card.width - padding);
  const maxTop = Math.max(padding, viewport.height - card.height - padding);
  let left = Math.max(padding, Math.min(anchor.left, maxLeft));
  let top: number;
  if (anchor.bottom + gap + card.height <= viewport.height - padding) {
    top = anchor.bottom + gap;
  } else if (anchor.top - gap - card.height >= padding) {
    top = anchor.top - gap - card.height;
  } else {
    if (anchor.right + gap <= maxLeft) left = anchor.right + gap;
    top = Math.max(padding, Math.min(anchor.top, maxTop));
  }
  return { left, top };
}
