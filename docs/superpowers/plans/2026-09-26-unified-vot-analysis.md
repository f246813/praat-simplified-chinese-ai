# Unified VOT Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make SoundEditor and the AI `vot` tool submit the same immutable request to one model-alignment and C++ acoustic-analysis service and consume the same result.

**Architecture:** Python owns VOT orchestration because MFA/wav2vec2 already run there; the shared service owns request validation, model evidence, ambiguity and failure status. Praat's C++ core remains the only detector of release and voicing boundaries, reading the exact audio snapshot and sample-index ranges passed by either entry point. The editor submits asynchronous jobs and polls progress; the AI tool uses the same service and acoustic adapter.

**Tech Stack:** Praat C++ (`Sound`, `LongSound`, `SegmentAcousticAnalysis`), Python 3.10+ (`dataclasses`, existing MFA/wav2vec2 backends, `PraatBridge`), Praat script actions, existing `unittest` and Praat test harness.

**Spec:** `docs/superpowers/specs/2026-09-26-unified-vot-analysis-design.md`

## Global Constraints

- “SoundEditor 和 AI 工具各自只有输入/显示适配器，均把规范化请求交给同一服务。”
- “模型对齐定位目标音素，不能把音素开始/结束直接当成 VOT 两边界。”
- “比例分配的区间不得作为模型辅助 VOT 的有效依据。”
- “请求内时间以原音频采样点为规范表示。”
- “分析完成后不自动修改标注；用户点击‘应用’才更新。”
- “此前观察到的 `+14 ms` 不得作为正确答案。”
- Repeatability evidence must come from fresh calculations with result caching disabled.
- The workspace already contains unrelated edits in several VOT files. For each task, stage and commit only that task's new hunks; inspect `git diff --cached` before committing and leave inseparable pre-existing hunks untouched.
- Build the acceptance executable as `D:\Praat-work\vot-unified-acceptance\Praat.exe`, leaving the user's existing `Praat.exe` and any running session untouched.

## Review Focus

- A nonzero audio origin or LongSound context must preserve absolute sample/time mapping. Pin in Task 4 with Sound and LongSound snapshots whose first sample is not time zero.
- Missing, unsupported, or mismatched language/transcript/phoneme metadata must not fall through to proportional timing. Pin in Tasks 1–2 with absent and mismatched metadata cases.
- A selection that clips the aligned phone or lands on a neighboring phone must not produce a single VOT. Pin in Tasks 2–3 with boundary-touching, partial-phone, and adjacent-phone selections.
- A high-frequency path that cannot run must report the path actually used and the fallback reason. Pin in Task 3 with below-band-Nyquist and forced high-band failure cases.
- Audio or selection edits while a model job is pending must prevent a late result from replacing the current result. Pin in Task 5 with a changed audio-version/request-generation test.

---

### Task 1: Preserve model alignment evidence for VOT

**Files:**
- Modify: `ai/praat_ai/models.py`
- Modify: `ai/praat_ai/forced_alignment.py`
- Test: `ai/tests/test_forced_alignment.py`

**Interfaces:**
- Produces: `VOTAlignmentEvidence(results: list[AlignmentResult], backend_errors: list[str], disagreement_threshold_sec: float)` in `models.py` and `CompositeAligner.align_for_vot(audio_path, phones, language, transcript="") -> VOTAlignmentEvidence`.
- `align_for_vot` returns backend results unchanged, never invokes `ProportionalAligner`, and never averages model boundaries or confidence values. Target selection and final ambiguity status are owned by Task 2.

- [x] **Step 1: Write failing alignment-evidence tests**

Add `test_vot_alignment_does_not_use_proportional_fallback`, `test_vot_alignment_retains_dual_results_without_averaging`, `test_vot_alignment_reports_backend_errors`, and `test_vot_alignment_preserves_single_backend_boundaries`. Assert no-model returns no aligned phones, two backends retain their distinct phone times and raw source/confidence fields, and one-backend output is unchanged.

- [x] **Step 2: Run the tests and verify they fail**

Run: `$env:PYTHONPATH='ai'; & 'D:\Praat-work\venv-ai\Scripts\python.exe' -m unittest discover -s ai/tests -p test_forced_alignment.py -v`

