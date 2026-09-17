"""Transcription, verbatim merge, diarization, emotion, stance and prosody.

Models are loaded once per Transcriber and reused for every file in the queue,
which is what makes dropping a batch of recordings worthwhile: the several
minutes of model loading is paid once rather than once per file.
"""

import gc

import numpy as np

from . import asr
from .analysis import EMOTION_MIN_SPEECH, build_turns, overlap_events
from .audio import Cancelled, load_audio

MIN_SEGMENT_SECONDS = 1.0   # Wav2Vec2's conv stack needs about a second of input
MAX_SEGMENT_SECONDS = 30.0  # Bound the emotion forward pass so long turns cannot OOM

EMOTION_MODEL_ID = "audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim"
DIARIZATION_MODEL_ID = "pyannote/speaker-diarization-community-1"
FALLBACK_DIARIZATION_ID = "pyannote/speaker-diarization-3.1"

# Relative cost of each stage, used to turn per-stage progress into one bar. These
# are the measured seconds of a 28.5-minute call on an RTX 5060 Ti (638 in all);
# only their proportions matter.
STAGE_WEIGHTS = {
    "decode": 5,
    "transcribe": 28,
    "align": 20,
    "verbatim": 487,   # CrisperWhisper on the PyTorch backend: three quarters of a run
    "diarize": 43,
    "emotion": 5,      # one pass per scored turn, not per segment
    "stance": 12,
    "prosody": 38,     # PENN on the GPU plus a threaded CPU Viterbi decode
}


class ProgressTracker:
    """Maps a fraction within the current stage onto an overall 0..1 fraction."""

    def __init__(self, stages, callback):
        weights = {s: STAGE_WEIGHTS[s] for s in stages}
        total = sum(weights.values()) or 1.0
        self.weights = {s: w / total for s, w in weights.items()}
        self.order = list(stages)
        self.callback = callback
        self.stage = self.order[0] if self.order else "decode"

    def _base(self, stage):
        return sum(self.weights[s] for s in self.order[: self.order.index(stage)])

    def set_stage(self, stage, message=""):
        self.stage = stage
        self.report(0.0, message)

    def report(self, fraction, message=""):
        fraction = min(max(float(fraction or 0.0), 0.0), 1.0)
        overall = self._base(self.stage) + self.weights[self.stage] * fraction
        if self.callback:
            self.callback(self.stage, overall, message)


def _emotion_model_class():
    """Build audeering's published architecture on top of the transformers base.

    The checkpoint uses a RegressionHead that transformers does not ship.
    Loading it as Wav2Vec2ForSequenceClassification silently leaves the head
    randomly initialised, which yields near-constant predictions.
    """
    import torch
    import torch.nn as nn
    from transformers.models.wav2vec2.modeling_wav2vec2 import (
        Wav2Vec2Model,
        Wav2Vec2PreTrainedModel,
    )

    class RegressionHead(nn.Module):
        def __init__(self, config):
            super().__init__()
            self.dense = nn.Linear(config.hidden_size, config.hidden_size)
            self.dropout = nn.Dropout(config.final_dropout)
            self.out_proj = nn.Linear(config.hidden_size, config.num_labels)

        def forward(self, features, **kwargs):
            x = self.dropout(features)
            x = self.dense(x)
            x = torch.tanh(x)
            x = self.dropout(x)
            return self.out_proj(x)

    class EmotionModel(Wav2Vec2PreTrainedModel):
        def __init__(self, config):
            super().__init__(config)
            self.config = config
            self.wav2vec2 = Wav2Vec2Model(config)
            self.classifier = RegressionHead(config)
            self.init_weights()

        def forward(self, input_values, attention_mask=None):
            outputs = self.wav2vec2(input_values, attention_mask=attention_mask)
            hidden_states = outputs[0]
            if attention_mask is not None:
                mask = self._get_feature_vector_attention_mask(
                    hidden_states.shape[1], attention_mask
                )
                hidden_states = (hidden_states * mask.unsqueeze(-1)).sum(dim=1)
                hidden_states = hidden_states / mask.sum(dim=1).unsqueeze(-1)
            else:
                hidden_states = torch.mean(hidden_states, dim=1)
            return hidden_states, self.classifier(hidden_states)

    return EmotionModel




