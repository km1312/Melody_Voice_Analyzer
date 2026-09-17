"""Pitch and energy features, measured per turn.

The emotion model gives one compressed number per dimension and nothing about how
a voice actually moved. Pitch and loudness are cheap, deterministic and directly
interpretable: a rise at the end of a statement reads as uncertainty, a narrow
pitch range reads as flat delivery, and loudness variance marks emphasis.

librosa's `yin` and `pyin` were measured at 2x realtime on this machine, which
would add a quarter-hour to a half-hour recording. The estimator below is YIN
computed from a batched FFT, measured at roughly 200x realtime and exact on steady
synthetic tones, so a 30-minute recording costs about nine seconds.

Pitch is reported in semitones rather than hertz wherever it is compared. Hertz is
not perceptually linear, so a 20 Hz spread means something different on a low voice
than a high one, and speakers cannot be put on the same scale without the log.

Two of the three cues Goupil et al. (2021) isolate as the prosodic signature of
perceived certainty are measured here: pitch falling at the end of a turn, and,
given word timings, energy placed mid-word. The third is speaking rate, which
`analysis` derives from the same word timings. A filled pause and where it falls
is the strongest single cue in that literature and is not measured anywhere,
because the default recognizer deletes most of them before this module is
reached: 0.73% of tokens on the sample call against roughly 2% in conversation.

There is deliberately no F0 standard deviation. Choi et al. (2025) measured F0 SD
across openSMILE, Praat and librosa on the same recordings and found it
uncorrelated between them (r = -0.54 to 0.14), where F0 percentiles agree at 0.96
and above. The percentile range below is on the right side of that result; an SD
would be a measurement of which library was installed.
"""

import math

import numpy as np

HOP_SECONDS = 0.010
WINDOW_SECONDS = 0.040
F0_MIN_HZ = 60.0
F0_MAX_HZ = 400.0

# Which estimator `track` uses. "auto" takes PENN when it is installed and a CUDA
# GPU is present, and YIN otherwise. The two are not interchangeable mid-analysis:
# a baseline built from one and a turn measured with the other would compare two
# instruments, so the Track records which one produced it.
PITCH_TRACKER = "auto"

# PENN's periodicity is an entropy over its pitch posterior, not YIN's dip depth,
# so it needs its own voicing cut. See `_track_penn` for how it was chosen.
PENN_VOICING_THRESHOLD = 0.1625
# Frames per forward pass. 2048 peaked at 3.6 GB on the sample call, which is a
# lot to add beside the ASR, alignment, diarization and emotion models; 1024
# halves that for a few seconds' cost.
PENN_BATCH_FRAMES = 1024
# Viterbi runs on the CPU in pieces of about this length, cut at the quietest
# frame near each boundary, in a thread pool. See `_viterbi`.
PENN_PIECE_SECONDS = 60.0

# YIN's absolute threshold: the first dip below this is taken as the period.
YIN_THRESHOLD = 0.15
# Frames whose chosen dip is shallower than this are treated as unvoiced.
VOICING_THRESHOLD = 0.60
# Lags to scan past the threshold crossing when descending into the dip.
DIP_LOOKAHEAD = 32
# Frames quieter than this, relative to the turn's own loudest frame, are ignored
# so that silence between words cannot drag the pitch statistics around.
SILENCE_FLOOR_DB = -45.0

# Terminal contour is fitted over the final stretch of voiced speech in a turn.
TERMINAL_SECONDS = 0.40
MIN_VOICED_FRAMES = 12

# Word-internal intensity. A word shorter than this, or covering fewer whole
# analysis windows than this, cannot be split into thirds without the thirds
# being noise. The floor is WINDOW_SECONDS plus room for nine hops.
MIN_WORD_SECONDS = 0.15
MIN_WORD_FRAMES = 9
# Below this many usable words the per-turn median is not worth reporting.
MIN_INTENSITY_WORDS = 5


