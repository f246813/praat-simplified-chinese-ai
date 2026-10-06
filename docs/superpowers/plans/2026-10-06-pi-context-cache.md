# Pi context/cache implementation plan

**Goal:** Implement the confirmed Python/Pydantic AI design with upstream reuse and measured results.
**Architecture:** SDK messages own protocol history; AnalysisState retains task authority and counters; per-session CloudRuntime owns connections. Local skills append task guidance; HTTP observation measures final serialized requests.
**Tech Stack:** Python 3.12, pydantic-ai-slim[openai]==2.52.0; no SDK upgrade.
**Spec:** ../specs/2026-10-06-pi-context-cache-skills-design.md
**Execution:** Native in this session, as requested. This workspace has no .git; preserve a backend snapshot under backups/pi-context-cache-20261006 instead of commits.

## Global constraints
- Preserve L0–L4, seven report gates and existing automatic repairs, delivery/unknown and correction/exit semantics.
- Shared total request/tool limits and execution state survive phase/skill/compaction changes.
- Filename hints are metadata only and never audio/measurement/dependency evidence.
- Reuse SDK public messages, serialization, usage extraction and runtime; keep upstream versions/licenses.
- Runtime skills live in ai/skills; development skill in .agents/skills/aipraat-prompt-cache.

## Review focus
- Cancelled/failed drafts must not become a new task's authoritative dialogue.
- Output retries must retain protocol history without duplicated goals or orphan tool calls.
- Compression/model/config changes delimit epochs without deleting original evidence.
- Missing usage is null; cached input counts toward context and is never counted twice.
- Multiple audio files/renamed attachments and explicit user corrections retain source binding.

### Task 1: Observe wire requests and preserve baseline
- [x] Save old package, create SDK/localhost regression tests; run RED.
- [x] Add HTTP request fingerprints and per-attempt raw usage observation, reuse SDK RequestUsage.extract.
- [x] Verify missing/inclusive/exclusive usage and per-request deduplication.

### Task 2: Native contexts and session lifecycle
- [x] Use ModelRequest/ModelResponse/ModelMessagesTypeAdapter, pass message_history to Agent.iter.
- [x] Add additive model_events persistence and epoch migration, exclude binaries/drafts from replay.
- [x] Hold one runtime per session, release on configuration change/delete/close; preserve independent cancellation.
- [x] Verify three HTTP turns append complete history with stable static rules and connection reuse.

### Task 3: Task guidance, source metadata and budgeting
- [x] Move existing prosody/placement/failure instructions into locally selected, versioned skills.
- [x] Append goals/materials/evidence after native baseline; share RunUsage/Budget/AnalysisState across phases.
- [x] Preserve original attachment names; conservative filename fallback with user/dictionary precedence.
- [x] Make summary input role-native and preflight phase-aware; preserve originals and increment epochs.
- [x] Run existing guards, delivery, escape, dialogue, modern app/execution regression suites.

### Task 4: Reuse provenance and measurements
- [x] Vendor upstream cache probe and licenses, adapt project developer skill; record necessary glue differences.
- [x] Run final wire verification and live same-model A/B with fixed tasks/settings; preserve count-only metrics.
- [x] Report actual token/cache/time/request results and observed limits; no invented speedup.

Validation result: 237 key regressions; final HTTP append/static-prefix and connection checks passed. Live A/B uses 20 fixed-stage cases (two alternating repeats); dialogue/compaction show gains, measurement/failure do not. Full real agent-loop speedup and default-high gains are not claimed. Details: ../../verification/2026-10-06-pi-context-cache-results.md