Expected: the new `align_for_vot` contract is missing; the existing permissive `align` tests remain unchanged.

- [x] **Step 3: Implement `VOTAlignmentEvidence` and `CompositeAligner.align_for_vot`**

Collect each available backend result and its error. Preserve backend order, raw output, and per-backend provenance. Do not change `CompositeAligner.align` behavior used by pronunciation analysis.

- [x] **Step 4: Run forced-alignment tests**

Run: `$env:PYTHONPATH='ai'; & 'D:\Praat-work\venv-ai\Scripts\python.exe' -m unittest discover -s ai/tests -p test_forced_alignment.py -v`

Expected: all forced-alignment tests pass, including the four new strict VOT evidence tests.

- [x] **Step 5: Commit**

```powershell
git add ai/praat_ai/models.py ai/praat_ai/forced_alignment.py ai/tests/test_forced_alignment.py
git commit -m "feat: preserve forced-alignment evidence for VOT"
```

### Task 2: Add the canonical VOT request, result, and service

**Files:**
- Create: `ai/praat_ai/vot.py`
- Create: `ai/tests/test_vot_service.py`
- Modify: `ai/praat_ai/models.py`

**Interfaces:**
- Consumes: Task 1 `VOTAlignmentEvidence` and `CompositeAligner.align_for_vot(...)`.
- Produces: `VOTMode` (`model_assisted`, `acoustic_only`, `manual`), `VOTAudioSnapshot`, `VOTAnalysisRequest`, `VOTAcousticResult`, and `VOTAnalysisResult`.
- Produces: `VOTAcousticAnalyzer.analyze(request: VOTAnalysisRequest, aligned_phone: VOTAlignedPhone | None) -> VOTAcousticResult` protocol and the Task 2 service methods defined below.
- Request fields: request ID; audio snapshot path/hash, object ID/version, source kind, sample rate/channels/count, snapshot first source sample and original time origin; target-search, acoustic-context, and fixed alignment-context sample-index pairs; language, transcript, phonemes and optional zero-based target-phone index; mode, parameters/model IDs, and optional manual boundary sample indices.
- `VOTStatus`: `candidate`, `ambiguous`, `requires_input`, `target_incomplete`, `failed`, `manual_confirmed`, or `stale`.
- Result fields: request ID/audio hash, status, target phone, burst/onset sample indices, VOT milliseconds, failure reason, all alignment evidence, separate burst/onset boundary sources, negative prevoicing evidence, actual C++ detector provenance, and model/algorithm versions.
- `VOTAlignedPhone(phone_index, ipa, start_sample, end_sample, source, confidence)` carries aligned bounds in original source sample indices. `VOTPreparedAnalysis(request, alignment_evidence, target_phone: VOTAlignedPhone | None, status, reason)`; `VOTAnalysisService.prepare(request, use_cache=False) -> VOTPreparedAnalysis` performs validation and model alignment only.
- `VOTAnalysisService.complete(prepared, acoustic_analyzer) -> VOTAnalysisResult` invokes the acoustic analyzer and maps its structured result. `VOTAnalysisService.analyze(request, acoustic_analyzer, use_cache=False) -> VOTAnalysisResult` composes `prepare` and `complete` and is the synchronous canonical path used by the AI tool. `VOTAnalysisService.confirm_manual(request) -> VOTAnalysisResult` validates and computes `(onset_sample - burst_sample) * 1000 / sample_rate` while retaining both boundary sources.
- `VOTJobState`: `queued`, `aligning`, `ready_for_acoustics`, `completed`, `failed`, or `cancelled`; `VOTJobSnapshot(job_id: str, state: VOTJobState, stage: str, progress: float, prepared_analysis: VOTPreparedAnalysis | None, result: VOTAnalysisResult | None, error: str)`, with progress in `[0.0, 1.0]`.
- Task 2 defines the `VOTJobState` and `VOTJobSnapshot` data types. Task 5 implements the editor coordinator methods using the same `prepare` and `complete` service rules.
- `use_cache=False` forces a fresh alignment and acoustic run; cache keys never replace request/version validation.

