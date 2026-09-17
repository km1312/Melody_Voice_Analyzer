# Revolv Transcriber

A Windows desktop app that turns a recording into a transcript you can read
someone's state of mind from. It measures how each voice moved, marks the silences
where they fell, and writes an analysis view built for a language model to read.

The transcript is verbatim by default: two recognizers run and are merged, so it
keeps the filled pauses, cut-off words and repetitions that ordinary transcription
deletes, without mangling names. See "Verbatim by default".

Everything runs locally. No audio leaves the machine.

---

## Quick start

```powershell
.\.venv\Scripts\python.exe main.py
```

Drop files on the window, pick formats, press **Start transcribing**. Or drop files
straight onto `Revolv Transcriber.exe`.

To check a build end to end without the window:

```powershell
& ".\dist\Revolv Transcriber\Revolv Transcriber.exe" --selftest "some-clip.wav"
```

Exit code 0 means the bundle is sound. Without a file it checks imports and
hardware detection only.

**Before the first run**, accept the model terms on huggingface.co for
`pyannote/speaker-diarization-community-1` and `pyannote/segmentation-3.0`, and
put a HuggingFace token in Settings. A token that has only ever accepted the
older `speaker-diarization-3.1` still works: the pipeline says so in the log and
falls back to it. Without one, transcription still runs but every
segment is labelled `UNKNOWN`.

First run downloads about 4.5 GB of models into `%USERPROFILE%\.cache\huggingface`
and takes roughly ten minutes. Every run after that is offline and loads in under
half a minute.

---

## The pipeline, stage by stage

One file moves through eight stages. The seconds are measured on a 28.5-minute
two-person call on an RTX 5060 Ti, 638 seconds end to end with models cached.

| # | Stage | What happens | Seconds |
| --- | --- | --- | ---: |
| 1 | **Decode** | Any container PyAV opens becomes mono 16 kHz float32, via an `AudioResampler` so channel layout and sample rate are the decoder's problem | 5 |
| 2 | **Transcribe** | Whisper large-v3 through faster-whisper: the content words, names and jargon | 28 |
| 3 | **Align** | wav2vec2 forced alignment gives Whisper's words start and end times | 20 |
| 4 | **Verbatim** | CrisperWhisper 2.0 transcribes again, keeping fillers, cut-offs, repetitions and vocal events with its own word timings, and the two are merged word by word | 487 |
| 5 | **Diarize** | pyannote community-1. Words are assigned from its *exclusive* annotation; the overlapping one is kept so simultaneous speech survives | 43 |
| 6 | **Emotion** | audeering's wav2vec2 scores arousal once per turn | 5 |
| 7 | **Stance** | A small learned head on the Whisper encoder reads each turn | 12 |
| 8 | **Prosody** | PENN pitch tracking and loudness across the whole recording | 38 |

Then a ninth step, which is pure Python and needs no GPU:

9. **Analysis.** Segments merge into turns, pauses are extracted from the word
   timings, baselines are computed per speaker, and turns that departed from their
   own speaker's habits are selected. Takes about a second and a half.

Stages 4 to 8 can each be switched off in Settings. Stages 1 to 3 always run.

### Running a stage by hand

Each piece is importable and works on its own.

```python
from revolv.audio import load_audio
from revolv.hardware import detect
from revolv.pipeline import Transcriber

profile = detect()
t = Transcriber(profile, hf_token="hf_...", language="en", log=print)
t.load_models()
segments, meta = t.run("recording.mp4", progress=lambda stage, pct, msg: print(stage, pct))
t.close()
```

`segments` is the same list the `.json` holds. `meta` carries the run details plus
`meta["analysis"]`, the derived account.

### Trimming a recording

Recordings often keep rolling after the participants say goodbye. That tail is
usually a different conversation with different people in it, and because every
observation here is measured against a speaker's own baseline, a few minutes of
unrelated chatter shifts the baseline the whole analysis rests on.

Pass a `(start, end)` pair in seconds. Either end may be `None`:

```python
segments, meta = t.run("recording.mp4", trim=(None, 1780.0))   # drop the tail
segments, meta = t.run("recording.mp4", trim=(90.0, None))     # drop the pre-roll
```

Timestamps are reported against the original media, not the excerpt, so they still
line up when seeking the source file. The range used is recorded in
`meta["trimmed_from"]` and `meta["trimmed_to"]`.

To find the cut point, look for a long silence near the end of a first pass. A call
that ends properly has a goodbye, then a gap, then whatever the room said next.

### Re-analysing a finished transcript

The analysis pass reads output rather than audio, so thresholds can be re-tuned in
about a second without touching the GPU:

