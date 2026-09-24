# Shared Segment Core, VOT and Comparison UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the shared C++ segment-analysis contract, migrate VOT into it, and ship the reusable target/reference editor and result/export path.

**Architecture:** `fon` owns source slices, result/status types, VOT calculation and compatibility checks. Sound/LongSound object actions and the native `foned` editor adapt Praat objects to that core; AI tools call the object actions and read the same serialized result. The comparison editor is first made useful for VOT, then the Nasality and R plans add their metric pages.

**Tech Stack:** Praat C++17-style code, Praat `Sound`/`LongSound` and DSP routines, native Praat GUI, Praat scripting actions, Python `unittest` for the AI adapter.

**Spec:** `docs/superpowers/specs/2026-09-24-segment-acoustic-analysis-design.md`

## Global Constraints

- Use absolute source-object time in seconds; preserve the original range through extraction and export.
- Route editor menus, Sound/LongSound object actions and AI tools through the same C++ calculation functions.
- A metric has `measured`, `warning` or `unavailable` status; an unavailable metric has no numeric value, while numeric zero is valid.
- Missing input and explicit numeric zero are distinct; validate times against the source object's domain, not a nonnegative-time rule.
- Compare only identical metric definitions, units and compatible parameters; incompatible values remain visible but receive no difference.
- Do not add whole-utterance phone recognition, automatic class decisions, ordinary-language pronunciation scores, or network/model dependencies.
- Reserve versioned result fields for possible future F0 normalization, but do not compute or display normalized F0 in this work.
- Keep all implementation commits in an isolated worktree created from the recorded `923a32f2a537fdfcaaeb26f59c54efa7139d08c9`; do not copy, stage or reset the current root worktree's uncommitted files.
- Before applying isolated commits back to the live workspace, inspect every path with current user edits and merge those files deliberately; never replace them wholesale.

## Review Focus

- Explicit zero, equal boundaries and negative VOT: test that zero is not a missing-value sentinel, zero VOT returns `0 ms`, and prevoicing returns a negative value.
- A missing or out-of-domain editor selection: test that the UI asks for a range and does not silently analyze the full file.
- Reference-file loading while an editor selection exists: test that target identity, target range and selected Praat object are preserved.
- Sound versus LongSound and sample-rate mismatch: test that both use the same function and that unsupported bandwidth blocks only the difference.
- Analysis or output failure: test that Praat errors become visible messages and never escape a window callback or leave a partial success result.

---

### Task 1: Add the shared result and source contract

**Files:**
- Create: `fon/SegmentAcousticAnalysis.h`
- Create: `fon/SegmentAcousticAnalysis.cpp`
- Modify: `fon/Makefile`
- Modify: `fon/meson.build`
- Modify: `fon/Praat_tests_enums.h`
- Modify: `fon/Praat_tests.cpp`

**Interfaces:**
- Produces: `SourceIdentity`, `SegmentMetadata`, borrowed `SegmentInput`, `AnalysisKind`, `ParameterSnapshot`, `TimeSeries`, `MetricStatus`, `MetricResult`, `AnalysisResult`, `ComparisonResult`, `compareCompatibleMetrics(...)`, and the shared `AnalysisResult_toTsv(...)` formatter.
- `AnalysisResult` contains a `schemaVersion` and generic result/parameter extension points so a later design may add F0 normalization fields without changing current exported columns; this work leaves those future values absent.
- `AnalysisResult` stores metadata by value and must never retain the temporary extracted `Sound *`.
- `fon/Makefile` and `fon/meson.build` must list every new C++ translation unit.

- [x] **Step 1: Add a failing result-contract case**

Add a `CHECK_SEGMENT_ANALYSIS_RESULT` item to `fon/Praat_tests_enums.h`. In `fon/Praat_tests.cpp`, add a case that constructs measured-zero and unavailable metrics, then asserts the zero remains present, unavailable has no value, and incompatible parameter snapshots yield no difference.

