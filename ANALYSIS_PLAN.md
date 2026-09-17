# Transcript analysis: plan and reasoning

**Status:** proposal. Nothing in this document has been built.
**Scope:** a derived-analysis pass over existing transcript output, plus a
model-facing output format. The transcription pipeline itself is untouched.

---

## 1. The problem

The `.json` a run produces today is faithful and close to unreadable. It is a flat
list of Whisper segments, each carrying its text, a full word-by-word timing array,
pacing figures and three emotion scores. Two things follow from that:

- **It is too large to hand to a language model.** A 28-minute call comes to roughly
  137,000 tokens. An hour would be near 290,000.
- **It reads as fragments, not conversation.** Whisper cuts roughly every four
  seconds regardless of who is speaking or whether a sentence finished.

Both are fixable without changing what the pipeline records.

---

## 2. What the measurements say

All figures below come from `transcript_output.json`, a real 28.1-minute
two-speaker call: 446 segments, 4,359 word entries.

### Where the bytes go

| Rendering | Bytes | Share | Approx. tokens |
| --- | ---: | ---: | ---: |
| Full JSON as written today | 549,486 | 100% | 137,000 |
| Without the `words` array | 151,540 | 27.6% | 38,000 |
| Without words, pacing and emotion | 65,069 | 11.8% | 16,000 |
| Spoken text characters only | 23,291 | 4.2% | 5,800 |
| Rendered as speaker turns | 25,982 | 4.7% | 6,500 |

Word timings are 72% of the file. The words actually spoken are 4%.

Token counts are characters divided by four, an estimate, not a tokenizer run.

### Fragmentation

| Measure | Value |
| --- | ---: |
| Segments | 446 |
| Speaker turns after merging | 107 |
| Reduction in blocks | 4.2x |
| Mean words per segment | 9.8 |
| Mean words per turn | 40.7 |
| Segments of 3 words or fewer | 110 (25%) |

That last row matters beyond readability. A quarter of segments are short enough
that the emotion model is scoring roughly a second of audio, at or below the one
second its convolutional stack needs. Examples from this call: "Yes.", "Yep.",
"Okay.", "As always."

### Pauses

| Measure | Value |
| --- | ---: |
| Word-to-word gaps measured | 3,913 |
| Median gap | 0.04s |
| 90th percentile | 0.20s |
| 99th percentile | 0.94s |
| Longest mid-sentence gap | 4.73s |
| Gaps of 1s or more, inside a segment | 35 |
| Gaps of 1s or more, at segment boundaries | 86 |
| **Share of long pauses needing word timings** | **29%** |

Longest mid-sentence hesitations in this call, all from the same speaker:

```
[14:17] 4.73s   ...What, <PAUSE> are...
[02:22] 4.46s   ...the <PAUSE> presentation...
[24:05] 4.26s   ...for <PAUSE> just...
```

Turn-taking latency, visible without word timings:

| Gap type | Count | Median | 90th percentile |
| --- | ---: | ---: | ---: |
| Same speaker continuing | 339 | 0.30s | 1.28s |
| Speaker change | 106 | 0.47s | 1.80s |

### Pacing

Across the 218 segments with eight or more words, the ratio of fastest to slowest
word rate *inside a single segment* has a median of **9x**. One words-per-minute
figure per segment hides a great deal.

### Emotion distribution

| Dimension | Mean | SD | Min | Max | Below 0.5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Valence | 0.582 | 0.127 | 0.209 | 0.984 | 25% |
| Arousal | 0.573 | 0.094 | 0.000 | 0.817 | 21% |
| Dominance | 0.605 | 0.077 | 0.147 | 0.818 | 5% |

Per speaker:

| Speaker | n | Valence | Arousal |
| --- | ---: | --- | --- |
| SPEAKER_00 | 205 | 0.584 ± 0.141 | 0.613 ± 0.094 |
| SPEAKER_01 | 241 | 0.580 ± 0.113 | 0.540 ± 0.079 |

