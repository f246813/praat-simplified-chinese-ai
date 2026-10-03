// SPDX-License-Identifier: LGPL-3.0
// PI-Desktop 0d47d26769ecbeca1c3ab56fa83b58a91de8190e
// apps/desktop/src/lib/scrollbar-reveal.ts; logic unchanged, comments shortened.
// Source and license: ../../../third_party/pi-desktop/NOTICE.md
export const SCROLLING_ATTRIBUTE = "data-scrolling";
export const SCROLLBAR_REVEAL_HOLD_MS = 300;
interface MarkableElement {
  setAttribute(name: string, value: string): void;
  removeAttribute(name: string): void;
}
interface RevealRoot {
  documentElement: MarkableElement | null;
  addEventListener(type: "scroll", listener: (event: { target: unknown }) => void, options: AddEventListenerOptions): void;
  removeEventListener(type: "scroll", listener: (event: { target: unknown }) => void, options: EventListenerOptions): void;
}
export interface ScrollbarRevealOptions { holdMs?: number; }
function isMarkable(target: unknown): target is MarkableElement {
  return (
    typeof target === "object" && target !== null &&
    typeof (target as MarkableElement).setAttribute === "function" &&
    typeof (target as MarkableElement).removeAttribute === "function"
  );
}
export function installScrollbarReveal(root: RevealRoot, options: ScrollbarRevealOptions = {}): () => void {
  const holdMs = options.holdMs ?? SCROLLBAR_REVEAL_HOLD_MS;
  const timers = new Map<MarkableElement, ReturnType<typeof setTimeout>>();
  const onScroll = (event: { target: unknown }) => {
    const element = isMarkable(event.target) ? event.target : root.documentElement;
    if (!element) return;
    element.setAttribute(SCROLLING_ATTRIBUTE, "");
    const pending = timers.get(element);
    if (pending !== undefined) clearTimeout(pending);
    timers.set(element, setTimeout(() => {
      timers.delete(element);
      element.removeAttribute(SCROLLING_ATTRIBUTE);
    }, holdMs));
  };
  root.addEventListener("scroll", onScroll, { capture: true, passive: true });
  return () => {
    root.removeEventListener("scroll", onScroll, { capture: true });
    for (const [element, timer] of timers) {
      clearTimeout(timer);
      element.removeAttribute(SCROLLING_ATTRIBUTE);
    }
    timers.clear();
  };
}