```python
import json
from pathlib import Path
from revolv.writers import write_all

segments = json.load(open("call.json", encoding="utf-8"))
meta = {"source": "call.mp4", "media_seconds": 1799.0, "speakers": 2}
write_all(segments, meta, Path("."), "call", ["md"])
```

To include pitch and loudness, decode the audio and pass a track:

```python
from revolv.audio import load_audio
from revolv import prosody, analysis

audio = load_audio("call.mp4")
track = prosody.track(audio, 16000)
meta["analysis"] = analysis.analyse(segments, meta, track=track)
write_all(segments, meta, Path("."), "call", ["md"])
```

**If you clip the array yourself, pass `offset=`.** Turn timestamps are always in
original-media coordinates, so a track built from `audio[90 * 16000:]` must be
`prosody.track(clip, 16000, offset=90.0)`. Without it every pitch and loudness
figure is read 90 seconds late and nothing reports an error. `Transcriber.run`
does this for you when you give it `trim`.

**Check `audio_coverage` in the result.** Nothing else verifies that a transcript
and an audio file belong together, and a mismatch is otherwise silent: prosody just
gets measured at the wrong offsets. The field reports audio length, transcript
length, and how many turns fall inside the audio. If `complete` is false, the pitch
figures past that point are meaningless.

---

## What it writes

| Format | Contents |
| --- | --- |
| `.json` | Every segment with words, timings, speaker, pacing and emotion. Same shape the old pipeline produced, so existing downstream code still reads it. Emotion is now measured once per turn and repeated across that turn's segments, with `emotion.measured_over` giving the span; segments in turns below the four-second gate carry none. |
| `.md` | **The analysis view.** Turns rather than fragments, silences marked where they fell, sparse notes on how a voice departed from its own baseline. Written for a language model. |
| `.analysis.json` | Written alongside the `.md`. Everything the `.md` glosses, as numbers: baselines, per-turn pace, pauses, prosody, emotion, audio coverage. |
| `.txt` | A readable transcript grouped by speaker. |
| `.srt` | Subtitles with the speaker name in each cue. |
| `.csv` | One row per segment. Opens directly in Excel. |

Existing files are never overwritten. A second run writes `name (2).json`.

### About the `.md`

Three things about it are deliberate.

**It describes evidence, not verdicts.** A turn is annotated `(faster than usual;
pitch unusually flat)`, never `(animated)`. A label compresses a noisy acoustic
estimate into a claim the reader cannot reopen, and a wrong one propagates
silently. The reader has the words and the surrounding turns that the acoustic
model never saw, so the inference is better left to them.

**It is sparse.** Only turns that departed from their speaker's own baseline carry
a note. Annotating everything would cost tokens and bury the real departures among
distractors.

**It says what it does not know.** The header states that speaker labels are
automatic and sometimes wrong, that notes are measurements rather than feelings,
and that a turn without a note was not measured rather than found to be flat.

```markdown
# Brian Call 2026-08-19 12-00-26 - 28.5 min - 3 speakers - 105 turns

## Participants
| | Talk time | Turns | Baseline | Articulation | Median reply |
| --- | ---: | ---: | ---: | ---: | ---: |
| SPEAKER_00 | 65% | 51 | 30 turns | 211 wpm | 0.42s |
| SPEAKER_02 | 34% | 49 | 27 turns | 231 wpm | 0.70s |
| SPEAKER_01 | 1% | 5 | none | 180 wpm | 1.32s |

Speakers held the floor at once 85 times, 60s in total, 4.3% of all speech. The
longest ran 4.5s at 04:56. Of those, 55 were backchannels inside another speaker's
turn and 30 were someone taking the floor (SPEAKER_02 21, SPEAKER_00 8, SPEAKER_01 1).

## Moments
- 07:09 SPEAKER_02 - less energy than usual; more mid-sentence hesitation than usual; pauses for 2.4s

## Transcript
[07:09] SPEAKER_02 (less energy than usual; more mid-sentence hesitation than usual):
uh That makes a ton of sense. What was the... um (...2.4s) uh What's the word I'm
looking for? It's like s- s- standard, not standard error, like rate of error.
```

That call comes to about 8,300 tokens this way, against more than 137,000 for the
raw `.json`. The legend at the top of the file is left out of the excerpt.

---

## What changed from the old pipeline

The goal is reading intent. The old pipeline could not deliver that for two reasons
that had nothing to do with how well it ran.

**Whisper transcribes what a speaker meant, not what they said.** It was trained on
subtitle-style text and removes filled pauses, restarts, repetitions and stutters,
which are the most direct evidence of hesitation and discomfort that speech
carries. It also passed `initial_prompt="This is a meeting recording"`, pushing
decoding further toward clean minutes-style prose.