The two sit on top of each other on valence, a gap of 0.004, but most of a standard
deviation apart on arousal. Any absolute threshold would systematically mislabel one
of them. **Baselines must be per speaker.**

13% of segments fall more than 1.5 standard deviations from their own speaker's
valence baseline, which is a workable rate for "notable moment" selection.

---

## 3. Should word timings be dropped?

**No.** They are the only source for two signals worth having, and both would be
destroyed by discarding them:

- 29% of long pauses are mid-sentence and invisible at segment boundaries.
- Within-segment pacing varies 9x, which no per-segment average can recover.

The distinction that matters is **consume versus ship**. Word timings should stay
in the `.json` and feed the analysis pass. They should not be what a language model
reads, because a model cannot reliably do arithmetic across 4,359 timestamps anyway,
and the derived answer is both exact and 88 times smaller:

| Form | Approx. tokens |
| --- | ---: |
| Word timings serialized | 55,700 |
| The same pauses as annotations | 640 |

Likewise for emotion: inline on every segment costs about 7,700 tokens, and
restricting it to outliers costs about 490.

### Pros and cons of a sentence-level model-facing view

| | Pros | Cons |
| --- | --- | --- |
| **Readability** | 446 fragments become 107 turns; sentences stop breaking mid-thought | None |
| **Token cost** | ~6,500 instead of ~137,000 | None |
| **Emotion quality** | Scored on a full turn instead of 1 to 2 seconds of audio | Loses shifts occurring inside a long turn |
| **Pacing** | Turn-level rate is more stable | Loses the 9x within-segment variation |
| **Pauses** | Between-turn gaps still visible | Loses the 29% that are mid-sentence |
| **Audio seeking** | Turn start times still work | Cannot jump to a word |

Every entry in the cons column is recovered by deriving features from word timings
before emitting sentences. That is what the plan below does.

---

## 4. The plan

A new module, `revolv/analysis.py`, holding a pure function over the existing
segment list. No models, no GPU, sub-second. Because it only reads finished output,
**it can also be run against transcripts already on disk without re-transcribing.**

### 1. Merge segments into turns

Group consecutive segments from the same speaker, but break the turn anyway when the
gap exceeds about two seconds. A long silence is a boundary even when the same
person resumes. This is the single change that fixes readability.

### 2. Extract pauses from word timings

Two kinds, kept distinct because they mean different things: mid-sentence hesitation
inside a turn, and latency between turns. A threshold near one second isolates
roughly the top 1% of gaps in the sample data, which is a principled place to cut
rather than a round number.

### 3. Filter pause artifacts

Forced alignment can emit a gap where a word simply failed to align, inventing a
hesitation that never happened. Guard: require both flanking words to have plausible
durations, and cross-check long pauses against the voice-activity spans the VAD
already produces. Anything failing the check is dropped, not reported. **This is the
item most likely to need iteration**, since a false hesitation is worse than a
missed one.

### 4. Two pace figures per turn

Overall rate including pauses, and articulation rate with pauses removed. A single
number conflates "spoke slowly" with "stopped to think." The 4.7-second gap in the
sample call would drag one turn's rate down and misrepresent it as slow speech.

### 5. Per-speaker baselines

Mean and standard deviation for valence and arousal, mean articulation rate, talk
time, turn count, median turn length. Everything downstream is expressed relative to
these, for the reason established in section 2.

### 6. Select notable moments

Turns departing from their own speaker's baseline by at least 1.5 standard
deviations. At segment level 13% cleared this bar; at turn level it should be fewer
and better founded, since each turn averages 40.7 words against 9.8.

### 7. Gloss in two dimensions, not three

Valence against arousal yields four readable states: tense, animated, flat, settled.

