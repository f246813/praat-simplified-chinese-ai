# R Acoustic Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add class-selected R acoustic measurements for fricatives, affricates and approximant-like r, with raw values and reference differences in the shared C++ editor.

**Architecture:** A focused `fon` module consumes the shared `SegmentInput` and the user's explicit class/boundaries. Fricative and affricate spectral features run only on marked frication windows; approximant formants use the shared Praat Burg implementation. The shared editor and serializer render results without a Mandarin pass/fail threshold.

**Tech Stack:** Praat C++ core, `Sound_to_Spectrum`, `Spectrum_getCentreOfGravity`, `Sound_to_Formant_burg`, native comparison editor, Praat script tests and project Python unittest/template verifier.

**Spec:** `docs/superpowers/specs/2026-09-24-segment-acoustic-analysis-design.md`

## Global Constraints

- Name the feature “R 音声学分析”; do not expose or use “卷舌度” as the feature name.
- Keep implementation in a worktree based on the accepted shared-core commit; at integration, merge any root-worktree edits in changed AI files manually.
- Require explicit choice among fricative, affricate and approximant-like r; unsupported classes return a specific unsupported reason.
- Compute only raw acoustics; do not classify using Mandarin thresholds or describe values as directly measuring tongue curl.
- Mark closure, release time, release-transition end/steady-frication start and frication end independently for affricates.
- Exclude closure and release transient from spectral measures; if steady friction is shorter than one window, preserve durations and mark spectra unavailable.
- Target/reference use compatible bands, windows, preprocessing and formant settings; preserve true absolute times and duration even when curves are plotted on relative time.
- Missing formants, unvoiced frames and low-energy spectra are unavailable with explicit reasons, never zero substitutes.

## Review Focus

- Unsupported class: UI must explain unsupported and must not choose the nearest supported formula.
- Affricate release burst present outside the marked steady-frication interval: COG/peak must not include it.
- Frication interval shorter than one window or silent: retain phase durations but mark all affected spectral metrics unavailable.
- F2/F3 missing or invalid on a frame: keep other valid frames and report gaps/reason rather than plotting zeros.
- Target/reference settings or effective bands differ: keep both sides' values but remove the difference and state why.

---

### Task 1: Add class and boundary types plus unsupported-class tests

**Files:**
- Modify: `fon/SegmentAcousticAnalysis.h`
- Create: `fon/SegmentAcousticR.h`
- Create: `fon/SegmentAcousticR.cpp`
- Modify: `fon/Makefile`
- Modify: `fon/meson.build`
- Modify: `fon/Praat_tests_enums.h`
- Modify: `fon/Praat_tests.cpp`
- Test: `test/fon/segmentRAcoustics.praat`

**Interfaces:**
- Consumes: shared `SegmentInput`, result/status/parameter types and comparison function.
- Produces: `enum class RSegmentClass { Fricative, Affricate, ApproximantR, Unsupported }`, R boundary/settings structs, and `AnalysisResult analyseRSegment(const SegmentInput &, RSegmentClass, const RSegmentParameters &)`.
- `RSegmentBoundaries` has optional `segmentStart`, `releaseTime`, `steadyFricationStart`, `fricationEnd`, and `segmentEnd`; each class validates only its required fields against the source time domain.
- Testable helpers: `bool RAnalysis_areAffricateBoundariesValid(const RSegmentBoundaries &, double sourceStart, double sourceEnd)`, `optional<double> RAnalysis_f3MinusF2(optional<double> f2Hz, optional<double> f3Hz)`, and `optional<double> RAnalysis_spectralCentroid(constVEC frequencies, constVEC powers, double minFrequency, double maxFrequency)`.

- [ ] **Step 1: Add failing class and boundary validation checks**

Add `CHECK_R_SEGMENT_BOUNDARIES` and test `start < release <= frictionStart < end`, object-domain limits, unsupported class, and short steady-frication spans. An unsupported class must return `unavailable` with the class name and must not call a fallback metric.

```cpp
const RSegmentBoundaries valid { 0.10, 0.20, 0.23, 0.40, 0.55 };
const RSegmentBoundaries invalid { 0.10, 0.20, 0.19, 0.40, 0.55 };
Melder_assert (RAnalysis_areAffricateBoundariesValid (valid, 0.0, 0.60));
Melder_assert (! RAnalysis_areAffricateBoundariesValid (invalid, 0.0, 0.60));
```

- [ ] **Step 2: Implement explicit class/boundary parameter types**

Define separate intervals for closure, release time, steady frication, and approximant voice range. Validate them before any DSP call and copy them into the result metadata/parameter snapshot.

- [ ] **Step 3: Run boundary cases and commit the type contract**

Run `Praat` > `Praat test...` with `CHECK_R_SEGMENT_BOUNDARIES`, run `Praat.exe --FULL-TRUST --run test/fon/segmentRAcoustics.praat`, then rebuild.

