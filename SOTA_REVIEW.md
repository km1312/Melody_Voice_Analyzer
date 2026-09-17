# Pipeline comparison and state of the art, September 2026

**Status:** review, written before any of it was built. Much of part III has since
been built or tested; the outcome note below says what the measurements found, and
`README.md` has the detail.
**Date:** 2026-09-13.
**Scope:** part I compares `legacy/` against `revolv/` and collects every measured
result recorded across `README.md`, `ANALYSIS_PLAN.md`, `ANALYSIS_REVIEW.md` and
the two run logs. Part II is an independent survey of what is currently available
for transcription, diarization, alignment, prosody and paralinguistics. Part III
is what I would change, ranked.

**On the evidence.** Part II mixes two grades of claim, and they are marked. A
figure tagged **[verified]** was read from the primary source during this review:
a model card, an arXiv abstract, or a benchmark repository. A figure tagged
**[survey]** came from a broad literature sweep and was not independently
re-checked. Leaderboard standings in particular are the weakest material here,
because the authoritative source is a paper snapshot several months stale and the
secondary aggregators disagree with it. Treat anything **[survey]** as a lead, not
a number to design against.

**Outcome, 2026-09-16.** Measured on two real half-hour calls on an RTX 5060 Ti,
neither with hand labels.

- **Verbatim (section 7): built,** as a word-level merge of Whisper large-v3 and
  CrisperWhisper 2.0 rather than a choice between recognizers. Filled pauses went
  from 0.73% of tokens to 2.88% and the names that 1.0 mangled survive. The verbatim
  pass is the slow stage: about 490 of 640 seconds per call, on the PyTorch backend,
  since the CTranslate2 backend is Linux-only.
- **Diarization (section 8): community-1 adopted; DiariZen tested, not adopted.**
  DiariZen agrees with community-1 on 94-95% of speech and reports about twice the
  overlap, but takes three times as long, peaks at 11.8 GB of GPU memory, and needs
  its own environment. Both found a real bystander that 3.1 missed, so an extra
  speaker is not always an error.
- **Pitch (section 10): PENN adopted.** torbi, its decoder, has no CUDA kernel for
  RTX 50-series cards; a cropped CPU decode reproduces PENN's own output and takes
  38 seconds a call. Median per-turn pitch range fell from 14.0 to 8.7 semitones.
- **Emotion (section 11): audeering kept.** An arousal/valence head on the Whisper
  encoder was not built: it needs the MSP-Podcast licence and would carry no new
  information. A stance head trained on SpeechSense was built. It scores 0.41
  macro-F1 on the held-out set, does not carry over to real speech, and is held
  behind an absolute floor.
- **Turn-taking (section 12): VAP tested, not adopted.** On channels cut from the
  mix by diarization it predicts who speaks after a pause at 0.62-0.76 balanced
  accuracy, but its `p_future` does not separate floor-takes from backchannels
  (AUC 0.33-0.42), and it takes about 14 minutes a call.

---

# Part I — The two pipelines

## 1. What each one is

`legacy/` is the pipeline as of 2026-09-09: a faithful recorder. It decodes audio,
transcribes with Whisper large-v3 through WhisperX, aligns words with wav2vec2,
assigns speakers with pyannote 3.1, scores valence / arousal / dominance per
segment with audeering's wav2vec2, and writes four formats. It answers "what was
said, by whom, when, and how energetically."

`revolv/` is the same skeleton with a different purpose bolted to it. Everything
in `legacy/` is still there, unchanged in structure, and four things sit on top:
a selectable verbatim recognizer, a prosody stage, a pure-Python analysis pass,
and a fifth output format written for a language model rather than a person. It
answers "what was said, and what the delivery suggests about it."

The distinction that matters is not that the second is bigger. It is that the
first records and the second *derives*. `legacy/revolv/writers.py` is 4,562 bytes
of serialisation. The current `writers.py` is 11,153 bytes, and the difference is
almost entirely one function that decides what a reader should be told and what
they should be spared. `analysis.py` did not exist at all and is now the largest
module in the package outside the GUI.

## 2. Stage by stage

| Stage | `legacy/` | `revolv/` |
| --- | --- | --- |
| Decode | PyAV → mono 16 kHz float32 | identical file, byte for byte |
| Recognize | Whisper large-v3, `initial_prompt="This is a meeting recording."` | Whisper large-v3 **or** CrisperWhisper 1.0 (`nyralabs/faster_CrisperWhisper`), no initial prompt, optional hotword vocabulary |
| Align | wav2vec2 forced alignment | unchanged |
| Diarize | pyannote 3.1, `assign_word_speakers`, annotation discarded | pyannote 3.1, annotation **retained** and mined for overlap (`_overlaps`) |
| Emotion | V/A/D per segment, clipped to [0,1] | same, plus raw pre-clip values recorded when a prediction left range |
| Prosody | — | YIN pitch, voicing confidence, loudness across the whole recording |
| Analysis | — | turns, pauses, two pace figures, per-speaker baselines, lexical sentiment, moment selection |
| Trim | — | `(start, end)` window, timestamps still reported against the original media |
| Output | json, txt, srt, csv | + `md` (model-facing) and `.analysis.json` |
| Defaults | `json, txt, srt` | `json, md, txt` |

Three design decisions in the newer code are worth naming, because they are the
actual content of the change and none of them is a model swap.

