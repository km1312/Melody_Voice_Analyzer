# Results view checklist — run of 2026-09-21

Graded from two screenshots of the Results window on a real 18-minute two-speaker call (the staging build), not from a live walk. No model reply had been imported yet, so the window showed the Import, Speakers and How you sounded tabs; the Notes and Under the surface items cannot be judged until a reply is imported. Items marked *not judged* need either that import or a live session.

| Section | Item | Result | Note |
| --- | --- | --- | --- |
| FR-10 Notes | Summary reads as 3–5 sentences | not judged | No `.insights.json` yet |
| FR-10 Notes | Lines link to turns and cue audio | not judged | Same |
| FR-11 Under the surface | Cards grouped by speaker, names applied | not judged | Same; names would fail anyway, see fix list #2 |
| FR-11 | No numbers on cards | not judged | Same |
| FR-11 | "Nothing notable" looks normal | not judged | Same |
| FR-12 Timeline | One lane per baselined speaker; labels use context names | **fail** | Two lanes, correct; labels are `SPEAKER_00` / `SPEAKER_01` (fix list #2) |
| FR-12 | Tick colours differ by family; silences as bands; pins only where readings sit | **partial** | Four tick colours and grey silence bands are drawn; no pins, correctly, since no readings. Nothing on screen says what the colours mean, and grey is used both for silence bands and for a tick family (fix list #3) |
| FR-12 | Clicking a tick plays from ~1.5 s before the turn | not judged | Needs a live session |
| FR-13 Speakers | Talk-share bars sum to roughly 100% | **pass** | ~72% + ~26% |
| FR-13 | Medians and wpm match the `.md` | not judged | `.md` not to hand |
| FR-13 | No score for non-me speakers | **pass** | Counts and medians only |
| FR-13 | (unlisted) Questions column | **partial** | Counted as turns whose text ends in `?`; a question asked mid-turn is missed, so a speaker who asks and then keeps talking shows 0 (fix list #8) |
| FR-14 Sync | Current turn highlights during playback | not judged | Position label reads the recording's end, consistent with a finished range; cannot see motion in a still image |
| FR-14 | Clicking a turn seeks | **fail** (owner-reported) | Fix list #1 |
| FR-15 Missing media | Controls disabled with a reason | not judged | Skipped on purpose: it renames a source file |
| Import | Truncated reply gives a plain-words error | not judged | Needs a reply to paste |
| Import | Second import writes `(2)` and shows the newer one | not judged | Same |
| Theme | Dark mode readable | not judged | Both screenshots are light mode |
| FR-16 How you sounded | Each row shows this call, usual, and direction | **partial** | "This call" and "Usual" columns present; "Usual" is `-` everywhere (no history yet, correct). The direction column is blank until history exists, so the table reads as two columns (fix list #6) |
| FR-17 | "Building your baseline, n of 8" before 8 calls | not judged | The label exists in code above the table, but the screenshot is scrolled below it; confirm it is visible when the tab opens |
| FR-18 | Per-topic contrast | not judged | Needs topics from an imported reply |
| FR-22 | Self labels on me-speaker moments | **pass** | Yes / No / Not sure per moment with Play; the highlighted "No" buttons are stored answers, not a default (`setChecked(stored == answer)`) |
| Transcript pane | (unlisted) Long turns render fully | **fail** | One long turn is cut with "…" and followed by blank space; a horizontal scroll bar shows despite word wrap (fix list #7) |

## What unblocks the rest

- Import one model reply. The pack is at `<name>.prompt\`; `README.txt` in it says what to paste where. With LM Studio or Ollama installed, the faster route is Settings → Interpretation → provider `openai_compat`, base URL `http://127.0.0.1:1234/v1` (LM Studio) or `http://127.0.0.1:11434/v1` (Ollama), the model's name, then the row's Interpret button. Both are loopback, so the net guard accepts them. The model needs a 32k context.
- Then the Notes, Under the surface, pins, topic contrast and Import items can be judged in one sitting.