**The output was unreadable by a model.** A half-hour call came to about 137,000
tokens, 72% of it word timings, arriving as hundreds of four-second fragments.

Measured on one 30-minute recording transcribed both ways, with CrisperWhisper 1.0
(since replaced by the two-pass merge below):

| | Old Whisper | CrisperWhisper 1.0 |
| --- | ---: | ---: |
| Filled pauses | 3 | 169 |
| As share of tokens | 0.07% | 3.41% |
| Repeated words | 18 | 43 |
| Words total | 4,499 | 4,955 |

The 3.41% sits squarely in the range ordinary conversation carries.

| | Old | New |
| --- | --- | --- |
| Recognizer | Whisper large-v3 | Whisper large-v3 for content words, merged with CrisperWhisper 2.0 for everything Whisper deletes |
| Decoding bias | "This is a meeting recording" | None |
| Emotion dimensions | Valence, arousal, dominance | Arousal, valence carried but not surfaced |
| Emotion on short turns | Scored anything, padded with silence | Not reported below 4 seconds of speech |
| Pitch and energy | None | Per turn from PENN, normalised per speaker |
| Overlapping speech | Discarded | Kept from the diarization annotation |
| Model-facing output | None | `.md` at about 8,600 tokens |

### Verbatim by default

Neither recognizer is right on its own. Whisper deletes the hesitations; on the
28.5-minute sample call it kept 32 filled pauses in 4,388 tokens, 0.73%, against
roughly 2% in ordinary conversation. CrisperWhisper keeps them, but 1.0 produced
"Chachi" for ChatGPT, "Rubik" for rubric and "Zoo" for Zoom, lost ESG, OpenRouter
and neobanks entirely, and looped on a vocabulary list. So both run, and
`revolv/verbatim.py` merges them:

- **Content words come from Whisper** wherever the two disagree on anything but a
  filler. The vocabulary list applies here and only here.
- **Fillers, cut-offs, repetitions and events come from CrisperWhisper 2.0**, which
  writes them as `[UM]`, `th-`, `we we`, `[laughter]`. They land in the transcript as
  `um`, `th-`, `we we` and `[laughter]`, and each word in the `.json` carries a
  `kind` so nothing downstream has to guess.
- **Timings come from CrisperWhisper** wherever it heard the same word, and
  Whisper's words are fitted between them otherwise, so the transcript runs on one
  clock.

On the sample call:

| | Whisper alone | Merged |
| --- | ---: | ---: |
| Filled pauses | 32 (0.73%) | 132 (2.88%) |
| of which mid-sentence | - | 59 |
| Cut-off words | 0 | 29 |
| Repetitions | - | 33 |
| Whisper's other words, all kept in order | 4,394 | 4,394 |
| Pauses with speech inside them, by CrisperWhisper's timeline | 37 of 80 | 17 of 84 |

Four things went wrong on the way and are recorded so they are not repeated.
Sorting merged words by time scrambled them ("I look got to at some stuff"),
because Whisper's wav2vec2 timings run about 0.12 s later than CrisperWhisper's;
order now comes from the alignment, never from timestamps. Spreading Whisper's
words across a gap moved one sentence 15 seconds and invented a four-second pause;
each word now keeps its own timing clamped into place. And a 1-second guard that
rejected matches whose timings disagreed threw away correct matches: the gaps decay
smoothly to 3.2 seconds with no second cluster, so it is 5 seconds now. And 31 of
Whisper's own 32 fillers were written a second time beside CrisperWhisper's copy of
the same sound ("Um, um correct"); a Whisper filler now survives only where
CrisperWhisper heard none.

What the merge gives up: 210 words only CrisperWhisper heard, mostly restarts and
spelled-out numbers, are dropped by the rule that Whisper wins a disagreement.

**Cost.** CrisperWhisper 2.0 runs on the PyTorch backend with stock
`transformers`; its fast CTranslate2 backend is Linux-only. The verbatim stage is
487 seconds of the 638, and it peaks near 7 GB of VRAM, so the model waits on the
CPU between files. Left on the GPU, it pushed a 16 GB card to 15.9 GB and a
42-second diarization was still running six minutes later. Its weights are under
the Nyra Health Non-Commercial Research License.

### Emotion, reduced on purpose

The emotion model is unchanged. Less of it is believed.

- **Dominance is gone.** It correlated 0.931 with arousal, so it was never a third
  dimension.
- **Valence is recorded but not presented as acoustic evidence.** The paper behind
  this model found its valence performance rests on linguistic information learnt
  during fine-tuning, so it partly reads the words rather than the voice.