**Observations replace verdicts.** `_observations()` in `analysis.py` emits
"faster than usual", "pitch unusually flat", "ends higher than usual". It never
emits an emotion word. The reasoning is set out in §9 of `ANALYSIS_REVIEW.md` and
it is correct: a label compresses a noisy estimate into a claim the reader cannot
reopen, and the reader has the words and the surrounding turns that the acoustic
model never saw.

**Everything is relative to the speaker's own baseline.** Not one threshold in the
output is absolute. This follows from a real measurement — the two speakers in the
sample call sat 0.004 apart on mean valence and most of a standard deviation apart
on arousal — and it is the single most defensible choice in the package.

**A duration gate, and gated turns are excluded from the baselines too.** The
second half of that is the subtle part and it is right. Including unreliable turns
in the baseline inflates the deviation that every other turn is measured against.

## 3. Everything the two pipelines were measured to do

Collected from the four documents and the run logs, since it is otherwise spread
across three files that partly supersede each other.

### Recognizer, same 30-minute call transcribed both ways

| | Whisper large-v3 | CrisperWhisper 1.0 |
| --- | ---: | ---: |
| Filled pauses | 3 | 169 |
| As share of tokens | 0.07% | 3.41% |
| Repeated words | 18 | 43 |
| Words total | 4,499 | 4,955 |

On the older 28.1-minute call: 5 filled pauses in 4,323 tokens, 16 repeated words
of which 9 were emphatic (`yeah, yeah`), **0** word-fragment stutters, 12
hesitation marks.

CrisperWhisper's cost, recorded in `README.md` and `asr.py`: "Chachi" for ChatGPT,
"Rubik" for rubric, "Vika" for Vivica, "Zoo" for Zoom, "rock house" for raw
counts, and ESG, Grace, OpenRouter, neobanks, CSV and subsectors lost entirely.
Two attempted fixes, both recorded so they are not retried blindly — `beam_size=5`
recovered "raw counts" but not ESG at roughly twelve times the runtime, and a
20-term hotword list recovered ESG, ChatGPT, rubric, Grace and subsectors and then
sent the decoder into a loop ("the" repeated 291 times, a 108-word segment
consisting of one word, 42% of filler markers lost).

**The most useful negative result in the whole set:** prosody is invariant to the
recognizer. Across both transcripts of the same call, pitch range 12.8 / 8.9
semitones against 12.1 / 8.7, terminal rise +2.7 / −3.5 against +3.1 / −4.5,
median reply latency 0.44 / 0.59 s against 0.40 / 0.66 s. The behavioural read
does not depend on which model produced the words. That decouples two decisions
that would otherwise be entangled.

### Token economy, 28.1-minute call, 446 segments, 4,359 words

| Rendering | Bytes | Share |
| --- | ---: | ---: |
| Full JSON | 549,486 | 100% |
| Without `words` | 151,540 | 27.6% |
| Without words, pacing, emotion | 65,069 | 11.8% |
| Spoken text only | 23,291 | 4.2% |
| As speaker turns | 25,982 | 4.7% |

Word timings are 72% of the file; the words are 4%. Serialized they cost about
55,700 tokens; the same pauses as annotations cost about 640. Emotion inline on
every segment costs about 7,700; restricted to outliers, about 490. A 30-minute
recording renders to roughly 8,600 tokens as `.md` against 137,000 as `.json`.

### Structure

446 segments merge to 107 turns with no break rule, 119 with the two-second break.
Mean 9.8 words per segment against 40.7 per turn; 110 segments (25%) are three
words or fewer. Median word duration 0.16 s; articulation rate 143 to 314 wpm
between the 10th and 90th percentiles.

Pauses: 3,913 word-to-word gaps, median 0.04 s, p90 0.20 s, p99 0.94 s, longest
mid-sentence 4.73 s. Of gaps at or over one second, 35 fall inside a segment and
86 at a boundary — **29% of long pauses are invisible without word timings**,
which is the entire justification for keeping them.

Turn-taking: same-speaker continuation 339 instances, median 0.30 s, p90 1.28 s;
speaker change 106 instances, median 0.47 s, p90 1.80 s.

Within a single segment, the ratio of fastest to slowest word rate has a median of
**9x**, which is why one wpm figure per segment is close to meaningless.

Overlap: **zero** negative gaps between consecutive segments, which is a property
of WhisperX's VAD chunking rather than of the conversation. 106 speaker changes in
28.1 minutes, one every 15.9 seconds, which is low for a two-person call; 24 of
those changes had a gap under 0.2 s.

Alignment sanity, one file: no zero-duration words, none snapped to a segment
boundary, 5 words over two seconds out of 4,359.

### Emotion

| Dimension | Mean | SD | Below 0.5 |
| --- | ---: | ---: | ---: |
| Valence | 0.582 | 0.127 | 25% |
| Arousal | 0.573 | 0.094 | 21% |
| Dominance | 0.605 | 0.077 | 5% |

Correlations: arousal–dominance **0.931**, valence–dominance 0.311,
valence–arousal 0.266. Arousal against speaking rate, 0.33.

Spread by segment duration, which is the finding the whole gate rests on:

| Duration | n | Valence SD | Arousal SD |
| --- | ---: | ---: | ---: |
| under 1 s | 120 | **0.147** | 0.087 |
| 1–2 s | 103 | 0.131 | 0.108 |
| 2–5 s | 145 | 0.119 | 0.079 |
| over 5 s | 78 | **0.096** | 0.069 |