```cpp
case kPraatTests::CHECK_SEGMENT_ANALYSIS_RESULT: {
    const MetricResult zero { U"duration", U"ms", 0.0, MetricStatus::measured, U"" };
    const MetricResult missing { U"A1-P0", U"dB", {}, MetricStatus::unavailable, U"no P0 peak" };
    Melder_assert (zero.value.has_value() && zero.value.value() == 0.0);
    Melder_assert (! missing.value.has_value());
} break;
```

- [x] **Step 2: Build to confirm the new case fails to compile**

Run the Windows build command in Task 6 after the test edit. Expected: missing segment-analysis types or enum case; save the build output in the task notes.

- [x] **Step 3: Implement the shared value types and compatibility function**

Define the spec's source, result, parameter-snapshot and comparison types in `fon/SegmentAcousticAnalysis.h`. Implement `compareCompatibleMetrics` in `.cpp`: match rows by metric ID, require identical units and compatibility keys, compute `target - reference` only when both values exist, and preserve each side's status and reason otherwise. Add the source file to both build manifests.

```cpp
struct MetricResult {
    string id, unit;
    optional<double> value;
    MetricStatus status;
    string reason;
};
```

- [x] **Step 4: Add and run the result serialization contract test**

Extend `CHECK_SEGMENT_ANALYSIS_RESULT` to format a synthetic `AnalysisResult` through `AnalysisResult_toTsv(...)`, then assert the schema version, metric ID, measured zero, explicit unavailable field, reason and units. Run `Praat` > `Praat test...` with `CHECK_SEGMENT_ANALYSIS_RESULT`. The script-level writer smoke test moves to Task 4, when the VOT object action is registered.

- [x] **Step 5: Commit the shared contract**

```powershell
git add fon/SegmentAcousticAnalysis.h fon/SegmentAcousticAnalysis.cpp fon/Makefile fon/meson.build fon/Praat_tests_enums.h fon/Praat_tests.cpp
git commit -m "feat: add shared segment analysis contract"
```

### Task 2: Implement explicit VOT semantics in C++

**Files:**
- Modify: `fon/SegmentAcousticAnalysis.h`
- Modify: `fon/SegmentAcousticAnalysis.cpp`
- Modify: `fon/Praat_tests_enums.h`
- Modify: `fon/Praat_tests.cpp`
- Test: `test/fon/segmentAcousticVOT.praat`

**Interfaces:**
- Produces: `AnalysisResult analyseVOT(const SegmentInput &, optional<double> burstTime, optional<double> voicingTime, VOTBoundaryMode)`.
- `manual` requires both explicit boundaries; `estimateCandidates` requires both absent; one-sided input is a field error.

- [x] **Step 1: Write failing VOT boundary cases**

Add `CHECK_SEGMENT_VOT_BOUNDARIES` with expected `+20 ms`, `0 ms` and `-20 ms` cases. Include a source slice whose time domain begins below zero to prove validation uses the object's domain.

```cpp
Melder_assert (votMilliseconds (0.30, 0.32) == 20.0);
Melder_assert (votMilliseconds (0.30, 0.30) == 0.0);
Melder_assert (votMilliseconds (0.30, 0.28) == -20.0);
```

- [x] **Step 2: Implement manual-boundary validation and measurement**

Implement `analyseVOT` so `optional<double>{0.0}` is treated as a supplied time. Check finite values, source-domain bounds, and mode/argument consistency. Return VOT in seconds and milliseconds with burst/voicing timestamps in metadata; do not reject `voicingTime <= burstTime`.

- [x] **Step 3: Run the boundary cases and build**

Run `CHECK_SEGMENT_VOT_BOUNDARIES`, `Praat.exe --FULL-TRUST --run test/fon/segmentAcousticVOT.praat`, then rebuild. Expected: positive, zero and negative VOT assertions pass; missing and out-of-range boundaries fail with specific messages.

