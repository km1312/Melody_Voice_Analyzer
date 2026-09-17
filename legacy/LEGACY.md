# Legacy pipeline

A copy of Revolv as it stood on 2026-09-09, before the verbatim recognizer and the
analysis pass were added. Nothing imports it. It is here so output from the old and
new pipelines can be compared on the same recording.

The differences are set out under "What changed, and why" in the top-level README.

Two things to know if you run anything from here:

- `transcript_output.json` in the project root was produced by `VoiceModel.py`,
  which predates even this snapshot. It is older than the code in this folder.
- The audio decoder in this snapshot is already the fixed one. The version before
  it downmixed by averaging raw frame arrays, which misreads packed formats.