- [x] **Step 1: Write failing service tests**

Add `test_missing_alignment_metadata_requires_input`, `test_language_mismatch_is_failure`, `test_transcript_without_phoneme_sequence_requires_input`, `test_partial_target_selection_is_target_incomplete`, `test_adjacent_phone_selection_does_not_guess_target`, `test_invalid_sample_range_returns_failure`, and `test_negative_candidate_requires_prevoicing_evidence`, plus cases for sample-index/time-origin round-trip, model unavailable, dual-model disagreement, explicit acoustic-only bypass, manual positive/zero/negative arithmetic, failed C++ output, cache-disabled repetition, and shared-result serialization. Assert incomplete/invalid cases have no VOT and `use_cache=False` invokes alignment and acoustic analysis on every call.

- [x] **Step 2: Run the service tests and verify they fail**

Run: `$env:PYTHONPATH='ai'; & 'D:\Praat-work\venv-ai\Scripts\python.exe' -m unittest discover -s ai/tests -p test_vot_service.py -v`

Expected: module/types/service are not defined yet.

- [x] **Step 3: Implement the request/result types and synchronous service**

Validate that target/context ranges are increasing, inside the snapshot, and use the same sample axis. For model-assisted requests, require language and usable transcript/phoneme data; consume no proportional fallback. Select only a target phone fully supported by the selection. For multiple models, return `ambiguous` and retain each result if phone counts differ or target boundaries exceed the configured threshold; otherwise select a deterministic backend result without averaging. Do not interpret backend confidence as calibrated VOT confidence. Always invoke the injected acoustic analyzer for accepted model-assisted/acoustic-only work and map its actual status and provenance into `VOTAnalysisResult`; manual mode goes through `confirm_manual` and does not run alignment.

- [x] **Step 4: Run service tests**

Run: `$env:PYTHONPATH='ai'; & 'D:\Praat-work\venv-ai\Scripts\python.exe' -m unittest discover -s ai/tests -p test_vot_service.py -v`

Expected: all service contract tests pass; missing metadata, unsupported alignment, disagreement, and invalid ranges produce explicit nonnumeric results.

- [x] **Step 5: Commit**

```powershell
git add ai/praat_ai/models.py ai/praat_ai/vot.py ai/tests/test_vot_service.py
git commit -m "feat: add shared VOT analysis service"
```

### Task 3: Repair context-aware C++ VOT candidate detection

**Files:**
- Modify: `fon/SegmentAcousticAnalysis.h`
- Modify: `fon/SegmentAcousticAnalysis.cpp`
- Modify: `fon/SegmentAcousticVOT.h`
- Modify: `fon/praat_Sound.cpp`
- Modify: `fon/Praat_tests.cpp`
- Modify: `test/fon/segmentAcousticVOT.praat`

**Interfaces:**
- Consumes: Task 2 request target/context sample ranges and optional aligned-phone range.
- Produces: C++ analysis input carrying the full context Sound plus distinct target-search and aligned-phone ranges; candidate metrics/status preserve original sample indices and absolute times.
- Produces: burst detection provenance fields for the actual selected frequency band and fallback reason.

- [x] **Step 1: Add failing C++ regression fixtures**

Extend `CHECK_SEGMENT_VOT_ESTIMATOR` and the VOT test script with: a target whose first stable voiced frames occur after the old 10 ms threshold; leading pre-voicing in context; target-bounded multiple release candidates; a later unrelated energy rise; sustained/decoy voicing; an incomplete aligned phone; nonzero time origin; high-band unavailable/fallback; and ambiguous candidate pairing. Assert absolute boundary samples, explicit unavailable/ambiguous status, and actual path/reason. Keep positive, zero, and negative manual formula cases.

- [x] **Step 2: Build and run the C++ VOT regression to verify failure**

Run: `& 'C:\msys64\usr\bin\bash.exe' -lc "cd /d/Praat-work/praat-simplified-chinese && mkdir -p /d/Praat-work/vot-unified-acceptance && make EXECUTABLE_FILE=/d/Praat-work/vot-unified-acceptance/Praat.exe PRAAT_COMPILER=clang -j16"`

