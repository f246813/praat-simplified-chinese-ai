# Exercise the LongSound path through the shared SoundEditor implementation.

longSound = Open long sound file: "examples/example.wav"
selectObject: longSound
View
editor: longSound
information$ = Editor info
assert index (information$, "Editor type: SoundEditor" + newline$)
assert index (information$, "Object type: LongSound" + newline$)
assert index (information$, "Number of channels:")
Close

selectObject: longSound
View
editor: longSound
information$ = Editor info
assert index (information$, "Editor type: SoundEditor" + newline$)
assert index (information$, "Object type: LongSound" + newline$)
Close
Remove