```powershell
git add fon/SegmentAcousticAnalysis.h fon/SegmentAcousticR.h fon/SegmentAcousticR.cpp fon/Makefile fon/meson.build fon/Praat_tests_enums.h fon/Praat_tests.cpp test/fon/segmentRAcoustics.praat
git commit -m "feat: add R segment classes and boundaries"
```

### Task 2: Implement fricative and affricate spectral features

**Files:**
- Modify: `fon/SegmentAcousticR.cpp`
- Modify: `fon/Praat_tests_enums.h`
- Modify: `fon/Praat_tests.cpp`
- Modify: `test/fon/segmentRAcoustics.praat`

**Interfaces:**
- Produces: COG (Hz), peak frequency (Hz), spread (Hz), flatness (0–1), and phase durations (ms), each with independent quality.
- Reuses the same helper for Fricative and the steady-frication span of Affricate.
- Testable helpers: `RAnalysis_spectralCentroid`, `RAnalysis_spectralPeak`, `RAnalysis_spectralSpread` and `RAnalysis_spectralFlatness` return `optional<double>` and consume frequency/power vectors plus the same `minFrequency`/`maxFrequency` band; an empty/invalid band or zero total power returns no value.

- [ ] **Step 1: Write failing power-spectrum tests**

Add `CHECK_R_SEGMENT_SPECTRA` to `fon/Praat_tests_enums.h` and `fon/Praat_tests.cpp` for the formula case below, invalid/empty bands, silence and the release-exclusion case.

Use known two-tone power bins to assert the power-weighted centroid, the maximum-power peak, the weighted standard deviation and the spectral-flatness formula. Add a high-amplitude release transient before the marked steady-frication segment and assert it cannot affect the result.

```cpp
autoVEC frequencies = raw_VEC (2);
autoVEC powers = raw_VEC (2);
frequencies [1] = 1000.0; powers [1] = 1.0;
frequencies [2] = 3000.0; powers [2] = 3.0;
const double expectedCog = (1000.0 * 1.0 + 3000.0 * 3.0) / 4.0;
const auto centroid = RAnalysis_spectralCentroid (frequencies.get(), powers.get(), 500.0, 4000.0);
Melder_assert (centroid.has_value());
Melder_assert (std::abs (centroid.value() - expectedCog) < 1e-8);
```

- [ ] **Step 2: Implement the shared windowed spectral helper**

For each 25 ms Hann window at 5 ms steps, restrict bins to the user's configured frequency band. Compute `COG=Σ(f·P)/ΣP`, spread `sqrt(Σ(P·(f−COG)^2)/ΣP)`, peak as the max-power bin, and flatness `exp(mean(log(P+ε)))/mean(P+ε)` with `ε=max(P)*1e-12`. Return unavailable when the band has no usable power.

- [ ] **Step 3: Implement affricate phase durations and steady-frication extraction**

Set closure duration to release time minus closure start; release-transition duration to steady-frication start minus release time; frication duration to frication end minus steady-frication start. Send only the steady-frication interval to the spectral helper. If it is shorter than one window, retain the three duration values and mark spectral metrics unavailable.

- [ ] **Step 4: Run spectral tests and commit**

Run the C++ test case, `Praat.exe --FULL-TRUST --run test/fon/segmentRAcoustics.praat`, and rebuild. Verify repeated target/reference calls with identical settings yield matching raw values.

```powershell
git add fon/SegmentAcousticR.cpp fon/Praat_tests_enums.h fon/Praat_tests.cpp test/fon/segmentRAcoustics.praat
git commit -m "feat: measure R frication spectra"
```

### Task 3: Implement approximant-like r formant trajectories

**Files:**
- Modify: `fon/SegmentAcousticR.cpp`
- Modify: `fon/Praat_tests_enums.h`
- Modify: `fon/Praat_tests.cpp`
- Modify: `test/fon/segmentRAcoustics.praat`

**Interfaces:**
- Produces: per-frame F2, F3, F3−F2 values in Hz with absolute frame times, plus relative plotting coordinates.

- [ ] **Step 1: Add failing synthetic formant cases**

Add `CHECK_R_SEGMENT_FORMANTS` for the frame-result helper: verify `RAnalysis_f3MinusF2(1500, 2500)` contains 1000, and verify a frame missing either formant yields no value. Extend `test/fon/segmentRAcoustics.praat` to invoke the Sound action on a stable voiced segment and a segment containing an unvoiced gap; assert that each populated row satisfies `F3−F2 = F3 - F2` and that the gap row has no fabricated zero.

```cpp
const auto f3MinusF2 = RAnalysis_f3MinusF2 (1500.0, 2500.0);
Melder_assert (f3MinusF2.has_value() && f3MinusF2.value() == 1000.0);
Melder_assert (! RAnalysis_f3MinusF2 ({}, 2500.0).has_value());
```

- [ ] **Step 2: Implement common-parameter Burg trajectories**

Run `Sound_to_Formant_burg` with the exact `FormantSettings` from the request. For each valid frame, report F2, F3 and `F3-F2`; attach the reason to missing frames and preserve original timestamps. Do not interpolate across missing voiced/formant frames in the stored result.

