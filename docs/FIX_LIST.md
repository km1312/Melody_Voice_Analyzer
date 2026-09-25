# Fix list — from the first dogfood pass

2026-09-21. Items found by the owner using the `interpret-phase1` build on a real call, plus the one Phase 1 gap the build status already recorded. Each entry says what was seen, what the code is actually doing (with the file and lines read on 2026-09-21), and the fix. Line numbers drift; the function names will not.

Order is by how much they get in the way of dogfooding, not by size.

| # | Item | Size | Files |
| --- | --- | --- | --- |
| 1 | Cannot jump to another point while audio is playing | S | `revolv/gui_results.py`, `revolv/player.py` |
| 2 | Names from the context panel are not shown in Results | S | `revolv/gui_results.py`, `revolv/gui_context.py`, `revolv/gui.py` |
| 3 | Timeline colours have no legend and one is misleading | S | `revolv/widgets/timeline.py`, `revolv/gui_results.py` |
| 4 | Short interjections ("yeah") from the other speaker are folded into the floor-holder's turn | S for the display fix; owner decision for anything deeper | `revolv/gui_results.py`, and see the note |
| 5 | FR-21 same-person outcome trigger is not wired in the UI | S | `revolv/gui_feedback.py`, `revolv/gui_results.py` |
| 6 | "How you sounded" shows no direction until history exists | XS | `revolv/gui_coaching.py` |
| 7 | Transcript pane truncates long turns and shows a horizontal scroll bar | XS | `revolv/gui_results.py` |
| 8 | Questions column counts only turns that *end* with a question mark | XS | `revolv/gui_results.py` |
| 9 | Coaching baseline row is dated by the day Results was opened | XS | `revolv/gui_coaching.py` |
| 10 | Units and formats on the coaching table | XS | `revolv/gui_coaching.py`, `revolv/coaching.py` |

Items 6 to 10 were found from screenshots on 2026-09-21 (`docs/CHECKLIST_RUN_2026-09-21.md`).

## 1. Cannot jump to another point while audio is playing

**Seen.** In the Results window, clicking a different turn while a range is playing does nothing; you have to press Stop first, then click.

**What the code does.** Two things, one of which is the cause and the other a latent bug that makes it worse.

- `ResultsWindow._follow_position` (`gui_results.py` ~617–628) runs on every 50 ms position tick and, whenever the playing turn differs from the transcript's current row, calls `setCurrentRow(index)` and `scrollToItem(..., PositionAtCenter)`. A mouse click on a transcript line sets the current row on *press*; the next tick sees a mismatch and snaps the selection and the scroll position back to the playing turn before the mouse is *released*. Qt only emits `itemClicked` when press and release land on the same item, so the click is swallowed. Once Stop is pressed the timer stops, nothing fights the selection, and clicks work again. The timeline and the card Play buttons do not go through this path, which is why they may still respond mid-playback.
- `Player._stream_ended` (`player.py` ~198–202) calls `self._teardown()`, which does not exist anywhere in the module. When a range plays to its natural end, the audio thread's finished callback hops to the GUI thread, hits `AttributeError` inside a Qt slot (printed to the log, not fatal), and the player is left in state `playing` with a stopped stream, the 50 ms timer still running and `finished` never emitted. The next `play()` call recovers because it calls `stop()` first, but until then the sync keeps firing against a stale position, which is the worst case for the click problem above.

**Fix.**

1. In `_follow_position`, do not use the list's selection to show the playing turn. Mark the current turn with a background/foreground role on the item (or a "▶" prefix) and keep the user's selection alone. Auto-scroll only when the playing item is outside the visible viewport, not on every change, and suppress auto-scroll for ~2 s after the user scrolls or clicks (an `itemPressed` handler or a `QScrollBar.sliderMoved` hook sets a timestamp).
2. In `player.py`, replace `self._teardown()` with `self.stop()` (which already stops the timer, clears the cursor and sets state `ready`), then emit `finished`. Guard against the old stream's finished callback arriving after a new range has started: have `_on_stream_end` capture the stream object and have `_stream_ended` ignore the call when that object is no longer `self._stream`.
3. Add a test: play range A, then call `play` for range B before A ends, and assert state is `playing`, the cursor is B's, and a late finished-callback for A does not stop B. The fake stream factory in `tests/test_player.py` already makes this possible.

## 2. Names from the context panel are not shown in Results

**Seen.** Speakers appear as `SPEAKER_00` and `SPEAKER_01` in Results after names were typed into the Context window.

**What the code does.** The plumbing exists and is correct as far as it goes: `ContextWindow.collect` (`gui_context.py` ~243–267) writes `speaker_names`, `ResultsData` (`gui_results.py` ~122–142) reads them from the same `<name>.context.json` under the same folder, and the transcript, cards, Speakers tab, notes and timeline all go through `display_name`. The gap is *when* each side does its work:

