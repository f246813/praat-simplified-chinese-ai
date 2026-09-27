# Japanese VOT accuracy fixture

Keep recordings and the completed `gold_manifest.json` in the local-only
`ai/tests/fixtures/vot/local/` directory. Do not add private recordings or
speaker-identifying metadata to Git. The tracked schema describes the manifest;
the evaluator checks the file hash, WAV sample rate/count, annotation coverage,
and both real entry points before scoring.

## Annotation protocol

Use uncompressed PCM WAV files and annotate boundaries as zero-based sample
indices on that WAV's timeline. At least two annotators label burst release and
voicing onset independently; record their pairs, then store the adjudicated pair
and its uncertainty in samples. Preserve disagreements instead of replacing the
independent annotations with the adjudicated values. Identify Japanese language,
transcript, target phoneme sequence/index, and target selection in every case.

The set must contain positive, zero, and negative VOT, at least one case with
multiple burst candidates, and at least one case with sustained voicing. Mark
ambiguous evidence explicitly and list plausible non-gold pairings in
`alternative_pairs` when annotators can identify them. A numeric result on a
case marked ambiguous is reported as a false single-value decision.

`audio_sha256` is the SHA-256 digest of the exact WAV file bytes. `sample_count`
counts frames per channel, not interleaved scalar values. `target_selection_samples`
is a half-open `[start, end)` pair; it should still contain the complete target
phone. Optional context indices default to the full recording.

## Run

```powershell
$env:PYTHONPATH = 'ai'
& 'D:\Praat-work\venv-ai\Scripts\python.exe' ai/tests/verify_vot_accuracy.py `
  --manifest ai/tests/fixtures/vot/local/gold_manifest.json `
  --praat-exe D:\Praat-work\vot-unified-acceptance\Praat.exe `
  --alignment-config ai/ai_config.json `
  --entrypoints full `
  --report ai/tests/fixtures/vot/local/accuracy_report.json
```

The command loads the same alignment configuration for the editor worker and AI
tool, runs both the native SoundEditor VOT command and registered AI `vot` tool
for every case, and writes per-entrypoint boundary errors, signed VOT error,
sign agreement, misses, wrong pairings, ambiguity decisions, cross-entrypoint
consistency, and annotator disagreement. The report intentionally has no overall
pass/fail accuracy threshold; the threshold must be agreed after reviewing the
annotated results. The previous synthetic `+14 ms` observation is not a gold
label and must not be added as one.

If Praat consumes an editor command without creating its native VOT job, the
report status is `entrypoint_harness_failed` and the CLI exits nonzero. Such a
report is diagnostic only; accuracy conclusions require returned results from
both real entry points for each gold case.