- [ ] **Step 3: Run the formant tests and commit**

Run `CHECK_R_SEGMENT_FORMANTS`, the R Praat script and the build. Expected: voiced values are present, unvoiced gaps are unavailable, and target/reference use identical formant settings.

```powershell
git add fon/SegmentAcousticR.cpp fon/Praat_tests_enums.h fon/Praat_tests.cpp test/fon/segmentRAcoustics.praat
git commit -m "feat: add approximant R formant trajectories"
```

### Task 4: Connect class selection, boundaries, comparison and export to the editor

**Files:**
- Modify: `foned/SegmentAcousticEditor.cpp`
- Modify: `foned/SegmentAcousticEditor.h`
- Modify: `fon/praat_Sound.cpp`
- Modify: `ai/praat_ai/tools.py`
- Modify: `ai/tests/test_segment_analysis_tools.py`
- Modify: `ai/tests/verify_segment_analysis_templates.py`
- Modify: `ai/HANDOFF.md`
- Modify: `ai/README.zh-CN.md`

**Interfaces:**
- Consumes: shared target/reference editor, C++ `analyseRSegment`, and `compareCompatibleMetrics`.
- Produces: Sound/LongSound file actions `Write R acoustic analysis to file...`, AI adapters that invoke those actions without reimplementing formulas, R class selector, per-class manual boundary controls, side-by-side metric rows, curves and TSV export.

- [ ] **Step 1: Add failing object-action, adapter and interaction cases**

Register tests in `test_segment_analysis_tools.py` for each supported class, unsupported class, missing reference and reference setting mismatch. Add a Praat template verifier case that creates a Sound, invokes `Write R acoustic analysis to file...`, parses its TSV and checks a raw result/status. Assert the affricate table displays closure/release/frication durations separately and that its plot legend names both sources and intervals. The AI adapter must pass class, source, absolute boundaries and the shared parameter snapshot to the C++ action; it must not calculate a metric in Python.

- [ ] **Step 2: Add Sound/LongSound actions, AI adapter and class-specific editor rows**

Register matching Sound and LongSound actions in `fon/praat_Sound.cpp`; extract only the requested LongSound interval and retain absolute times. Route the AI adapter through those actions. In `foned/SegmentAcousticEditor.cpp`, enable documented boundaries for the selected class. Show `R 音声学分析`; offer only “擦音”, “塞擦音” and “近音类 r”. Keep reference required for compare mode. Do not add a default threshold, probability, correctness label or “卷舌度” field.

- [ ] **Step 3: Add relative-time overlays and reproducible export**

Map each series to relative segment time only for plotting. Export source identity, absolute ranges, class, all boundary points, preprocessing/window/formant parameters, metric values/units/status/reasons, reference difference or incompatibility reason, and metadata.

- [ ] **Step 4: Run core, adapter, template and GUI checks; document limitations**

Run the all-AI suite and segment template verifier from the commands below, `Praat` > `Praat test...` for `CHECK_R_SEGMENT_BOUNDARIES`, `CHECK_R_SEGMENT_SPECTRA`, and `CHECK_R_SEGMENT_FORMANTS`, the R Praat script, and the Windows build. In the native GUI, verify source selection, file loading, range edits, individual/sequential audition, release exclusion and unsupported class messaging. Use manually labeled Mandarin samples when available; otherwise label validity as unverified and keep results descriptive.

- [ ] **Step 5: Commit the R editor integration**

```powershell
git add fon/praat_Sound.cpp ai/praat_ai/tools.py foned/SegmentAcousticEditor.cpp foned/SegmentAcousticEditor.h ai/tests/test_segment_analysis_tools.py ai/tests/verify_segment_analysis_templates.py ai/HANDOFF.md ai/README.zh-CN.md
git commit -m "feat: add R acoustic analysis workflow"
```

### Validation commands

Run these from the implementation worktree root. The project virtual environment is shared from the parent workspace:

```powershell
$venv = 'D:\Praat-work\venv-ai\Scripts\python.exe'
$env:PYTHONPATH = 'ai'; $env:PYTHONIOENCODING = 'utf-8'
& $venv -m unittest discover -s ai/tests
& $venv ai/tests/verify_segment_analysis_templates.py
$env:MSYSTEM = 'CLANG64'
$repoPath = (Get-Location).Path
$drive = $repoPath.Substring(0, 1).ToLowerInvariant()
$msysPath = "/$drive" + $repoPath.Substring(2).Replace('\', '/')
& 'C:\msys64\usr\bin\bash.exe' -lc "cd '$msysPath' && make PRAAT_COMPILER=clang -j16"
```

After closing Praat, run `.\Praat.exe --FULL-TRUST --run test/fon/segmentRAcoustics.praat` from the worktree root and run the three named C++ checks through `Praat` > `Praat test...`.

### Rollback

Follow the shared plan's rollback procedure. Revert only the R feature commit(s) in the implementation worktree, close Praat before removing its menu/action registrations, and preserve the accepted shared core and all user recordings, TextGrids and result exports.