def _trim_audio(audio, sr, trim):
    """Clip the decoded array to (start, end) seconds. Returns (audio, offset, kept)."""
    start, end = (trim + (None, None))[:2] if isinstance(trim, tuple) else (None, None)
    begin = max(int((start or 0.0) * sr), 0)
    finish = len(audio) if end is None else min(int(end * sr), len(audio))
    if finish <= begin:
        raise ValueError("trim range is empty")
    clipped = audio[begin:finish]
    return clipped, begin / sr, len(clipped) / sr


def _annotation_rows(annotation):
    """pyannote's Annotation as plain dicts.

    Kept deliberately dumb so that nothing downstream needs pyannote or pandas
    imported to read a diarization, and so the rows survive a round trip through
    JSON when a transcript is re-analysed later.
    """
    try:
        return [{"start": round(float(segment.start), 3),
                 "end": round(float(segment.end), 3),
                 "speaker": str(label)}
                for segment, _, label in annotation.itertracks(yield_label=True)]
    except Exception:
        return []


def _frame_rows(frame):
    """The same, from whisperx's dataframe form."""
    try:
        return [{"start": round(float(r.start), 3),
                 "end": round(float(r.end), 3),
                 "speaker": str(r.speaker)}
                for r in frame.itertuples()]
    except Exception:
        return []


def _diarization_hook(progress_callback):
    """pyannote's progress hook, mapped onto one monotonic 0-100 range.

    Diarization has two trackable steps, each with its own counter that resets in
    between, so each is given a slice of the range. Lifted from whisperx, which
    is bypassed here only because its wrapper discards the exclusive annotation.
    """
    if progress_callback is None:
        return None

    ranges = {"segmentation": (0.0, 50.0), "embeddings": (50.0, 99.0)}
    highest = [0.0]

    def hook(step_name, step_artifact, file=None, total=None, completed=None):
        if total is None or completed is None or total <= 0:
            return
        begin, finish = ranges.get(step_name, (0.0, 99.0))
        percent = begin + min(completed / total, 1.0) * (finish - begin)
        if percent > highest[0]:
            highest[0] = percent
            progress_callback(percent)

    return hook