Then run: `$env:PRAAT_EXE='D:\Praat-work\vot-unified-acceptance\Praat.exe'; & 'D:\Praat-work\venv-ai\Scripts\python.exe' ai/tests/verify_segment_analysis_templates.py`

Expected: the build succeeds, then the new regression assertions fail against the old candidate behavior or absent result provenance. Do not use a previously built executable as evidence.

- [x] **Step 3: Implement contextual, target-bounded acoustic analysis**

Analyze filter, energy, pitch, and HNR over the supplied context while mapping every frame back to the original sample axis. Search and pair releases only near the aligned target. Use pre-context to identify voicing transitions; require target-related prevoicing evidence for negative candidates. Evaluate stable post-onset voicing and HNR as validity evidence. Return `target_incomplete` or `ambiguous` without a VOT for incomplete or multiply plausible pairs. Record the band actually used and why any fallback occurred.

- [x] **Step 4: Rebuild and run C++/template regressions**

Run: `& 'C:\msys64\usr\bin\bash.exe' -lc "cd /d/Praat-work/praat-simplified-chinese && mkdir -p /d/Praat-work/vot-unified-acceptance && make EXECUTABLE_FILE=/d/Praat-work/vot-unified-acceptance/Praat.exe PRAAT_COMPILER=clang -j16"`

Then run: `$env:PRAAT_EXE='D:\Praat-work\vot-unified-acceptance\Praat.exe'; & 'D:\Praat-work\venv-ai\Scripts\python.exe' ai/tests/verify_segment_analysis_templates.py`

Expected: `SEGMENT_ANALYSIS_TEMPLATE_PASS: VOT contract and AI template bridge`; all new candidate statuses, sample mappings, and provenance assertions pass on the newly built executable.

- [x] **Step 5: Commit**

```powershell
git add -p -- fon/SegmentAcousticAnalysis.cpp fon/SegmentAcousticAnalysis.h fon/Praat_tests.cpp fon/praat_Sound.cpp
git add fon/SegmentAcousticVOT.h test/fon/segmentAcousticVOT.praat
git diff --cached --check
git diff --cached
git commit -m "fix: bound VOT candidates to aligned context"
```

### Task 4: Snapshot audio exactly and bridge the C++ analyzer

**Files:**
- Create: `ai/praat_ai/vot_bridge.py`
- Modify: `ai/praat_ai/bridge.py`
- Modify: `fon/SegmentAcousticVOT.h`
- Modify: `fon/praat_Sound.cpp`
- Modify: `ai/tests/test_vot_service.py`
- Create: `ai/tests/test_vot_bridge.py`

**Interfaces:**
- Consumes: Task 2 `VOTAnalysisRequest`/`VOTAcousticAnalyzer`; Task 3 contextual C++ analyzer.
- Produces: `PraatBridge.create_vot_snapshot(object_id, snapshot_start_sample, snapshot_end_sample) -> VOTAudioSnapshot` and `PraatVOTAcousticAnalyzer.analyze(request, aligned_phone: VOTAlignedPhone | None) -> VOTAcousticResult`.
- `VOTAudioSnapshot.snapshot_start_sample` maps absolute source sample indices to cropped PCM. Its conversion methods map between original sample indices and timeline seconds without losing the LongSound offset.
- Snapshot format: JSON manifest plus interleaved little-endian float64 PCM bytes; the content hash covers manifest identity and PCM. `time_origin_seconds` maps the first PCM sample to the source object's original timeline. The snapshot range must cover the acoustic context and fixed alignment context; the target, acoustic-context, and aligned-phone ranges remain source sample indices. The C++ analyzer reads this snapshot rather than re-reading a possibly changed object. Add one registered native action, `VOT analysis snapshot and result: manifest path, PCM path, target start sample, target end sample, context start sample, context end sample, aligned start sample, aligned end sample, parameters JSON, result path`, shared by SoundEditor and `PraatBridge`.

- [x] **Step 1: Write failing snapshot/bridge tests**