class Track:
    """Frame-level pitch, voicing confidence and loudness for a whole recording.

    `offset` is where frame 0 sits in the original media. When a recording is
    trimmed from the front the array starts partway into the file while every
    timestamp in the transcript still refers to the original media, and without
    this the two disagree by exactly the trim: pitch and loudness for a turn get
    read from a stretch of audio `offset` seconds earlier than the words.
    """

    def __init__(self, f0, confidence, rms, hop_seconds, offset=0.0,
                 estimator="yin", voicing_threshold=VOICING_THRESHOLD):
        self.f0 = f0
        self.confidence = confidence
        self.rms = rms
        self.hop_seconds = hop_seconds
        self.offset = float(offset or 0.0)
        self.estimator = estimator
        self.voicing_threshold = voicing_threshold

    def __len__(self):
        return len(self.f0)

    @property
    def start_seconds(self):
        """First instant this track covers, in original-media coordinates."""
        return self.offset

    @property
    def end_seconds(self):
        return self.offset + len(self.f0) * self.hop_seconds

    def frame_range(self, start, end):
        """Frame indices covering [start, end], given in original-media time."""
        lo = max(int((start - self.offset) / self.hop_seconds), 0)
        hi = min(int((end - self.offset) / self.hop_seconds) + 1, len(self.f0))
        return lo, hi

    def inner_frame_range(self, start, end):
        """Frames whose analysis window lies wholly inside [start, end].

        Every frame reads WINDOW_SECONDS of audio from where it starts, so the
        last few frames of an ordinary range hear well past the end of it. Across
        a turn that hardly matters; across a word it is most of the measurement,
        because the silence after a word is tens of dB below the word and drags
        the word's own mean down with it.
        """
        window = WINDOW_SECONDS / self.hop_seconds
        lo = max(int(math.ceil((start - self.offset) / self.hop_seconds)), 0)
        hi = min(int((end - self.offset) / self.hop_seconds - window) + 1, len(self.f0))
        return lo, max(hi, lo)

    def slice(self, start, end):
        lo, hi = self.frame_range(start, end)
        if hi <= lo:
            return None
        return self.f0[lo:hi], self.confidence[lo:hi], self.rms[lo:hi]


def track(audio, sr, chunk_frames=2048, offset=0.0, tracker=None, log=None):
    """Estimate pitch, voicing confidence and loudness across `audio`.

    `offset` is where this array begins in the original media, and is carried on
    the returned Track so that turn timestamps, which are always in original-media
    coordinates, land on the right frames.

    `tracker` overrides PITCH_TRACKER. "auto" falls back to YIN, saying so through
    `log`, when PENN is missing or there is no GPU; an explicit "penn" raises.
    """
    choice = (tracker or PITCH_TRACKER).lower()
    log = log or (lambda message: None)
    if choice in ("auto", "penn"):
        try:
            return _track_penn(audio, sr, offset)
        except Exception as error:
            if choice == "penn":
                raise
            log("Pitch tracking fell back to YIN: {0}".format(error))
    return _track_yin(audio, sr, chunk_frames, offset)


def _frame_rms(audio, hop_n, win_n):
    """Loudness per frame, framed exactly as `_track_yin` frames it.

    Frame k reads [k * hop, k * hop + window). Keeping that identical across both
    trackers matters more than it looks: the word-intensity figures and every
    frame range in `Track` assume it.
    """
    count = 1 + (len(audio) - win_n) // hop_n
    power = np.concatenate(([0.0], np.cumsum(audio.astype(np.float64) ** 2)))
    starts = hop_n * np.arange(count)
    energy = np.maximum(power[starts + win_n] - power[starts], 0.0)
    return np.sqrt(energy / win_n).astype(np.float32)