class Transcriber:
    """Holds the loaded models and runs one media file at a time."""

    def __init__(self, profile, hf_token="", language="en", diarize=True,
                 emotion=True, log=None, backend=None, prosody=True,
                 analyse=True, model_override="auto", vocabulary="",
                 verbatim=True, stance=True):
        self.profile = profile
        self.hf_token = (hf_token or "").strip()
        self.language = (language or "").strip() or None
        self.want_diarize = bool(diarize and self.hf_token)
        self.want_emotion = bool(emotion)
        self.want_prosody = bool(prosody)
        self.want_analysis = bool(analyse)
        self.want_verbatim = bool(verbatim)
        self.want_stance = bool(stance)
        self.log = log or (lambda msg: None)
        self.backend_choice = backend or asr.DEFAULT_BACKEND
        self.model_override = model_override or "auto"
        self.vocabulary = vocabulary or ""
        self.backend = None        # resolved at load time, once language is known

        self.asr_model = None
        self.align_models = {}
        self.diarize_model = None
        self.emotion_processor = None
        self.emotion_model = None
        self.verbatim_pass = None
        self.stance_head = None
        self._loaded = False

        if diarize and not self.hf_token:
            self.log("No HuggingFace token is set, so speaker diarization is off.")

    # -- model loading -----------------------------------------------------
    def load_models(self, progress=None, cancel=None):
        if self._loaded:
            return
        import torch
        import whisperx

        def step(msg):
            self.log(msg)
            if progress:
                progress(msg)
            if cancel is not None and cancel.is_set():
                raise Cancelled()

        p = self.profile
        name, model_id, asr_options = asr.resolve(
            self.backend_choice, p, self.language, log=self.log,
            model_override=self.model_override)
        self.backend = name
        spec = asr.BACKENDS[name]
        asr_options = asr.with_vocabulary(asr_options, self.vocabulary)
        if self.vocabulary:
            step("Biasing decoding toward {0} custom terms".format(
                len(self.vocabulary.split(","))))

        # No initial_prompt. The old pipeline passed "This is a meeting recording",
        # which nudges decoding toward clean minutes-style prose and away from the
        # hesitations and restarts this project exists to capture.
        step("Loading {0} on {1} ({2})".format(spec["label"], p.device, p.compute_type))
        self.asr_model = whisperx.load_model(
            model_id,
            device=p.device,
            compute_type=p.compute_type,
            language=self.language,
            threads=p.cpu_threads,
            asr_options=asr_options,
        )

        if self.language:
            step("Loading the word alignment model for {0}".format(self.language))
            self._align_model_for(self.language)

        if self.want_verbatim:
            self._load_verbatim(step)

        if self.want_stance:
            from .stance import HEAD_PATH, StanceHead

            if StanceHead.available():
                self.stance_head = StanceHead()
                step("Stance head loaded ({0}, test macro-F1 {1})".format(
                    self.stance_head.info.get("trained", "?"),
                    self.stance_head.info.get("test_macro_f1", "?")))
            else:
                self.log("No stance head at {0}; run tools/train_stance_head.py "
                         "to build one. Continuing without it.".format(HEAD_PATH))

        if self.want_diarize:
            step("Loading the speaker diarization model")
            from whisperx.diarize import DiarizationPipeline

            # community-1, not 3.1. Same licence terms in practice (CC-BY-4.0,
            # gated), VBx clustering rather than AHC, and better on every public
            # meeting set: AMI SDM 19.9 against 22.7 DER, AliMeeting 20.3 against
            # 24.5. It also emits the exclusive annotation that `_diarize` uses.
            # whisperx >= 3.8 already defaults to it; the old pin was the only
            # thing holding this pipeline on the previous model.
            #
            # It finds small extra speakers 3.1 does not, and they are not all
            # errors: on one test call it found a bystander in the room ("Hi,
            # Grace") that 3.1 folded into a main speaker, alongside a genuine
            # split of a main speaker. DiariZen was tested as a replacement and
            # agreed on 95% of speech at three times the runtime and 11.8 GB of
            # GPU memory; see "Speakers and overlap" in README.md.
            try:
                self.diarize_model = DiarizationPipeline(
                    model_name=DIARIZATION_MODEL_ID,
                    token=self.hf_token,
                    device=torch.device(p.diarize_device),
                )
            except Exception as error:
                # Both models are gated, and their conditions are accepted
                # separately. A token that was only ever used for 3.1 cannot
                # fetch community-1 until someone visits its model page, and
                # that is worth saying rather than failing the whole run.
                self.log("Could not load {0} ({1}). Falling back to {2}; accept "
                         "the conditions on its HuggingFace model page to get "
                         "the newer diarizer.".format(
                             DIARIZATION_MODEL_ID, error, FALLBACK_DIARIZATION_ID))
                self.diarize_model = DiarizationPipeline(
                    model_name=FALLBACK_DIARIZATION_ID,
                    token=self.hf_token,
                    device=torch.device(p.diarize_device),
                )

        if self.want_emotion:
            step("Loading the emotion model")
            from transformers import Wav2Vec2Processor

            emotion_class = _emotion_model_class()
            self.emotion_processor = Wav2Vec2Processor.from_pretrained(EMOTION_MODEL_ID)
            self.emotion_model = emotion_class.from_pretrained(EMOTION_MODEL_ID)
            self.emotion_model.to(p.emotion_device)
            self.emotion_model.eval()

        self._loaded = True
        step("Models ready")

    def _load_verbatim(self, step):
        """Load CrisperWhisper 2.0, or explain why the run goes on without it.

        A missing verbatim pass degrades the transcript to Whisper alone, which
        is what every run produced before, so it is logged rather than raised.
        """
        from .verbatim import VERBATIM_LICENCE, VERBATIM_MODEL_ID, VerbatimPass

        if self.profile.device != "cuda":
            self.log("The verbatim pass needs a CUDA GPU; on the CPU it would take "
                     "hours. Transcripts will not include fillers or cut-offs.")
            return
        step("Loading CrisperWhisper 2.0 for the verbatim pass. "
             "Licence: {0}".format(VERBATIM_LICENCE))
        try:
            self.verbatim_pass = VerbatimPass(
                device="cuda", compute_type=self.profile.compute_type,
                log=self.log, token=self.hf_token)
        except Exception as error:
            self.verbatim_pass = None
            self.log("Could not load {0} ({1}). Transcripts will not include "
                     "fillers or cut-offs.".format(VERBATIM_MODEL_ID, error))

    def _align_model_for(self, language_code):
        import whisperx

        if language_code not in self.align_models:
            model, metadata = whisperx.load_align_model(
                language_code=language_code, device=self.profile.device
            )
            self.align_models[language_code] = (model, metadata)
        return self.align_models[language_code]

    # -- emotion -----------------------------------------------------------
    def _segment_samples(self, audio, sr, start, end):
        end = min(end, start + MAX_SEGMENT_SECONDS)
        seg = audio[int(start * sr): int(end * sr)]
        floor = int(MIN_SEGMENT_SECONDS * sr)
        if len(seg) >= floor:
            return seg
        if len(seg) == 0:
            return np.zeros(floor, dtype=np.float32)
        return np.pad(seg, (0, floor - len(seg)), mode="constant")

    def _predict_raw(self, audio, sr, start, end):
        """One forward pass over [start, end]. Returns unclipped V/A/D, or None."""
        import torch

        if not self.want_emotion or self.emotion_model is None:
            return None

        seg = self._segment_samples(audio, sr, start, end)
        prepared = self.emotion_processor(seg, sampling_rate=sr)
        values = prepared["input_values"][0].reshape(1, -1)

        logits = None
        for attempt in range(2):
            device = self.profile.emotion_device
            try:
                tensor = torch.from_numpy(values).to(device)
                with torch.no_grad():
                    _, logits = self.emotion_model(tensor)
                break
            except torch.cuda.OutOfMemoryError:
                if device == "cpu" or attempt == 1:
                    return None
                self.log("The GPU ran out of memory on the emotion model; "
                         "moving it to the CPU.")
                torch.cuda.empty_cache()
                self.emotion_model.to("cpu")
                self.profile.emotion_device = "cpu"

        if logits is None:
            return None

        arousal, dominance, valence = logits.detach().cpu().numpy().squeeze()
        return {
            "valence": float(valence),
            "arousal": float(arousal),
            "dominance": float(dominance),
        }

    @staticmethod
    def _emotion_entry(raw):
        """Package raw V/A/D for output, keeping any excursion outside [0, 1].

        A prediction that left the range is a sign the model was out of its depth,
        and silently pinning it to a boundary hides that: the sample call had a
        turn reported at arousal 0.000, which read as certainty rather than as a
        clipped miss.
        """
        if raw is None:
            return None
        result = {key: round(float(np.clip(value, 0.0, 1.0)), 3)
                  for key, value in raw.items()}
        if any(value < 0.0 or value > 1.0 for value in raw.values()):
            result["raw"] = {k: round(float(v), 4) for k, v in raw.items()}
            result["clipped"] = True
        return result

    def predict_emotion(self, audio, sr, start, end):
        """Return valence/arousal/dominance for [start, end], each in [0, 1]."""
        return self._emotion_entry(self._predict_raw(audio, sr, start, end))

    def emotion_over(self, audio, sr, start, end):
        """Score one whole turn, splitting only when it exceeds the memory bound.

        The per-segment version this replaces measured whatever Whisper happened
        to cut, which is roughly every four seconds regardless of who is speaking.
        A twelve-second turn therefore became four noisy three-second estimates
        averaged together, and the emotion model's spread is widest on exactly the
        shortest input: valence SD 0.147 under a second against 0.096 over five.
        The duration gate downstream filtered what was *reported* but could not
        change what had been *measured*. This does.

        Turns longer than the memory bound are split at that bound rather than at
        segment edges, so the pieces are as long as the hardware allows, and they
        are combined on raw values before clipping.
        """
        if end - start <= 0:
            return None

        cuts = []
        cursor = start
        while cursor < end - 1e-6:
            stop = min(cursor + MAX_SEGMENT_SECONDS, end)
            cuts.append((cursor, stop))
            cursor = stop
        # A sliver left at the end is worse than a slightly over-long final piece:
        # the model is least reliable on exactly that length.
        if len(cuts) > 1 and cuts[-1][1] - cuts[-1][0] < MIN_SEGMENT_SECONDS:
            tail = cuts.pop()
            cuts[-1] = (cuts[-1][0], tail[1])

        scored = []
        for begin, finish in cuts:
            raw = self._predict_raw(audio, sr, begin, finish)
            if raw is not None:
                scored.append((finish - begin, raw))
        if not scored:
            return None

        weight = sum(seconds for seconds, _ in scored)
        combined = {
            key: sum(seconds * raw[key] for seconds, raw in scored) / weight
            for key in scored[0][1]
        }
        entry = self._emotion_entry(combined)
        if entry is not None and len(scored) > 1:
            entry["passes"] = len(scored)
        return entry

    def score_turn_emotion(self, segments, audio, sr, offset,
                           tracker=None, check=None):
        """Attach a turn-level emotion reading to every segment of each turn.

        The value is written onto each segment rather than kept beside the turn so
        that the `.json` and `.csv` keep the shape every existing consumer reads;
        `measured_over` records the span it actually came from, so nobody can
        mistake it for a per-segment measurement.

        Turns below the reporting gate are not scored at all. Nothing downstream
        uses them: they are excluded from the notes and from the baselines alike,
        because unreliable turns otherwise inflate the deviation everything else
        is measured against.
        """
        turns = [t for t in build_turns(segments)
                 if t["speech_seconds"] >= EMOTION_MIN_SPEECH]
        scored = 0
        for index, turn in enumerate(turns):
            if check is not None:
                check()
            # The audio array starts at the trim point; the timestamps do not.
            entry = self.emotion_over(
                audio, sr, turn["start"] - offset, turn["end"] - offset)
            if entry is not None:
                entry["measured_over"] = [round(turn["start"], 2),
                                          round(turn["end"], 2)]
                for segment in turn["segments"]:
                    segment["emotion"] = entry
                scored += 1
            if tracker is not None and turns:
                tracker.report((index + 1) / len(turns), "Scoring emotion")
        return scored

    def score_turn_stance(self, segments, audio, sr, offset, tracker=None, check=None):
        """Attach the stance head's reading to every segment of each scored turn.

        Same gate and same storage as emotion: one reading per turn, repeated on
        its segments with the span it came from, and nothing for turns too short
        to measure.
        """
        from .stance import span_features

        encoder = getattr(self.asr_model, "model", None)
        if self.stance_head is None or encoder is None:
            return 0
        turns = [t for t in build_turns(segments)
                 if t["speech_seconds"] >= EMOTION_MIN_SPEECH]
        scored = 0
        for index, turn in enumerate(turns):
            if check is not None:
                check()
            features = span_features(encoder, audio, sr,
                                     turn["start"] - offset, turn["end"] - offset)
            if features is not None:
                entry = self.stance_head.reading(features)
                entry["measured_over"] = [round(turn["start"], 2), round(turn["end"], 2)]
                for segment in turn["segments"]:
                    segment["stance"] = entry
                scored += 1
            if tracker is not None and turns:
                tracker.report((index + 1) / len(turns), "Reading stance")
        return scored

    # -- diarization -------------------------------------------------------
    def _diarize(self, audio, sr, progress_callback=None):
        """Diarize once, keeping both of the annotations community-1 produces.

        whisperx's wrapper returns only the overlapping annotation, and
        `assign_word_speakers` then hands each word to whichever speaker overlaps
        it most. community-1 also emits an *exclusive* annotation, built for
        exactly this downstream use: overlapping speech is resolved once, by the
        model that heard it, rather than by a per-word argmax over regions where
        two people were talking. Words are assigned from that one.

        The overlapping annotation is kept as well, because it is the only record
        that two people spoke at once: whisperx segments come from voice-activity
        chunks and cannot overlap by construction, so without this simultaneous
        speech is not merely unmeasured, it is unmeasurable downstream.

        Audio is handed over as an in-memory waveform dict, which is also what
        keeps pyannote 4 away from torchcodec, whose shared libraries do not load
        on this machine.

        Returns (words_frame, overlapping_rows, speaker_count).
        """
        import pandas as pd
        import torch

        output = None
        model = getattr(self.diarize_model, "model", None)
        if model is not None:
            try:
                output = model(
                    {"waveform": torch.from_numpy(audio[None, :]),
                     "sample_rate": sr},
                    **({"hook": _diarization_hook(progress_callback)}
                       if progress_callback else {}),
                )
            except Exception as error:
                self.log("Could not read pyannote's full output ({0}); falling "
                         "back to whisperx's wrapper.".format(error))
                output = None

        if output is None or not hasattr(output, "speaker_diarization"):
            frame = self.diarize_model(audio, progress_callback=progress_callback)
            rows = _frame_rows(frame)
            return frame, rows, len({r["speaker"] for r in rows})

        if progress_callback:
            progress_callback(100.0)

        full_rows = _annotation_rows(output.speaker_diarization)
        exclusive = getattr(output, "exclusive_speaker_diarization", None)
        word_rows = _annotation_rows(exclusive) if exclusive is not None else []
        if not word_rows:
            word_rows = full_rows
        else:
            self.log("Assigning words from the exclusive diarization "
                     "({0} turns, {1} with overlap).".format(
                         len(word_rows), len(full_rows)))
        frame = pd.DataFrame(word_rows, columns=["start", "end", "speaker"])
        return frame, full_rows, len({r["speaker"] for r in full_rows})

    # -- main entry point --------------------------------------------------
    def run(self, path, progress=None, cancel=None, trim=None):
        """Transcribe one file. Returns (segments, metadata).

        `trim` is an optional (start_seconds, end_seconds) pair. Either end may be
        None. Recordings often keep rolling after the participants say goodbye, and
        that tail is usually a different conversation with different people in it,
        which drags the per-speaker baselines the whole analysis rests on.

        Timestamps are reported against the original media, not the trimmed
        excerpt, so they still line up with the source file when seeking.
        """
        import whisperx

        def check():
            if cancel is not None and cancel.is_set():
                raise Cancelled()

        stages = ["decode", "transcribe", "align"]
        if self.verbatim_pass is not None:
            stages.append("verbatim")
        if self.want_diarize:
            stages.append("diarize")
        if self.want_emotion:
            stages.append("emotion")
        if self.stance_head is not None:
            stages.append("stance")
        if self.want_prosody:
            stages.append("prosody")
        tracker = ProgressTracker(stages, progress)

        sr = 16000
        tracker.set_stage("decode", "Decoding audio")
        audio = load_audio(
            path,
            target_sr=sr,
            progress=lambda f: tracker.report(f, "Decoding audio"),
            cancel=cancel,
        )
        media_seconds = len(audio) / sr
        offset = 0.0
        trimmed = False
        if trim:
            audio, offset, kept = _trim_audio(audio, sr, trim)
            # A range wider than the file is not a trim. Saying so anyway would
            # misreport an untouched recording as an excerpt.
            trimmed = kept < media_seconds - 0.05 or offset > 0.05
            if trimmed:
                self.log("Trimmed to {0:.1f}s-{1:.1f}s of {2:.1f}s".format(
                    offset, offset + kept, media_seconds))
            else:
                self.log("Trim range covers the whole file; nothing removed.")
            media_seconds = kept
        check()

        tracker.set_stage("transcribe", "Transcribing")
        result = self.asr_model.transcribe(
            audio,
            batch_size=self.profile.batch_size,
            progress_callback=lambda f: tracker.report(f / 100.0, "Transcribing"),
        )
        check()

        language = result.get("language") or self.language or "en"
        tracker.set_stage("align", "Aligning word timestamps")
        align_model, metadata = self._align_model_for(language)
        result = whisperx.align(
            result["segments"],
            align_model,
            metadata,
            audio,
            self.profile.device,
            return_char_alignments=False,
            progress_callback=lambda f: tracker.report(
                f / 100.0, "Aligning word timestamps"),
        )
        check()

        verbatim_stats = None
        if self.verbatim_pass is not None:
            from .verbatim import merge

            tracker.set_stage("verbatim", "Transcribing verbatim")
            words = self.verbatim_pass.words(audio, sr, language=language)
            check()
            verbatim_stats = {"verbatim_words": len(words)}
            result["segments"] = merge(result["segments"], words, verbatim_stats)
            tracker.report(1.0, "Transcribing verbatim")
            self.log("Verbatim merge: {0}".format(verbatim_stats))

        speaker_count = 0
        diarization = []
        overlaps = []
        if self.want_diarize:
            tracker.set_stage("diarize", "Identifying speakers")
            frame, diarization, speaker_count = self._diarize(
                audio, sr,
                progress_callback=lambda f: tracker.report(
                    f / 100.0, "Identifying speakers"),
            )
            # fill_nearest: a word always belongs to someone. The verbatim merge
            # times segments by their words, which is tighter than Whisper's
            # bounds, and on the sample call it left one 0.12 s "Right." between
            # two diarized turns, where it became a fourth speaker, UNKNOWN.
            result = whisperx.assign_word_speakers(frame, result, fill_nearest=True)
            if offset:
                for row in diarization:
                    row["start"] = round(row["start"] + offset, 3)
                    row["end"] = round(row["end"] + offset, 3)
            overlaps = overlap_events(diarization)
            check()

        model_label = (asr.BACKENDS[self.backend]["label"] if self.backend
                       else self.profile.model_size)
        segments = result.get("segments", [])
        output = []

        for seg in segments:
            check()
            start = float(seg.get("start", 0.0) or 0.0)
            end = float(seg.get("end", start + 1.0) or start + 1.0)
            text = (seg.get("text") or "").strip()

            words = []
            for w in seg.get("words", []):
                item = {
                    "word": w.get("word", ""),
                    "start": round(float(w.get("start", start) or start), 2),
                    "end": round(float(w.get("end", end) or end), 2),
                }
                if "speaker" in w:
                    item["speaker"] = w["speaker"]
                if w.get("kind"):
                    item["kind"] = w["kind"]
                words.append(item)

            duration = max(end - start, 0.01)
            # A vocal event is not a word. A filler is: it takes speaking time.
            spoken = [w for w in words if w.get("kind") != "event"]
            word_count = len(spoken) if words else len(text.split())
            if offset:
                for item in words:
                    item["start"] = round(item["start"] + offset, 2)
                    item["end"] = round(item["end"] + offset, 2)
            output.append({
                "start": round(start + offset, 2),
                "end": round(end + offset, 2),
                "speaker": seg.get("speaker", "UNKNOWN"),
                "text": text,
                "words": words,
                "pacing": {
                    "word_count": word_count,
                    "duration_seconds": round(duration, 2),
                    "wpm": round(word_count / (duration / 60.0), 1),
                },
            })

        # Emotion runs after the segments are assembled, because it is scored over
        # whole turns and a turn is not known until its segments are.
        scored_turns = 0
        if self.want_emotion:
            tracker.set_stage("emotion", "Scoring emotion")
            scored_turns = self.score_turn_emotion(
                output, audio, sr, offset, tracker=tracker, check=check)
            tracker.report(1.0, "Scoring emotion")

        stance_turns = 0
        if self.stance_head is not None:
            tracker.set_stage("stance", "Reading stance")
            stance_turns = self.score_turn_stance(
                output, audio, sr, offset, tracker=tracker, check=check)
            tracker.report(1.0, "Reading stance")

        meta = {
            "source": str(path),
            "media_seconds": round(media_seconds, 2),
            "language": language,
            "segments": len(output),
            "speakers": speaker_count,
            "backend": self.backend,
            "verbatim": verbatim_stats is not None,
            "model": model_label,
            "device": self.profile.device,
            "device_name": self.profile.device_name,
            "compute_type": self.profile.compute_type,
        }
        if verbatim_stats is not None:
            from .verbatim import VERBATIM_MODEL_ID, summary

            meta["verbatim_model"] = VERBATIM_MODEL_ID
            meta["verbatim_merge"] = verbatim_stats
            meta["verbatim_tokens"] = summary(output)
        if self.stance_head is not None:
            meta["stance_head"] = self.stance_head.info
            meta["stance_scored_turns"] = stance_turns
        if self.want_emotion:
            # Say where the reading came from, so a reader of the `.json` cannot
            # mistake a value repeated across a turn's segments for a measurement
            # of each of them.
            meta["emotion_scope"] = "turn"
            meta["emotion_scored_turns"] = scored_turns
        if trimmed:
            meta["trimmed_from"] = round(offset, 2)
            meta["trimmed_to"] = round(offset + media_seconds, 2)
        if diarization:
            # Kept for the analysis pass, which needs whole diarized utterances to
            # tell a backchannel from someone taking the floor. Not written out:
            # `writers` only ever serialises `meta["analysis"]`.
            meta["diarization"] = diarization
        if overlaps:
            meta["overlaps"] = overlaps
            meta["overlap_seconds"] = round(sum(o["seconds"] for o in overlaps), 2)

        # Prosody runs on the decoded audio, so it has to happen before the array
        # is released. It is a batched FFT autocorrelation, around 300x realtime,
        # which is why it can run on every file rather than on request.
        track = None
        if self.want_prosody:
            from . import prosody

            tracker.set_stage("prosody", "Measuring pitch and energy")
            # `offset` matters: the array starts at the trim point while every
            # timestamp in `output` is in original-media coordinates, so without
            # it every pitch and loudness figure is read `offset` seconds early.
            track = prosody.track(audio, sr, offset=offset, log=self.log)
            meta["pitch_tracker"] = track.estimator
            tracker.report(1.0, "Measuring pitch and energy")
            check()

        del audio
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

        if self.want_analysis:
            from .analysis import analyse

            meta["analysis"] = analyse(output, meta, track=track)

        return output, meta

    def close(self):
        if self.verbatim_pass is not None:
            self.verbatim_pass.close()
        self.verbatim_pass = None
        self.stance_head = None
        self.asr_model = None
        self.align_models = {}
        self.diarize_model = None
        self.emotion_model = None
        self.emotion_processor = None
        self._loaded = False
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