Predictions are most extreme exactly where they are least trustworthy. Selection
run ungated flagged 27 of 119 turns, 63% under three seconds, led by "Yep." at
0.2 s. Gated at four seconds it flagged 15, none short.

Lexical sentiment against valence, by duration: +0.195 / +0.341 / +0.346 / +0.244.
Flat across bands and weak everywhere, which the review reads correctly — it
cannot distinguish Wagner's linguistic-mediation finding from the innocent
explanation that pleasant things tend to be said pleasantly.

The PAD octant mapping was tested and rejected on evidence: an absolute 0.5
midpoint made 60.5% of an ordinary business call "exuberant" and 18.2% "hostile";
a per-speaker median split manufactured 28.0% "bored" by construction.

### Prosody, and two bugs caught by running real audio

Naive normalised autocorrelation reported a mean pitch range of **23 semitones**
per turn, nearly two octaves, because a zero-padded FFT overlaps fewer samples at
longer lags and so favours short ones. It pinned the top decile against the 400 Hz
ceiling and jumped by more than 1.8x across 9.9% of voiced frame transitions. YIN
with dip descent and parabolic interpolation brought that to a 10.3 semitone
median. A least-squares terminal slope had a spread reaching 21 semitones per
second and was replaced by a level comparison with a spread of 4.6 to 6.9.

Both were caught because someone ran a real recording instead of a synthetic tone.
That is the most transferable lesson in the repository.

### Speed

RTX 5060 Ti, 15.9 GB: 30-minute recording, about four minutes end to end with
models cached. Prosody about nine seconds, roughly 200x realtime. Stage weights
in `pipeline.py` put transcription at 45%, alignment and diarization at 18% each,
emotion 12%, decode 7%, prosody 2%.

## 4. Four things the code does not do that its own documents assume

These are gaps between the reasoning and the implementation, not disagreements
with the reasoning.

**Emotion is still scored per segment, not per turn.** `ANALYSIS_PLAN.md` §3 lists
"scored on a full turn instead of 1 to 2 seconds of audio" as a benefit of the
turn-level view, and `ANALYSIS_REVIEW.md` §6 establishes that short input is
exactly where the model is unreliable. But `pipeline.py:462` calls
`predict_emotion` with each *segment's* bounds, and `_turn_emotion` then
duration-weights those segment scores. A 12-second turn made of four 3-second
segments still gets four noisy estimates averaged, rather than one forward pass
over 12 seconds of speech. The four-second gate filters which turns are reported;
it does not change what was measured. Prosody got this right —
`prosody.turn_features(track, turn["start"], turn["end"])` operates on the turn —
and emotion did not. Scoring the merged turn directly is a small change and it is
the cheapest quality improvement available anywhere in the package.

**Baselines can be built from four turns.** `MIN_TURNS_FOR_BASELINE = 4`, and
`_spread` uses `statistics.pstdev`. A 1.5σ threshold against a population standard
deviation estimated from four samples is not a threshold, it is a coin flip with
extra steps. On a short or lopsided recording this fires more or less at random,
and there is no way to tell from the output that it did. Either raise the floor to
something like 12, or record `n` beside every note so a reader can discount it.

**Mean and standard deviation on heavy-tailed data.** Conversational prosody is
not Gaussian. One shouted sentence or one laugh inflates σ enough to suppress
every genuine departure for the rest of the recording — which is a plausible
explanation for why the word-voice mismatch check has never fired. Median and
median absolute deviation cost two lines and are robust to exactly this.

**pyannote 3.1 is hardcoded while pyannote.audio 4.0.7 is installed.**
`pipeline.py:233` pins `pyannote/speaker-diarization-3.1`. The bundled
`pyannote_audio-4.0.7.dist-info` means the runtime for `community-1` is already
present. See §8.

## 5. A provenance note

`ANALYSIS_REVIEW.md` §1 is right to flag that `transcript_output.json` came from
`VoiceModel.py` rather than the current package, and right that the risk worth
worrying about was the audio downmix. One further check, since the evidence was
sitting in the project root and points the wrong way:

`pipeline_err.log` contains the line *"Some weights of
Wav2Vec2ForSequenceClassification were not initialized … You should probably TRAIN
this model."* That is the failure `pipeline.py` documents in
`_emotion_model_class()`: the checkpoint loaded without its RegressionHead, so the
emotion head is random and every V/A/D number from that run is noise.

It is not the run that produced the analysed file. `pipeline_err.log` is stderr
from a run at 16:49 on 2026-08-19. `pipeline.log` — the run that ends "Saved to
transcript_output.json (446 segments)" — started at 21:04 the same day, contains
no such warning, and `.venv/VoiceModel.py` defines the correct `RegressionHead`.
The fix went in between the two runs and the analysed file is on the right side
of it.

So the numbers stand. But `pipeline_err.log` is stale evidence of a fixed bug
sitting in the project root, and the next person to read it will reach the wrong
conclusion faster than I did. Delete it or rename it.

---

# Part II — State of the art, September 2026

## 6. Recognizers

Whisper large-v3 is now roughly seventeenth on the Open ASR Leaderboard.
**[survey]** The models above it are mostly 0.6B to 2.5B and mostly Apache-2.0:
IBM Granite Speech 4.1 2B (avg WER 5.33), Cohere Transcribe 03-2026 (5.42),
Granite 4.0 1B Speech (5.52), NVIDIA Canary-Qwen-2.5B (5.63), Qwen3-ASR-1.7B
(5.76), against Whisper large-v3 at 7.44 and large-v3-turbo at 7.75.

