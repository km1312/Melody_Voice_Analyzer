r"""Persisted user settings.

Settings live in %LOCALAPPDATA%\MelodyToneAnalyzer\settings.json so the app keeps
working when it is installed somewhere read-only such as Program Files.
"""

import json
import os
import shutil
import sys
from pathlib import Path

# Seeded into settings.json on first run, from the first of these that is set:
# the REVOLV_HF_TOKEN environment variable, or a token build.ps1 wrote into the
# bundle at build time (revolv/assets/hf_token.txt, gitignored). The source
# itself carries no token, so nothing is committed; a build made on a machine
# with a token compiles it in, and anyone with that app folder can read it.
BUNDLED_TOKEN_PATH = Path(__file__).resolve().parent / "assets" / "hf_token.txt"


def _bundled_token() -> str:
    try:
        return BUNDLED_TOKEN_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


DEFAULT_HF_TOKEN = os.environ.get("REVOLV_HF_TOKEN", "").strip() or _bundled_token()

MEDIA_EXTENSIONS = {
    ".mkv", ".mp4", ".mov", ".avi", ".webm", ".m4v", ".mpg", ".mpeg", ".wmv", ".flv",
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff", ".aif",
}

DEFAULTS = {
    "hf_token": DEFAULT_HF_TOKEN,
    "output_dir": "",          # "" means write beside each input file
    "formats": ["json", "md", "txt"],
    "model_override": "auto",  # "auto" or a faster-whisper model name
    "device_override": "auto", # "auto", "cuda" or "cpu"
    "language": "en",          # "" means auto-detect
    "diarize": True,
    "emotion": True,
    "asr_backend": "whisper",  # content-word recognizer; "crisper" is retired
    "verbatim": True,          # CrisperWhisper 2.0 pass for fillers, cut-offs, events
    "stance": True,            # learned stance head on the Whisper encoder
    "prosody": True,           # pitch and energy per turn, for the .md analysis
    "analysis": True,          # derive turns, baselines and notable moments
    "vocabulary": "",          # comma-separated names and jargon to bias decoding
    "last_input_dir": "",
    "theme": "light",          # "light" or "dark"

    # Interpretation layer (stage 10). Keys must live here: load() copies only
    # keys present in DEFAULTS, so one added anywhere else is dropped on the
    # next launch.
    "interpret": True,             # build the prompt pack after analysis
    "interpret_mode": "single_pass",  # "single_pass" or "multi_pass"
    "provider": "manual",          # "manual" or "openai_compat"
    "provider_base_url": "http://127.0.0.1:8080/v1",  # loopback only in Phase 1
    "provider_model": "",          # model name sent to the endpoint
    "subtext_enabled": True,       # off hides Under the surface and skips passes B/C
    "offline_mode": True,          # HF/transformers offline switches once cached
    "retention": "keep_source",    # "keep_source", "clips" or "none"
    "max_insights_per_call": 8,    # verifier cap
    "max_insights_per_speaker": 3, # verifier cap
    "me_baseline_min_calls": 8,    # stored calls before the coaching ring shows
}


# The app was called Revolv Transcriber until 2026-09-17. Settings saved under
# that name are copied across the first time the new name runs, and the old
# folder is left as it was.
APP_DIR_NAME = "MelodyToneAnalyzer"
OLD_APP_DIR_NAME = "RevolvTranscriber"


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        path = Path(base) / APP_DIR_NAME
        old = Path(base) / OLD_APP_DIR_NAME
    else:
        path = Path.home() / ".melody_tone_analyzer"
        old = Path.home() / ".revolv_transcriber"
    if not path.exists() and (old / "settings.json").exists():
        path.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(old / "settings.json", path / "settings.json")
        except OSError:
            pass
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_file() -> Path:
    return app_data_dir() / "melody.log"


def settings_file() -> Path:
    return app_data_dir() / "settings.json"


def bundle_dir() -> Path:
    """Directory holding the running app (the .exe folder when frozen)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


class Settings(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        self.path = settings_file()
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            for key in DEFAULTS:
                if key in stored:
                    self[key] = stored[key]
        except FileNotFoundError:
            self.save()
        except (json.JSONDecodeError, OSError):
            pass  # Corrupt or unreadable settings fall back to defaults.

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(dict(self), f, indent=2)
        except OSError:
            pass


def is_media_file(path) -> bool:
    return Path(path).suffix.lower() in MEDIA_EXTENSIONS
