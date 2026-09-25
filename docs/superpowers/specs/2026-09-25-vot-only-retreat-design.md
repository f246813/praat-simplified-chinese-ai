# VOT-only rollback design

## Goal

Reduce the recently added segment-analysis work to one supported capability: VOT measurement. Preserve the C++ manual and candidate estimators and the AI `vot` tool. Remove the target/reference comparison editor and its general comparison/overlay framework.

## Retained behavior

- Keep the C++ VOT analyzer, including explicit manual boundaries, zero and negative VOT, automatic burst/voicing candidates, range-aware estimation, HNR handling, metric status/reason values, and the parameter settings that affect those results.
- Keep one visible `VOT` button in the shared SoundEditor toolbar for both Sound and LongSound. Its hidden `VOT...` command is registered in the editor's existing Edit menu so the button can dispatch it without adding a visible menu item.
- The toolbar action accepts a range and either both manual boundaries or neither. It displays the VOT value, burst/voicing times when available, source range, and whether the result is manually measured or needs review in Praat's Info window. It has no result-file field and does not create a user-facing TSV export.
- Keep the script-callable `Write VOT analysis to file...` action registered as hidden from the Objects menu (`GuiMenu_HIDDEN`) but callable by Praat scripts for the AI adapter. It writes the temporary TSV consumed by the AI `vot` tool. Keep atomic replacement for this internal result file.
- Keep Sound and LongSound source identity, absolute range, sample rate, VOT parameters, metric values, units, statuses, and reasons in the internal TSV used by AI.

## Removed behavior and code

- Remove the Sound editor's `辅音分析` menu and target/reference comparison entry. Keep the VOT form reachable from the shared SoundEditor toolbar.
- Remove `SegmentAcousticEditor`, source-pair selection, comparison summaries/exports, normalized time overlays, shared frequency-grid overlays, and comparison-only boundary-confirmation state.
- Remove comparison-only result types and APIs from the acoustic core, including target/reference comparison, compatibility checks, and frequency-curve interpolation, plus analysis categories and unused curve placeholders that have no VOT implementation.
- Remove comparison-only build registrations and scripts/tests. Retain VOT tests for manual and candidate modes, zero/negative/equal boundaries, selected-range behavior, Sound and LongSound, TSV metadata/atomic output, and AI adapter use.
- Keep earlier broad nasality/R design and task-plan documents as historical records; this design supersedes them for the implemented scope. Update `ai/HANDOFF.md` and `ai/README.zh-CN.md` so they describe VOT-only support and do not claim that comparison UI is present. Preserve unrelated uncommitted work in those docs and in the AI source/tests.

## Interfaces and error handling

The SoundEditor toolbar action and hidden AI object action share the same C++ `analyseVOT` implementation and settings validation. The toolbar action formats a summary for Info without writing a file. The hidden object action retains the existing internal TSV contract so AI scripts continue to receive structured values, units, statuses, reasons, and source metadata. Invalid or one-sided boundary input remains an error; explicit zero is valid. Candidate results remain marked for review and are never described as confirmed measurements.

## Archive and verification

After implementation, create `D:\Praat-work\VOT-only-rollback.zip` outside the repository. Include a manifest, the original segment-analysis feature patch and its task briefs/logs being retired, the VOT-only rollback patch, and build/test logs from this change. Do not include executables, user configuration, recordings, the generated `vot-analysis.tsv`, or unrelated uncommitted user files.

Validate with a clang Praat build, the C++ VOT regression scripts, the segment-analysis AI adapter verifier, the full Python test suite, the general chat-template verifier, and `git diff --check`. Confirm Sound and LongSound editor creation and the VOT toolbar action in a live Praat session if available; do not claim UI validation unless actually performed.

## Out of scope

Implementing nasality, nasal-consonant, or R analyzers; scientific validation against annotated Mandarin corpora; changes to unrelated AI tools or uncommitted user work; and adding target/reference comparison back into the VOT flow.