- **Nothing is scored below four seconds of speech.** The model's spread is widest
  on its shortest input, and since picking notable moments keys on extremity, an
  ungated selector finds artifacts first. Ungated it flagged 27 turns, 63% under
  three seconds, led by "Yep." at 0.2 seconds. Gated it flagged 15, none short.
- **The score is taken over the whole turn, in one forward pass.** It used to be
  taken per segment, and Whisper cuts roughly every four seconds regardless of who
  is speaking, so a twelve-second turn became four noisy three-second estimates
  averaged together. The gate filtered what was reported; it could not change what
  had been measured. Turns longer than 30 seconds are split at that bound, which
  is a memory limit rather than a linguistic one. `meta["emotion_scope"]` says
  `turn`, and each segment's `emotion.measured_over` gives the span it came from.

### Pitch and energy

New, and the part that does most for reading intent. Each turn gets median pitch,
pitch range in semitones, how far its closing pitch sits above or below the rest of
the turn, loudness variation, and where inside a word the speaker puts the energy,
all against that speaker's own baseline for that recording.

**The tracker is PENN** (FCNF0++), which scores about 91% on clean speech and 76%
on noisy speech in the public pitch benchmark, against about 72% and 43% for the
pYIN family the earlier YIN tracker belongs to. That matters more than it sounds,
because range and terminal rise are z-scored and thresholded: tracker error does
not average out, it becomes notes. On the sample call, PENN and YIN on the same
58 turns:

| | YIN | PENN |
| --- | ---: | ---: |
| Pitch range, median semitones | 13.97 | 8.95 |
| Pitch range, 90th percentile | 20.72 | 12.07 |
| Terminal rise, spread (SD) | 7.03 | 5.26 |
| Turns with a terminal rise at all | 44 | 51 |

YIN read an octave high on 3-7% of the frames both called voiced, and a p90 range
of nearly two octaves in a single turn is that error, not speech.

Two things were needed to run PENN here. Its Viterbi decoder, torbi, ships no CUDA
kernel for this GPU, and on the CPU it took 26 seconds per minute of audio. Cutting
the decode to the 60-400 Hz band is exact provided the transition rows are *not*
renormalised afterwards (renormalising changed the octave on 1.2% of voiced
frames), and decoding pieces on a thread pool brings the whole call to 38 seconds.
And PENN's documented voicing threshold is only valid on periodicity computed
over its full posterior; computed over the 60-400 Hz band every frame gains a floor
of 0.108 and a 0.1 threshold called all of them voiced. On machines without a GPU
the old YIN tracker runs instead, and the `.analysis.json` records which one did.

The YIN history, for the record: a plain normalised autocorrelation first reported
a mean pitch range of 23 semitones per turn, because a zero-padded FFT overlaps
fewer samples at longer lags. YIN with dip descent and parabolic interpolation
fixed that. A least-squares slope over the closing stretch of a turn spread to 21
semitones per second and was replaced by the level comparison still used.

### Hesitation

Filled pauses are counted per turn and placed within their sentence: before the
first word, in the middle, or after the last. The middle matters. A medial filled
pause was the strongest single cue to low confidence in Kirkland et al.
(Interspeech 2022), ahead of high pitch and slow speech, where a filler before a
sentence starts is ordinary planning.

A turn is noted as "more mid-sentence hesitation than usual" when its rate of
medial fillers is unusual for that speaker **and** it has at least two of them.
Half the scored turns on the sample call had none, and one speaker's median was
zero, so without the second condition a single "um" scored far past the threshold.
On that call it fired four times, including "What was the... um uh What's the word
I'm looking for? It's like s- s- standard, not standard error".

### Stance, learned, and why it rarely speaks

Every other note is hand-built. `revolv/stance.py` adds a learned one: a
multinomial logistic regression on the Whisper large-v3 encoder states the
pipeline already computes, trained on SpeechSense (CC-BY-4.0), eight stances from
confident to sarcastic. `tools/train_stance_head.py` rebuilds it; the weights are
a few hundred kilobytes in `revolv/assets/`, beside a report with every figure.

What it measures, honestly:

- **0.41 macro-F1** on the held-out SpeechSense test set. Cross-validation on the
  training set says 0.95 and is not to be believed: a classifier reading only the
  training *transcripts* reaches 0.87, because those texts were written to express
  each stance.
- **It hears nervousness, not confidence.** Nervous F1 0.78; confident recall 0.14.
  The axis the analysis uses, P(confident) - P(nervous), averages -0.74 on nervous
  test clips and about zero on every other stance.
- **On a real call it barely moves.** SpeechSense is synthesised speech. On the
  sample call the head read 52 of 58 turns as warm, the axis stayed between -0.08
  and 0.000, and it did not correlate with mid-sentence hesitation (r = 0.015).

