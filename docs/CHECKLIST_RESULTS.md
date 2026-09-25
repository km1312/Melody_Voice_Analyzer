# Results view — manual checklist (M5)

The automated tests cover loading, arithmetic, sync and import offscreen.
This list is what still needs eyes and ears on a real machine; walk it once
per release with one real call.

## FR-10 Notes

- [ ] Summary reads as 3–5 plain sentences.
- [ ] Every decision / action item / open question / key number line shows a
      (mm:ss) link; clicking it scrolls the transcript there and cues audio.

## FR-11 Under the surface

- [ ] Cards grouped by speaker; names from the context applied.
- [ ] Each card: claim, likelihood *word*, evidence-strength *word*,
      evidence chips, alternatives visible without a click, follow-up, Play.
- [ ] No number, percentage or gauge anywhere on a card (PR-8).
- [ ] A speaker with no readings shows "Nothing notable." and looks normal,
      not apologetic (FR-8).

## FR-12 Timeline

- [ ] One lane per baselined speaker only; labels use context names.
- [ ] Tick colours differ by family (pace / pitch / energy / hesitation);
      silences show as vertical bands; pins only where readings sit.
- [ ] Clicking a tick plays from ~1.5 s before the turn and stops at its end.

## FR-13 Speakers

- [ ] Talk-share bars sum to roughly 100%; medians and wpm match the .md.
- [ ] No score of any kind for non-me speakers.

## FR-14 Sync

- [ ] During playback the current turn highlights and follows.
- [ ] Clicking a transcript turn seeks the audio; the position label moves.

## FR-15 Missing media

- [ ] Rename the source file, reopen Results: play controls disabled with a
      one-line reason; transcript, notes, cards and facts all still there.

## Import

- [ ] Pasting a truncated reply produces a plain-words error naming the key.
- [ ] A valid reply lands on the Notes tab; a second import writes
      `call.insights (2).json` and the window shows the newer one.

## Theme

- [ ] Flip dark mode in Settings with the Results window open, reopen it:
      cards, chips, tabs, timeline and transcript all readable in both.