- The Context window saves only in `closeEvent` (~282–284). While it is open, nothing has been written. The only hint is a footer line, "Closing this window saves it."
- The Results window reads the context once, in its constructor, and has no reload path. `MainWindow._context_saved` (`gui.py` ~1126–1148) reacts to a save by rebuilding the prompt pack, but does not tell an open Results window anything.

So names are applied only if Context is closed *before* Results is opened, and never update an already-open Results window. Both windows can be open at once, which is the natural way to use them, and that order is the one that fails. A second loss path: both windows are children of the main window; closing the app with Context still open destroys it without `closeEvent`, so the names are never written.

**Fix.**

1. Save the context on every change, not on close: connect `textEdited` / `currentIndexChanged` / `toggled` on the fields to a debounced (~500 ms) `save()`. Keep the close-time save as a backstop. Drop the footer sentence or change it to "Saved automatically."
2. Give `ResultsWindow` a `reload_context()` that re-reads the file and re-renders the transcript labels, card headers, Speakers tab, notes owners and timeline lane labels (everything that already calls `display_name`). In `MainWindow`, keep a reference to each job's open Results window and call it from `_context_saved`.
3. Also show a name-less speaker as its label, as now, so an empty name is not an error.
4. Test: open Results, save a context with names, assert the transcript's first item text contains the name.

## 3. Timeline colours have no legend and one is misleading

**Seen.** The coloured marks on the per-speaker bars mean nothing to a viewer.

**What the code does.** `widgets/timeline.py` draws one lane per baselined speaker; each tick is a moment coloured by the family of its *first* note (`moment_family`, ~60–65): pace → `accent`, pitch → `ok_text`, energy → `bad_text`, hesitation → `accent_text`, silence → grey bands across all lanes; pins (readings) use `accent` too (`FAMILY_COLOR_KEYS`, ~31–37; `paintEvent`, ~211–251). Nothing on screen names the families, there is no hover text, and two choices mislead: "energy" borrows the palette's *error* red so an energetic turn reads as "bad", and "pace" and the reading pins share the same accent colour.

**Fix.**

1. Add a legend row under the timeline: one swatch and word per family (pace, pitch, energy, hesitation), a grey band swatch labelled "silence ≥ 2 s", and a pin swatch labelled "reading". Reuse `sectionCount` styling so it stays quiet.
2. Give the four families their own categorical colours in `theme.py` (`LIGHT`/`DARK`), distinct from `accent` and from the ok/bad semantic colours; keep pins on `accent`.
3. Add a tooltip: on hover over a tick, show the moment's notes as the `.md` phrases them ("less energy than usual; more mid-sentence hesitation than usual"), so the colour is a cue and the words are the meaning. `hit_test` already finds the mark; a `QToolTip.showText` in `mouseMoveEvent` with `setMouseTracking(True)` is enough.
4. A moment with notes from two families currently shows one colour. Either draw a split tick or mention "+1" in the tooltip; the tooltip alone is acceptable for now.

## 4. Short interjections from the other speaker are folded into the floor-holder's turn

**Seen.** When SPEAKER_01 says "yeah" during SPEAKER_00's stretch, it is not shown as a SPEAKER_01 turn.

**What the code does.** This is the pipeline behaving as documented, not the new code. `analysis.split_segments_by_speaker` cuts a Whisper segment only where another speaker's words form a *sustained* run: at least `SPLIT_MIN_WORDS = 4` words spanning `SPLIT_MIN_SECONDS = 1.0` s. Anything shorter "stays with whoever held the floor" (README, "Speakers and overlap"), because at segment edges the diarizer mislabels a word or two often enough that splitting on them created more errors than it fixed on the two calls it was tuned on. So a one-word "yeah" keeps its word-level `speaker: SPEAKER_01` tag in the `.json`, but the turn it sits in, the `.md`, and the Results transcript all show it under SPEAKER_00. It *is* counted: the diarization-based overlap classifier records it as a backchannel by SPEAKER_01, which is where the Speakers tab's backchannel figure comes from. A second, smaller case: a "yeah" spoken *over* the other person may never be transcribed at all, because Whisper writes one stream and the merge drops CrisperWhisper-only words that are not anchored to Whisper's; the README lists gap-fill as the next change worth measuring.

**Fix, in two parts.**

