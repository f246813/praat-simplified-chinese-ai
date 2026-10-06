import type { Session } from '../../types';
/** Renderer-only projection of Praat sessions onto Pi's sidebar contracts. */
export interface SessionSummary extends Session { createdAt: string; updatedAt: string; }
export interface SessionMeta { pinned?: boolean; archived?: boolean; }
export interface ProjectMeta { archived?: boolean; }