Mehrabian's [PAD model](https://en.wikipedia.org/wiki/PAD_emotional_state_model)
offers eight octants, named in [his own materials](https://www.kaaj.com/psych/scales/emotion.html)
as exuberant, hostile, anxious, relaxed and their opposites. Tested against this
model's actual output, the mapping does not hold up:

| Thresholding | Result |
| --- | --- |
| Absolute 0.5 midpoint | 60.5% of an ordinary business call reads "exuberant", 18.2% "hostile" |
| Each speaker's own median | Spread improves, but 28.0% becomes "bored" purely by construction |

Neither is trustworthy. The model is not calibrated to Mehrabian's scale, and a
median split manufactures variety since half of everything falls below the median by
definition. Dominance is the weakest of the three dimensions here, with a standard
deviation of 0.077 and 95% of segments on one side of the midpoint, so a third
binary axis adds label churn rather than information. Two dimensions, applied only
to moments that clear a real distance from baseline, is the defensible version.

### 8. Conversation-level summary

Talk-time share, longest uninterrupted stretch, median turn-taking latency per
speaker. Overlapping speech is a candidate but **needs measuring first**; the
analysis behind this document discarded negative gaps, so the overlap rate in these
recordings is currently unknown.

### 9. A separate `.analysis.json`

The existing `.json` is a bare list, so prepending a header would break anything
reading it. A sibling file costs nothing and keeps the contract intact.

### 10. A `.md` writer, the model-facing view

Header carrying what a model would otherwise have to count badly, body as turns with
inline pause markers and sparse glosses:

```markdown
# 28.1 min · 2 speakers · 107 turns
Talk time: SPEAKER_01 61% · SPEAKER_00 39%
Pace: SPEAKER_01 168 wpm · SPEAKER_00 145 wpm (articulation)
Notable: 15:56 animated · 21:41 animated · 27:40 animated

[02:11] SPEAKER_00: Could be better. Okay. Well, yeah, I'd love to see.
So I took a review at the <4.5s> presentation you put together.

[15:56] SPEAKER_00 (animated, +1.8σ valence): That's awesome.
```

### 11. A fifth format chip in the window

Alongside JSON, Text, Subtitles and Spreadsheet. Thresholds live in settings with
sane defaults rather than on the main surface.

### 12. Editable speaker names — second pass

`SPEAKER_00` is not merely opaque, it is unstable across files, so the same person
carries a different label in every recording. Renaming after a run and persisting it
would do as much for legibility as items 1 through 10 combined, but it needs
interface and storage decisions the rest of this does not. Deliberately deferred.

---

## 5. Suggested sequencing

| Phase | Items | Why this order |
| --- | --- | --- |
| 1 | 1, 5, 10 | Turns, baselines and the `.md` writer deliver most of the readability and token win on their own |
| 2 | 2, 3, 4 | Pause and pacing features, once there is an output to show them in |
| 3 | 6, 7, 8, 9 | Emotion selection and the structured sibling file |
| 4 | 11, 12 | Interface work, after the output has been seen and judged |

---

## 6. Open questions

- **Thresholds rest on one recording.** Every cut-off here (one second for pauses,
  two seconds for turn breaks, 1.5 standard deviations for notable moments) was
  derived from a single 28-minute two-speaker call. They should be re-checked across
  several files, especially ones with more than two speakers.
- **Overlap rate is unmeasured**, as noted in item 8.
- **Alignment reliability is unquantified.** Item 3 proposes a guard, but how often
  alignment actually produces spurious gaps is not yet known.
- **Emotion on short turns stays suspect** even after merging. A turn that is a
  single "Okay." is still about a second of audio. Worth considering a minimum
  duration below which no emotion figure is reported at all, rather than reporting a
  number the model will over-trust.
- **Whether the `.md` should be the default format.** It is the most useful output
  for most purposes, but defaulting to it changes what a normal run writes.

---

## Appendix: how these numbers were produced

Four throwaway scripts read `transcript_output.json` directly and printed the
tables above. They were not kept, since the analysis module will supersede them.
Anything in this document can be regenerated from that file, which remains in the
project root.

Sources consulted for the emotion mapping:

- [PAD emotional state model](https://en.wikipedia.org/wiki/PAD_emotional_state_model)
- [Mehrabian, The PAD Comprehensive Emotion Tests](https://www.kaaj.com/psych/scales/emotion.html)