def _track_penn(audio, sr, offset):
    """Pitch from PENN (FCNF0++), loudness framed as before.

    YIN, the estimator this replaces, sits in the pYIN tier of the public pitch
    benchmark: roughly 72% on clean speech and 43% on noisy. PENN reaches about
    91% and 76% on the same sets. The two features it feeds, pitch range and
    terminal rise, are z-scored and thresholded, so tracker error does not average
    out -- it becomes false annotations.

    Voicing uses PENN's documented cut of 0.1625, which is only valid on the
    periodicity PENN itself computes: an entropy over the *full* 1440-bin
    posterior. Computed over the 60-400 Hz band instead, a flat posterior has
    entropy log(658) rather than log(1440), every frame gains a floor of 0.108,
    and on the sample call thresholds of 0.065 and 0.1 marked 100% of audible
    frames voiced. So periodicity is taken from the full posterior on the GPU,
    before the band is cut out for decoding.

    Frame alignment: `_frame_rms` frame k is centred at k * hop + 20 ms. PENN with
    "zero" centring pads half its 128 ms window on each side, which centres its
    frame j at j * hop, so frame k's pitch is PENN frame k + 2.
    """
    import torch
    import penn

    if not torch.cuda.is_available():
        raise RuntimeError("PENN needs a CUDA GPU to run at a usable speed")
    if audio is None or len(audio) < int(WINDOW_SECONDS * sr):
        raise RuntimeError("audio is too short to track")

    hop_n = int(round(HOP_SECONDS * sr))
    win_n = int(round(WINDOW_SECONDS * sr))
    rms = _frame_rms(audio, hop_n, win_n)

    low = int(penn.convert.frequency_to_bins(torch.tensor(F0_MIN_HZ)))
    high = int(penn.convert.frequency_to_bins(torch.tensor(F0_MAX_HZ), torch.ceil))

    # Forward passes on the GPU, keeping only the 60-400 Hz band of each
    # posterior. Outside it PENN's own postprocess sets the logits to -inf, so
    # nothing below is lost by never copying them off the device.
    kept = []
    periodic = []
    tensor = torch.from_numpy(np.ascontiguousarray(audio, dtype=np.float32))[None, :]
    with torch.inference_mode():
        for frames in penn.preprocess(tensor, sr, HOP_SECONDS, PENN_BATCH_FRAMES, "zero"):
            logits = penn.infer(frames.to("cuda")).detach().float()
            periodic.append(penn.periodicity.entropy(logits).reshape(-1).cpu())
            kept.append(logits[:, low:high, 0].cpu())
    logits = torch.cat(kept, 0)
    periodicity = torch.cat(periodic, 0)
    del kept, periodic

    probabilities = torch.softmax(logits, dim=1)

    quiet = 20.0 * np.log10(np.maximum(rms, 1e-10))
    bins = _viterbi(probabilities, low, high, quiet)
    pitch = _local_expected_hz(logits, bins, low)

    count = min(len(rms), len(pitch) - 2)
    f0 = pitch[2:2 + count].numpy().astype(np.float32)
    confidence = periodicity[2:2 + count].numpy().astype(np.float32)
    return Track(f0, confidence, rms[:count], HOP_SECONDS, offset,
                 estimator="penn", voicing_threshold=PENN_VOICING_THRESHOLD)


