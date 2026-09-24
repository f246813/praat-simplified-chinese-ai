# Vowel Nasality and Nasal Consonant Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add separately measured, quality-marked vowel-nasality and nasal-consonant features to the shared segment-analysis core and comparison editor.

**Architecture:** Add a focused `fon` module that consumes the common `SegmentInput` and parameter snapshot. It uses Praat's Spectrum/Formant routines and produces per-metric values, reasons and curves; the existing shared editor renders target/reference results and exports the same serialized rows.

**Tech Stack:** Praat C++ core, `Sound_to_Spectrum`, `Sound_to_Formant_burg`, `Formant_getBandwidthAtTime`, native comparison editor, Praat `.praat` tests and the project's Python unittest/template verifier.

**Spec:** `docs/superpowers/specs/2026-09-24-segment-acoustic-analysis-design.md`

## Global Constraints

- Keep vowel nasality and nasal-consonant metrics as separate analysis kinds with no shared score.
- Preserve A1−P0 and A1−P1; add B1 and A3−P0 as individually reported metrics.
- Use the spec's window/frequency settings, record actual values, and require identical parameters for differences.
- Store every metric as raw value + unit + `measured`/`warning`/`unavailable` status + reason; unavailable means no number, zero remains valid.
- Support editable target/reference ranges and optional language/IPA/speaker/neighboring-vowel metadata; never require a language profile.
- Do not calculate “nasalization percentage”, arbitrary weighted scores, cross-speaker normalization or F0 normalization.
- The 0–320/320–5360 Hz nasal-consonant band is a literature-informed descriptive default, not a validated Mandarin classifier.
- Implement in a worktree based on the accepted shared-core commit. At integration, inspect and manually merge any root-worktree edits to shared AI files.

## Review Focus

- A1 and P0 resolving to the same harmonic in a low-F1 vowel: A1−P0 must be unavailable while independently measurable metrics remain.
- No local P1/P0 peak in the recorded search band: return a reason rather than zero or a copied value.
- Silent/too-short segment and zero high-band power: mark only affected metrics unavailable; preserve valid duration.
- Different target/reference sample rates: retain original measurements, warn, and block differences only if common bandwidth/settings fail.
- Low-frequency ratio on Mandarin /m n ŋ/: keep it descriptive and require manually labeled Mandarin validation before making linguistic claims.

---

### Task 1: Create the nasality analysis module and formula tests

**Files:**
- Create: `fon/SegmentAcousticNasality.h`
- Create: `fon/SegmentAcousticNasality.cpp`
- Modify: `fon/praat_Sound.cpp`
- Modify: `fon/Makefile`
- Modify: `fon/meson.build`
- Modify: `fon/Praat_tests_enums.h`
- Modify: `fon/Praat_tests.cpp`
- Test: `test/fon/segmentNasality.praat`

**Interfaces:**
- Consumes: `SegmentInput`, `SegmentMetadata`, `SpectralSettings`, `FormantSettings`, `MetricResult`, `AnalysisResult` from the shared core plan.
- Produces: `AnalysisResult analyseVowelNasality(const SegmentInput &, const VowelNasalityParameters &)` and `AnalysisResult analyseNasalConsonant(const SegmentInput &, const NasalConsonantParameters &)`.
- Testable helpers: `optional<double> SegmentNasality_amplitudeDifferenceDb(optional<double> numeratorAmplitude, optional<double> denominatorAmplitude)` returns `20*log10(numerator/denominator)` only for finite positive amplitudes; and `optional<double> SegmentNasality_lowHighEnergyRatio(constVEC frequencies, constVEC powers, double lowEdge, double splitEdge, double highEdge)`.

- [ ] **Step 1: Add failing formula, status and integration cases**

Add `CHECK_SEGMENT_NASALITY_FORMULAS`. It must call the not-yet-implemented `SegmentNasality_amplitudeDifferenceDb` helper, verify a missing peak produces no value, and verify zero denominator is unavailable. Add `test/fon/segmentNasality.praat` with an A1/P0 and A1/P1 harmonic stack and call the planned object action so the integration case currently fails.

```cpp
const auto differenceDb = SegmentNasality_amplitudeDifferenceDb (0.5, 0.25);
Melder_assert (differenceDb.has_value());
Melder_assert (std::abs (differenceDb.value() - 6.0205999) < 1e-5);
Melder_assert (! SegmentNasality_amplitudeDifferenceDb (0.5, {}).has_value());
Melder_assert (! SegmentNasality_amplitudeDifferenceDb (0.5, 0.0).has_value());
```

- [ ] **Step 2: Run the new formula case and confirm failure**

Run `Praat` > `Praat test...` with `CHECK_SEGMENT_NASALITY_FORMULAS`. Expected: the enum/test case or helper is absent, so the test cannot pass before implementation.

