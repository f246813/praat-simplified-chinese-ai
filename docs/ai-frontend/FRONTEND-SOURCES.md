# Modern frontend: sources and adaptation boundaries

Implementation constraint confirmed by the user: for UI work, first inspect
public Codex / PI-Desktop source and copy existing applicable renderer code.
Prefer transporting and connecting proven components over writing replacements.
Limit local adaptations to the current host/data/IPC boundary and clearly record
which original files and fragments are used; never claim inaccessible desktop
source was copied.

## Actual dependencies

Versions are pinned in [`ai/frontend/package.json`](../../ai/frontend/package.json) and its `package-lock.json` (resolved URLs and integrity hashes). Host dependencies are in [`ai/requirements.txt`](../../ai/requirements.txt).

| Capability | Mature implementation / version | Project adaptation | License / source |
| --- | --- | --- | --- |
| Chat runtime, message list, composer state, attachments, scroll following | `@assistant-ui/react` 0.15.23 | `Chat.tsx` external-store runtime; `store.ts` owns host state; no second Agent runtime | MIT; https://github.com/assistant-ui/assistant-ui |
| UI | React / React DOM 19.1.1 | Session sidebar, settings dashboard and task-specific actions | MIT; https://github.com/facebook/react |
| Rich editor / IME / document model | Tiptap core/pm 3.31.4, react/starter-kit 3.6.6; ProseMirror Markdown 1.13.2 | `Composer.tsx`, `editor.ts`: Markdown serialization, IME commit guard, shortcuts, input history, attachment tags | MIT; https://github.com/ueberdosis/tiptap and https://github.com/ProseMirror/prosemirror-markdown |
| Markdown / tables / math | react-markdown 10.1.0, remark-gfm 4.0.1, remark-math 6.0.0 | Safe host-mediated links; external images and raw HTML blocked | MIT; https://github.com/remarkjs/react-markdown |
| Sanitization | rehype-sanitize 6.0.0, DOMPurify 3.2.7 | Sanitize Markdown tree and Mermaid SVG; no executable attachments | MIT (rehype); Apache-2.0 OR MPL-2.0 (DOMPurify); https://github.com/cure53/DOMPurify |
| Math / code | KaTeX 0.16.22, rehype-katex 7.0.1; highlight.js 11.11.1, rehype-highlight 7.0.2 | Offline fonts/styles; trust disabled; copy actions | MIT (KaTeX/rehype); BSD-3-Clause (highlight.js) |
| Diagrams | Mermaid 11.12.0 | Copy official browser ESM and lazy chunks into `public/vendor/mermaid`; load from host origin; strict mode and SVG sanitization | MIT; https://github.com/mermaid-js/mermaid |
| Icons | lucide-react 0.468.0 | Local SVG icons | ISC; https://github.com/lucide-icons/lucide |
| History dropdown submenus | `@radix-ui/react-dropdown-menu` 2.1.24, already installed and now pinned directly | Official Sub/Portal/RadioGroup composition; existing Pi menu styles; host sort/group preferences | MIT; https://www.radix-ui.com/primitives/docs/components/dropdown-menu |
| Desktop shell / .NET bridge | pywebview 6.2.1; pythonnet 3.2.0 | WebView2, loopback assets, source-checked single RPC facade | BSD-3-Clause (pywebview); MIT (pythonnet) |
| Build / tests | Vite 6.3.6, TypeScript 5.9.3, Vitest 3.2.4, Playwright 1.56.1 | Offline production output; bounded fixtures and desktop acceptance | MIT (Vite/Vitest); Apache-2.0 (TypeScript/Playwright) |

The dependency notices generator preserves package-root LICENSE/NOTICE/COPYING texts and KaTeX font notices in `ai/frontend/public/THIRD-PARTY-NOTICES.txt`, also shipped in `dist`. It includes installed non-development dependencies, not a precise tree-shaken bundle inventory. Packages lacking a root license text are explicitly identified with their source URLs; it does not claim to resolve all redistribution obligations automatically.

## PI-Desktop: local source extraction; no bundled application runtime

Search input follow-up (2026-10-04) directly reuses composition-key bypasses
and native text input attributes from `SearchDialog.tsx` / `useAppShellRuntime.tsx`,
and the no-outline rule from `styles/overlays.css`. Full pinned originals are
preserved under `ai/third_party/pi-desktop/upstream/search/` and distributed with
production assets. Search services/Agent runtime are not imported. See
[search input acceptance](SEARCH-INPUT-RESULTS.zh-CN.md).