Two cautions before anyone acts on that list. The spread across the top ten is
under one WER point, which is inside the noise of a domain change. And the
short-form leaderboard is a poor proxy for 30 to 90 minute conversational audio;
on the long-form track the closed systems still lead the open ones by roughly
2.4 WER. **[survey]**

Three that are genuinely interesting for this project rather than for a
leaderboard:

- **`ibm-granite/granite-speech-4.1-2b-plus`** — Apache-2.0, ~5 GB, and it emits
  ASR *plus* speaker attribution *plus* word timestamps from one model, with
  keyword-list biasing built in. Reported AMI 8.63 WER against Whisper
  large-v3's ~16, word-timestamp average absolute shift 38.8 ms, word diarization
  error 2.2% on CALLHOME-En and 14.6% on AMI-SDM. **[survey]** It runs on stock
  `transformers`, so it needs neither NeMo nor CTranslate2 — which on Windows is
  not a small thing.
- **`nvidia/parakeet-tdt-0.6b-v3`** — CC-BY-4.0, ~2 GB, RTFx in the thousands.
  NeMo is not supported on Windows via pip, but `onnx-asr` with
  `istupakov/parakeet-tdt-0.6b-v3-onnx` sidesteps that entirely, and
  `onnxruntime` is already in the bundle. **[survey]** Worth having as a fast
  first-pass option.
- **`Qwen/Qwen3-ASR-1.7B`** — Apache-2.0, 30 languages, `pip install qwen-asr`,
  and it ships alongside the forced aligner in §9. **[survey]**

None of these is a reason to move off Whisper on accuracy alone. The reason to
look at Granite specifically is that it collapses three of the current six stages
into one, which removes two places where errors compound.

## 7. Verbatim transcription — this is the big one

`README.md` frames the recognizer choice as a forced trade: verbatim text or
correct proper nouns, pick one, and Whisper wins because mangled names damage the
analysis more than missing hesitations help it. That trade was real in 2025. It is
no longer the state of the art.

**CrisperWhisper 2.0** (nyra labs, mid-2026) **[verified]** addresses every
specific complaint in `asr.py`:

| `asr.py` says | 2.0 |
| --- | --- |
| verbatim-only, no readable mode | `mode="verbatim"` / `mode="intended"` per call |
| English and German only | multilingual, benchmarked on ten languages |
| CT2 build's own timestamps not trusted, overwritten by wav2vec2 | ~30 ms mean boundary error on read speech, 41 ms conversational, 29.6 ms on TIMIT |
| chunking artifacts on long files | ">30s transcribed seamlessly via conditional continuation, with no chunk-boundary duplicates, drops, or stitching" |
| hotwords send the decoder into a loop | hotword boosting supported (Pro tier only) |
| — | hallucination-mitigation decoding, speculative decoding at 1.3–1.4x |

Disfluency F1, ten-language average: 87.8 base, **93.5 Pro**. **[verified]** For
comparison, CrisperWhisper 1.0 — the model currently wired up — scores 71.4 on the
English benchmark and Whisper large-v3 scores 9.7. **[survey]**

The proper-noun problem specifically has a named solution. Nyra's **Verbatimize**
reframes the task as "copy the transcript, insert from audio": the model receives
the audio *plus* a trusted clean transcript and inserts only the disfluencies that
are acoustically present, copying content words verbatim. Reported rare-word
recall 96.1% against 6.8% from acoustics alone, on 1,843 manually verified rare
words. **[survey]** That is precisely the ESG / OpenRouter / neobanks failure,
solved.

**Three caveats, and they matter.**

The licence got worse, not better. Standard 2.0 weights are under the **Nyra Health
Non-Commercial Research License**; commercial use requires the `_pro` variants.
**[verified]** Verbatimize is Pro-only. The current pipeline already ships
CrisperWhisper 1.0, which is CC-BY-NC-4.0, so the exposure exists today — 2.0 does
not create it, it just raises the stakes.

Second, the install path. `pip install "crisperwhisper[ct2]"` is documented for
**NVIDIA Linux**; Windows is directed to `pip install "crisperwhisper[transformers]"`.
**[verified]** Whether that extra pins a `transformers` version compatible with
pyannote 4.0.7 and whisperx is the exact question `asr.py` already documents for
1.0, and it has to be answered before committing. Check it in a scratch venv
before touching the real one.

Third, and the honest version of the recommendation: the Verbatimize pattern can
be approximated without the Pro licence. Run Whisper (or Granite with keyword
biasing) for the accurate pass, then run a verbatim model constrained to that
transcript. That is a build rather than a download, but it is the shape of the
answer and it is not licence-encumbered.

There is also an API answer if local ever stops being a hard requirement:
ElevenLabs Scribe v2 scores 90.3 disfluency F1, effectively tied with open
CrisperWhisper 2.0. **[survey]** It would break the no-audio-leaves-the-machine
promise, so it is noted and not recommended.

## 8. Diarization

`pyannote/speaker-diarization-community-1` **[verified]** — CC-BY-4.0, loads
through `pyannote.audio` 4.x, which is already bundled.

