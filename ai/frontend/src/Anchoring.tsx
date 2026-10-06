/**
 * Transcript scroll machinery. Currently the disclosure anchor; see `scroll.ts`
 * for the adopted PI-Desktop interaction and its constants.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, type RefObject } from 'react';
import { disclosureAnchorOffset, resolveDisclosureAnchor, SCROLL_READING_KEYS, type DisclosureAnchor } from './scroll';

/**
 * Holds the reading position of a transcript row across its own expand/collapse.
 *
 * The anchor is taken in the click handler, before `<details>` flips, and restored
 * from the content's ResizeObserver. It is re-adopted at the settled position after
 * every correction, so a later layout change that does not move the row is a no-op,
 * and a real gesture releases it so streaming growth can never drag the view away
 * from what the user just opened.
 */
export function useDisclosureAnchor(scroller: RefObject<HTMLElement | null>, content: RefObject<HTMLElement | null>) {
  const hold = useRef<{element: HTMLElement; anchor: DisclosureAnchor} | null>(null);
  const measure = useCallback((element: HTMLElement): DisclosureAnchor | null => {
    const node = scroller.current;
    if (!node || !node.contains(element)) return null;
    return {offset: disclosureAnchorOffset(node.getBoundingClientRect().top, element.getBoundingClientRect().top)};
  }, [scroller]);
  const notify = useCallback((element: HTMLElement) => {
    const anchor = measure(element);
    if (anchor) hold.current = {element, anchor};
  }, [measure]);
  const release = useCallback(() => { hold.current = null; }, []);
  const restore = useCallback(() => {
    const node = scroller.current; const current = hold.current;
    if (!node || !current) return false;
    if (!current.element.isConnected) { hold.current = null; return false; }
    const rect = current.element.getBoundingClientRect();
    const frame = {elementOffset: rect.top - node.getBoundingClientRect().top, scrollTop: node.scrollTop, scrollHeight: node.scrollHeight, clientHeight: node.clientHeight};
    const target = resolveDisclosureAnchor(current.anchor, frame);
    if (target !== null) node.scrollTop = target;
    const settled = current.element.isConnected ? measure(current.element) : null;
    hold.current = settled ? {element: current.element, anchor: settled} : null;
    return true;
  }, [measure, scroller]);
  useLayoutEffect(() => {
    const node = content.current;
    if (!node || typeof ResizeObserver === 'undefined') return;
    // The content element, not the scroller: expanding a row changes scrollHeight
    // but leaves the viewport box untouched, so a scroller observer would not fire.
    const observer = new ResizeObserver(() => { restore(); });
    observer.observe(node, {box: 'border-box'});
    return () => observer.disconnect();
  }, [content, restore]);
  useEffect(() => {
    const node = scroller.current;
    if (!node) return;
    const onWheel = () => release();
    const onKeyDown = (event: KeyboardEvent) => { if (!SCROLL_READING_KEYS.has(event.key)) release(); };
    node.addEventListener('wheel', onWheel, {passive: true});
    node.addEventListener('touchstart', onWheel, {passive: true});
    node.addEventListener('keydown', onKeyDown);
    return () => { node.removeEventListener('wheel', onWheel); node.removeEventListener('touchstart', onWheel); node.removeEventListener('keydown', onKeyDown); };
  }, [release, scroller]);
  return notify;
}