Search performance follow-up: the earlier project-local sidebar hydration/filter
is replaced by Codex host-search/generation flow and literal matching, adapted
from pinned Rust to React/Python and the existing SQLite boundary. All four exact
originals, hashes and explicit adaptations are preserved in
`ai/third_party/codex/upstream/search/` and Codex NOTICE. See
[search performance acceptance](SEARCH-PERFORMANCE-RESULTS.zh-CN.md).

Search scrolling repair: the local React session-array dependency is replaced
by stable search-relevant metadata, so reading-position writes and Pi preview
loads retain matching rows without dispatching a new search. The existing Codex
debounce/generation and SQLite matcher remain unchanged. See
[scrolling/search acceptance](SEARCH-SCROLL-RESULTS.zh-CN.md).

PI-Desktop research baseline: https://github.com/vastsa/PI-Desktop/tree/0d47d26769ecbeca1c3ab56fa83b58a91de8190e (desktop package 0.16.0, LGPL-3.0). Referenced composer/editor, activity/tool details, transcript scrolling, Markdown and style entry points are recorded in [architecture section 10](CHAT-UI-ARCHITECTURE.zh-CN.md#10-开源来源版本与复用边界).

Initially these interactions were project-local adaptations using assistant-ui/Tiptap/Markdown. The history-menu follow-up directly extracts/adapts `ContextMenu.tsx`, `context-menu.ts`, `scrollbar-reveal.ts`, and context-menu/6px-scrollbar CSS from the fixed PI-Desktop revision. Their LGPL-3.0 sources, originals, full license texts, modification/rebuild notice and replaceable frontend build inputs are retained in [`ai/third_party/pi-desktop/NOTICE.md`](../../ai/third_party/pi-desktop/NOTICE.md) and shipped under `dist/pi-desktop-source`. Session CRUD/pin host integration remains project-local. No global app-store, Electron IPC, plugins, work panels or Agent runtime is bundled. `useSmooth` and the earlier composer status remain project-local adapters, not copied Pi modules. Upstream tests were not run here; local checks are recorded in [SESSION-MENU-RESULTS.zh-CN.md](SESSION-MENU-RESULTS.zh-CN.md).

The transcript right-click menu reuses that same extracted `ContextMenu.tsx` rather than extracting a second copy; only its item vocabulary is project-local (`ai/frontend/src/transcript-menu.ts`), reduced to the actions this host can honour — message mutation, regenerate and branch are deliberately absent because no RPC backs them. See [PI-DESKTOP-GAP-AUDIT.zh-CN.md](PI-DESKTOP-GAP-AUDIT.zh-CN.md) §6.3.

The 2026-10-04 conversation-sidebar follow-up preserves the complete original
`Sidebar.tsx` and 11 dependencies in `upstream/sidebar/`, with byte comparisons
against that same fixed revision. `src/pi/sidebar/` extracts grouping, hover,
armed-delete, preview placement and sidebar CSS, and adapts the conversation
renderer to Praat's existing store/RPC. It includes pin/time groups, sorting,
preview, modifier selection, menus, keyboard controls and host-backed resizing.
The native scrollbar lane is widened to 14px for pointer usability, and the hover
hook repairs pending dismissal when reentering the same row. The full source
and modifications remain in the LGPL distribution described by NOTICE; no Pi
Agent or application store is imported. See [current acceptance](PI-SESSION-SIDEBAR-RESULTS.zh-CN.md).

Long-history windowing and the composer completion interact with PI-Desktop's `lib/transcript-window.ts` / `lib/transcript-reading.ts` and `features/chat/composer/slash-dispatch.ts`. Both are interaction ports implemented as project-local code (`ai/frontend/src/transcript-window.ts`, `completions.ts`). The reading position could not be borrowed as-is: PI stores a transcript reading target of its own, while this contract only had a pixel `scroll`, which stops identifying a place once the transcript is windowed — so `sessions.view` gained a validated `anchor:{messageId,offset}` and the `sessions` table gained an additively migrated column. Command sets and the window budget were reduced to what this host can actually carry out; see §6.4 and §6.5 of the audit.

The conversation minimap is likewise an interaction port (`ai/frontend/src/minimap.ts`, `MinimapRail.tsx`) from PI-Desktop's `ConversationMinimap.tsx` / `lib/conversation-minimap.ts`. No source was copied; the rail is adapted to describe only mounted rows and its "earlier history" dash reveals the next window page rather than fetching an older one. See §6.6 of the audit.