Z-scored against a spread that narrow, it produced eleven "sounds less certain"
notes on that call. Read back, about half were genuinely hesitant turns and half
were ordinary questions or narration, and the most extreme (z = -44) was a plain
question. Half right is not good enough for a note. So a stance note needs the
head to lean nervous in absolute terms (axis at or below -0.25) as well as
relative to the speaker, and only the "sounds less certain than usual" direction
exists. It fired on none of Brian's turns and on one of 87 on a second 30-minute
call. Its probabilities are kept per turn in the
`.analysis.json`. Real conversational stance labels, not a better classifier, are
what would make it useful.

### Baselines

Every note compares a turn with the same speaker's other turns in the same
recording. How that reference is built:

- **A median and a median absolute deviation**, scaled to match a standard
  deviation, not a mean and a standard deviation. One laugh inflates an SD enough to
  silence every genuine departure after it; the median and MAD need half the turns
  to be outliers before they move. Where more than half the turns share a value, as
  with mid-sentence fillers, the interquartile range stands in, and if that is zero
  too no note fires.
- **At least 12 turns**, both scored turns for the speaker (it was 4) and turns with
  a value for the particular feature. Terminal pitch is missing on turns without two
  voiced stretches, and one reference for it had rested on 8.
- **A trailing window on long calls.** Past 15 minutes a turn is compared with the
  speaker's preceding 30 scored turns rather than the whole call, never including
  itself, so a call that warms up is not measured against its own average.
- **The arithmetic travels with the note.** Each moment in the `.analysis.json`
  carries its z-score, the number of turns behind the reference, and whether the
  call-wide or trailing reference was used. The `.md` shows the count per speaker.

**Notes are denser than they were.** A MAD scale is tighter than an SD on these
distributions, and PENN's pitch figures are tighter than YIN's, so more turns clear
1.5 deviations. Pitch-range notes land on 24% of scored turns on Brian's call and
33% on Sanjay's, where normally distributed data would give about 13%. Brian's call
carries 35 moments, Sanjay's 66. A 52-minute three-speaker call carries 88 across
131 scored turns: each feature on its own flags 20-29% of them, and the union over
six features is what leaves two thirds of scored turns with at least one note.
`NOTABLE_SIGMA` has not been retuned: three calls without hand labels are not
enough to choose a value.

### Speakers and overlap

**Diarization is pyannote community-1**, replacing 3.1. Words take their speaker
from its exclusive annotation, which resolves overlapping speech once, and a word
falling between diarized turns takes the nearest one. The overlapping annotation is
kept separately, because whisperx's segments cannot overlap by construction.

**Overlap is classified with the NaturalTurn rule** (Scientific Reports, 2025).
Each speaker's stretches are merged across gaps of up to 1.5 seconds; a listener's
utterance falling wholly inside another speaker's is a backchannel, and anything
else that overlaps is someone taking the floor. On Brian's call that gives 85
overlaps: 55 backchannels and 30 floor-takes, 21 of them by one speaker.

**Three diarizers were compared** on the same audio. Neither call has a reference
diarization, so this is agreement between systems, not accuracy. Talk time per
speaker, in seconds:

| | pyannote 3.1 | community-1 | DiariZen (large-s80-md-v2) |
| --- | --- | --- | --- |
| Brian's call | 890, 553 | 890, 536, 17 | 906, 554, 18, 5 |
| Sanjay's call | 880, 698 | 876, 682, 11, 9 | 902, 703, 15, 6 |
| Overlapping speech, Brian / Sanjay | 37 s / 53 s | 37 s / 53 s | 69 s / 93 s |
| Time per call | 42 s | 42 s | 120 s, 11.8 GB of GPU memory |

On speech frames, after matching speakers, community-1 and 3.1 agree on 99% of both
calls and DiariZen agrees with either on 94-95%.

**A small extra speaker is not always a mistake.** Someone else in the office spoke
during Sanjay's call. community-1 and DiariZen both put a minor speaker at
18:46-18:52, where the words are "Oh my gosh, it's done? Well, it's not reports,
it's not done. It's still in progress. Hi, Grace. Hi, good to see you." pyannote
3.1 folded that into one of the two main speakers. The other minor speaker, in both
systems, is scattered pieces of the presentation: a main speaker split in two. On
Brian's call both put the opening ("Can you give me 20 seconds here? I'm in a
negotiation with the startup") on a minor speaker, which may be a participant away
from the microphone; that is unverified. A speaker with a few seconds of talk can
be a real bystander or a split, and nothing in the output tells which.

