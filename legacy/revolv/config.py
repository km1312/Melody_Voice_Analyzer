r"""Persisted user settings.

Settings live in %LOCALAPPDATA%\RevolvTranscriber\settings.json so the app keeps
working when it is installed somewhere read-only such as Program Files.
"""

import json
import os
import sys
from pathlib import Path

# Seeded into settings.json on first run. Anyone with access to the app folder can
# read this, so rotate the token if you ever hand the bundle to someone else.
DEFAULT_HF_TOKEN = ""  # cleared before publishing; paste a token in Settings

MEDIA_EXTENSIONS = {
    ".mkv", ".mp4", ".mov", ".avi", ".webm", ".m4v", ".mpg", ".mpeg", ".wmv", ".flv",
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aiff", ".aif",
}

DEFAULTS = {
    "hf_token": DEFAULT_HF_TOKEN,
    "output_dir": "",          # "" means write beside each input file
    "formats": ["json", "txt", "srt"],
    "model_override": "auto",  # "auto" or a faster-whisper model name
    "device_override": "auto", # "auto", "cuda" or "cpu"
    "language": "en",          # "" means auto-detect
    "diarize": True,
    "emotion": True,
    "last_input_dir": "",
    "theme": "light",          # "light" or "dark"
}


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        path = Path(base) / "RevolvTranscriber"
    else:
        path = Path.home() / ".revolv_transcriber"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_file() -> Path:
    return app_data_dir() / "revolv.log"


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