Add `test_sound_snapshot_contains_current_samples_and_hash`, `test_longsound_snapshot_preserves_absolute_origin`, `test_snapshot_sample_ranges_are_not_rounded_to_seconds`, and `test_acoustic_bridge_returns_the_cpp_result_contract`. Assert exact PCM round-trip, stable digest, correct sample rate/channel count, nonzero origin preservation, and identical C++ arguments for equal request objects.

- [x] **Step 2: Run bridge tests and verify failure**

Run: `$env:PYTHONPATH='ai'; & 'D:\Praat-work\venv-ai\Scripts\python.exe' -m unittest discover -s ai/tests -p test_vot_bridge.py -v`

Expected: snapshot and analyzer adapter methods are missing.

- [x] **Step 3: Implement shared snapshot writing and C++ acoustic adapter**

Use the same native snapshot writer for current edited Sound and context reads from LongSound. Pass the immutable snapshot, sample-index ranges, aligned phone range, settings, and manual boundaries to the C++ action; parse its structured result without reconstructing boundaries from rounded decimal seconds.

- [x] **Step 4: Run bridge tests and the C++ snapshot action regression**

Run: `$env:PYTHONPATH='ai'; & 'D:\Praat-work\venv-ai\Scripts\python.exe' -m unittest discover -s ai/tests -p test_vot_bridge.py -v`

Then run: `$env:PRAAT_EXE='D:\Praat-work\vot-unified-acceptance\Praat.exe'; & 'D:\Praat-work\venv-ai\Scripts\python.exe' ai/tests/verify_segment_analysis_templates.py`

Expected: all bridge tests pass and the Praat harness reports `SEGMENT_ANALYSIS_TEMPLATE_PASS: VOT contract and AI template bridge` using the new snapshot action.

- [x] **Step 5: Commit**

```powershell
git add ai/praat_ai/vot_bridge.py ai/tests/test_vot_bridge.py
git add -p -- fon/praat_Sound.cpp
git add ai/praat_ai/bridge.py ai/tests/test_vot_service.py fon/SegmentAcousticVOT.h
git diff --cached --check
git diff --cached
git commit -m "feat: analyze immutable VOT audio snapshots"
```

### Task 5: Run editor VOT jobs asynchronously and apply only current results

**Files:**
- Modify: `foned/SoundEditor.cpp`
- Modify: `foned/SoundEditor.h`
- Modify: `sys/PraatAiControl.cpp`
- Modify: `sys/PraatAiControl.h`
- Modify: `ai/praat_ai/vot.py`
- Create: `ai/tests/test_vot_jobs.py`
- Modify: `fon/Praat_tests.cpp`
- Modify: `ai/tests/verify_segment_analysis_templates.py`

**Interfaces:**
- Consumes: Task 2 request/result/job models and Task 4 snapshot/acoustic adapter.
- Produces: `VOTEditorJobCoordinator.submit(request) -> str`, `poll(job_id) -> VOTJobSnapshot`, `complete_acoustics(job_id, acoustic_analyzer) -> VOTJobSnapshot`, and `cancel(job_id) -> bool`; plus `PraatAiControl_submitVOTJob(request_json: str) -> str`, `PraatAiControl_pollVOTJob(job_id: str) -> str` (JSON-serialized `VOTJobSnapshot`), `PraatAiControl_completeVOTJob(job_id: str) -> str` (JSON-serialized `VOTAnalysisResult`), and `PraatAiControl_cancelVOTJob(job_id: str) -> bool`. The model worker stops at `ready_for_acoustics`; polling on the editor event loop then calls `complete_acoustics`, which invokes the registered native C++ action and stores the shared result. SoundEditor retains request generation and applies only a result whose generation, selection samples, audio version, mode and parameters still match.

- [x] **Step 1: Add failing editor lifecycle contract tests**

Add `test_vot_editor_job_lifecycle.py` cases for background alignment, progress, main-thread-only acoustic completion, cancellation and stale-response rejection. Add verifier assertions for the three modes, request generation, separate target/context samples, progress display, explicit failure display, and click-to-apply behavior. Add C++ tests for a late job result after selection/audio version changes; assert that no worker thread calls the native C++ action.

- [x] **Step 2: Run editor contract tests and verify failure**

Run: `& 'D:\Praat-work\venv-ai\Scripts\python.exe' ai/tests/verify_segment_analysis_templates.py`

