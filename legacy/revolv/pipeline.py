"""Transcription + diarization + V/A/D emotion pipeline.

Models are loaded once per Transcriber and reused for every file in the queue,
which is what makes dropping a batch of recordings worthwhile: the several
minutes of model loading is paid once rather than once per file.
"""

import gc

import numpy as np

from .audio import Cancelled, load_audio

MIN_SEGMENT_SECONDS = 1.0   # Wav2Vec2's conv stack needs about a second of input
MAX_SEGMENT_SECONDS = 30.0  # Bound the emotion forward pass so long turns cannot OOM

EMOTION_MODEL_ID = "audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim"

# Relative cost of each stage, used to turn per-stage progress into one bar.
STAGE_WEIGHTS = {
    "decode": 0.07,
    "transcribe": 0.45,
    "align": 0.18,
    "diarize": 0.18,
    "emotion": 0.12,
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


class Transcriber:
    """Holds the loaded models and runs one media file at a time."""

    def __init__(self, profile, hf_token="", language="en", diarize=True,
                 emotion=True, log=None):
        self.profile = profile
        self.hf_token = (hf_token or "").strip()
        self.language = (language or "").strip() or None
        self.want_diarize = bool(diarize and self.hf_token)
        self.want_emotion = bool(emotion)
        self.log = log or (lambda msg: None)

        self.asr_model = None
        self.align_models = {}
        self.diarize_model = None
        self.emotion_processor = None
        self.emotion_model = None
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
        step("Loading Whisper {0} on {1} ({2})".format(
            p.model_size, p.device, p.compute_type))
        self.asr_model = whisperx.load_model(
            p.model_size,
            device=p.device,
            compute_type=p.compute_type,
            language=self.language,
            threads=p.cpu_threads,
            asr_options={"initial_prompt": "This is a meeting recording."},
        )

        if self.language:
            step("Loading the word alignment model for {0}".format(self.language))
            self._align_model_for(self.language)

        if self.want_diarize:
            step("Loading the speaker diarization model")
            from whisperx.diarize import DiarizationPipeline

            self.diarize_model = DiarizationPipeline(
                model_name="pyannote/speaker-diarization-3.1",
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

    def predict_emotion(self, audio, sr, start, end):
        """Return valence/arousal/dominance for [start, end], each in [0, 1]."""
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
            "valence": round(float(np.clip(valence, 0.0, 1.0)), 3),
            "arousal": round(float(np.clip(arousal, 0.0, 1.0)), 3),
            "dominance": round(float(np.clip(dominance, 0.0, 1.0)), 3),
        }

    # -- main entry point --------------------------------------------------
    def run(self, path, progress=None, cancel=None):
        """Transcribe one file. Returns (segments, metadata)."""
        import whisperx

        def check():
            if cancel is not None and cancel.is_set():
                raise Cancelled()

        stages = ["decode", "transcribe", "align"]
        if self.want_diarize:
            stages.append("diarize")
        if self.want_emotion:
            stages.append("emotion")
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

        speaker_count = 0
        if self.want_diarize:
            tracker.set_stage("diarize", "Identifying speakers")
            diarize_segments = self.diarize_model(
                audio,
                progress_callback=lambda f: tracker.report(
                    f / 100.0, "Identifying speakers"),
            )
            result = whisperx.assign_word_speakers(diarize_segments, result)
            try:
                speaker_count = int(diarize_segments["speaker"].nunique())
            except Exception:
                speaker_count = 0
            check()

        segments = result.get("segments", [])
        output = []
        if self.want_emotion:
            tracker.set_stage("emotion", "Scoring emotion")

        for index, seg in enumerate(segments):
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
                words.append(item)

            duration = max(end - start, 0.01)
            word_count = len(words) if words else len(text.split())
            entry = {
                "start": round(start, 2),
                "end": round(end, 2),
                "speaker": seg.get("speaker", "UNKNOWN"),
                "text": text,
                "words": words,
                "pacing": {
                    "word_count": word_count,
                    "duration_seconds": round(duration, 2),
                    "wpm": round(word_count / (duration / 60.0), 1),
                },
            }
            emotion = self.predict_emotion(audio, sr, start, end)
            if emotion is not None:
                entry["emotion"] = emotion
            output.append(entry)

            if self.want_emotion and segments:
                tracker.report((index + 1) / len(segments), "Scoring emotion")

        del audio
        gc.collect()

        meta = {
            "source": str(path),
            "media_seconds": round(media_seconds, 2),
            "language": language,
            "segments": len(output),
            "speakers": speaker_count,
            "model": self.profile.model_size,
            "device": self.profile.device,
            "device_name": self.profile.device_name,
            "compute_type": self.profile.compute_type,
        }
        return output, meta

    def close(self):
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
