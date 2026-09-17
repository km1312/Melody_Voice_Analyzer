# Review of ANALYSIS_PLAN.md, and a revised plan

**Status:** review, second revision. Supersedes `ANALYSIS_PLAN.md` where the two
disagree.
**Scope:** the analysis pass, the model-facing output format, and four changes to
the transcription pipeline that the original plan treated as out of bounds.
**Re-run:** 2026-09-16. The sample recording has since been through the current
pipeline, alongside a second call. Section 14 records which findings held.

**Revised after a rebuttal.** Three claims in the first draft were wrong and are
corrected here: the evidence offered for finding 3 was confounded with finding 4
and the claim is now weaker, the stutter count in finding 1 was an artifact of a
too-strict regular expression, and finding 5 attributed a legacy defect to current
code. A fourth point the rebuttal raised, and neither draft had caught, now opens
section 1.

**Stated goals, in the order they were given:**

1. A transcript carrying as much emotion and nuance as the audio holds, enough to
   infer what a speaker was thinking.
2. An output a language model can read without drowning in it.

The second is in service of the first. A record no model can parse yields no
inference, however faithful it is.

---

## 1. Verdict

The original plan is right about structure, token economy and per-speaker
normalisation, and those parts should be built as written. It is wrong about what
its emotion signal is worth, and the error is not small: the mechanism it proposes
for finding notable moments, applied to the sample file, returns artifacts more
often than it returns moments.

Underneath that sits a larger problem the plan does not raise. Whisper does not
transcribe what was said. It transcribes what was meant. The hesitations,
restarts and filled pauses that carry most of goal 1 are deleted before any
analysis runs, and no derived feature recovers them.

Six findings follow. Each was measured against `transcript_output.json`, the same
28.1-minute two-speaker call the original plan used.

### Caveat over everything below

**That file is not output from the current pipeline.** `pipeline.log` records the
run as `.\Scripts\python VoiceModel.py`, and the dates place it three weeks before
the package that replaced it:

| File | Modified |
| --- | --- |
| `transcript_output.json`, `pipeline.log` | 2026-08-19 |
| `revolv/pipeline.py`, `revolv/audio.py` | 2026-09-09 |

This has one concrete consequence, corrected in section 7, and one open risk. The
risk is the audio decode. `revolv/audio.py` documents in its own docstring that the
script it replaced "downmixed by averaging raw frame arrays, which only works for
planar formats; packed formats arrive as a single interleaved row and would be
misread." A misread downmix would corrupt every timestamp and every emotion score
underneath both documents.

The evidence says this particular file escaped it. A packed stream read as mono
yields interleaved samples at twice the rate, so speech would appear stretched.
It does not:

| Measure | Value | Normal conversational English |
| --- | ---: | --- |
| Median word duration | 0.16s | 0.15 to 0.20s |
| Articulation rate, 10th to 90th percentile | 143 to 314 wpm | 140 to 180 wpm at the median |

The transcript is also coherent, which badly downmixed audio would not produce.
So the numbers here are probably sound. **Probably is not a basis for a
threshold.** Re-run this recording through the current pipeline and re-check the
key figures before committing to the four-second gate, the two-second turn break
or the 1.5 standard deviation cut-off. Section 13 carries this as the first open
question.

---

## 2. What holds

Verified against the file and left unchanged:

- **The size accounting.** 549,486 bytes whole, 151,540 without `words`, 23,291
  characters of actual speech. Word timings really are most of the file.
- **Keeping word timings on disk and out of the model's view.** Correct, and for
  the right reason. A model cannot do arithmetic over 4,359 timestamps.
- **Merging segments into turns.** Real and worth doing.
- **Per-speaker baselines.** Not merely defensible, mandatory. See finding 4.
- **Refusing the eight-octant PAD mapping.** The reasoning given is sound and
  finding 2 below strengthens it.
- **Markdown over JSON for the model-facing view.** Supported by the format
  benchmarks: markdown costs fewer tokens than JSON or XML and is read more
  accurately. Forcing a model to emit JSON is separately known to cost reasoning.