Expected: the verifier identifies missing job/progress/stale-state contract items.

- [x] **Step 3: Implement the SoundEditor job lifecycle**

Expose model-assisted, acoustic-only, and manual modes; gather available annotation or report which fields are missing. Start the same Python service request without blocking the window, poll progress on the editor event loop, mark old results stale on relevant edits, discard late responses, and update the object only after explicit Apply.

- [x] **Step 4: Rebuild and run editor lifecycle regressions**

Run: `& 'C:\msys64\usr\bin\bash.exe' -lc "cd /d/Praat-work/praat-simplified-chinese && mkdir -p /d/Praat-work/vot-unified-acceptance && make EXECUTABLE_FILE=/d/Praat-work/vot-unified-acceptance/Praat.exe PRAAT_COMPILER=clang -j16"`

Then run: `$env:PRAAT_EXE='D:\Praat-work\vot-unified-acceptance\Praat.exe'; & 'D:\Praat-work\venv-ai\Scripts\python.exe' ai/tests/verify_segment_analysis_templates.py`

Expected: build exits 0 and the verifier reports `SEGMENT_ANALYSIS_NATIVE_PASS: VOT contract and AI local-tool bridge`.

- [x] **Step 5: Commit**

```powershell
git add -p -- foned/SoundEditor.cpp foned/SoundEditor.h sys/PraatAiControl.cpp sys/PraatAiControl.h fon/Praat_tests.cpp ai/tests/verify_segment_analysis_templates.py
git diff --cached --check
git diff --cached
git commit -m "feat: run VOT editor analysis asynchronously"
```

### Task 6: Route AI `vot` through the same service and exact range contract

**Files:**
- Modify: `ai/praat_ai/tools.py`
- Modify: `ai/praat_ai/chat.py`
- Modify: `ai/praat_ai/vot.py`
- Modify: `ai/tests/test_chat_tools.py`
- Modify: `ai/tests/verify_chat_templates.py`

**Interfaces:**
- Consumes: Tasks 2 and 4 `VOTAnalysisService`, `VOTAnalysisRequest`, snapshot builder, and C++ analyzer adapter.
- Produces: the registered `vot` tool builds and submits exactly one canonical request; its parameters cover explicit range/target, language, transcript/phonemes, three modes, manual boundaries, and existing acoustic settings. It returns the same serialized `VOTAnalysisResult` consumed by SoundEditor.

- [x] **Step 1: Add failing AI tool tests**

Add `test_vot_submits_canonical_request`, `test_vot_does_not_replace_explicit_range_with_nearby_selection`, `test_vot_requires_selection_or_explicit_range`, `test_vot_requires_missing_alignment_metadata_or_acoustic_mode`, and `test_vot_returns_ambiguous_and_failed_statuses`. Assert sample indices and exact snapshot identity, not six-decimal script literals. Keep TextGrid manual boundary insertion behavior separate from Sound/LongSound acoustic analysis.

- [x] **Step 2: Run AI VOT tests and verify failure**

Run: `$env:PYTHONPATH='ai'; & 'D:\Praat-work\venv-ai\Scripts\python.exe' -m unittest discover -s ai/tests -p test_chat_tools.py -v`

Expected: tests fail because the current `vot` builder emits the old TSV action and applies the approximate selection heuristic.

- [x] **Step 3: Replace the VOT-only builder path with the shared service**

Resolve exact explicit sample ranges or the exact editor selection once; never use the 2 ms echo rule for VOT and never fall back to the whole audio. Read available language/transcript/phone data, otherwise return a concrete request for it or honor explicit acoustic-only mode. Preserve explicit TextGrid manual-boundary behavior, and do not change other tools' range rules.

- [x] **Step 4: Run AI tool tests and full Python suite**

Run: `$env:PYTHONPATH='ai'; & 'D:\Praat-work\venv-ai\Scripts\python.exe' -m unittest discover -s ai/tests -p test_chat_tools.py -v`

Then run: `$env:PYTHONPATH='ai'; & 'D:\Praat-work\venv-ai\Scripts\python.exe' -m unittest discover -s ai/tests -v`

