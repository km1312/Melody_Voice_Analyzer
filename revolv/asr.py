"""The content-word recognizer.

Whisper large-v3 through whisperx is the pass that gets names and jargon right,
and with a vocabulary list it gets more of them right. It is not the only pass:
Whisper transcribes what a speaker *meant* and deletes the filled pauses, restarts
and cut-offs this project most wants, so `verbatim.py` runs CrisperWhisper 2.0
beside it and merges the two word by word.

The earlier arrangement made the recognizer a choice, CrisperWhisper 1.0 or
Whisper, and defaulted to Whisper, which meant a stock run kept none of the
verbatim evidence. That 1.0 CTranslate2 build is retired: 2.0 nearly halves its
verbatim word error rate, emits its own ~40 ms word timings, and runs on stock
transformers. A settings file that still names the old "crisper" backend gets
Whisper plus the verbatim pass, which is what that setting was asking for.
"""

# Retired backend names, mapped to what now serves the same request.
RETIRED_BACKENDS = {"crisper": "whisper"}

BACKENDS = {
    "whisper": {
        "label": "Whisper (readable)",
        "model_id": None,          # filled from the hardware profile's model size
        "asr_options": {},
        "languages": None,         # multilingual
        "verbatim": False,
        "licence": "MIT",
        "notes": ("Accurate names and jargon. Deletes disfluencies on its own, "
                  "which the verbatim pass restores."),
    },
}

BACKEND_CHOICES = ["whisper"]
DEFAULT_BACKEND = "whisper"


def with_vocabulary(options, vocabulary):
    """Bias decoding toward names and jargon the recording is known to contain.

    This applies to the Whisper pass only, which is where content words come
    from. CrisperWhisper 1.0 looped on a hotword prefix ("the" 291 times on a
    30-minute call), and 2.0 restricts hotwords to its commercial Pro weights, so
    the verbatim pass never sees the list. It does not need to: wherever the two
    passes disagree on a content word, the merge takes Whisper's.
    """
    terms = (vocabulary or "").strip()
    if terms:
        options = dict(options)
        options["hotwords"] = terms
    return options


def resolve(backend, profile, language, log=None, model_override="auto"):
    """Pick the backend to actually run, and return (name, model_id, asr_options).

    Falls back to Whisper when the requested backend cannot serve the language or
    the requested model size, reporting why rather than degrading in silence.
    """
    log = log or (lambda msg: None)
    if backend in RETIRED_BACKENDS:
        log("The '{0}' backend is retired. Content words now come from Whisper, "
            "and the verbatim pass supplies the disfluencies.".format(backend))
        backend = RETIRED_BACKENDS[backend]
    name = backend if backend in BACKENDS else DEFAULT_BACKEND
    spec = BACKENDS[name]
    model_id = spec["model_id"] or profile.model_size
    options = dict(spec["asr_options"])
    return name, model_id, options


def is_verbatim(name):
    return bool(BACKENDS.get(name, {}).get("verbatim"))