def _viterbi(probabilities, low, high, loudness_db):
    """PENN's Viterbi decode, made usable on a GPU torbi does not support.

    torbi's CUDA kernel is not built for this card (Blackwell: "no kernel image is
    available"), and its CPU path is single-threaded per sequence: 26 seconds per
    minute of audio, about twelve minutes for a half-hour call. Two things fix
    that without changing the answer.

    The state space is cut to the 60-400 Hz band, 658 of 1440 bins. PENN has
    already given every bin outside it zero probability, so no path can use them.
    The transition rows are deliberately *not* renormalised after the cut: doing
    so boosts paths along the band edges during unvoiced stretches and changed the
    octave chosen on 1.2% of voiced frames. Left as they are, the decode matched
    PENN's own to the bin on 99.97% of frames with no octave differences.

    The recording is then decoded in pieces on a thread pool (torbi releases the
    GIL). Each cut is moved to the quietest frame within two seconds of its
    nominal position, where a Viterbi path has nothing to carry across anyway.
    """
    import os
    from concurrent.futures import ThreadPoolExecutor

    import torch
    import torbi
    import penn

    transition = penn.decode.triangular_transition_matrix()[low:high, low:high]
    transition = transition.contiguous()
    initial = torch.full((high - low,), 1.0 / (high - low))

    count = probabilities.shape[0]
    piece = max(int(PENN_PIECE_SECONDS / HOP_SECONDS), 1)
    slack = int(2.0 / HOP_SECONDS)
    cuts = [0]
    for nominal in range(piece, count, piece):
        # Loudness frame k lines up with posterior frame k + 2.
        lo = max(nominal - slack, cuts[-1] + 1)
        hi = min(nominal + slack, count - 1)
        if hi <= lo:
            continue
        window = loudness_db[max(lo - 2, 0):max(hi - 2, 0)]
        cuts.append(lo + int(np.argmin(window)) if len(window) else nominal)
    cuts.append(count)
    spans = [(a, b) for a, b in zip(cuts, cuts[1:]) if b > a]

    def decode(span):
        begin, end = span
        return torbi.from_probabilities(
            probabilities[begin:end][None].contiguous(),
            transition=transition, initial=initial, num_threads=1).reshape(-1)

    workers = max(1, min(len(spans), os.cpu_count() or 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return torch.cat(list(pool.map(decode, spans))).long()


def _local_expected_hz(logits, bins, low, window=None):
    """PENN's local expected value around the Viterbi path, on the cropped band.

    Equivalent to `penn.decode.local_expected_value_from_bins` on full logits:
    bins outside the band are -inf there, and the -inf padding here stands in for
    them.
    """
    import torch
    import penn

    window = window or penn.LOCAL_PITCH_WINDOW_SIZE
    half = window // 2
    padded = torch.nn.functional.pad(logits, (half, half), value=-float("inf"))
    indices = bins[:, None] + torch.arange(window)[None, :]
    absolute = torch.clip(indices - half + low, 0)
    cents = penn.convert.bins_to_cents(absolute)
    return penn.decode.expected_value(torch.gather(padded, 1, indices), cents).reshape(-1)


def _track_yin(audio, sr, chunk_frames=2048, offset=0.0):
    """YIN, kept as the fallback for machines without a GPU.

    This is YIN: a cumulative-mean-normalised difference function with an absolute
    threshold. The first version here used the normalised autocorrelation peak
    directly, which is faster to write and wrong on real speech. A zero-padded FFT
    autocorrelation overlaps fewer samples at longer lags, so short lags score
    higher for free and the tracker reports octaves. Measured on a 30-minute
    recording it pinned the top decile against the 400 Hz ceiling and jumped by
    more than 1.8x across 9.9% of voiced frame transitions.

    The difference function is recovered from the same batched FFT, so the fix
    costs correctness-preserving arithmetic rather than speed.
    """
    hop_n = int(round(HOP_SECONDS * sr))
    win_n = int(round(WINDOW_SECONDS * sr))
    min_lag = max(int(sr / F0_MAX_HZ), 1)
    max_lag = int(sr / F0_MIN_HZ)
    span = win_n + max_lag

    empty = np.zeros(0, np.float32)
    if audio is None or len(audio) < span:
        return Track(empty, empty, empty, HOP_SECONDS, offset)

    count = 1 + (len(audio) - span) // hop_n
    starts = hop_n * np.arange(count)
    nfft = 1 << int(np.ceil(np.log2(span + win_n)))

    # Running power, so the energy of every shifted window is one subtraction.
    power = np.concatenate(([0.0], np.cumsum(audio.astype(np.float64) ** 2)))

    f0 = np.zeros(count, np.float32)
    confidence = np.zeros(count, np.float32)
    rms = np.zeros(count, np.float32)
    lags = np.arange(min_lag, max_lag + 1)

    for begin in range(0, count, chunk_frames):
        block = starts[begin:begin + chunk_frames]
        buffers = audio[block[:, None] + np.arange(span)[None, :]].astype(np.float32)
        windows = buffers[:, :win_n]

        rms[begin:begin + chunk_frames] = np.sqrt(np.mean(windows * windows, axis=1))

        # Cross-correlation of the window against the longer buffer.
        head = np.fft.rfft(windows, nfft, axis=1)
        whole = np.fft.rfft(buffers, nfft, axis=1)
        cross = np.fft.irfft(np.conj(head) * whole, nfft, axis=1)[:, :max_lag + 1]

        # d(tau) = power(window) + power(shifted window) - 2 * cross(tau)
        base = (power[block + win_n] - power[block])[:, None]
        shifted = (power[block[:, None] + np.arange(max_lag + 1)[None, :] + win_n]
                   - power[block[:, None] + np.arange(max_lag + 1)[None, :]])
        diff = np.maximum(base + shifted - 2.0 * cross, 0.0)

        # Cumulative mean normalisation: this is what makes the measure comparable
        # across lags and is precisely what the autocorrelation version lacked.
        running = np.cumsum(diff[:, 1:], axis=1)
        denominator = running / np.arange(1, max_lag + 1)[None, :]
        denominator[denominator <= 0] = 1e-9
        normalised = diff[:, 1:] / denominator

        window_view = normalised[:, min_lag - 1:max_lag]
        below = window_view < YIN_THRESHOLD
        has_dip = below.any(axis=1)
        # The first dip under the threshold, not the deepest: the deepest is
        # routinely an integer multiple of the true period.
        first = np.where(has_dip, below.argmax(axis=1), window_view.argmin(axis=1))

        # Descend to the bottom of that dip. The threshold is crossed on the way
        # in, which is a shorter lag than the true period, and taking the crossing
        # point directly biases every estimate upward: on a synthetic 120 Hz
        # reference it read 132 Hz.
        rows = np.arange(len(first))
        offsets = np.arange(DIP_LOOKAHEAD)[None, :]
        probe = np.minimum(first[:, None] + offsets, window_view.shape[1] - 1)
        local = window_view[rows[:, None], probe]
        trough = first + np.argmin(local, axis=1)
        trough = np.minimum(trough, window_view.shape[1] - 1)

        # Parabolic interpolation against the two neighbouring lags, so the period
        # is not quantised to whole samples. At 16 kHz one sample is nearly 3 Hz
        # of resolution around 200 Hz.
        left = np.maximum(trough - 1, 0)
        right = np.minimum(trough + 1, window_view.shape[1] - 1)
        a = window_view[rows, left]
        b = window_view[rows, trough]
        c = window_view[rows, right]
        curve = a - 2.0 * b + c
        shift = np.where(np.abs(curve) > 1e-12, (a - c) / (2.0 * curve), 0.0)
        shift = np.clip(shift, -1.0, 1.0)

        period = lags[trough].astype(np.float64) + shift
        period[period < min_lag] = min_lag
        f0[begin:begin + chunk_frames] = (sr / period).astype(np.float32)
        confidence[begin:begin + chunk_frames] = np.clip(1.0 - b, 0.0, 1.0)

    f0 = _despike(f0, confidence)
    return Track(f0, confidence, rms, HOP_SECONDS, offset)


def _despike(f0, confidence, width=5):
    """Median-filter the contour so a single stray frame cannot define a turn.

    Only confident frames vote, since an unvoiced frame's pitch is meaningless.
    """
    if len(f0) < width:
        return f0
    voiced = confidence > VOICING_THRESHOLD
    padded = np.pad(np.where(voiced, f0, np.nan), width // 2, constant_values=np.nan)
    strided = np.lib.stride_tricks.sliding_window_view(padded, width)
    with np.errstate(all="ignore"):
        smoothed = np.nanmedian(strided, axis=1)
    return np.where(np.isfinite(smoothed), smoothed, f0).astype(np.float32)


def _semitones(hz, reference):
    """Convert hertz to semitones above `reference`, guarding the log's domain."""
    hz = np.asarray(hz, dtype=np.float64)
    safe = np.where(hz > 0, hz, np.nan)
    return 12.0 * np.log2(safe / reference)


def turn_features(track_data, start, end, words=None):
    """Pitch and loudness description of one turn, or None if it is unusable.

    Returns hertz and decibel figures only. Everything comparative is left to the
    analysis pass, which has the speaker's own baseline to measure against.

    `words` are that turn's word timings, in original-media coordinates. They are
    optional because a transcript without them is still worth measuring; when
    present they buy the word-internal intensity figures.
    """
    window = track_data.slice(start, end)
    if window is None:
        return None
    f0, confidence, rms = window
    if len(f0) < MIN_VOICED_FRAMES:
        return None

    loud = 20.0 * np.log10(np.maximum(rms, 1e-10))
    peak = loud.max()
    audible = loud > (peak + SILENCE_FLOOR_DB)
    voiced = (confidence > track_data.voicing_threshold) & audible
    if int(voiced.sum()) < MIN_VOICED_FRAMES:
        return None

    voiced_f0 = f0[voiced]
    median_hz = float(np.median(voiced_f0))
    if not np.isfinite(median_hz) or median_hz <= 0:
        return None

    # Spread is taken between the 10th and 90th percentile rather than as a full
    # range, so one octave-halving error cannot define the turn.
    low, high = np.percentile(voiced_f0, [10, 90])
    span = float(_semitones(high, low)) if low > 0 else 0.0

    features = {
        "f0_median_hz": round(median_hz, 1),
        "f0_range_semitones": round(span, 2),
        "f0_terminal_rise": _terminal_rise(f0, voiced, track_data.hop_seconds,
                                            median_hz),
        "loudness_db_sd": round(float(np.std(loud[audible])), 2),
        "voiced_fraction": round(float(voiced.mean()), 3),
    }
    features.update(_word_intensity(track_data, words))
    return features


def _word_intensity(track_data, words):
    """Where inside a word the speaker put the energy, in dB about the word mean.

    Goupil et al. (2021) isolate greater intensity mid-word, alongside a faster
    rate and a falling terminal pitch, as the prosodic signature listeners read as
    certainty. Rate and terminal pitch are measured elsewhere in this module; this
    is the third cue, and it costs one more pass over the loudness track that was
    computed anyway.

    Each figure is relative to the word's own mean level, so it survives a speaker
    simply being loud, and the per-turn figure is a median over words, so one
    clipped or mis-aligned word cannot define a turn. An empty dict is returned
    when the turn has too few usable words, which is the honest answer for a turn
    made of short function words.
    """
    usable = []
    for word in words or []:
        try:
            begin = float(word["start"])
            finish = float(word["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if finish - begin < MIN_WORD_SECONDS:
            continue
        lo, hi = track_data.inner_frame_range(begin, finish)
        if hi - lo < MIN_WORD_FRAMES:
            continue
        loud = 20.0 * np.log10(np.maximum(track_data.rms[lo:hi], 1e-10))
        third = len(loud) // 3
        if third < 1:
            continue
        mean = float(loud.mean())
        usable.append((float(loud[:third].mean()) - mean,
                       float(loud[third:2 * third].mean()) - mean))

    if len(usable) < MIN_INTENSITY_WORDS:
        return {}
    onsets = np.array([u[0] for u in usable])
    mids = np.array([u[1] for u in usable])
    return {
        "intensity_onset_db": round(float(np.median(onsets)), 2),
        "intensity_mid_db": round(float(np.median(mids)), 2),
        "intensity_words": len(usable),
    }


def _terminal_rise(f0, voiced, hop_seconds, median_hz):
    """How the turn's closing pitch sits against the rest of it, in semitones.

    A least-squares slope over the final voiced stretch was tried first and was
    too noisy to use: across a 30-minute recording its spread reached 21 semitones
    per second, so the measure was mostly fitting noise. Comparing the level of the
    closing pitch against the level of the turn body is bounded, robust to stray
    frames, and answers the question actually being asked, which is whether the
    speaker ended higher or lower than they had been.

    Positive is a rise. On a declarative sentence that reads as uncertainty, or as
    a speaker signalling they have not finished.
    """
    index = np.flatnonzero(voiced)
    if len(index) < 2 * MIN_VOICED_FRAMES:
        return None

    tail_frames = max(int(TERMINAL_SECONDS / hop_seconds), MIN_VOICED_FRAMES)
    tail = index[index >= index[-1] - tail_frames]
    body = index[index < index[-1] - tail_frames]
    if len(tail) < MIN_VOICED_FRAMES or len(body) < MIN_VOICED_FRAMES:
        return None

    tail_hz = float(np.median(f0[tail]))
    body_hz = float(np.median(f0[body]))
    if tail_hz <= 0 or body_hz <= 0:
        return None

    rise = float(_semitones(tail_hz, body_hz))
    if not np.isfinite(rise):
        return None
    return round(rise, 2)
