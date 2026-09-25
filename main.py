"""Entry point for Melody Tone Analyzer.

Accepts files as command line arguments, so dropping recordings straight onto
the .exe icon works as well as dropping them into the window.
"""

import os
import sys
from pathlib import Path


class _LogStream:
    """Stand-in for stdout/stderr.

    A windowed PyInstaller build has no console, so sys.stdout and sys.stderr
    are None. Libraries in this stack print progress and warnings freely and
    would crash on the first write, so both are pointed at a log file.
    """

    def __init__(self, handle, mirror=None):
        self._handle = handle
        self._mirror = mirror

    def write(self, text):
        try:
            self._handle.write(text)
            self._handle.flush()
        except Exception:
            pass
        if self._mirror is not None:
            try:
                self._mirror.write(text)
                self._mirror.flush()
            except Exception:
                pass
        return len(text)

    def flush(self):
        try:
            self._handle.flush()
        except Exception:
            pass

    def isatty(self):
        return False

    def fileno(self):
        raise OSError("no file descriptor")


def _install_logging():
    from revolv.config import log_file

    path = log_file()
    try:
        if path.exists() and path.stat().st_size > 8 * 1024 * 1024:
            path.replace(path.with_suffix(".log.old"))
    except OSError:
        pass

    try:
        handle = open(path, "a", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        return

    handle.write("\n===== started {0} =====\n".format(
        __import__("datetime").datetime.now().isoformat(timespec="seconds")))
    sys.stdout = _LogStream(handle, mirror=sys.__stdout__)
    sys.stderr = _LogStream(handle, mirror=sys.__stderr__)


def selftest(clip=None):
    """Prove the bundle works: import the stack, probe hardware, transcribe.

    A windowed build gives no feedback when a dependency failed to pack, so
    `"Melody Tone Analyzer.exe" --selftest [audio file]` walks the whole pipeline
    and prints the outcome to the log file. Exit code 0 means the bundle is good.
    """
    import tempfile
    import traceback
    from pathlib import Path as P

    def say(msg):
        # print() already reaches both the log file and the console, if there
        # is one; a windowed build has only the log.
        print("[selftest] {0}".format(msg))

    try:
        say("frozen={0}".format(bool(getattr(sys, "frozen", False))))

        say("importing the pipeline stack")
        import numpy  # noqa: F401
        import torch
        import transformers  # noqa: F401
        import whisperx  # noqa: F401
        import av  # noqa: F401
        from whisperx.diarize import DiarizationPipeline  # noqa: F401
        import pyannote.audio  # noqa: F401
        say("torch {0}, cuda={1}".format(torch.__version__, torch.cuda.is_available()))

        from revolv.config import Settings
        from revolv.hardware import detect
        from revolv.pipeline import Transcriber
        from revolv.writers import write_all

        settings = Settings()
        profile = detect(settings["device_override"], settings["model_override"])
        say("hardware: " + profile.summary().replace("\n", " | "))

        # Interpretation layer: net guard, pack build, verifier, store, all
        # on synthetic data in a temp folder. No models, no network.
        from revolv.selfcheck import run as selfcheck

        if not selfcheck(say):
            say("FAIL (interpretation self-checks)")
            return 1

        if clip is None:
            say("no audio file given, so stopping after the import, probe "
                "and interpretation checks")
            say("PASS")
            return 0

        transcriber = Transcriber(
            profile, hf_token=settings["hf_token"], language="en",
            diarize=settings["diarize"], emotion=settings["emotion"],
            backend=settings.get("asr_backend"),
            prosody=settings.get("prosody", True),
            analyse=settings.get("analysis", True),
            verbatim=settings.get("verbatim", True),
            stance=settings.get("stance", True),
            log=say,
        )
        transcriber.load_models(progress=lambda m: None)
        say("models loaded")

        segments, meta = transcriber.run(
            clip, progress=lambda stage, overall, msg: None)
        say("transcribed {0} segments, {1} speakers, {2:.0f}s of audio".format(
            meta["segments"], meta["speakers"], meta["media_seconds"]))

        out = P(tempfile.gettempdir()) / "revolv_selftest"
        written = write_all(segments, meta, out, "selftest",
                            ["json", "md", "txt", "srt", "csv"])
        for path in written:
            say("wrote {0} ({1} bytes)".format(path, path.stat().st_size))

        if segments:
            # A count, not text: the log must never carry transcript content.
            say("first segment: {0} words".format(
                len((segments[0].get("text") or "").split())))
        report = meta.get("analysis")
        if report:
            summary = report["summary"]
            say("analysis: {0} turns, {1} scored, {2} moments".format(
                summary["turns"], summary["scored_turns"], len(report["moments"])))
        transcriber.close()
        say("PASS")
        return 0
    except Exception:
        say("FAIL\n" + traceback.format_exc())
        return 1


def main():
    if getattr(sys, "frozen", False):
        # Keep HuggingFace and torch caches in the user profile rather than
        # beside a possibly read-only app folder.
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

    _install_logging()

    # Offline switches before anything touches the model stack, so a source
    # run behaves like the bundle. Telemetry always off; the HF offline flags
    # only once the first-run download exists to be offline against.
    try:
        from revolv import netguard
        from revolv.config import Settings

        if Settings().get("offline_mode", True):
            applied = netguard.apply_offline_env()
            print("[melody] offline_env applied={0}".format(str(applied).lower()))
    except Exception:
        pass

    files = [a for a in sys.argv[1:] if not a.startswith("-") and Path(a).exists()]

    if "--selftest" in sys.argv[1:]:
        return selftest(files[0] if files else None)

    # Qt declares per-monitor DPI awareness for us, so there is no manual
    # SetProcessDpiAwareness call here; adding one would only conflict.
    try:
        from revolv.gui import launch
    except Exception:
        import traceback

        message = traceback.format_exc()
        print(message)
        # A Qt dialog is not an option when Qt is what failed to import, so
        # fall back to the Win32 message box, which needs nothing but ctypes.
        try:
            import ctypes

            from revolv.config import log_file

            ctypes.windll.user32.MessageBoxW(
                None,
                "{0}\n\nFull details in:\n{1}".format(message[-1200:], log_file()),
                "Melody Tone Analyzer failed to start",
                0x10,  # MB_ICONERROR
            )
        except Exception:
            pass
        return 1

    return launch(files) or 0


if __name__ == "__main__":
    sys.exit(main())