1. Display (do now): in `ResultsWindow._fill_transcript`, render the turn from its words rather than its text, and where a run of words carries a different word-level speaker, show it inline with that speaker's name in a muted style, e.g. `Brian: … and then we [Me: yeah] moved on to…`. The word-level speakers are in the `.json` segments, which `ResultsData` already loads; `analysis.build_turns(analysis.split_segments_by_speaker(segments))` gives the words per turn in the same order as the report. Do the same in the `.md`? No: the model view is deliberately per-turn and the verifier's speaker check depends on it. Leave the `.md` alone.
2. Pipeline (owner decision, not Phase 1): lowering `SPLIT_MIN_WORDS`/`SPLIT_MIN_SECONDS` or adding a rule for a whole-word backchannel bounded by silence would change turns, baselines and moments for every recording, and the PRD rules out threshold changes until there are labelled calls. Record the wish in `docs/DECISIONS.md` as a Phase 1.5 item with the measurement it needs: on three or more real calls, count how many sub-4-word other-speaker runs are real interjections versus diarizer edge errors.

## 5. FR-21 same-person outcome trigger is not wired in the UI

**Seen.** Nothing yet; carried over from `PHASE1_STATUS.md`.

**What the code does.** `Store.pending_outcomes(call_ids=...)` accepts the ids of other calls and `gui_feedback.ask_pending_outcomes` (~113–120) passes none, so only the seven-day trigger fires.

**Fix.** When a Results window opens, read the current call's `speaker_names`, scan the other calls in the store (`calls.source_path` gives the `.context.json` location), collect the ids of calls sharing a non-empty name, and pass them as `call_ids`. Names never enter the store; the comparison happens in the caller, which is what the store's comment asks for.

## 6. "How you sounded" shows no direction until history exists

**Seen.** The components table has "This call" and "Usual" columns; with no past calls, "Usual" is `-` on every row and the table looks like two columns.

**What the code does.** `CoachingTab._feature_grid` (`gui_coaching.py` ~190–223) has a fourth column, but it is headed `""` and filled only when both this call's value and a "usual" value exist, with the words "steadier than usual" / "less steady than usual". Before eight calls that column is always empty, so FR-16's "this call, usual, and direction" collapses to "this call".

**Fix.** Head the column "Steadier when" and always show the static direction from `coaching.DIRECTIONS` ("lower", "higher, within your range", "reported only"); once history exists, append the comparison ("· steadier than usual"). Two lines.

## 7. Transcript pane truncates long turns and shows a horizontal scroll bar

**Seen.** One long turn is cut off with "…" and followed by a block of empty space; a horizontal scroll bar sits at the bottom of the pane although text wraps.

**What the code does.** The transcript is a `QListWidget` with `setWordWrap(True)` (`gui_results.py` ~275–278) and nothing else. Qt lays out wrapped item heights for the viewport width at the time items are added; when the splitter or window is resized afterwards the heights are not recomputed, so an item keeps its old height while the delegate elides the text to the new width. The horizontal bar appears for the same reason.

**Fix.** After creating the list: `setResizeMode(QListView.Adjust)`, `setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)`, `setTextElideMode(Qt.ElideNone)`, and `setUniformItemSizes(False)`. If elision persists on very long turns, replace the default delegate with one that returns a `sizeHint` computed from the current viewport width.

## 8. Questions column counts only turns that end with a question mark

**Seen.** A speaker who asks questions inside longer turns shows `0` under Questions.

**What the code does.** `questions_asked` (`gui_results.py` ~57–63) counts turns whose stripped text ends in `?`. The PRD says "questions asked", and the `.md` shows plenty asked mid-turn.

**Fix.** Count sentences ending in `?` within each turn (split on `.`, `?`, `!` after stripping event brackets and pause marks), and label the column "Questions asked". Keep it as a count only; no score.

## 9. Coaching baseline row is dated by the day Results was opened

**Seen.** Nothing yet; found while reading.

**What the code does.** `CoachingTab._store_baseline` (`gui_coaching.py` ~254–267) writes `me_baseline` with `datetime.date.today()`. The row is keyed by `call_id` (so re-opening does not add rows), but its date is when the window was opened, not when the call happened, and re-opening later rewrites it. `me_baseline_rows` orders by that date, so "your past calls" can end up in the wrong order.

**Fix.** Use the recording's date: the `.json`'s or media file's modification time, or the date in the file name when it has one (`YYYY-MM-DD` at the start, as the app's own recordings do). Fall back to today only when neither exists.

## 10. Units and formats on the coaching table

**Seen.** "Statements ending on a rise 0.091" and "Median reply time 0.75" with no unit.

**What the code does.** `FEATURE_LABELS` and the grid print raw floats.

**Fix.** Show shares as percentages ("9%"), seconds with the unit ("0.75 s"), and rates to one decimal. Keep the stored features numeric; only the display changes.

## Not on the list

- The old build in `dist\Melody Tone Analyzer\` predates all of this; the new one is `dist\staging\`. Swap or rename before the next dogfood session so the two are not confused.
