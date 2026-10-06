# Codex public thread-section protocol / Apache-2.0

Desktop cloud activation fix (2026-10-04): the modified host now honors an
enabled API configuration in the interactive desktop entry without requiring
a CLI flag. Startup/save never call a provider; the existing explicit test
confirmation, request configuration snapshots, endpoint validation and
restricted standalone service default remain. This is a local host adapter
fix, not upstream Codex UI or agent code.

Archive page completion (2026-10-04): the user's current Codex screenshot is
the layout reference for top search/source/project filters, original group
headers, a no-project bucket, row Delete/Unarchive actions, group menus and
Delete all. Additional complete public `ThreadDeleteParams.ts`,
`ThreadSourceKind.ts` and `ThreadListParams.ts` are preserved/consumed unchanged
with pinned Git blob/SHA-256 records in `upstream/archived-settings/`. Public
sourceKinds filtering maps to the host's desktop chats (appServer) and legacy
records of unknown origin; no cloud/CLI/agent history source is invented.
Menus reuse the existing Pi ContextMenu and installed Radix RadioGroup;
search reuses the existing Codex debounce/generation/compact-ID adapter.
Deletion calls existing sessions.delete. Legacy archive removal uses an
additive deleted flag in modern sidecar metadata; source legacy SQLite remains
read-only and unchanged. Removed legacy entries are absent from list/search
after restart. Modern deletion continues to delete local history/evidence via
the existing cascade. Group/global operations aggregate existing host methods,
with explicit confirmation and partial-failure reporting. The desktop renderer
is not part of the public repository; these are documented local adapters.

Archived settings migration (2026-10-04): the complete generated
`ThreadUnarchiveParams.ts` is preserved unchanged in `upstream/archived-settings/`
with Git blob/SHA-256 provenance and consumed from `src/codex/protocol/`.
`ArchivedSessions.tsx` / `archived-sessions.css` adapt the public settings
documentation and the archive-page screenshot in openai/codex issue #13018:
title, date/project context and trailing neutral Unarchive button. The public
repository does not publish that desktop React settings renderer; no claim is
made that its private UI source was copied. The adapter calls existing Praat
archive/restore RPC, retaining legacy read-only state and section membership.
The entry moves from the Pi sidebar to the existing settings navigation.
Opening a historical chat uses existing session loading with the unsaved-settings
guard. Section-wide restore remains available in the existing section menu.
No new storage, dependency, agent or model runtime is introduced.

Upstream: https://github.com/openai/codex
Fixed revision: `ab45264919aaeb8a421cc156f1a5459ef9d60b72`.
Copyright and author notice: see `UPSTREAM-NOTICE`. License: Apache-2.0 (`LICENSE`).

`upstream/` preserves the listed original files unchanged. `SOURCE.json` records the exact revision, Git blob identities and SHA-256 checksums, verified against that Git tree. The two generated TypeScript files `ThreadSection.ts` and `ThreadSectionAppearance.ts` are copied byte-for-byte into `ai/frontend/src/codex/protocol/` and included in `modified/protocol/` in built assets. The generated headers are retained.

Local adaptation (2026-10-04):
- `HistoryOrganization.tsx` and `organization.css` render section headers, menus, editing, move selection and drag targets using this project's existing React/Pi renderer. The public repository does not supply the Codex desktop React sidebar/menu source. These are local rendering, not copied Codex desktop components.
- `modern_organization.py` implements stable section identity, nullable single membership, append/insert-before ordering with a 1,000,000 position gap, protected built-in pinned section, trimmed nonempty names, 64-byte icon/color limits, and detach-on-section-delete from the public protocol/SQLite/thread-store behavior. UUID generation uses the existing local host UUID4 helper instead of upstream UUID7; section names are additionally limited to 100 characters. Python/storage names and transaction plumbing are adapted to Praat's existing store.
- Public `thread/fork` establishes the independent history-fork operation. The local host snapshots full conversation history into new session/message/activity identities, preserves compressed context and historical evidence, resets draft/reading state, marks live fragments interrupted, and records parent provenance. Optional cutoff-turn and Codex process/worktree options are not implemented in this conversation-menu scope.
- Per-section archive/restore is a local aggregation of conversation archive operations, not a claimed upstream `sections.archive` API. Archiving retains membership and the section; deleting a section detaches conversations without deleting history. Legacy records use modern sidecar metadata; the old database remains read-only.

