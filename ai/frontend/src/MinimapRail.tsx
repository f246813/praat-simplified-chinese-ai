/**
 * Conversation minimap rail. Wiring only: the vocabulary, thresholds and geometry live
 * in `minimap.ts`, and the row offsets come from the same measurement the mount window uses.
 *
 * The active dash is driven imperatively from a rAF-coalesced scroll handler, and the
 * magnification writes `--magnify` directly, so neither one re-renders React per frame.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type RefObject } from 'react';
import {
  activeMarkerIndex, magnifyScale, markerGap, MINIMAP_ANCHOR_RATIO,
  MINIMAP_JUMP_OFFSET_PX, MINIMAP_POPOVER_SNAP, OVERFLOW_EPSILON_PX, popoverTop, prefersReducedMotion,
  shouldRenderMinimap, type ConversationMarker,
} from './minimap';
import type { RowOffset } from './transcript-window';

export function ConversationMinimap({markers, rows, viewport, hiddenAbove, onRevealEarlier}: {
  markers: ConversationMarker[]; rows: RefObject<RowOffset[]>; viewport: RefObject<HTMLDivElement | null>;
  hiddenAbove: number; onRevealEarlier: () => void;
}) {
  const rail = useRef<HTMLElement>(null);
  const centers = useRef<{y: number; marker: number}[]>([]);
  const [visible, setVisible] = useState(false);
  const [hovered, setHovered] = useState<{marker: number; top: number} | null>(null);

  const markerButtons = useCallback(() => Array.from(rail.current?.querySelectorAll<HTMLButtonElement>('.minimap-marker:not(.history)') || []), []);
  /** Same order as `markers`, so a dash index is a marker index. */
  const topsFor = useCallback(() => {
    const byId = new Map(rows.current.map(row => [row.id, row.top]));
    return markers.map(marker => byId.get(marker.id) ?? Number.POSITIVE_INFINITY);
  }, [markers, rows]);

  /**
   * Dashes carry their own marker index: the rail also holds the "earlier history" entry,
   * so a button index is not a marker index once that entry is present.
   */
  const measureCenters = useCallback(() => {
    let marker = -1;
    centers.current = Array.from(rail.current?.querySelectorAll<HTMLButtonElement>('.minimap-marker') || []).map(button => {
      const isMarker = !button.classList.contains('history');
      if (isMarker) marker += 1;
      return {y: button.offsetTop + button.offsetHeight / 2, marker: isMarker ? marker : -1};
    });
  }, []);

  useLayoutEffect(() => {
    const node = viewport.current;
    if (!node) return;
    let frame = 0;
    const sync = () => {
      frame = 0;
      setVisible(shouldRenderMinimap({markerCount: markers.length, overflows: node.scrollHeight - node.clientHeight > OVERFLOW_EPSILON_PX, hasEarlier: hiddenAbove > 0}));
      const active = activeMarkerIndex(topsFor(), node.scrollTop + node.clientHeight * MINIMAP_ANCHOR_RATIO);
      markerButtons().forEach((button, index) => {
        const on = index === active;
        button.classList.toggle('active', on);
        // aria-current is the state a screen reader can hear; the class is the paint.
        if (on) button.setAttribute('aria-current', 'true'); else button.removeAttribute('aria-current');
      });
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(sync); };
    sync();
    node.addEventListener('scroll', schedule, {passive: true});
    const observer = new ResizeObserver(schedule); observer.observe(node);
    return () => { node.removeEventListener('scroll', schedule); observer.disconnect(); if (frame) cancelAnimationFrame(frame); };
  }, [markerButtons, markers, hiddenAbove, topsFor, viewport]);

  useLayoutEffect(() => { measureCenters(); }, [measureCenters, markers.length, hiddenAbove, visible]);

  useEffect(() => {
    const node = rail.current;
    if (!node || typeof ResizeObserver === 'undefined') return;
    // The rail's own height moves when the composer grows, even though the dashes do not.
    const observer = new ResizeObserver(() => { centers.current = []; measureCenters(); });
    observer.observe(node);
    return () => observer.disconnect();
  }, [measureCenters, visible]);

  const onPointerMove = (event: ReactPointerEvent<HTMLElement>) => {
    const node = rail.current;
    if (!node) return;
    if (!centers.current.length) measureCenters();
    const y = event.clientY - node.getBoundingClientRect().top;
    let nearest = -1; let distance = Number.POSITIVE_INFINITY;
    centers.current.forEach((center, index) => { const gap = Math.abs(center.y - y); if (gap < distance) { distance = gap; nearest = index; } });
    // The dashes widen with the pointer; the preview only appears for the nearest one.
    const buttons = Array.from(node.querySelectorAll<HTMLButtonElement>('.minimap-marker'));
    buttons.forEach((button, index) => button.style.setProperty('--magnify', magnifyScale(centers.current[index].y - y).toFixed(3)));
    const hit = nearest >= 0 && distance <= MINIMAP_POPOVER_SNAP ? centers.current[nearest] : null;
    setHovered(current => {
      const next = hit && hit.marker >= 0 ? {marker: hit.marker, top: popoverTop(hit.y, node.clientHeight)} : null;
      return current?.marker === next?.marker && current?.top === next?.top ? current : next;
    });
  };
  const clearMagnify = () => {
    const node = rail.current;
    if (node) node.querySelectorAll<HTMLButtonElement>('.minimap-marker').forEach(button => button.style.removeProperty('--magnify'));
    setHovered(null);
  };

  const jump = (id: string) => {
    const node = viewport.current;
    if (!node) return;
    const row = rows.current.find(entry => entry.id === id);
    if (!row) return;
    // The jump is a reader action, so it deliberately does not claim the scroll as an
    // internal write: the reading anchor should follow where the reader just went.
    node.scrollTo({top: Math.max(0, row.top - MINIMAP_JUMP_OFFSET_PX), behavior: prefersReducedMotion() ? 'auto' : 'smooth'});
  };

  // Rendering before the first overflow measurement would flash an empty rail.
  if (!visible || (!markers.length && hiddenAbove === 0)) return null;
  const total = markers.length + (hiddenAbove > 0 ? 1 : 0);
  const hoveredMarker = hovered && hovered.marker < markers.length ? markers[hovered.marker] : undefined;
  return <nav ref={rail} className="minimap-rail" aria-label="会话缩略图" style={{'--minimap-gap': `${markerGap(total)}px`} as CSSProperties} onPointerMove={onPointerMove} onPointerLeave={clearMagnify}>
    {hiddenAbove > 0 && <button type="button" className="minimap-marker history" aria-label={`显示更早的 ${hiddenAbove} 条消息`} title={`显示更早的 ${hiddenAbove} 条消息`} onClick={onRevealEarlier}/>}
    {markers.map((marker, index) => <button key={marker.id} type="button" data-marker-id={marker.id} className={`minimap-marker ${marker.role}`} aria-label={`${marker.role === 'user' ? '你说' : '声学助手'}：${marker.preview.slice(0, 40)}`} onClick={() => jump(marker.id)} onFocus={() => setHovered({marker: index, top: popoverTop(centers.current.find(center => center.marker === index)?.y ?? 0, rail.current?.clientHeight ?? 0)})} onBlur={() => setHovered(null)}/>)}
    {hovered && hoveredMarker && <div className="minimap-popover" role="tooltip" style={{top: `${hovered.top}px`}}><div className="minimap-popover-role">{hoveredMarker.role === 'user' ? '你' : '声学助手'}</div><div className="minimap-popover-text">{hoveredMarker.preview}</div></div>}
  </nav>;
}