Expected: VOT tool tests and the full AI suite pass; unrelated tool range behavior remains unchanged.

- [x] **Step 5: Commit**

```powershell
git add -p -- ai/praat_ai/tools.py ai/praat_ai/chat.py ai/tests/test_chat_tools.py ai/tests/verify_chat_templates.py
git add ai/praat_ai/vot.py
git diff --cached --check
git diff --cached
git commit -m "feat: route AI VOT through shared analysis service"
```

### Task 7: Prove cross-entry consistency, repeatability, and selection stability

**Files:**
- Create: `ai/tests/verify_vot_entrypoints.py`
- Modify: `ai/tests/verify_segment_analysis_templates.py`
- Modify: `ai/tests/test_vot_service.py`

**Interfaces:**
- Consumes: editor and AI entry points from Tasks 5–6 and the canonical service result.
- Produces: a verification report recording request hashes, audio/model/algorithm versions, per-boundary sample indices, VOT, status and source for each full entry-point run.

- [ ] **Step 1: Write failing end-to-end acceptance cases**

Add tests that submit the same fixed fixture in model-assisted, acoustic-only, and manual modes through the actual `Praat.exe` SoundEditor VOT window and registered AI `vot` tool, comparing canonical request/result fields in every mode. Run five fresh model-assisted calculations with caching disabled, move each selection edge by up to 5 ms while retaining the same complete phone and assert boundary drift is at most 5 ms, and truncate the target phone and assert `target_incomplete` with no VOT number.

- [ ] **Step 2: Run the acceptance harness against the current build and verify failure**

Run: `& 'D:\Praat-work\venv-ai\Scripts\python.exe' ai/tests/verify_vot_entrypoints.py --praat-exe .\Praat.exe --manifest ai/tests/fixtures/vot/local/entrypoint_manifest.json`

Expected: the current executable/tool do not emit the canonical request/result contract. If the local entry-point manifest is unavailable, the harness exits with a clear missing-fixture message; do not substitute `vot-analysis.tsv` or an internal formula test.

- [ ] **Step 3: Implement the real entry-point harness**

Drive the actual SoundEditor window in the target `Praat.exe` and invoke the registered AI `vot` tool through its Praat bridge. Save each emitted request/result to `ai/tests/fixtures/vot/local/entrypoint-results/`, compare them, and repeat by forcing fresh service instances with caches disabled. Do not use `tools.render`, C++ unit tests, or a recomputed VOT formula as a substitute for either complete entry path.

- [ ] **Step 4: Build the target executable and run the complete acceptance harness**

Run: `& 'C:\msys64\usr\bin\bash.exe' -lc "cd /d/Praat-work/praat-simplified-chinese && mkdir -p /d/Praat-work/vot-unified-acceptance && make EXECUTABLE_FILE=/d/Praat-work/vot-unified-acceptance/Praat.exe PRAAT_COMPILER=clang -j16"`

Then run: `& 'D:\Praat-work\venv-ai\Scripts\python.exe' ai/tests/verify_vot_entrypoints.py --praat-exe D:\Praat-work\vot-unified-acceptance\Praat.exe --manifest ai/tests/fixtures/vot/local/entrypoint_manifest.json --report ai/tests/fixtures/vot/local/entrypoint_report.json --output-dir ai/tests/fixtures/vot/local/entrypoint-results`

Expected: both entry points produce the same normalized request, boundary sample indices, VOT, state, reason and provenance; five independent runs agree; same-phone selection movement stays within 5 ms; incomplete targets have no numeric VOT. Archive the generated report and request/result pairs.

- [ ] **Step 5: Commit**

```powershell
git add ai/tests/verify_vot_entrypoints.py
git add -p -- ai/tests/verify_segment_analysis_templates.py ai/tests/test_vot_service.py
git diff --cached --check
git diff --cached
git commit -m "test: verify complete VOT entry-point consistency"
```

### Task 8: Measure accuracy against independently annotated real speech

**Files:**
- Create: `ai/tests/verify_vot_accuracy.py`
- Create: `ai/tests/test_vot_accuracy.py`
- Create: `ai/tests/fixtures/vot/README.md`
- Create: `ai/tests/fixtures/vot/gold_manifest.schema.json`