- [ ] **Step 3: Implement A1−P0 and A1−P1 extraction**

For 50 ms configurable windows and 5 ms frame shift, get F1/F2 from the shared Burg settings. A1 is the highest-amplitude harmonic inside the F1 bandwidth; P0 is the harmonic at the strongest local peak in the configurable P0 band (initially 250–450 Hz); P1 is the strongest local-peak harmonic in the P1 band (initially 790–1100 Hz) intersected with the F1–F2 interval. Compute `20*log10(A1/P0)` and `20*log10(A1/P1)` in dB. Return per-frame points and an effective-frame median. If A1 and P0 are the same harmonic, make only A1−P0 unavailable. Register `Write vowel nasality analysis to file...` for Sound/LongSound in `fon/praat_Sound.cpp` and serialize via the shared writer; do not add a Python formula.

- [ ] **Step 4: Implement B1 and A3−P0**

Use the same Formant result for F1/F3 centers and bandwidths. Report B1 from `Formant_getBandwidthAtTime` in Hz. Report `20*log10(A3/P0)` in dB and label it “频谱倾斜相关特征（A3−P0）”; do not label it a global spectral slope. Set a concrete unavailable reason for missing F1/F3/P0 or unreliable frames.

- [ ] **Step 5: Run the Praat test and commit the vowel measures**

Extend `test/fon/segmentNasality.praat` with synthetic harmonic segments whose known amplitudes make expected A1−P0/P1 differences, plus high-vowel harmonic collision and too-short cases. Run the script with the built Praat executable and rebuild.

```powershell
git add fon/SegmentAcousticNasality.h fon/SegmentAcousticNasality.cpp fon/praat_Sound.cpp fon/Makefile fon/meson.build fon/Praat_tests_enums.h fon/Praat_tests.cpp test/fon/segmentNasality.praat
git commit -m "feat: add vowel nasality metrics"
```

### Task 2: Implement the nasal-consonant ratio and duration

**Files:**
- Modify: `fon/SegmentAcousticNasality.h`
- Modify: `fon/SegmentAcousticNasality.cpp`
- Modify: `fon/praat_Sound.cpp`
- Modify: `fon/Praat_tests_enums.h`
- Modify: `fon/Praat_tests.cpp`
- Modify: `test/fon/segmentNasality.praat`

**Interfaces:**
- Produces: `NasalConsonantParameters` with low/high/split frequency, window length, hop, window kind, FFT sizing policy and preprocessing snapshot.
- Duration reads the confirmed absolute start/end on `SegmentMetadata`; ratio is computed frame by frame.

- [ ] **Step 1: Add failing ratio and duration tests**

Add `CHECK_SEGMENT_NASAL_CONSONANT` calling `SegmentNasality_lowHighEnergyRatio` on bins below, at and above `splitEdge`; assert the split bin occurs only in the high-band denominator and that a zero denominator returns no value. Add a script case that invokes `Write nasal consonant analysis to file...` on a marked 80 ms segment; assert the ratio, duration and status fields in its TSV.

```praat
durationMilliseconds = (0.180 - 0.100) * 1000
assert abs (durationMilliseconds - 80) < 0.001
```

- [ ] **Step 2: Implement the frame ratio and summary**

Use `sum(power[f_low <= f < f_split]) / sum(power[f_split <= f <= f_high])`; count the split bin only in the high-band denominator. Use 25 ms Hann windows and 2.5 ms hop; 512 FFT points is the 16 kHz starting setting, while other sample rates choose an FFT size at least as large as their window sample count. Store all effective settings. The segment value is the median of valid frame ratios and the result keeps the frame curve. Register `Write nasal consonant analysis to file...` for Sound/LongSound through the shared writer.

- [ ] **Step 3: Implement duration and quality reasons**

Return `end-start` in seconds in the data and ms in presentation. Keep duration measured when the ratio fails. Return unavailable for zero denominator, silence, empty band intersection or frame shorter than the window; include the specific cause in `MetricResult.reason`.

- [ ] **Step 4: Run tests and commit the nasal-consonant metrics**

Run `CHECK_SEGMENT_NASALITY_FORMULAS`, `Praat.exe --FULL-TRUST --run test/fon/segmentNasality.praat`, and rebuild. Expected: ratio and duration are present independently; no failed metric is serialized as zero.

```powershell
git add fon/SegmentAcousticNasality.h fon/SegmentAcousticNasality.cpp fon/praat_Sound.cpp fon/Praat_tests_enums.h fon/Praat_tests.cpp test/fon/segmentNasality.praat
git commit -m "feat: add nasal consonant measurements"
```

### Task 3: Connect the nasal modes to the native comparison editor