- [x] **Step 4: Commit explicit VOT support**

```powershell
git add fon/SegmentAcousticAnalysis.h fon/SegmentAcousticAnalysis.cpp fon/Praat_tests_enums.h fon/Praat_tests.cpp test/fon/segmentAcousticVOT.praat
git commit -m "fix: support zero and negative VOT"
```

### Task 3: Move the current VOT estimate into the shared core

**Files:**
- Modify: `fon/SegmentAcousticAnalysis.h`
- Modify: `fon/SegmentAcousticAnalysis.cpp`
- Modify: `fon/Praat_tests_enums.h`
- Modify: `fon/Praat_tests.cpp`
- Test: `test/fon/segmentAcousticVOT.praat`

**Interfaces:**
- `VOTBoundaryMode::estimateCandidates` takes no explicit boundaries and returns burst and voicing candidates plus per-boundary quality.
- It does not infer phone identity; the user confirms or edits both candidates before accepting a measurement.

- [x] **Step 1: Add synthetic estimator regression cases**

Extend the Praat script with a known 30 ms release-to-voicing signal, a low-pitch case, prevoicing and a transient burst that decays immediately. Assert the stable signal estimates within 5 ms and the transient-only case is `unavailable` or `warning`, not a fabricated precise result.

```praat
Create Sound from formula: "vot30", 1, 0, 1, 44100, ~ if x < 0.30 then 0 else if x < 0.33 then 0.3 * randomGauss (0, 1) else 0.5 * sin (2*pi*220*x) fi fi
```

- [x] **Step 2: Port the existing estimator stages without changing their tested thresholds**

Move the high-band burst-envelope and pitch-onset candidate calculations from `ai/praat_ai/tools.py` into the C++ core. Keep current documented parameters together in a settings struct, preserve the short HNR slice, return each boundary's quality/reason, and keep the candidate times editable in the caller.

- [x] **Step 3: Run synthetic estimator tests and compare with the current baseline**

Run the `Praat` test case and `.praat` script. Compare the current 30 ms fixture against the previous accepted 30/32/32 ms outputs; any difference greater than 5 ms must be explained by the new quality rule before continuing.

- [ ] **Step 4: Commit the shared estimator**

```powershell
git add fon/SegmentAcousticAnalysis.h fon/SegmentAcousticAnalysis.cpp fon/Praat_tests_enums.h fon/Praat_tests.cpp test/fon/segmentAcousticVOT.praat
git commit -m "feat: move VOT estimation into C++ core"
```

### Task 4: Add Sound and LongSound actions plus the AI adapter

**Files:**
- Modify: `fon/praat_Sound.cpp`
- Modify: `ai/praat_ai/tools.py`
- Test: `ai/tests/test_segment_analysis_tools.py`
- Test: `ai/tests/verify_segment_analysis_templates.py`
- Test: `test/fon/segmentAcousticVOT.praat`
- Test: `test/fon/segmentAcousticCore.praat`

**Interfaces:**
- Produces: a native editor action `辅音分析 > VOT...` and Sound/LongSound script action `Write VOT analysis to file...`; both call `analyseVOT` and the shared serializer.
- AI action passes `optional` boundaries without converting zero to missing and passes the result-file path so no Info window is opened.

- [ ] **Step 1: Add Python tests for zero, negative and omitted arguments**

Add adapter tests asserting `burst=0, voicing=0` is rendered as explicit zero, negative VOT boundaries remain unchanged, no-boundary mode selects candidate estimation, and one-sided input raises `ToolError` before script dispatch.

```python
def test_zero_times_are_explicit(self):
    script = tools._build_vot(
        {"object": "Sound tone", "burst": 0.0, "voicing": 0.0},
        self.sound_context,
    )
    self.assertIn("Write VOT analysis to file", script)
    self.assertIn("0.000000", script)
```