One arithmetic slip. Item 1 breaks a turn when the gap exceeds two seconds, but
the figure quoted throughout is 107, which is the count with no break applied.
With the two-second break the file yields 119 turns, mean 36.6 words, median 20.

---

## 3. Finding 1: the transcript is not verbatim

Whisper was trained on subtitle-style text and emits intended speech, not spoken
speech. Measured on the sample call:

| Signal | Found | Expected in conversation |
| --- | ---: | ---: |
| Filled pauses, of 4,323 word tokens | 5 | roughly 2% of tokens |
| Repeated words | 16 | several per minute |
| Word-fragment stutters | 0 | present in most speakers |
| Hesitation marks (`...`) | 12 | — |

This is the single largest constraint on goal 1. Filled pauses, false starts and
self-repairs are the most direct evidence of planning difficulty, reluctance and
discomfort available in speech, and they are being discarded at the recognizer.

The repeated-word row read 0 in the first draft, from a regular expression that
would not match across punctuation. The corrected figure is 16, and 9 of those
are `yeah, yeah` or `okay, okay`, which is emphatic repetition rather than
disfluency. The conclusion is unchanged: filled pauses appear at roughly a
sixteenth of their expected rate, and word-fragment stutters are absent entirely.

The original plan's proudest finding is downstream of exactly this loss. Its three
longest mid-sentence pauses are silences where a deleted disfluency used to be:

```
[14:17] 4.73s   ...What, <PAUSE> are...
[02:22] 4.46s   ...the <PAUSE> presentation...
```

A silence tells you the speaker stopped. It does not tell you whether they filled
it, restarted the sentence, or corrected themselves, and those three mean
different things. The plan is reconstructing a shadow of what the ASR threw away.

Two aggravating factors in the current code:

- `revolv/pipeline.py:151` passes `initial_prompt="This is a meeting recording."`,
  which biases decoding further toward clean minutes-style prose.
- Nothing in the pipeline detects laughter, sighs, audible breath or throat
  clearing. Whisper drops all of them silently.

