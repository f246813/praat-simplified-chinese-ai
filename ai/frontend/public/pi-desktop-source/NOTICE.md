# PI-Desktop renderer excerpts / LGPL-3.0

This distribution uses renderer-only excerpts from **PI-Desktop**, by its upstream authors/contributors, licensed under GNU LGPL version 3. The excerpts and our modifications remain under LGPL-3.0. See `LICENSE` (LGPL-3.0) and `COPYING` (GPL-3.0, incorporated by LGPL).

Source: https://github.com/vastsa/PI-Desktop
Fixed revision: `0d47d26769ecbeca1c3ab56fa83b58a91de8190e` (research checkout, not a claim to match the user's installed Pi version).

Original files are preserved in `upstream/`:
- `apps/desktop/src/components/ContextMenu.tsx`
- `apps/desktop/src/lib/context-menu.ts`
- `apps/desktop/src/lib/scrollbar-reveal.ts`
- `apps/desktop/src/styles/base.css` (scrollbar rules, lines 126–161)
- `apps/desktop/src/styles/ui-kit.css` (context menu, lines 256–340)

Local modifications (2026-10-03):
- ContextMenu: direct React body portal; remove transcript/TeX selection integrations; explicit sidebar point/trigger; preserve viewport placement, dismissal, focus restoration and keyboard navigation; prevent the trigger's pointerdown from defeating click-to-toggle; avoid refocusing on metadata renders.
- Placement: retain Pi's viewport clamp/rounding, expose only renderer types needed here.
- Scrollbar reveal: logic unchanged, comments/formatting shortened; capture passive scroll and 300ms hold, including timer/attribute cleanup.
- CSS: map Pi theme variables to this project's tokens; reset local button defaults; restore `scrollbar-width/color: auto` to prevent older project rules from overriding the 6px WebKit scrollbar. Quiet transparent track/thumb; hover/focus/scroll reveal.

Project-local `SessionRow` and `sessions.pin` implement dialogue operations using the Praat host, not Pi's Sidebar/store/IPC/Agent runtime. The earlier composer status was project-local adaptation, not this source extraction.

## Replace / rebuild

Production assets include this notice, both licenses, original excerpts, `modified/` (the exact used LGPL source), and `rebuild/` (frontend source/build inputs). The full project also includes `ai/frontend` and its pinned npm lockfile. You may modify/replace these LGPL renderer portions and reverse engineer the combined work for debugging those modifications; this distribution imposes no contrary restriction.

With Node/npm available, in `rebuild/` (or the full project's `ai/frontend`):
1. `npm ci`
2. `node scripts/offline-assets.mjs`
3. `npx tsc -b && npx vite build`
4. Replace the full project's `ai/frontend/dist` with the rebuilt `dist`, preserving these notices/licenses/source; close and reopen the frontend normally from Praat's menu.

The standalone rebuild recipe skips the full project's prebuild notice-copy step because notices/source are supplied beside `rebuild/`. The full project may use `npm run build` instead. No signature, proprietary loader or Pi IPC is required. The local deliverable is an unpacked source project, not a newly released installer. Any future installer must retain these notices and replacement/rebuild capability.
