// SPDX-License-Identifier: LGPL-3.0
// From PI-Desktop 0d47d26769ecbeca1c3ab56fa83b58a91de8190e:
// apps/desktop/src/lib/context-menu.ts (placement math unchanged).
// Source and license: ../../../third_party/pi-desktop/NOTICE.md
/** Keeps a floating surface off the window edge it would otherwise touch. */
export const CONTEXT_MENU_MARGIN = 8;
export type ContextMenuPoint = { x: number; y: number };
export type ContextMenuSize = { width: number; height: number };
export type ContextMenuPlacement = { top: number; left: number };
function clamp(value: number, minimum: number, maximum: number) {
  return Math.max(minimum, Math.min(value, maximum));
}
export function placeContextMenu(
  point: ContextMenuPoint,
  surface: ContextMenuSize,
  viewport: ContextMenuSize,
  margin: number = CONTEXT_MENU_MARGIN,
): ContextMenuPlacement {
  const maxLeft = viewport.width - surface.width - margin;
  const maxTop = viewport.height - surface.height - margin;
  return {
    // Rounded so the surface lands on a whole pixel.
    left: Math.round(clamp(point.x, margin, maxLeft)),
    top: Math.round(clamp(point.y, margin, maxTop)),
  };
}