- [ ] **Step 2: Run the new adapter tests to confirm they fail**

```powershell
$venv = 'D:\Praat-work\venv-ai\Scripts\python.exe'
$env:PYTHONPATH = 'ai'
& $venv -m unittest ai.tests.test_segment_analysis_tools -v
```

- [ ] **Step 3: Register Sound/LongSound wrappers and replace duplicated AI formulas**

Register matching actions in `fon/praat_Sound.cpp`; extract LongSound only for the requested interval and preserve absolute times. Catch Praat and standard C++ exceptions at the object-action boundary and return a readable error without leaving a partial result. Change `_build_vot_explicit` and `_build_vot_auto` to invoke `Write VOT analysis to file...` and read the result file. Keep AI prose explicit about candidate estimates versus manually confirmed times.

- [ ] **Step 4: Run adapter and real-Praat template tests**

Run the new unittest file and `ai/tests/verify_segment_analysis_templates.py`. The verifier must create a synthetic Sound in Praat, invoke the C++ VOT action, read its TSV and verify schema, metric ID, explicit zero/negative values, units, status and reason. Run both `test/fon/segmentAcousticCore.praat` and `test/fon/segmentAcousticVOT.praat`; the core script must check the same shared formatter through an object action. Expected: no `writeInfoLine`/Info popup and no Python-side acoustic calculation.

- [ ] **Step 5: Commit the entry-point migration**

```powershell
git add fon/praat_Sound.cpp ai/praat_ai/tools.py ai/tests/test_segment_analysis_tools.py ai/tests/verify_segment_analysis_templates.py test/fon/segmentAcousticVOT.praat test/fon/segmentAcousticCore.praat
git commit -m "feat: route VOT tools through C++ analysis"
```

### Task 5: Add the native two-source comparison editor

**Files:**
- Create: `foned/SegmentAcousticEditor.h`
- Create: `foned/SegmentAcousticEditor.cpp`
- Modify: `foned/SoundAnalysisArea.cpp`
- Modify: `foned/Makefile`
- Modify: `foned/meson.build`
- Test: `ai/tests/verify_segment_analysis_templates.py`

**Interfaces:**
- Produces: native “辅音分析” menu entries that open the shared target/reference editor and a target/reference segment descriptor consumed by the `fon` functions.
- Each side owns its source identity, absolute interval, selected analysis kind and playback range; loading one side cannot mutate the other.

- [ ] **Step 1: Add a failing state-preservation integration scenario**

Extend the verifier to start with a selected target interval, load a second Sound as reference, and assert the target object ID and range remain unchanged. Add a separate case for selecting an already-loaded LongSound from the dropdown.

- [ ] **Step 2: Build the source selectors and range state from native Praat APIs**

Create a two-panel native editor. Populate each Sound/LongSound dropdown by enumerating current Praat audio objects and showing their names; add a refresh action. Use `GuiFileSelect_getInfileNames` for “从文件夹读取……”, `Sound_readFromSoundFile` for ordinary files and `LongSound_open` for long files. Store opened sources per panel without replacing the current Praat selection. Catch Praat and standard C++ exceptions in callbacks and convert them to a visible editor error; no exception may escape a window procedure.

- [ ] **Step 3: Add waveform/spectrogram preview, range edits and audition controls**

Use the selected source's waveform and spectrogram; validate `start < end` and source bounds. Add “分别试听” for each panel and “依次试听” for target then reference. Keep the previous target interval immutable when reference selection changes. If preview drawing fails, keep result text visible and report the preview error separately.

- [ ] **Step 4: Run the state-preservation test and a real GUI check**

Run the verifier, build Praat, then manually open a Sound editor with a non-zero selection. Open comparison, change/load only the reference, and confirm the original editor and selection still display the same source/range.

- [ ] **Step 5: Commit the native editor shell**