| Benchmark | 3.1 (current) | community-1 |
| --- | ---: | ---: |
| AMI (IHM) | 18.8 | **17.0** |
| DIHARD 3 | 21.4 | **20.2** |
| VoxConverse v0.3 | 11.2 | 11.2 |
| CALLHOME part 2 | 28.5 | **26.7** |

Protocol: "fully automatic processing, no forgiveness collar, nor skipping
overlapping speech" — the strict variant, so do not compare these against the
friendlier numbers third-party roundups quote.

Two reasons to take it beyond the ~1.8 DER points. The gains are concentrated in
speaker *assignment and counting*, which is the failure mode that matters when
a wrong label propagates into a per-speaker baseline. And it adds an **exclusive
diarization mode** producing non-overlapping segments that reconcile cleanly with
word timestamps **[survey]** — relevant because `_overlaps()` currently
reconstructs overlap by brute-force interval intersection over the raw annotation.

This is close to a one-line change: the model name string at `pipeline.py:233`.
Check the installed whisperx version first; 3.8.6 and later already default to
community-1, which would mean the pin is actively holding the pipeline back.

Two others, both ruled out rather than recommended. **DiariZen** is the strongest
open diarizer measured (AMI-SDM 13.9 against pyannote 3.1's 22.4) and its weights
are CC-BY-NC-4.0. **NVIDIA Sortformer** is commercially licensed in its streaming
v2.1 form but caps at four speakers, degrading to 41% DER at five or more, and
needs NeMo. **[survey]**

## 9. Forced alignment

Verified directly from the model card, since this is the claim I most wanted to be
true and it turned out to be smaller than the survey suggested.

`Qwen/Qwen3-ForcedAligner-0.6B` **[verified]** — Apache-2.0, 29 January 2026,
11 languages including English, up to 5 minutes of audio per inference,
`pip install -U qwen-asr`, roughly 1.5 GB.

Average absolute shift, milliseconds, lower is better:

| Condition | Qwen3-ForcedAligner | WhisperX (wav2vec2) |
| --- | ---: | ---: |
| MFA-labeled, raw, English | **37.5** | 92.1 |
| MFA-labeled, concat-300s, English | **58.6** | 227.2 |
| MFA-labeled, concat-300s, French | **53.4** | 2052.2 |

**The catastrophic long-form number is French, not English.** A secondary source I
checked this against reported ~2,700 ms for WhisperX at 300 seconds; that figure
is not the English one. For English the honest claim is a 2.5x improvement on
normal segments and a 3.9x improvement on long concatenated audio.

What that is worth here: `PAUSE_MIN_SECONDS` is 1.0 s, so a 55 ms improvement in
boundary accuracy changes almost nothing about pause detection. It matters more
for articulation rate on short turns and for `TERMINAL_SECONDS = 0.40`, where the
window is only seven boundary errors wide. Real, worth doing, not urgent.

The more interesting route is deleting the stage. CrisperWhisper 2.0 reports 41 ms
on conversational speech and Granite 4.1 2B-Plus reports 38.8 ms, both better than
wav2vec2's 92 ms, both from the recognizer itself. `asr.py` notes that the CT2
build of 1.0 "does not promise to reproduce" its timestamps, which is why the
alignment stage exists. If 2.0 does promise them, an entire 18%-of-runtime stage
and one model load disappear.

## 10. Pitch tracking

The hand-rolled YIN should go, and the reason is not that it is badly written.
It is carefully written, the two bugs it fixed were real, and the module docstring
is the best piece of engineering writing in the repository. The reason is that
YIN-family estimators as a class are now well behind neural trackers on speech.

Independent benchmark, 12 algorithms across 8 datasets, harmonic-mean accuracy
**[verified]**:

| Algorithm | PTDB clean | PTDB noisy |
| --- | ---: | ---: |
| PENN (FCNF0++) | **91.0%** | **76.4%** |
| SwiftF0 | 90.4% | 74.0% |
| Praat | 86.2% | 65.3% |
| CREPE | 79.7% | 53.8% |
| TorchCREPE | 78.3% | 61.2% |
| **pYIN** | **72.1%** | **43.2%** |

The gap between pYIN and either neural tracker is 18 to 33 points. The current
estimator is not pYIN — it has dip descent and parabolic interpolation that
librosa's does not — but it is the same family and the same failure modes, and
nothing in the repository measures it against ground truth. The synthetic-tone
check confirms it is exact on steady periodic input, which is the case that was
never in doubt.

This matters more than it would in most pipelines, because `f0_range_semitones`
and `f0_terminal_rise` are z-scored and thresholded at 1.5σ. Tracker error does
not average out of a range statistic — it inflates it — and a false "pitch
unusually varied" note is exactly the kind of wrong-but-confident annotation §9 of
the review argues against.

Two candidates, both cheap given what is already bundled:

- **`penn`** (FCNF0++) — best on clean and noisy speech, GPU-native via torch,
  which is already a dependency. Roughly 400x realtime on a 3090, so a 90-minute
  recording costs under 15 seconds. **[survey]** Competes with Whisper for VRAM,
  but prosody runs after the ASR stage in the current design anyway.
- **`swift-f0`** — 95,842 parameters, "approximately 42x faster than CREPE on
  CPU", 91.80% harmonic mean at 10 dB SNR, degrading only 2.3 points from clean
  **[verified]**. ONNX-based, and `onnxruntime` is already in the bundle. Leaves
  the GPU alone entirely.

Given the app already ships `onnxruntime`, `swift-f0` is the smaller change and
the better first experiment. Run both against the current tracker on one real
recording and compare the resulting `f0_range_semitones` distributions before
committing; the 23-semitones-versus-10.3 episode is the template for how to do
that.

For the rest — jitter, shimmer, harmonics-to-noise, formants — **Parselmouth**
(Praat in Python) is still the answer, and **openSMILE**'s eGeMAPSv02 gives a
standardized 88-dimension per-turn vector that is citable in a way a bespoke
feature set is not. Note that openSMILE's core is dual-licensed and commercial use
needs a paid audEERING licence. **[survey]**

## 11. Emotion

The scepticism in `ANALYSIS_REVIEW.md` §5 is vindicated, and the fix is one the
package is already three-quarters of the way to.

Valence from acoustics alone is the hard dimension, and the current best practice
is to stop trying. The winning system in the Interspeech 2025 speech-emotion
challenge fused WavLM-Large + Whisper-Large-V3 + RoBERTa-Large **on the
transcript**, and adding the text channel moved average CCC from .6394 to .6588.
76% of top-placing teams were multimodal speech-plus-text; 95% used ensembles.
Dominance came in around .48–.50 across every system, confirming it as the weakest
attribute independently of the 0.931 correlation measured here. **[survey]**

So: the current design computes a lexical channel and an acoustic channel and
*compares* them, looking for mismatch. The literature says the same two channels
should also be *fused* for the valence estimate itself. Those are not in conflict —
fuse for the estimate, keep an unfused acoustic-only figure for the mismatch test —
but the mismatch test needs the unfused one, so the two have to be kept separate
in the code rather than one derived from the other.

On the model itself: audeering's checkpoint reports CCC .744 arousal / .655
dominance / .638 valence on MSP-Podcast v1.7, which remains respectable. **[survey]**
Its licence is listed as CC-BY-NC-SA-4.0, research-only — verify that before any
commercial use. The interesting replacement is not another off-the-shelf SER model
but the Whisper-large-v3 encoder itself: the EmoBox benchmark ranks it top-1 on
23 of 32 datasets for intra-corpus emotion recognition **[survey]**, and the
encoder is already loaded. An attentive-pooling head on frozen Whisper features is
a small amount of training and an MIT-licensed result.

One number to keep in view before any of this gets more ambitious: world-best
eight-way categorical emotion on naturalistic speech is around 43% macro-F1.
**[survey]** The decision not to emit emotion labels is not conservatism, it is
the only defensible reading of that number.

## 12. The channel that is missing

Turn-taking is measured here as reply latency — the gap before a turn begins,
in `_latencies()`. That is the shadow of the real signal.

**Voice Activity Projection** models predict, continuously, whether the acoustic
signal is projecting a turn-yield. `VAP-Realtime` is MIT-licensed code, runs
natively on Windows (explicitly not WSL), CPU or GPU, and ships heads for
backchannel and nodding prediction alongside the base `p_now` / `p_future`
outputs. Pretrained checkpoints are academic-use only, which is the usual caveat.
**[survey]**

Why this is worth more than another emotion model: it distinguishes *interrupted*
from *invited to speak* from *silence after a completed turn*. A 1.8-second gap
means opposite things depending on whether the previous speaker's prosody had
closed the turn. That distinction is the difference between "hesitant" and
"waiting politely", and it is currently invisible — reply latency alone cannot
separate them. It also directly addresses the finding in §7 of the review that
backchannels are being absorbed into the dominant speaker's turn rather than
recorded.

`README.md` lists word-voice mismatch as "the most promising signal here and the
least validated". I would argue turn-taking projection is more promising and
better validated, and it does not depend on the crude lexicon.

There is also a grounded target for the hedging signal, which the current
`_mismatch` rule reaches for without a reference. Goupil et al., *Nature
Communications* 12:861 (2021), used reverse correlation to isolate the prosodic
signature of perceived certainty and honesty: falling intonation, greater loudness
at syllable onsets, faster rate, **lower pitch variability**, reduced duration
variability, with pitch variability at d = 1.11 for honesty and d = 0.62 for
certainty. **[survey]** Three of those five are already computed here. The authors
are explicit that this is a signature of *perception*, not of truth — it tells you
what a listener will infer, which is exactly what a conversation-analysis tool
wants, and is not a lie detector.

## 13. Audio LLMs, and why this architecture is right

The most useful thing I found is that the central architectural bet here — extract
acoustic features, write them down as text, hand them to a language model — is now
the peer-reviewed better option rather than the pragmatic fallback.

**TRACE** (Findings of EACL 2026) **[verified]** converts audio into a textual
"blueprint" of inexpensive signals — transcript, voice quality, prosody, pitch,
loudness, emotion scores, speech rate — and prompts a text LLM over it. The
abstract's claim, verbatim in substance: it "achieves higher agreement with human
raters than ALMs and transcript-only LLM judges while being significantly more
cost-effective." The paper body reports 68.6% against 62.7% text-only and 61.1%
audio-LLM on SPEAKBENCH, and 57.0% / 45.9% / 47.5% on S2S-ARENA, at roughly a
third the cost. **[survey, from the body rather than the abstract]**

`ANALYSIS_REVIEW.md` §12 already cites the earlier EACL result and reaches the
right conclusion. TRACE is the stronger, more recent version of the same argument,
and it goes further: it does not merely say audio LLMs underuse prosody, it shows
the written-down version wins.

Two 2026 papers explain the mechanism. *Heard but Not Heeded* (1 September 2026)
**[verified]** probes Whisper-large-v2, Qwen2-Audio-7B, Qwen2.5-Omni-7B and
Chroma-4B and finds, verbatim: "All models strongly encode speaking style in the
late encoder, that is, the top third of the audio encoder's layers, but this
information is consistently degraded before reaching the output." *Represented but
Ignored* (August 2026) separates perception from interpretation from use, finds
internal prosodic categories decodable at AUC 0.81–1.00, and behavioural recovery
ranging from 92% down to **0%** — DeSTA2.5 represented intonation perfectly and
acted on it not at all. **[survey]**

The one structural suggestion TRACE implies: its blueprint is **structured JSON**,
not prose. The `.analysis.json` sibling file already holds everything needed, so
this is a question of what gets handed to the model rather than what gets
computed. Prose annotations read better to a person; a compact per-turn JSON block
is harder to skim past. Worth an A/B on one recording, since it costs nothing to
try both.

If an audio model is added at all, the shape that survives this evidence is a
narrow second opinion: a small open model (`Eureka-Audio-Instruct`, 1.7B,
Apache-2.0/MIT, roughly 5–6 GB, reported MMAU 74.67 **[survey]**) run only on the
short clips the blueprint already flagged, asked only about tone, with
disagreement treated as a flag for review rather than an override. Not a
replacement for any of this.

---

# Part III — What I would do

## 14. Ranked

Ordered by value against the stated goal — reading what a person means and what
sits behind it — divided by effort.

**1. Score emotion on the merged turn, not on each segment.** §4. Free, internal,
fixes a gap between the documented reasoning and the code, and improves the signal
that the entire moment-selection layer keys on. Nothing to install.

**2. Replace the pitch tracker.** `swift-f0` first, since `onnxruntime` is already
bundled and it leaves the GPU alone. pYIN-class accuracy is 72% clean and 43%
noisy against 90% and 74%, and the two features it feeds are z-scored and
thresholded. Validate by comparing `f0_range_semitones` distributions on a real
recording, the same way the 23-semitone bug was caught.

**3. Robust baselines.** Median and MAD instead of mean and pstdev; raise
`MIN_TURNS_FOR_BASELINE`; consider a trailing-window baseline alongside the global
one, since a 90-minute conversation drifts and a global z-score washes out slow
ramps. Two of the three are a handful of lines. This is also the most likely
reason word-voice mismatch has never fired.

**4. Add turn-taking projection.** §12. The largest genuinely new signal, it runs
on Windows, and it separates three situations the current reply-latency figure
conflates. Check the checkpoint licence.

**5. Fuse text into the valence estimate, keep an unfused copy.** §11. The
transcript is already there and the lexical channel is already computed; the
challenge result says fusion is the cheapest accuracy available. Keeping the
acoustic-only figure separate is what preserves the mismatch test.

**6. Swap the diarizer to `community-1`.** One string. ~1.8 DER points on AMI and
CALLHOME, concentrated in speaker assignment, which is where a wrong label does
the most damage downstream. Check whether the installed whisperx already defaults
to it.

**7. Evaluate CrisperWhisper 2.0.** §7. It resolves the trade `README.md`
documents as unresolved, and it may make the alignment stage redundant. Blocked on
two questions that have to be answered first: whether `crisperwhisper[transformers]`
coexists with pyannote 4.0.7 on Windows, and what the licence permits.

**8. Then consider the aligner.** §9. Qwen3-ForcedAligner is a real 2.5x on
English, Apache-2.0, and small. But if item 7 lands, the stage may not exist.

**9. Try the JSON blueprint against the prose `.md`.** §13. One recording, both
formats, same question, compare the answers.

Items 1 through 3 are internal, cost nothing to install, and can be done in an
afternoon. I would do those and re-run the sample recording before touching
anything with a model download attached, partly because it is the cheap half and
partly because the blocking open question in `ANALYSIS_REVIEW.md` §13 — that every
threshold rests on one call, produced by superseded code — is still open and gets
harder to resolve once more variables move.

## 15. Licence exposure

Worth resolving as a set rather than one at a time, because the answer depends on
whether this app is ever commercial.

| Component | Licence | Status |
| --- | --- | --- |
| `nyralabs/faster_CrisperWhisper` (in use) | CC-BY-NC-4.0 **[survey]** | Non-commercial. Already shipping. |
| CrisperWhisper 2.0 standard weights | Nyra Health Non-Commercial Research **[verified]** | Non-commercial |
| CrisperWhisper 2.0 `_pro` | commercial licence required **[verified]** | Paid; includes Verbatimize |
| audeering emotion model (in use) | CC-BY-NC-SA-4.0 **[survey]** | Non-commercial. Already shipping. |
| `pyannote/speaker-diarization-3.1` (in use) | gated, accept terms | Fine |
| `pyannote/speaker-diarization-community-1` | CC-BY-4.0 **[verified]** | Fine |
| Whisper, `swift-f0`, VAP-Realtime code | MIT | Fine |
| VAP-Realtime pretrained checkpoints | academic use only **[survey]** | Non-commercial |
| `Qwen3-ForcedAligner-0.6B`, Granite Speech 4.1 | Apache-2.0 **[verified / survey]** | Fine |
| openSMILE core | dual-licensed, paid for commercial **[survey]** | Only if adopted |

Two of these are already in the shipping bundle. The README's security note covers
the HuggingFace token; it does not cover this.

## 16. What not to do

- **Do not replace this with an omni-modal model.** §13. Prosody is encoded in the
  late encoder and dropped before the output, with behavioural recovery as low as
  zero. It would also break the local-only guarantee.
- **Do not emit a sarcasm label.** An August 2026 study found that the accuracy
  gain multimodal models get on sarcasm comes from a heuristic — elevated pitch
  and irregular pausing — that diverges from actual sarcasm cues, and that adding
  audio raised false positives 9.8% while cutting false negatives only 7.5%.
  **[survey]** A pitch-excursion-plus-pause rule would flag sincere enthusiasm as
  sarcasm. Emit the observation; let the reader weigh it.
- **Do not add deception detection, however the goal is phrased.** Human accuracy
  is 54% across 206 studies and ~24,500 judges, and acoustic classifiers that beat
  chance within one corpus do not transfer across corpus, speaker or context.
  **[survey]** The Goupil signature in §12 is the legitimate version of this and
  it measures *perceived* certainty. Naming it anything else in the output would
  create an anchoring bias with nothing behind it.
- **Do not ship a single categorical emotion per turn.** 43% macro-F1 is the
  ceiling. The existing decision is correct.
- **Do not chase the leaderboard.** The top ten are within one WER point and the
  benchmarks are short-form. Ten to twenty real calls scored on WER, cpWER and DER
  would be worth more than any of Part II.

## 17. Open questions

Carried forward, still unresolved, and still blocking in the same way:

- Every threshold rests on one 28-minute two-speaker call produced by superseded
  code. Nothing in Part II changes that, and every recommendation above makes it
  slightly harder to resolve.
- Whether `crisperwhisper[transformers]` coexists with pyannote 4.0.7 and whisperx
  on Windows. This gates item 7.
- Whether the app is commercial. This gates §15 and therefore items 7 and 4.
- Whether the current pitch tracker is actually as good as pYIN or better. It has
  never been measured against ground truth, only against a synthetic tone. The
  benchmark in §10 rules out the family, not this specific implementation.

---

## Sources

Verified directly during this review:

- [Qwen/Qwen3-ForcedAligner-0.6B](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B) — alignment AAS table, licence, limits
- [pyannote/speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) — DER table and evaluation protocol
- [nyralabs/CrisperWhisper2.0_large](https://huggingface.co/nyralabs/CrisperWhisper2.0_large) — licence, modes, timestamps, long-form, disfluency F1
- [nyralabs on Hugging Face](https://huggingface.co/nyralabs) — model inventory
- [nyrahealth/CrisperWhisper](https://github.com/nyrahealth/CrisperWhisper) — controllable transcription
- [lars76/pitch-benchmark](https://github.com/lars76/pitch-benchmark) — 12 trackers, 8 datasets
- [SwiftF0, arXiv:2508.18440](https://arxiv.org/abs/2508.18440) — parameters, speed, 10 dB SNR result
- [TRACE, arXiv:2601.13742](https://arxiv.org/abs/2601.13742) — Findings of EACL 2026
- [Heard but Not Heeded, arXiv:2609.00727](https://arxiv.org/abs/2609.00727) — 1 September 2026

From the wider survey, not independently re-checked:

- [Open ASR Leaderboard, arXiv:2510.06961](https://arxiv.org/abs/2510.06961) · [HF Space](https://huggingface.co/spaces/hf-audio/open_asr_leaderboard)
- [ibm-granite/granite-speech-4.1-2b-plus](https://huggingface.co/ibm-granite/granite-speech-4.1-2b-plus)
- [nvidia/parakeet-tdt-0.6b-v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) · [ONNX port](https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx)
- [Qwen/Qwen3-ASR-1.7B](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)
- [Nyra Verbatim Speech Benchmark](https://nyra-labs.com/research/nyra-verbatim-speech-benchmark) · [Verbatimize](https://nyra-labs.com/research/verbatimize)
- [DiariZen, arXiv:2604.21507](https://arxiv.org/html/2604.21507v1) · [Benchmarking Diarization Models, arXiv:2509.26177](https://arxiv.org/abs/2509.26177)
- [PENN / FCNF0++, arXiv:2301.12258](https://arxiv.org/pdf/2301.12258)
- [Interspeech 2025 SER Challenge](https://www.isca-archive.org/interspeech_2025/naini25_interspeech.pdf) · [winning system, arXiv:2506.10930](https://arxiv.org/html/2506.10930)
- [EmoBox, Interspeech 2024](https://www.isca-archive.org/interspeech_2024/ma24b_interspeech.pdf)
- [VAP-Realtime](https://github.com/inokoj/VAP-Realtime) · [Backchannel prediction, NAACL 2025](https://aclanthology.org/2025.naacl-long.367/)
- [Represented but Ignored, arXiv:2608.19211](https://arxiv.org/html/2608.19211)
- [Prosodic heuristics in sarcasm detection, arXiv:2608.30204](https://arxiv.org/html/2608.30204v1)
- [Goupil et al., Nature Communications 12:861 (2021)](https://www.nature.com/articles/s41467-020-20649-4)
- [Bond & DePaulo, PSPR 10(3) 2006](https://journals.sagepub.com/doi/10.1207/s15327957pspr1003_2)
- [audeering emotion model card](https://huggingface.co/audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim)