**DiariZen is not used.** It finds the same bystander and about twice as much
overlap, and without a reference there is no way to say whether that extra overlap
is real. Against it: three times the runtime, a GPU peak that does not fit beside
the pipeline's other models on 16 GB, non-commercial weights, and a fork of
pyannote 3.1 that cannot share an environment with pyannote 4. Running it at all
took a separate Python 3.11 environment, torch 2.7.1 with CUDA 12.8 in place of its
pinned 2.1.1 (which has no kernels for RTX 50-series cards), and allowlisting four
classes so torch's weights-only checkpoint loading would accept pyannote's
embedding model.

**Turn-taking projection (VAP) was tested and is not used.** The idea was to read
VAP's `p_future` for the incoming speaker just before an overlap begins, to tell an
invited turn from an intrusive one. VAP needs one audio channel per speaker, and
these recordings are mixed down (their two stereo channels are identical), so each
speaker's channel was cut from the mix using community-1's diarization. English
Switchboard model, 20 Hz, 2.5-second context:

| | Brian | Sanjay |
| --- | ---: | ---: |
| Who speaks after a pause, balanced accuracy | 0.76 | 0.62 |
| Floor-take vs backchannel, from `p_future` 0.6-0.1 s before onset, AUC | 0.42 | 0.33 |
| Takeover as the other speaker stops (<1 s of overlap) vs interruption (>=1.5 s), AUC | 0.65 (21 vs 3) | 0.59 (33 vs 5) |
| Runtime, streaming mode | 815 s | 852 s |

VAP works as a turn-taking model: on Brian's call it is close to the published
Switchboard figure of about 0.80. The signal proposed for it is not there. Before a
floor-take, the incoming speaker's `p_future` is lower than before a backchannel on
both calls, and the invited-versus-intrusive comparison rests on eight
interruptions in total, too few to read. It also takes longer than the verbatim
pass, and its checkpoints are for academic use only.

---

## Settings

Stored in `%LOCALAPPDATA%\RevolvTranscriber\settings.json`.

| Key | Default | Meaning |
| --- | --- | --- |
| `hf_token` | seeded by the build, else empty | Gates diarization. Without it every segment is `UNKNOWN`. A build made with a token carries it as the first-run default; otherwise paste one in Settings or set `REVOLV_HF_TOKEN` |
| `asr_backend` | `whisper` | The content-word recognizer. `crisper` is retired and maps to `whisper` |
| `verbatim` | `true` | The CrisperWhisper 2.0 pass. Needs a CUDA GPU; off gives Whisper's transcript alone |
| `stance` | `true` | The learned stance head. Skipped with a log line if its weights are missing |
| `vocabulary` | `""` | Comma-separated names and jargon, applied to the Whisper pass |
| `language` | `en` | `""` or `auto` detects per file |
| `model_override` | `auto` | Pins the Whisper model size |
| `device_override` | `auto` | `auto`, `cuda` or `cpu` |
| `diarize` | `true` | Speaker labelling |
| `emotion` | `true` | Arousal scoring |
| `prosody` | `true` | Pitch (PENN on a GPU, YIN otherwise) and loudness |
| `analysis` | `true` | Turns, baselines, moments. Off also stops `.md` and `.analysis.json` |
| `formats` | `json, md, txt` | Which files to write |
| `output_dir` | `""` | Empty writes beside each input |
| `theme` | `light` | `light` or `dark` |

---

## Tuning

Every threshold is a module-level constant, and every one was derived from a small
number of recordings. They should be re-checked against more, especially any with
more than two speakers.

`revolv/analysis.py`:

| Constant | Default | Effect |
| --- | ---: | --- |
| `TURN_BREAK_SECONDS` | 2.0 | Silence that ends a turn even mid-speaker |
| `EMOTION_MIN_SPEECH` | 4.0 | Speech required before emotion or prosody is reported |
| `PAUSE_MIN_SECONDS` | 1.0 | Gap that counts as a pause |
| `NOTABLE_SIGMA` | 1.5 | Distance from baseline before a turn is flagged |
| `MISMATCH_SIGMA` | 2.0 | Bar for words and voice disagreeing |
| `MIN_TURNS_FOR_BASELINE` | 12 | Scored turns a speaker needs before any note can fire |
| `BASELINE_WINDOW_TURNS` | 30 | Trailing window used instead of the whole call, on long recordings |
| `TRAILING_BASELINE_AFTER_SECONDS` | 900 | Length above which that window applies |
| `UTTERANCE_GAP_SECONDS` | 1.5 | NaturalTurn pause parameter, for backchannel vs floor-taking |
| `CERTAINTY_FLOOR` | -0.25 | How far the stance head must lean nervous before a note can fire |