```powershell
git add foned/SegmentAcousticEditor.h foned/SegmentAcousticEditor.cpp foned/SoundAnalysisArea.cpp foned/Makefile foned/meson.build ai/tests/verify_segment_analysis_templates.py
git commit -m "feat: add native segment comparison editor"
```

### Task 6: Add comparison rows, overlays, export and final regression

**Files:**
- Modify: `fon/SegmentAcousticAnalysis.cpp`
- Modify: `foned/SegmentAcousticEditor.cpp`
- Modify: `ai/tests/test_segment_analysis_tools.py`
- Modify: `ai/tests/verify_segment_analysis_templates.py`
- Modify: `ai/HANDOFF.md`
- Modify: `ai/README.zh-CN.md`

**Interfaces:**
- Produces: a shared comparison renderer for value/unit/difference/status/reason, normalized-time plot coordinates, and TSV/CSV export from `ComparisonResult`.

- [ ] **Step 1: Add compatibility and export tests**

Test equal settings, a changed band edge, different sample rates with a common band, and insufficient Nyquist bandwidth. Assert compatible rows contain `target-reference`; incompatible rows retain both original values, have no difference and name the reason. Assert real interval durations remain unchanged in exported fields.

- [ ] **Step 2: Implement common comparison rows and output serialization**

Use `compareCompatibleMetrics`; add target/reference labels and source/range to each result. Export schema version, source, boundaries, sample rate, channel, analysis kind, parameters, metrics, difference, status and reason. Serialize unavailable values as an explicit empty/NA field, never numeric zero.

- [ ] **Step 3: Add labeled overlays without rewriting source times**

For plots only, map each curve's absolute time interval to 0–100% relative duration. Label color/legend with source name and absolute range. For frequency plots, interpolate onto and record one common frequency grid; retain original sample rates and issue a warning when they differ.

- [ ] **Step 4: Run required regression and build checks**

```powershell
$venv = 'D:\Praat-work\venv-ai\Scripts\python.exe'
$env:PYTHONPATH = 'ai'; $env:PYTHONIOENCODING = 'utf-8'
& $venv -m unittest discover -s ai/tests
& $venv ai/tests/verify_segment_analysis_templates.py
```

Rebuild with Task 6's MSYS2 command and run the two new `test/fon` scripts. Expected: all existing AI tests and templates pass; no user configuration or unrelated fixture is changed.

- [ ] **Step 5: Update handoff, inspect the diff and commit**

Document the shared API/actions, how to run its tests, manual GUI steps, and the remaining Mandarin sample validation gate in `ai/HANDOFF.md` and `ai/README.zh-CN.md`. Review only the isolated worktree diff, then commit the plan deliverable.

```powershell
git add fon/SegmentAcousticAnalysis.cpp foned/SegmentAcousticEditor.cpp ai/tests/test_segment_analysis_tools.py ai/tests/verify_segment_analysis_templates.py ai/HANDOFF.md ai/README.zh-CN.md
git commit -m "feat: add reproducible segment comparison output"
```

### Validation commands and build

Run the Python regression suite and template verifier shown in Task 6 after the implementation tasks. Then build the isolated worktree with the shared command below.

Run from the isolated worktree root, with Praat closed:

```powershell
$env:MSYSTEM = 'CLANG64'
$repoPath = (Get-Location).Path
$drive = $repoPath.Substring(0, 1).ToLowerInvariant()
$msysPath = "/$drive" + $repoPath.Substring(2).Replace('\', '/')
& 'C:\msys64\usr\bin\bash.exe' -lc "cd '$msysPath' && make PRAAT_COMPILER=clang -j16"
```

### Rollback

Perform implementation only in the worktree from the recorded base commit. If a stage fails acceptance, close Praat, remove that stage's menu/action registration or revert its feature-only commit in the worktree, then rerun the prior stage's tests. Discarding the implementation worktree is also safe because it contains no root-worktree user changes. Do not remove result exports, user recordings, TextGrids or other user data as part of rollback.