**Recommendation.** Move to a verbatim-capable recognizer.
[CrisperWhisper](https://github.com/nyrahealth/CrisperWhisper) is the direct
replacement: it has an explicit verbatim mode covering fillers, repetitions,
stutters, false starts and vocal events, reports roughly 30 ms mean word-boundary
error against the WhisperX aligner's coarser output, and ships mitigation for
Whisper's looping-hallucination failure. **Check the licence before committing.**
Inference code is MIT; standard model weights are non-commercial research only,
and commercial use needs the Pro tier.

If that licence is a blocker, the fallback is
[SenseVoice-Small](https://huggingface.co/FunAudioLLM/SenseVoiceSmall) run
alongside Whisper purely as an event detector. It emits laughter, crying, breath,
cough and applause tags and is faster than Whisper-small, so the cost is a second
cheap pass rather than a replacement. It will not recover filled pauses.

At minimum, and at zero cost: drop the meeting-recording prompt.

---

## 4. Finding 2: dominance is not a third dimension

Correlations across the 446 scored segments:

| Pair | r |
| --- | ---: |
| arousal, dominance | **0.931** |
| valence, dominance | 0.311 |
| valence, arousal | 0.266 |

Dominance is very nearly a linear function of arousal. It carries no independent
information about this call and should be dropped from the analysis entirely, not
merely from the gloss as item 7 proposed. Continuing to write it to the `.json` is
harmless. Continuing to reason over it is not.

---

## 5. Finding 3: valence is partly lexical, but weakly evidenced here

The model in use is
[audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim](https://huggingface.co/audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim).
The paper introducing it,
[Wagner et al. 2023](https://arxiv.org/abs/2203.07378), found that its
state-of-the-art valence performance rests on **implicit linguistic information
learnt during fine-tuning**, which is why it matches multimodal systems that read
the text explicitly. That finding comes from the model's own authors, probing the
model on its own training corpus, and it stands.

**The first draft then offered file-level evidence that did not support it.** It
listed the six valence extremes as lexically obvious. Five of the six run under
1.2 seconds, which makes them exactly the segments finding 4 identifies as
unreliable. The evidence was confounded with the artifact. Worse, two of the three
lowest were "That makes sense to me." and "It's true.", which are lexically
positive and therefore cut against a lexical reading rather than for it. That
table has been withdrawn.

Re-measured with the four-second gate applied, the extremes look like this:

| Highest valence, 4s and over | Lowest valence, 4s and over |
| --- | --- |
| "Happy to provide any feedback in your career stuff" 0.813 | "not great current..." 0.263 |
| "if you're interested in getting involved" 0.805 | "What, are you backtracking?" 0.341 |
| "I don't want to take up any of your space" 0.766 | "the problem is that there's not much else we could do" 0.377 |

The lexical pattern survives the gate, and the extremes become more coherent
rather than less: offers and invitations at the top, problems and hedging at the
bottom. The gate also compresses the range from 0.209-to-0.984 down to
0.263-to-0.813, which is the artifact draining away.

Strength of the association, by segment length:

| Duration | n | Correlation of lexical sentiment with valence |
| --- | ---: | ---: |
| under 1s | 120 | +0.195 |
| 1 to 2s | 103 | +0.341 |
| 2 to 4s | 114 | +0.346 |
| 4s and over | 109 | +0.244 |

Two conclusions follow, and they point in opposite directions from the first
draft. The association is **not** a short-segment artifact: it is flat across
every duration band, so it would not have vanished under the gate. But it is
**weak everywhere**, roughly 0.2 to 0.35 against a crude lexicon, which is about
what you would expect simply because pleasant things tend to be said pleasantly.
This file cannot distinguish that innocent explanation from the one Wagner
reports.

**Revised position.** Trust the literature, not this file. Valence is partly
lexically mediated, which is reason enough not to present it to a model as
independent acoustic evidence, because it will read as corroboration it has not
earned. It is not reason enough to discard valence, and the first draft came close
to saying it was. Keep it in the `.json`, keep it out of the `.md`, and revisit
once there is a recording where the answer is known.

Arousal does not carry this ambiguity. It is the acoustically grounded dimension,
and in this file it correlates with speaking rate at 0.33, independent of content.

**The design consequence survives intact, on its own merits.** The most
informative thing in conversational audio is the *mismatch* between what the words
say and what the voice does: agreeable words delivered flat, enthusiasm at low
energy, a concession spoken fast and loud. Detecting that needs a lexical channel
and an acoustic channel that are genuinely independent. Whatever valence turns out
to be, it is not cleanly one of the two. Compute the lexical side from the text
and the acoustic side from arousal and prosody, and the comparison becomes
well-defined regardless of how finding 3 eventually resolves.
---

## 6. Finding 4: notable-moment selection inverts reliability

Emotion spread by segment duration:

| Duration | n | Valence SD | Arousal SD |
| --- | ---: | ---: | ---: |
| under 1s | 120 | **0.147** | 0.087 |
| 1 to 2s | 103 | 0.131 | 0.108 |
| 2 to 5s | 145 | 0.119 | 0.079 |
| over 5s | 78 | **0.096** | 0.069 |

Predictions are most extreme exactly where they are least trustworthy. Anything
under a second is zero-padded to a second at `revolv/pipeline.py:200`, so a
0.2-second "Yep" reaches the model as four-fifths silence.

Any selector keyed on distance from a baseline will therefore find short
utterances first. Running item 6 as specified, on turns merged at two seconds:

| | As specified | Gated at 4s of speech |
| --- | ---: | ---: |
| Turns flagged, of 119 | 27 (23%) | 15 (13%) |
| Flagged turns under 3s | **63%** | 0% |

The ungated list is led by "Yep." at 0.2s, "Yes." at 0.2s, "Right." at 0.2s and
"Wednesday." at 0.9s. One flagged turn, "Considered major unrest.", scored arousal
of exactly 0.000, a value clipped at `revolv/pipeline.py:236`; clipping conceals
that the raw prediction left the valid range.

The gated list contains no artifacts and reads like a map of the call: hesitation
at "I don't have that off the top of my head. It's... Let me think.", pushback at
"Isn't that just p-hacking though?", and a turn at 22:15 that is simultaneously
the most negative and among the most agitated in the recording.

**Recommendation.** Gate at four seconds of speech, and **exclude gated turns from
the baseline statistics as well**, since they currently inflate the standard
deviation that everything else is measured against. Roughly half the turns then
carry no emotion figure at all. That is the honest outcome and it costs little,
because those turns are mostly backchannels whose text already says what they are.

---

## 7. Finding 5: overlap is structurally invisible, not merely unmeasured

Item 8 lists overlap as a candidate needing measurement. It cannot be measured
from this data at all.

| Measure | Value |
| --- | ---: |
| Negative gaps between consecutive segments | **0** |
| Speaker changes in 28.1 minutes | 106 |
| Mean interval between speaker changes | 15.9s |
| Speaker changes with a gap under 0.2s | 24 |

Zero overlap is not a property of the conversation. WhisperX segments derive from
voice-activity chunks and cannot overlap by construction. One speaker change every
sixteen seconds is low for a two-person call, which suggests backchannels landing
on top of another person's speech are being absorbed into the dominant speaker's
turn rather than recorded as interruptions.

Overlap does exist upstream. pyannote emits overlapping speaker turns;
`whisperx.assign_word_speakers` at `revolv/pipeline.py:298` collapses them to one
label per word and the annotation is then discarded.

**Recommendation.** Retain the raw diarization annotation in the result and derive
overlap from it. The distinction worth surfacing is between a backchannel, which
does not take the floor, and an interruption, which does. Those mean opposite
things about the interrupter.

**Withdrawn from the first draft.** It reported that no word in the sample file
carries a `speaker` key, and treated that as a live defect. It is not. The file
came from `VoiceModel.py`, which never wrote one; the current
`revolv/pipeline.py:323` does. Nothing needs fixing, and the Phase 0 item that
chased it has been removed. The structural point above is unaffected, because it
was read from the current code rather than inferred from the file.

---

## 8. Finding 6: there is no prosody

The plan's only acoustic channel is a single black-box model with a compressed
output range, one dimension of which is redundant (finding 2) and another of which
is partly lexical (finding 3). What remains is arousal.

Missing, and cheap: pitch and energy. An
[eGeMAPSv02](https://arxiv.org/html/2506.01129v1) extraction via openSMILE or
Praat gives per-turn fundamental frequency statistics, loudness, jitter, shimmer
and harmonics-to-noise ratio. It is CPU-only, deterministic, sub-second, and
needs no GPU contention with the models already loaded.

Standard practice is to normalise these per speaker within the conversation,
which the plan already does for emotion and should extend here.

Four features earn their place for goal 1:

| Feature | Reads as |
| --- | --- |
| Pitch range over the turn | Flat delivery against animated delivery |
| Terminal pitch slope | A rise on a declarative sentence signals uncertainty or a bid to continue |
| Loudness variance | Emphasis and contrastive stress |
| Articulation rate against own baseline | Hurrying, or labouring |

None of these is an emotion label. They are observations, which is the point.

---

## 9. The design principle the format should follow

**Describe the evidence, not the verdict.**

The original plan's output asserts conclusions: `(animated, +1.8 sigma valence)`.
That is the weakest thing to hand a language model, for two reasons. It compresses
a measurement into a label the model cannot reopen, and it invites the model to
treat a noisy acoustic estimate as established fact. A wrong label propagates
silently through everything the model then infers.

`(faster and louder than usual, pitch flat)` is the same information without the
conclusion. The model is a far better inference engine than the pipeline is, and
it has the text, the pauses and the surrounding turns that the acoustic model
never saw. Give it observations and let it do the part it is good at.

This also resolves the tension in finding 3. Once the output describes what the
voice did rather than what the speaker felt, the model can notice that warm words
arrived in a flat voice, which is the inference actually worth having.

A supporting result: a 2026 EACL study of whether audio language models use
acoustic information found that most extract text early and underuse prosody,
with acoustic cues contributing single-digit accuracy gains over text-only
baselines. Feeding audio to an omni-modal model is not a shortcut past this work.
Writing the prosody down as text is what makes it usable.

---

## 10. The revised plan

### Phase 0 — pipeline, upstream of any analysis

These change what gets recorded. Nothing downstream recovers them.

| # | Change | Cost |
| --- | --- | --- |
| 0.1 | Drop the `initial_prompt="This is a meeting recording."` bias | One line |
| 0.2 | Move to a verbatim recognizer, licence permitting, for fillers, restarts and stutters | Model swap, re-benchmark |
| 0.3 | Retain the raw pyannote annotation on the result so overlap survives | Small |
| 0.4 | Record raw emotion logits alongside the clipped values, so out-of-range predictions are visible rather than silently pinned to 0 or 1 | Small |
| 0.5 | Vocal-event detection for laughter, breath and sighs, as a second cheap pass | New model |

0.1 and 0.4 are free and should go in regardless. 0.2 is the highest-value item
in this document and the one with a licence question attached. 0.5 is optional
and can wait until the rest has been judged.

### Phase 1 — the readable core

1. **Merge segments into turns.** As the original item 1, breaking on a gap over
   two seconds. Expect 119 turns from the sample call, not 107.
2. **Per-speaker baselines.** Articulation rate, arousal, pitch statistics, talk
   time, turn count, median reply latency. Computed only over turns clearing the
   duration gate.
3. **The `.md` writer.** Specified in section 11 below.

### Phase 2 — the observation layer

4. **Pauses from word timings.** As original items 2 and 3, kept as two distinct
   kinds. The artifact guard the original plan proposed is still needed, though
   the sample file shows no obvious alignment failures: no zero-duration words, no
   words snapped to a segment boundary, and only five words exceeding two seconds.
   Alignment reliability looks better than feared. Re-check on a noisier file.
5. **Two pace figures per turn.** Overall rate and articulation rate. As original
   item 4, unchanged and correct.
6. **Prosody per turn.** Finding 6. Pitch range, terminal slope, loudness
   variance, all normalised against the speaker's own baseline.
7. **Overlap classification.** Finding 5. Backchannel against interruption,
   derived from the retained annotation.

### Phase 3 — the selective layer

8. **Gate emotion at four seconds of speech.** Below the gate, report nothing.
   Exclude gated turns from baseline statistics too.
9. **Arousal only, from the emotion model.** Drop dominance entirely (finding 2).
   Keep valence in the `.json` but do not surface it as an independent acoustic
   signal (finding 3).
10. **Lexical sentiment as a separate channel**, computed over the text alone, so
    that agreement and disagreement between words and voice becomes measurable.
11. **Select notable moments** on departure from the speaker's own baseline,
    across arousal, prosody and word-voice mismatch. The 1.5 standard deviation
    threshold is a reasonable start and yielded 15 moments from 119 gated turns.
12. **`.analysis.json`** as a sibling file, as original item 9. Unchanged.

### Phase 4 — interface

13. **A fifth format chip**, thresholds in settings. As original item 11.
14. **Editable speaker names.** The original plan defers this as a nicety. It is
    not. `SPEAKER_00` is unstable across files and carries no meaning, and a model
    reasoning about intent does markedly better with a name attached to a person.
    A cheap partial win exists: scan the transcript for vocatives and
    self-introductions. The sample call contains exactly one usable cue, "Bye,
    Brian." from SPEAKER_01, which identifies SPEAKER_00. One cue in 28 minutes is
    low recall but high precision, so treat it as a suggested default the user
    confirms, never as an automatic label.

---

## 11. The model-facing `.md`, revised

Four changes from the original item 10: a legend, an explicit uncertainty
statement, observations in place of verdicts, and an index of moments near the top
where the model's attention is strongest.

````markdown
# Call with Brian · 28.1 min · 2 speakers · 119 turns

## How to read this
Times are mm:ss from the start of the recording. Speaker labels come from
automatic diarization and are sometimes wrong; treat a surprising attribution as a
possible error. `(...2.4s)` marks a silence of that length inside a turn.
Parenthetical notes after a speaker name are acoustic measurements, expressed as
distance from that speaker's own baseline for this call. They describe how the
voice sounded. They are not claims about what the speaker felt. Turns under four
seconds carry no acoustic note, because the measurement is unreliable at that
length, and their absence means nothing.

## Participants
| | Talk time | Turns | Articulation | Median reply latency |
| --- | ---: | ---: | ---: | ---: |
| SPEAKER_00 | 39% | 57 | 145 wpm | 0.52s |
| SPEAKER_01 | 61% | 62 | 168 wpm | 0.41s |

## Moments
- 13:11 SPEAKER_01 · long hesitation before answering
- 22:15 SPEAKER_00 · fastest and loudest of the call, pitch flat
- 24:14 SPEAKER_01 · sharp rise in energy

## Transcript

[02:11] SPEAKER_00: Could be better. Okay. Well, yeah, I'd love to see. So I took
a review at the (...4.5s) presentation you put together.

[13:11] SPEAKER_01 (slower than usual; two long pauses): I don't have that off the
top of my head. It's... (...2.1s) Let me think.

[22:15] SPEAKER_00 (faster and louder than usual; pitch range narrow): But it does
seem like right now, if we were to go back, not great current...
````

Notes on the choices:

- **The legend earns its tokens.** Roughly 120 of them, against a body of 6,500.
  Without it the model guesses at the notation and guesses inconsistently.
- **Stating that absence is not evidence** prevents the model reading an unmarked
  turn as an emotionally flat one.
- **The moments index sits near the top** because models attend to the beginning
  and end of a context better than the middle, and because it gives the model
  anchors before it reads 6,500 tokens of dialogue.
- **Sparse annotation is not just a token saving.** Semantically similar but
  irrelevant content actively misleads models at length, so annotating every turn
  would make the genuine departures harder to find, not easier.
- **The `.analysis.json` keeps the numbers.** Anything wanting standardised scores
  reads that file. The `.md` is for reading.

---

## 12. What not to do

- **Do not feed the audio to an omni-modal model and ask for an emotional
  transcript.** The 2026 EACL work cited in section 9 shows those models mostly
  reduce audio to text early and underuse prosody. It would also break the
  local-only guarantee in the README if the model were hosted.
- **Do not add more emotion models in the hope of averaging out the noise.** The
  failure in finding 4 is a duration problem, not a model problem. A second model
  scoring the same 0.2-second clip fails the same way.
- **Do not raise the notable-moment threshold to reduce noise.** It selects for
  extremity, and extremity is where the artifacts live. The duration gate is the
  fix; the threshold is not.
- **Do not make the `.md` the default output format yet.** Section 6 of the
  original plan leaves this open. It should stay open until a few files have been
  read end to end by a person.

---

## 13. Open questions

**First, and blocking.** Every number in both documents comes from a file the
current pipeline did not produce. Re-run that recording through `revolv/` and
re-check the six findings before any threshold is committed. Section 1 explains
why the risk is real and why it is probably not realised. Probably is not enough.

Carried over from the original plan and still unresolved:

- **Thresholds still rest on one recording**, and on the wrong version of the
  code. The four-second gate, the two-second turn break and the 1.5 standard
  deviation cut-off all come from the same 28-minute two-speaker call.
  Multi-speaker files will behave differently, particularly the turn break.
- **Alignment reliability is better than feared but only on one file.** No
  zero-duration words, no words snapped to segment boundaries, five words over two
  seconds out of 4,359. Re-check on noisy audio before trusting item 4.

New, arising from this review:

- **Whether the licence permits a verbatim recognizer.** This gates the largest
  single improvement available. It should be answered before anything in Phase 2
  is built, because verbatim text changes what the pause features mean.
- **How much a duration gate costs on shorter recordings.** Half the turns in a
  28-minute call clear four seconds. A rapid-fire ten-minute call might leave
  almost nothing scored.
- **Whether word-voice mismatch is measurable at this resolution.** It is the most
  promising signal in this document and the least proven. It needs a real
  sentiment channel and at least one recording where the answer is already known.
- **Whether valence is worth keeping at all.** Section 5 could not settle it from
  this file. The same recording where mismatch gets tested would settle it too.

---

## 14. Re-run, 2026-09-16

The blocking question in section 13 is answered for every finding that could be
re-measured. The same 28.5-minute recording went through the current pipeline end
to end: Whisper large-v3 merged word by word with CrisperWhisper 2.0, pyannote
community-1, emotion scored once per turn, PENN pitch tracking, median-and-MAD
baselines. A second call, the 29.5-minute SkyDeck Edge presentation, ran alongside
it. Neither has hand labels, so this is re-measurement, not validation. `README.md`
has the detail behind each figure.

| Finding | Recorded here | On the current pipeline |
| --- | --- | --- |
| 1. The transcript is not verbatim | 5 filled pauses in 4,323 tokens (0.12%) | Whisper alone, without the initial prompt: 32 (0.73%). With the verbatim merge: 132 (2.88%), 59 of them mid-sentence, plus 29 cut-off words and 33 repetitions. **Resolved.** |
| 2. Dominance is not a third dimension | r(arousal, dominance) 0.931 over 446 segments | 0.971 over 57 turn-level readings. **Holds, more strongly.** |
| 3. Valence is partly lexical | weakly evidenced | Not re-tested. **Open.** |
| 4. Selection inverts reliability | the shortest inputs were the most extreme | Emotion is scored once per turn and never below four seconds of speech; the shortest scored span was 4.1 s. **Resolved by construction.** |
| 5. Overlap is invisible | 0 negative gaps between segments | Still 0 between whisperx segments, as predicted. From the diarization: 85 overlaps, 60 s, 55 backchannels and 30 floor-takes. **Resolved.** |
| 6. There is no prosody | none | PENN pitch per turn: range median 8.7 semitones (p10 6.8, p90 12.0). The YIN tracker it replaced read a median of 14.0 on the same call, inflated by octave errors. **Resolved.** |

The open questions in section 13, as they now stand:

- **Thresholds rest on two recordings**, both run through the current code. The
  robust baselines and PENN together made notes denser: pitch-range notes land on
  24% of scored turns on this call and 33% on the second. `NOTABLE_SIGMA` has not
  been retuned.
- **Alignment reliability.** The merged transcript has 20 zero-length words in
  4,589, nearly all inherited from CrisperWhisper's own timings. Still untested on
  noisy audio.
- **The licence question is settled**: research-only use.
- **The cost of the duration gate on short recordings** is untested.
- **Word-voice mismatch** never fired on this call. It fired once on the second,
  on an artefact: a 110-second turn whose built-in-lexicon score came from
  discourse markers ("like" five times, "right", "yeah") and one "Great". It still
  needs a real sentiment channel and a recording where the answer is known.
- **Valence** is still unsettled.

One finding this document did not anticipate. Speaker counts differ between
diarizers, and a small extra speaker is not always an error: on the second call,
community-1 and DiariZen both found a bystander in the room ("Hi, Grace. Hi, good
to see you.") that pyannote 3.1 folded into a main speaker.

---

## Appendix: provenance

Every figure in sections 2 through 8 was measured directly from
`transcript_output.json` during this review, by scripts run in a scratch
directory and not kept. All of it is reproducible from that file, which remains in
the project root. **That file is output from `VoiceModel.py`, dated 2026-08-19,
not from the current `revolv/` package.** Section 1 sets out what follows from
that. Treat every figure here as provisional until the recording is re-run. Correlations are Pearson over the 446 scored segments unless
stated. Turn-level figures merge consecutive same-speaker segments with a
two-second break. The gated columns weight each constituent segment's emotion by
its duration and discard segments below the gate before averaging.

Line references point at `revolv/pipeline.py` as of this review.

Sources consulted:

- [CrisperWhisper, verbatim transcription with accurate timestamps](https://github.com/nyrahealth/CrisperWhisper)
- [Wagner et al., Dawn of the Transformer Era in Speech Emotion Recognition](https://arxiv.org/abs/2203.07378)
- [SenseVoice-Small, ASR with emotion and audio-event tags](https://huggingface.co/FunAudioLLM/SenseVoiceSmall)
- [pyannote community-1 diarization](https://www.pyannote.ai/blog/community-1)
- [Comparative evaluation of acoustic feature extraction tools](https://arxiv.org/html/2506.01129v1)
- [Do Audio LLMs Really LISTEN, or Just Transcribe?](https://aclanthology.org/2026.eacl-long.274.pdf)
- [Chroma, Context Rot: how increasing input tokens impacts LLM performance](https://www.trychroma.com/research/context-rot)