**Interfaces:**
- Consumes: Task 7 full-entry-point harness and independently adjudicated audio/label manifest supplied by the user.
- Produces: a per-case report with audio hash, language, VOT class, gold and detected release/onset samples, signed VOT, boundary/VOT absolute errors, candidate miss/wrong-pair and ambiguity results.
- Command interface: `verify_vot_accuracy.py --manifest PATH --praat-exe PATH --entrypoints full --report PATH`; for each case the evaluator invokes Task 7's complete SoundEditor and registered AI tool paths before scoring.

- [ ] **Step 1: Define the blinded annotation manifest and failing evaluator cases**

Define manifest fields for Japanese language, transcript/phones, positive/zero/negative class, multiple release/sustained-voicing flags, two independent annotator boundary pairs, adjudicated boundary samples and uncertainty. Add evaluator cases for each requested class and for ambiguous/missed results. Do not put the earlier `+14 ms` into the manifest as truth.

- [ ] **Step 2: Run evaluator tests and verify they fail**

Run: `$env:PYTHONPATH='ai'; & 'D:\Praat-work\venv-ai\Scripts\python.exe' -m unittest discover -s ai/tests -p test_vot_accuracy.py -v`

Expected: evaluator and manifest validation tests are missing.

- [ ] **Step 3: Implement the accuracy evaluator and fixture instructions**

Report burst and onset errors separately, signed and absolute VOT error, sign agreement, missed candidate rate, wrong release/onset pairing, and cases where the system returned a single value despite ambiguous evidence. Keep user audio and annotations in a local fixture directory unless the user explicitly asks to track them in Git. State the sample count and annotation disagreement in every report; do not claim accuracy without real adjudicated labels.

- [ ] **Step 4: Run accuracy evaluation on the user recording and Japanese real-speech cases**

Run: `& 'D:\Praat-work\venv-ai\Scripts\python.exe' ai/tests/verify_vot_accuracy.py --manifest ai/tests/fixtures/vot/local/gold_manifest.json --praat-exe D:\Praat-work\vot-unified-acceptance\Praat.exe --entrypoints full --report ai/tests/fixtures/vot/local/accuracy_report.json`

Expected: report covers Japanese and positive/zero/negative VOT, multiple burst candidates and sustained voicing. If the user's recording or adjudicated boundaries are not available, report this accuracy task as unverified and request the missing fixture; repository Japanese clips without VOT labels are not substitutes. The local gold manifest and recordings are not staged.

- [ ] **Step 5: Commit**

```powershell
git add ai/tests/verify_vot_accuracy.py ai/tests/test_vot_accuracy.py ai/tests/fixtures/vot/README.md ai/tests/fixtures/vot/gold_manifest.schema.json
git commit -m "test: report VOT accuracy against human labels"
```

## Handoff status — 2026-09-28

- Tasks 1–6 are implemented and committed; Tasks 5–6 have fresh focused verification. The native submit path invokes the short Python launcher, which starts the worker in a detached process and returns; the editor polls state on its event loop and applies only the current job result.
- Task 7 is partially verified through the actual target executable: acoustic-only and manual full-entrypoint results agree; two fresh repeated calculations agree; moving either selection edge inward 4.989 ms keeps boundaries stable; clipping the burst yields a shared nonnumeric failure. Manual positive, zero and negative cases match at exact sample indices. Successful Japanese model-assisted parity remains unverified because no usable Japanese model is configured.
- Task 8 remains unverified because no independently annotated Japanese real-speech cases were supplied. Synthetic data and the earlier `+14 ms` observation are not accuracy labels.
- Fresh checks: `ai/tests/test_vot_jobs.py` 7/7 passed; `ai/tests/verify_segment_analysis_templates.py` reported `SEGMENT_ANALYSIS_NATIVE_PASS: VOT contract and AI local-tool bridge`. The detailed continuation record is `HANDOFF-NEXT-COMPUTER.md`.
- Development is paused at the user's request after the handoff and Git update. The workspace stays on D: for this pause. Resume Task 7's model-assisted success coverage and Task 8 after Japanese model configuration and adjudicated real recordings become available.