The in-conversation search retains the PI-Desktop `SearchDialog.tsx` / `lib/transcript-search-highlight.ts` interaction and CSS Custom Highlight API so the rendered DOM is never rewritten. Literal matching now uses Codex `LiteralMatcher::find_ranges` translated in `src/codex/literal-matcher.ts`; navigation reuses matches. Its searchable set remains the rendered transcript, so every counted hit can be highlighted and aligned to. Sidebar search separately uses the new host search RPC across persisted conversation text, including unopened and legacy history. See §6.7 of the original audit and current search performance acceptance above.

SillyTavern (AGPL-3.0) and its official screenshot were interaction references for numeric sampling/token controls, not copied source or bundled assets. The project does not include its runtime or stylesheets.

## Codex historical sections and fork (2026-10-04)

Source is fixed to [openai/codex ab452649](https://github.com/openai/codex/tree/ab45264919aaeb8a421cc156f1a5459ef9d60b72).
The public tree supplies thread-section types, create/update/delete/move handlers,
SQLite membership/order rules and thread-fork contracts, but does not supply the
desktop React sidebar/menu components. `ThreadSection.ts` and
`ThreadSectionAppearance.ts` are copied byte-for-byte; section semantics are
adapted to the existing local SQLite host. The React headers, edit/move menus,
archive aggregation and full-history snapshot fork use this project's existing
assistant-ui/Pi renderer and host RPC. No Codex/Pi Agent core is loaded.

Original Apache-2.0 license/notice and 14 pinned source files, verified against
Git blob ids and SHA-256, are in [Codex source notice](../../ai/third_party/codex/NOTICE.md)
and shipped under `dist/codex-source/`, including modified renderer/host source.
Existing Pi source/rebuild distribution remains intact. The exact public/private
source boundary, host behavior and acceptance are recorded in
[Codex history results](CODEX-HISTORY-SECTIONS-RESULTS.zh-CN.md).

## Sidebar options (2026-10-04)

The sort double-arrow is replaced by the requested ellipsis menu with two real
flyout submenus. Organization modes are project, remote connection and list;
the four existing sort modes remain, without duplicating recent update.
Public Codex `ThreadSortKey.ts` and `SortDirection.ts` are copied unchanged and
consumed by sorting; `ThreadListParams.ts` is preserved as the cwd/filter
protocol reference. Public Codex does not publish the desktop React menu/grouping
source. Flyout placement, pointer grace, dismissal and keyboard control reuse
Radix's already installed component. Pi path normalization and an exact
`folderNameFromPath` extraction supply project labels. Local glue projects
stored origin metadata and validates/persists preferences. Originals, hashes
and modified source are distributed with production assets.
See [sidebar options acceptance](SIDEBAR-OPTIONS-RESULTS.zh-CN.md).

## Window partition resizing: interaction reference, project-local implementation

PI-Desktop's sidebar separator (`lib/sidebar-resize.ts`, `lib/sidebar-preferences.ts`) and centered conversation band (`packages/shared/src/chat-content-width.ts`, `components/ConversationWidthHandles.tsx`) were read at the same fixed revision, but **no source was copied**. Only the interaction and its bounds are adopted (240/272/520 sidebar with a 160px collapse threshold and 16px steps; 560px band minimum with 24px gutters and 1px pointer → 2px band). PI persists the sidebar width in `localStorage`; this host cannot, because pywebview runs WebView2 with `private_mode=True` and deletes the user data folder on close, so both widths are stored in the host `preferences` whitelist. Implementation: `ai/frontend/src/layout.ts`, `ai/frontend/src/Panes.tsx`; full audit in [PI-DESKTOP-GAP-AUDIT.zh-CN.md](PI-DESKTOP-GAP-AUDIT.zh-CN.md). No new LGPL-covered file was added.

## Pi model data only

Four official OpenAI model window/output records and a local budget policy are adapted from the pinned `@mariozechner/pi-ai` 0.73.1 publication. Exact publication hash, gitHead, license-text provenance and endpoint restrictions are in [PI-MODEL-SOURCES.md](PI-MODEL-SOURCES.md); retained MIT text is [`ai/third_party/pi-ai-LICENSE`](../../ai/third_party/pi-ai-LICENSE).

No Pi package or Pi Agent core is a production dependency. The Python Pydantic AI/Graph and local client remain the executors. Unknown models and gateways with same-named models do not inherit official endpoint metadata.