`revolv/prosody.py`:

| Constant | Default | Effect |
| --- | ---: | --- |
| `PITCH_TRACKER` | `auto` | `penn`, `yin`, or `auto` (PENN when a GPU is present) |
| `F0_MIN_HZ` / `F0_MAX_HZ` | 60 / 400 | Search range. Widen for very high or low voices |
| `PENN_VOICING_THRESHOLD` | 0.1625 | PENN periodicity below this is unvoiced |
| `PENN_PIECE_SECONDS` | 60 | Length of the pieces decoded in parallel |
| `YIN_THRESHOLD` | 0.15 | YIN fallback: lower is stricter about what counts as periodic |
| `VOICING_THRESHOLD` | 0.60 | YIN fallback: below this a frame is treated as unvoiced |
| `TERMINAL_SECONDS` | 0.40 | How much of a turn's end counts as its closing pitch |

`revolv/verbatim.py`:

| Constant | Default | Effect |
| --- | ---: | --- |
| `MATCH_SLACK_SECONDS` | 5.0 | A matched word further apart than this is treated as a different occurrence |
| `MAX_REPEATS` | 4 | More consecutive copies of an inserted word than this is a decoder loop |

---

## Hardware

On launch the app probes the machine and picks settings to match. With a CUDA GPU
it selects by available VRAM:

| VRAM | Whisper model | Precision | Batch |
| --- | --- | --- | --- |
| 15 GB and up | large-v3 | float16 | 16 |
| 11 GB | large-v3 | float16 | 12 |
| 8 GB | large-v3 | float16 | 8 |
| 6 GB | large-v3 | int8_float16 | 4 |
| 4.5 GB | medium | int8_float16 | 4 |
| 3 GB | small | int8_float16 | 4 |
| 2 GB | base | int8_float16 | 2 |

Below 6 GB the emotion model moves to the CPU so it does not compete for VRAM.
Below 2 GB, or with no CUDA GPU, everything falls back to the CPU and the model is
chosen from RAM and core count instead. GPUs older than compute capability 7.0 drop
to int8, since float16 buys them nothing. If the GPU runs out of memory mid-run the
emotion model relocates to the CPU and the run continues rather than failing.

**Speed.** On an RTX 5060 Ti with 15.9 GB, a 28.5-minute recording took 638
seconds end to end with models already cached, three quarters of it the verbatim
pass. A 52.1-minute three-speaker recording took 1,284 seconds on the same card:
954 of them the verbatim pass, 83 diarization, 81 prosody, 53 transcription, 42
alignment and 27 stance. With `verbatim` off it is about two and a half minutes
for the half-hour call. Model loading is paid once per
batch, not once per file, so queueing several recordings together is much faster
than running them one at a time. CPU-only is slower by more than an order of
magnitude.

---

## Troubleshooting

Activity is logged to the window and to
`%LOCALAPPDATA%\RevolvTranscriber\revolv.log`. **Settings > Open log file** opens
it. The log is the place to look if the app closes unexpectedly, since the windowed
build has no console. If a file fails, its row shows why and the rest of the queue
continues.

| Symptom | Cause |
| --- | --- |
| Every speaker is `UNKNOWN` | No HuggingFace token, or model terms not accepted |
| No `um` or `uh` in the transcript | The verbatim pass did not run: `verbatim` is off, there is no CUDA GPU, or the model failed to load. The log says which |
| Log says "loaded without alignment heads" | CrisperWhisper's download was incomplete. Delete its folder under `%USERPROFILE%\.cache\huggingface\hub` and run again |
| Diarization or emotion is suddenly very slow | VRAM is full and Windows is paging it. Close other GPU applications |
| `.md` has few or no notes | Turns are shorter than the four-second gate. Expected on rapid exchanges |
| `audio_coverage.complete` is false | Transcript and audio do not match. Pitch figures past that point are meaningless |
| `.analysis.json` says `pitch_tracker: yin` on a machine with a GPU | PENN failed to import and the log says why. In a bundle it means something PENN needs was left out; `tensorboard` and torbi's compiled `_C*.pyd` kernels were both found this way, and the spec now packs them |

---

## Building

```powershell
.\build.ps1
```

