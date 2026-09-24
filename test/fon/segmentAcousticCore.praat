sound = Create Sound from formula: "segment-acoustic-core", 1, 0, 1, 44100, ~ 0.5 * sin (2 * pi * 220 * x)
zeroResult$ = temporaryDirectory$ + "/praat-segment-acoustic-core-zero.tsv"
negativeResult$ = temporaryDirectory$ + "/praat-segment-acoustic-core-negative.tsv"
candidateResult$ = temporaryDirectory$ + "/praat-segment-acoustic-core-candidates.tsv"
longSoundResult$ = temporaryDirectory$ + "/praat-segment-acoustic-core-longsound.tsv"
waveFile$ = temporaryDirectory$ + "/praat-segment-acoustic-core.wav"
if fileReadable (waveFile$)
    deleteFile: waveFile$
endif
Write VOT analysis to file: 0, 1, 0, 0, 6, 75, zeroResult$
Write VOT analysis to file: 0, 1, 0.30, 0.28, 6, 75, negativeResult$
Write VOT analysis to file: 0, 1, undefined, undefined, 6, 75, candidateResult$
Save as WAV file: waveFile$
longSound = Open long sound file: waveFile$
Write VOT analysis to file: 0, 1, 0.30, 0.28, 6, 75, longSoundResult$
selectObject: sound, longSound
Remove
deleteFile: waveFile$
