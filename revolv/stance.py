"""A learned stance reading, from the Whisper encoder the pipeline already loads.

Everything else this project says about a voice is hand-built: a handful of
z-scores on pitch, loudness, rate and one emotion model's arousal. That is the
right trunk -- every audio language model that fits a 16 GB card scores 8-20% on
adversarial paralinguistics and tends to over-read prosody -- but it caps what the
`.md` can carry. On SpeechSense, eight interpersonal stances (confident, nervous,
passionate, impatient, warm, apathetic, sarcastic, neutral), text-only readers
collapse while models with acoustic access do far better, and a frozen speech
encoder with a small classifier recovers much of that gap. The reader of the `.md`
is a text-only model, so the gap is exactly what this closes.

The head is deliberately small: mean and standard deviation of the last encoder
layer over the turn, standardised, into a multinomial logistic regression. It
costs one extra encoder pass per scored turn and adds no model to the bundle; the
weights are a few hundred kilobytes of numbers in `assets/`. `tools/
train_stance_head.py` rebuilds them from scratch.

What it is, measured (`assets/stance_head.json` has every figure):

* 0.41 macro-F1 over the eight stances on the held-out SpeechSense test set, in
  line with published frozen-encoder baselines. Cross-validation on the training
  set says 0.95, and that number is not to be believed: a classifier reading only
  the training *transcripts* scores 0.87, because those texts were written to
  express each stance. Part of what the head learned is lexical.
* It hears nervousness well (F1 0.78) and confidence badly (recall 0.14; confident
  clips are mostly called apathetic). The axis P(confident) - P(nervous)
  separates the two classes at AUC 0.996, but the class means say why: -0.74 for
  nervous against +0.12 for confident and roughly zero for every other stance.
  In practice it is a nervousness detector.

So only its low end reaches the `.md`, as "sounds less certain than usual",
compared against the speaker's own baseline like every other note. The high end
is not reported: "less nervous than this speaker usually sounds" is not evidence
of confidence. SpeechSense is synthesised speech and a meeting is not, so class
probabilities are kept in the `.analysis.json` for research and never written
into the transcript as a label.
"""

import json
import math
from pathlib import Path

import numpy as np

STANCE_LABELS = ("confident", "nervous", "passionate", "impatient",
                 "warm", "apathetic", "sarcastic", "neutral")
HEAD_PATH = Path(__file__).resolve().parent / "assets" / "stance_head.npz"

# Whisper's encoder emits one frame per 20 ms over a fixed 30 s window.
FRAME_SECONDS = 0.02
WINDOW_SECONDS = 30.0
ENCODER_BATCH = 8


def encoder_states(whisper_model, audio, sr=16000):
    """Last-layer encoder states for up to 30 s of audio, padding frames removed.

    `whisper_model` is whisperx's (faster-whisper's) WhisperModel: the object
    `whisperx.load_model(...).model`. Returns a float32 array (frames, dim).
    """
    return encoder_states_batch(whisper_model, [audio], sr)[0]


def encoder_states_batch(whisper_model, clips, sr=16000):
    """Encoder states for several clips of up to 30 s each, in one pass."""
    import torch
    from whisperx.audio import N_SAMPLES, log_mel_spectrogram

    if sr != 16000:
        raise ValueError("Whisper's encoder expects 16 kHz audio")
    n_mels = whisper_model.feat_kwargs.get("feature_size") or 80
    features, frames = [], []
    for clip in clips:
        clip = np.asarray(clip, dtype=np.float32)[:N_SAMPLES]
        mel = log_mel_spectrogram(clip, n_mels=n_mels, padding=N_SAMPLES - len(clip))
        features.append(mel.numpy())
        frames.append(max(1, min(int(math.ceil(len(clip) / sr / FRAME_SECONDS)), 1500)))
    output = whisper_model.encode(np.stack(features))
    states = torch.as_tensor(output, device="cuda" if output.device == "cuda" else "cpu")
    states = states.float().cpu().numpy()
    return [states[i, :frames[i]] for i in range(len(clips))]


def pooled(states):
    """Mean and standard deviation over frames: the head's input."""
    states = np.concatenate(states, axis=0) if isinstance(states, list) else states
    return np.concatenate([states.mean(axis=0), states.std(axis=0)]).astype(np.float32)


def span_features(whisper_model, audio, sr, start, end):
    """Pooled encoder features for [start, end] in array time.

    Spans longer than the encoder window are cut into 30 s pieces and their
    frames pooled together, so a long turn is described by all of its speech
    rather than by its first half-minute.
    """
    begin = max(int(start * sr), 0)
    finish = min(int(end * sr), len(audio))
    if finish - begin < int(0.5 * sr):
        return None
    step = int(WINDOW_SECONDS * sr)
    pieces = [audio[i:min(i + step, finish)] for i in range(begin, finish, step)]
    if len(pieces) > 1 and len(pieces[-1]) < sr:
        pieces[-2] = np.concatenate([pieces[-2], pieces[-1]])[-step:]
        pieces.pop()
    states = []
    for i in range(0, len(pieces), ENCODER_BATCH):
        states.extend(encoder_states_batch(whisper_model, pieces[i:i + ENCODER_BATCH], sr))
    return pooled(states)


class StanceHead:
    """The trained classifier: standardise, then multinomial logistic regression."""

    def __init__(self, path=HEAD_PATH):
        data = np.load(path, allow_pickle=False)
        self.mean = data["mean"]
        self.scale = data["scale"]
        self.coef = data["coef"]
        self.intercept = data["intercept"]
        self.labels = tuple(str(label) for label in data["labels"])
        self.info = json.loads(str(data["info"])) if "info" in data else {}
        missing = {"confident", "nervous"} - set(self.labels)
        if missing:
            raise ValueError("stance head lacks labels: {0}".format(sorted(missing)))

    @staticmethod
    def available(path=HEAD_PATH):
        return Path(path).exists()

    def probabilities(self, features):
        z = (np.asarray(features, dtype=np.float64) - self.mean) / self.scale
        logits = z @ self.coef.T + self.intercept
        logits -= logits.max()
        weights = np.exp(logits)
        return weights / weights.sum()

    def reading(self, features):
        """Probabilities by label, plus the one axis the analysis compares."""
        probs = self.probabilities(features)
        by_label = {label: round(float(p), 4) for label, p in zip(self.labels, probs)}
        return {
            "certainty": round(by_label["confident"] - by_label["nervous"], 4),
            "probabilities": by_label,
        }
