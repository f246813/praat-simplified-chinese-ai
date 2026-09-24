# Segment Acoustic Analysis Implementation Roadmap

This roadmap breaks the integrated design into three reviewable implementation plans. All plans implement the same source/result contract in [the design spec](../specs/2026-09-24-segment-acoustic-analysis-design.md). Complete Plan 1 first; after its shared API and editor contracts are accepted, Plans 2 and 3 can proceed independently.

1. [Shared segment core, VOT and comparison UI](2026-09-24-segment-core-vot-comparison.md) establishes source/result types, explicit and estimated VOT, Sound/LongSound actions, AI adapter, the native target/reference editor, overlays and export.
2. [Vowel nasality and nasal-consonant analysis](2026-09-24-nasality-analysis.md) adds A1−P0, A1−P1, B1, A3−P0, low/high energy ratio and segment duration to the shared editor.
3. [R acoustic analysis](2026-09-24-r-acoustic-analysis.md) adds user-selected fricative, affricate and approximant-like r measurement to the same editor.

Plan 1 is a prerequisite for Plans 2 and 3. Plans 2 and 3 may proceed independently after the shared API and editor interfaces are accepted, but both must pass the same comparison, quality-status, export and Mandarin-validation gates. Each plan ends with its own tests, build, documentation update and feature-only commit. Start implementation only after the plans are reviewed and an execution method is selected.