**Files:**
- Modify: `foned/SegmentAcousticEditor.cpp`
- Modify: `foned/SegmentAcousticEditor.h`
- Modify: `fon/praat_Sound.cpp`
- Modify: `ai/praat_ai/tools.py`
- Modify: `ai/tests/test_segment_analysis_tools.py`
- Modify: `ai/tests/verify_segment_analysis_templates.py`
- Test: `test/fon/segmentNasality.praat`

**Interfaces:**
- Consumes: shared target/reference editor and `AnalysisResult`/`ComparisonResult` from the core plan.
- Produces: “元音鼻化” and “鼻辅音” modes with side-specific parameters, results and status text.

- [ ] **Step 1: Add failing UI/adapter scenarios**

Assert the mode selector does not expose one combined nasal score; a changed band or window blocks the difference with reason; opening a reference file keeps target object/range untouched; both target and reference receive the same parameter object.

- [ ] **Step 2: Add the object/AI adapters, vowel mode and optional metadata**

Add AI adapter methods in `ai/praat_ai/tools.py` and tests in `ai/tests/test_segment_analysis_tools.py`; each adapter invokes the matching Sound/LongSound object action without duplicating formulas. Extend `ai/tests/verify_segment_analysis_templates.py` to invoke each action against a synthetic Praat Sound and inspect the shared TSV. Add /a/, /i/, /ə/, other/unknown, language, IPA, speaker and neighboring-vowel fields as optional annotations. Render A1−P0, A1−P1, B1 and A3−P0 with units/status/reason. Do not fail analysis when annotations are empty.

- [ ] **Step 3: Add the nasal-consonant mode and adjustable boundaries/bands**

Show low/high/split band fields, frame settings and segment start/end for each side. Route both Sound-list and native-file sources to `analyseNasalConsonant`; preserve all settings in both `AnalysisResult.parameters` snapshots.

- [ ] **Step 4: Add comparative curves and export assertions**

Use the common renderer for side-by-side values and compatible difference; plot frame curves on relative time 0–100% while exporting the original absolute ranges and duration. Extend the Python verifier to assert each unavailable reason appears in TSV and that no “nasality percent” field exists. Catch Praat and standard C++ exceptions at the Sound/LongSound action, AI adapter and editor callback boundaries; keep other metric rows visible when one metric fails.

- [ ] **Step 5: Run all nasal tests and commit UI integration**

Run the C++/Praat tests, `test_segment_analysis_tools.py`, and the segment template verifier. Rebuild and manually check the two native UI modes on a loaded Sound and a file-opened LongSound.

```powershell
git add fon/praat_Sound.cpp ai/praat_ai/tools.py foned/SegmentAcousticEditor.cpp foned/SegmentAcousticEditor.h ai/tests/test_segment_analysis_tools.py ai/tests/verify_segment_analysis_templates.py test/fon/segmentNasality.praat
git commit -m "feat: add nasal analysis UI and comparison"
```

### Task 4: Validate applicability and update documentation

**Files:**
- Modify: `ai/HANDOFF.md`
- Modify: `ai/README.zh-CN.md`
- Add test data only under: `test/fon/fixtures/nasality/`

- [ ] **Step 1: Define the manually labeled validation table**

Store one row per sample with source, speaker, vowel/consonant class, adjacent vowel, recording conditions, absolute start/end, annotator and metric eligibility. Do not put unlicensed recordings in the repository.

- [ ] **Step 2: Verify the ordinary-sample and failure cases**

Run each metric against same-speaker matched samples where available. Record per-metric missing rate and direction/stability; do not invent cross-speaker thresholds. If Mandarin performance is not validated, label the affected metric experimental and keep it descriptive; do not claim linguistic validity or treat this gate as passed without labeled data.

- [ ] **Step 3: Run the full regression suite and commit the documentation**

Run the full AI suite and template verifier, `Praat` > `Praat test...` with both nasality test cases, the new `.praat` script and the Windows Praat build using the commands below. Update the handoff with evidence/limitations, then commit only the module's code, tests and docs in the implementation worktree.

```powershell
git add ai/HANDOFF.md ai/README.zh-CN.md
git commit -m "docs: record nasality validation and limits"
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

After closing Praat, run `.\Praat.exe --FULL-TRUST --run test/fon/segmentNasality.praat` from the worktree root and invoke `CHECK_SEGMENT_NASALITY_FORMULAS` and `CHECK_SEGMENT_NASAL_CONSONANT` via `Praat` > `Praat test...`.

### Rollback

Follow the shared plan's rollback procedure. Revert only the nasality feature commit(s) in the implementation worktree, close Praat before removing its menu/action registrations, and preserve the accepted shared core and all user recordings, TextGrids and result exports.