Sidebar options integration (2026-10-04): `upstream/sidebar-options/` retains
`ThreadSortKey.ts`, `SortDirection.ts` and `ThreadListParams.ts` unchanged, with
Git blob/SHA-256 provenance. The first two are copied byte-for-byte into
`src/codex/protocol/` and consumed by the existing history comparator.
`SidebarOptions.tsx` replaces the old sort icon with the requested Codex menu
hierarchy: organize by project/remote connection/list, and a sort submenu with
the four existing project choices (including exactly one recent-update choice).
The public repository has no desktop React menu/grouping renderer to copy.
Submenu mechanics reuse installed Radix Dropdown Menu 2.1.24 (MIT), its official
Sub/Portal/RadioGroup composition, and existing Pi context-menu styles; the
hierarchy and host preference wiring are local adapters.
`sidebar-origins.ts` uses Pi's existing path normalization and exact
`folderNameFromPath` excerpt to group recorded project/connection origins while
leaving pinned/custom sections intact. The host adds origin columns to its own
SQLite database and validates/persists the grouping preference. This desktop
host currently records its real local workspace; preserved imported remote
metadata can be grouped without starting a remote connector or agent. Missing
legacy project paths remain unknown. Model API endpoints are not connections.

No Codex app-server/CLI/agent/model runtime or Pi Agent kernel is imported or started. The frontend continues to use assistant-ui and explicit Praat host RPC through pywebview/WebView2.

Search replacement (2026-10-04): four complete original Rust files are retained unchanged in
`upstream/search/`, verified by its `SOURCE.json` against pinned Git blobs.
`src/codex/useSessionSearch.ts` translates `tui/src/task_mentions.rs::spawn_search`:
100ms debounce, generation checks before dispatch/after response, host search and title matches.
The existing sidebar consumes compact match IDs rather than fetching every full conversation.
`modern_search.py` translates the escaped case-insensitive literal matcher and user/assistant
text selection in `rollout/src/search.rs`, and matching-results transport in
`thread-store/src/local/search_threads.rs`. Storage adapts JSONL/ripgrep to existing SQLite
JSON rows; no additional engine, index or background service is installed.
Python `re.IGNORECASE` supplies host Unicode matching; this is a Python port, not the Rust regex binary.
`src/codex/literal-matcher.ts` translates `LiteralMatcher::find_ranges` in
`thread-store/src/local/thread_history/search.rs`, retaining linear two-pointer mapping while
adapting byte offsets to DOM UTF-16 offsets (with a length-preserving fast path).
`search.ts` maps these offsets to existing Pi-style DOM highlights; `SearchBar.tsx` reuses
matches while navigating. Mounted-message counting/window-reveal behavior is preserved.
Complete modified frontend/host source ships with originals and notices. These are source
ports with explicit language/storage adaptations, not private Codex desktop React UI.

Search scroll repair (2026-10-04): the local React dependency previously used
the entire session array identity. Reading-position/draft writes and Pi preview
loads replaced that array and unnecessarily restarted the Codex search flow,
temporarily unmounting body-only matches. `useSessionSearch.ts` now derives a
stable key from session identity, title, persisted update time and archive state,
independent of array order. View/preview changes retain results; actual history
changes still invalidate them. The upstream debounce/generation/RPC matcher is
unchanged. This is a repair of the local host-to-React adapter, not new upstream
source or a replacement search engine.

Built assets distribute this notice, original notice/license, pinned source excerpts and modified renderer source in `codex-source/`. Complete frontend build inputs are distributed in `pi-desktop-source/rebuild/` because the used Pi renderer remains under LGPL-3.0; see its own notice for replacement/rebuild instructions. The unpacked project also provides the Python host adaptations and tests. This record makes no claim that inaccessible desktop UI source was copied or that the current checkout is a release/installer.