The result is `dist\Revolv Transcriber\`: a 106 MB `.exe` plus an `_internal`
folder, most of it CUDA libraries inside PyTorch. Keep the two together and move
the folder as a unit. A clean build takes about 25 minutes. The build seeds the
bundle with this machine's HuggingFace token as the first-run default; see the
security note at the end.

The bundle is onedir rather than onefile, because a onefile build unpacks about
4 GB of CUDA libraries to a temp folder on every launch. UPX is off; it corrupts
some CUDA DLLs. `torchcodec` is excluded, being broken in this environment and only
reached through a `try`/`except`.

### Layout

| Path | Role |
| --- | --- |
| `main.py` | Entry point. Redirects stdout and stderr to the log, and runs `--selftest`. |
| `revolv/hardware.py` | Hardware probe and the tier tables above. |
| `revolv/audio.py` | Decodes any container PyAV opens to mono 16 kHz. |
| `revolv/asr.py` | The content-word recognizer and its vocabulary list. |
| `revolv/verbatim.py` | The CrisperWhisper 2.0 pass and the word-level merge. |
| `revolv/pipeline.py` | Stages 1 to 8: transcription, alignment, verbatim, diarization, emotion, stance, prosody. |
| `revolv/prosody.py` | PENN and YIN pitch tracking, loudness, and per-turn features. |
| `revolv/stance.py` | Encoder features and the learned stance head. |
| `revolv/assets/` | The stance head's weights and its training report. |
| `tools/train_stance_head.py` | Rebuilds the stance head from SpeechSense. |
| `revolv/analysis.py` | Stage 7. Turns, pauses, baselines, moments. Pure, no models. |
| `revolv/writers.py` | The five output formats. |
| `revolv/gui.py` | The window, built on PySide6. |
| `revolv/theme.py` | Light and dark palettes and the Qt stylesheet. |
| `revolv/config.py` | Settings persistence. |
| `legacy/` | The pipeline as it stood on 2026-09-09, before this change. Nothing imports it. |

### Why Qt and not Tkinter

Tk draws no rounded corners, no shadows and no real hover states, its widget
indicators are fixed-size bitmaps that break on a high-DPI display, and its file
drop hands over a quoted string rather than paths. Qt does all of it natively and
styles through a stylesheet, so the palette lives in one place.

Two Qt details worth knowing if you edit the interface. The stylesheet cannot draw
a chevron or a tick, so both are painted once with QPainter, cached as PNGs and
referenced from the stylesheet. And no drop shadow is applied to the file list: a
`QGraphicsDropShadowEffect` on a scroll area stops its viewport clipping, and the
rows spill over the controls underneath.

---

## Known limits

- **Thresholds rest on two recordings.** Both are half-hour calls between two main
  speakers, and neither has hand labels, so every figure in this file is agreement
  or re-measurement rather than accuracy. Multi-speaker files will behave
  differently, particularly the turn break.
- **Notes are denser than "sparse" suggests.** Each feature lands on a fifth to a
  third of scored turns, and on a 52-minute three-speaker call two thirds of
  scored turns carried at least one note. See "Baselines".
- **Word-voice mismatch has fired once, on an artefact.** On Sanjay's call it marked
  a 110-second walk through a chart ("B2B has always been the biggest sector...") as
  positive words with subdued delivery. The built-in lexicon's positive score came
  from discourse markers, "like" five times, "right" twice and "yeah", plus one
  "Great", and a sum like that grows with the length of the turn. It needs a real
  sentiment channel before it can be judged.
- **The lexical channel is crude.** A small hand-built lexicon, used only to make
  the words-against-voice comparison well-defined. If NLTK's VADER lexicon is
  installed it is used instead, and `settings.lexical_source` in the analysis output
  says which ran.
- **The stance head does not carry over to real speech.** It was trained on
  synthesised speech, reads nearly every real turn as warm, and is held behind an
  absolute floor, so it rarely produces a note. See "Stance".
- **A speaker with a few seconds of talk is ambiguous.** It can be a real bystander
  or a main speaker split in two. See "Speakers and overlap".
- **The verbatim pass needs a CUDA GPU** and takes three quarters of the runtime.
  Without one the transcript is Whisper's alone and carries no filler counts.
- **Emotion is unreported on about half of turns**, by design. Short turns are
  mostly backchannels whose text already says what they are.

## Security note

The HuggingFace token is stored in plain text in
`%LOCALAPPDATA%\RevolvTranscriber\settings.json`, so anyone who can read that file
can read the token. The source carries none: `DEFAULT_HF_TOKEN` in
`revolv/config.py` reads the `REVOLV_HF_TOKEN` environment variable, then a token
`build.ps1` wrote into the bundle, and is otherwise empty. `build.ps1` takes that
token from `REVOLV_HF_TOKEN` or from this machine's own settings file, packs it
as `_internal\revolv\assets\hf_token.txt`, and deletes it from the source tree
once PyInstaller is done; the file is gitignored either way. So a build made here
carries the token as its first-run default, and anyone with the app folder can
read it. Rotate the token at huggingface.co/settings/tokens before handing the
build to someone else.
