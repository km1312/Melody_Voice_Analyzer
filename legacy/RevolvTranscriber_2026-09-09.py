r"""Revolv Transcriber — the whole legacy app in one archival file.

This is the pipeline as it stood on 2026-09-09, the last build before the
verbatim recognizer and the analysis pass arrived, preserved so old and new
output can still be compared on the same recording. It became Melody Tone
Analyzer on 2026-09-17 and grew the interpretation layer (stage 10) on
2026-09-21; the top-level README's "What changed from the old pipeline"
section is the full delta.

ARCHIVAL, NOT RUNNABLE. The sections below are the original files verbatim,
in dependency order, with their package-relative imports intact — they will
not resolve from a single module. To actually run the legacy app, restore
the original tree from git:

    git log --oneline -- legacy/          # find the last commit with the tree
    git checkout <that-commit> -- legacy/ # bring the folder back

LINEAGE
    VoiceModel.py (pre-git single script; produced transcript_output.json)
      -> Revolv Transcriber (this snapshot, 2026-09-09)
      -> Melody Tone Analyzer (renamed 2026-09-17; package stayed `revolv`)
      -> + interpretation layer, branch interpret-phase1 (2026-09-21)

WHAT THIS APP WAS
    A Windows desktop app: drop recordings on a Qt window (or the .exe),
    get speaker-labelled transcripts with word timing, pace and
    valence/arousal/dominance emotion scores. Local only; no audio leaves
    the machine. Four output formats: .json (VoiceModel-compatible), .txt,
    .srt, .csv, never overwriting (unique_path appends " (2)").

THE PIPELINE (see the pipeline.py section)
    1. Decode      PyAV + AudioResampler -> mono 16 kHz float32. This
                   snapshot already carries the fixed decoder; the version
                   before it averaged raw frame arrays, which misreads
                   packed formats.
    2. Transcribe  WhisperX over faster-whisper/CTranslate2. Model size,
                   compute type and batch are tiered by VRAM in
                   hardware.py (large-v3/float16/16 at 15 GB down to
                   base/int8_float16/2 at 2 GB; CPU tiers below that;
                   int8 below compute capability 7.0). The legacy prompt
                   "This is a meeting recording" biased decoding.
    3. Align       wav2vec2 forced alignment for word timestamps, loaded
                   per language and cached.
    4. Diarize     pyannote/speaker-diarization-3.1, gated on a
                   HuggingFace token; without one every segment is
                   UNKNOWN. whisperx assign_word_speakers distributes
                   labels to words.
    5. Emotion     audeering wav2vec2 (msp-dim) per segment, with the
                   published RegressionHead rebuilt by hand because
                   transformers' generic class silently leaves the head
                   randomly initialised. Scores clipped to [0, 1]; the
                   model relocates to CPU on CUDA OOM and the run
                   continues.
    Models load once per batch, not per file. A 90-second clip ran ~15 s
    end to end on an RTX 5060 Ti (large-v3, float16), ~6x real time.

HOW IT WAS BUILT, EXACTLY
    Environment   .venv, Python 3.13 on Windows; the pipeline stack was
                  whisperx, faster-whisper, ctranslate2, pyannote.audio
                  3.1, transformers, torch + CUDA 12.8, av, PySide6
                  Essentials, psutil, pillow; PyInstaller for packaging.
    build.ps1     (full text in the BUILD_PS1 section) installs the build
                  deps (pyinstaller, PySide6-Essentials, psutil, pillow),
                  generates revolv.ico via make_icon.py when missing, and
                  runs:  python -m PyInstaller --noconfirm --clean
                  RevolvTranscriber.spec
    The spec      (full text in the REVOLV_TRANSCRIBER_SPEC section)
                  onedir, console=False, icon revolv.ico, runtime hook
                  setting MPLBACKEND/HF_HUB_DISABLE_TELEMETRY/
                  KMP_DUPLICATE_LIB_OK; collect_all over the packages
                  that resolve modules dynamically (whisperx,
                  faster_whisper, ctranslate2, pyannote*, lightning*,
                  transformers, torchaudio, onnxruntime, librosa, av,
                  ...); torch's CUDA DLLs collected explicitly because
                  Windows loads them by name; torchcodec excluded
                  (broken here, reached only through try/except); Qt
                  modules the app never used excluded; UPX off (corrupts
                  CUDA DLLs); onefile rejected (unpacks ~4 GB of CUDA to
                  temp on every launch).
    Result        dist\Revolv Transcriber\ — a 106 MB .exe plus
                  _internal, ~4.8 GB over ~13,800 files. First run
                  downloaded ~3 GB of models to
                  %USERPROFILE%\.cache\huggingface; offline after that.
    Verification  "Revolv Transcriber.exe" --selftest [clip] walked
                  imports, the hardware probe and, with a clip, the whole
                  pipeline; exit 0 meant the bundle was sound.
    Settings      %LOCALAPPDATA%\RevolvTranscriber\settings.json (the
                  rename migrated it to MelodyToneAnalyzer). The token
                  was DEFAULT_HF_TOKEN in config.py, kept "" in source
                  and pasted into Settings per machine; the current
                  scheme (build-time gitignored seed file) came later.

CONTENTS OF THIS FILE, IN ORDER
    LEGACY_MD / README_MD          the two markdown files, verbatim
    BUILD_PS1                      build.ps1, verbatim
    REVOLV_TRANSCRIBER_SPEC        RevolvTranscriber.spec, verbatim
    runtime_hook.py, make_icon.py  build helpers
    revolv/__init__.py, config.py, hardware.py, audio.py, theme.py,
    writers.py, pipeline.py, gui.py, main.py     the app, in import order
"""



##############################################################################
# LEGACY_MD  (was legacy/LEGACY.md)
##############################################################################

LEGACY_MD = r'''
# Legacy pipeline

A copy of Revolv as it stood on 2026-09-09, before the verbatim recognizer and the
analysis pass were added. Nothing imports it. It is here so output from the old and
new pipelines can be compared on the same recording.

The differences are set out under "What changed, and why" in the top-level README.

Two things to know if you run anything from here:

- `transcript_output.json` in the project root was produced by `VoiceModel.py`,
  which predates even this snapshot. It is older than the code in this folder.
- The audio decoder in this snapshot is already the fixed one. The version before
  it downmixed by averaging raw frame arrays, which misreads packed formats.
'''


##############################################################################
# README_MD  (was legacy/README.md)
##############################################################################

README_MD = r'''
# Revolv Transcriber

A Windows desktop app that turns recordings into speaker-labelled transcripts with
word-level timing, speaking pace, and valence / arousal / dominance scores. Everything
runs locally. No audio leaves the machine.

It is the pipeline from `VoiceModel.py`, wrapped in a drag-and-drop window and packaged
as a standalone `.exe`.

## Using it

1. Launch **Revolv Transcriber.exe**.
2. Drop audio or video files onto the window, or click the drop area to browse.
   Dropping files onto the `.exe` icon works too, and dropping a folder queues every
   media file inside it.
3. Choose where output goes: next to each original, or a folder you pick.
4. Tick the formats you want, then press **Start transcribing**.

Double-click any finished row to open its output in Explorer.

### What it writes

| Format | Contents |
| --- | --- |
| `.json` | Every segment with words, timings, speaker, pacing and emotion. Same shape `VoiceModel.py` produced, so existing downstream code still reads it. |
| `.txt` | A readable transcript grouped by speaker. |
| `.srt` | Subtitles with the speaker name in each cue. |
| `.csv` | One row per segment, for a spreadsheet. Opens directly in Excel. |

Existing files are never overwritten. A second run writes `name (2).json`.

## Hardware detection

On launch the app probes the machine and picks settings to match. The detected
configuration is shown under the title.

With a CUDA GPU it selects by available VRAM:

| VRAM | Whisper model | Precision | Batch |
| --- | --- | --- | --- |
| 15 GB and up | large-v3 | float16 | 16 |
| 11 GB | large-v3 | float16 | 12 |
| 8 GB | large-v3 | float16 | 8 |
| 6 GB | large-v3 | int8_float16 | 4 |
| 4.5 GB | medium | int8_float16 | 4 |
| 3 GB | small | int8_float16 | 4 |
| 2 GB | base | int8_float16 | 2 |

Below 6 GB the emotion model is moved to the CPU so it does not compete with
transcription for VRAM. Below 2 GB, or with no CUDA GPU at all, everything falls back
to the CPU and the model is chosen from RAM and core count instead. GPUs older than
compute capability 7.0 drop to int8, since float16 buys them nothing.

If the GPU runs out of memory mid-run, the emotion model relocates to the CPU and the
run continues rather than failing.

Override any of this under **Settings** by pinning a model size or forcing CPU.

## Appearance

The window is light by default. Dark is available under **Settings > Appearance**
and switches live, so you can see it before saving.

The design brief was calm, so the palette is muted rather than saturated, the
neutrals are warm rather than clinical grey, and the layout leans on space instead
of dividers and boxes. Containers are rounded 16 to 20 pixels and controls 10 to 12,
in the range current guidance puts soft, approachable interfaces. The accent is a
desaturated denim that sits back instead of competing with the content.

Every foreground and background pairing clears the WCAG AA contrast floor of 4.5:1
on the surface it sits on. The subtle grey is reserved for disabled controls and is
never used for text a reader needs.

### Why Qt and not Tkinter

The first version of this window was Tkinter. It could not be made to look calm.
Tk draws no rounded corners, no shadows and no real hover states, its widget
indicators are fixed-size bitmaps that break on a high-DPI display, and its file
drop hands over a quoted string rather than paths. Qt does all of it natively,
handles DPI scaling on its own, and styles through a stylesheet, so the palette
lives in one place and both themes stay in step.

Two Qt details worth knowing if you edit the interface:

- The stylesheet cannot draw a chevron or a tick. The zero-size-box border trick
  that works in CSS renders as a dash here. Both are painted once with QPainter,
  cached as PNGs in the temp folder, and referenced from the stylesheet.
- No drop shadow is applied to the file list. A `QGraphicsDropShadowEffect` on a
  scroll area stops its viewport clipping, and the rows spill over the controls
  underneath.

## Settings

Stored in `%LOCALAPPDATA%\RevolvTranscriber\settings.json`.

- **HuggingFace token** gates speaker diarization. Without one, transcription still
  runs but every segment is labelled `UNKNOWN`. Accept the terms for
  `pyannote/speaker-diarization-3.1` and `pyannote/segmentation-3.0` on huggingface.co
  before first use.
- **Language** defaults to English. Set it to `auto` to detect per file; the matching
  alignment model is then loaded on demand and cached.
- **Whisper model** and **Processor** override hardware detection.
- Speaker labelling and emotion scoring can each be turned off to save time.
- **Appearance** picks light or dark.

## First run

Models are downloaded from HuggingFace into `%USERPROFILE%\.cache\huggingface`, about
3 GB. That happens once and only needs a network connection the first time. Every run
after that is offline.

Model loading takes a couple of minutes. It happens once per batch, not once per file,
so queueing several recordings together is much faster than running them one at a time.

## Speed

On an RTX 5060 Ti with large-v3 at float16, a 90 second clip took 15 seconds end to
end, roughly 6x real time. A one hour meeting lands near ten minutes. CPU-only is
slower by more than an order of magnitude.

## Troubleshooting

Activity is logged to the window and to `%LOCALAPPDATA%\RevolvTranscriber\revolv.log`.
**Settings > Open log file** opens it. The log is the place to look if the app closes
unexpectedly, since the windowed build has no console.

If a file fails, its row shows why and the rest of the queue continues.

## Building from source

```powershell
.\build.ps1
```

The result is `dist\Revolv Transcriber\`, 4.8 GB across roughly 13,800 files: a
106 MB `.exe` and an `_internal` folder holding the rest, most of it the CUDA
libraries inside PyTorch. Keep the two together and move the folder as a unit.
A clean build takes about 25 minutes.

To confirm a build is sound, run the self-test. It walks the whole pipeline and
writes the outcome to the log:

```powershell
& ".\dist\Revolv Transcriber\Revolv Transcriber.exe" --selftest "some-clip.wav"
```

Exit code 0 means the bundle is good. Without a file argument it checks imports
and hardware detection only. This matters because a windowed build has no
console, so a missing dependency would otherwise show up as a window that never
appears.

### Layout

| Path | Role |
| --- | --- |
| `main.py` | Entry point. Redirects stdout and stderr to the log, since a windowed build has neither. |
| `revolv/hardware.py` | Hardware probe and the tier tables above. |
| `revolv/audio.py` | Decodes any container PyAV can open to mono 16 kHz. |
| `revolv/pipeline.py` | WhisperX transcription, alignment, diarization and emotion scoring. |
| `revolv/writers.py` | The four output formats. |
| `revolv/gui.py` | The window, built on PySide6. |
| `revolv/theme.py` | The light and dark palettes and the Qt stylesheet built from them. |
| `revolv/config.py` | Settings persistence. |
| `RevolvTranscriber.spec` | PyInstaller bundle definition. |

### Notes on the packaging

The bundle is onedir rather than onefile. A onefile build unpacks about 4 GB of CUDA
libraries to a temp folder on every launch, which makes startup take minutes.

UPX compression is off. It corrupts some CUDA DLLs.

`torchcodec` is excluded. It is broken in this environment and pyannote only reaches it
through a `try`/`except`, so its absence changes nothing.

## Security note

The HuggingFace token is stored in plain text in the settings file, and a copy is
compiled into the bundle as the first-run default. Anyone with the app folder can read
it. Rotate the token at huggingface.co/settings/tokens before sharing this build with
anyone, and clear `DEFAULT_HF_TOKEN` in `revolv/config.py` first so the next build
carries no secret.
'''


##############################################################################
# BUILD_PS1  (was legacy/build.ps1)
##############################################################################

BUILD_PS1 = r'''
# Build Revolv Transcriber into a standalone Windows app folder.
#
#   .\build.ps1
#
# The result lands in dist\Revolv Transcriber\, with the .exe at its root.
# Expect 15 to 40 minutes and roughly 8 GB on the first run.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "No virtual environment at $python. Create it and install the pipeline dependencies first."
}

Write-Host "Checking build dependencies..." -ForegroundColor Cyan
& $python -m pip install --quiet --upgrade pyinstaller PySide6-Essentials psutil pillow
if ($LASTEXITCODE -ne 0) { throw "Dependency install failed." }

if (-not (Test-Path (Join-Path $root "revolv.ico"))) {
    Write-Host "Generating the icon..." -ForegroundColor Cyan
    & $python make_icon.py
}

Write-Host "Running PyInstaller. This takes a while." -ForegroundColor Cyan
& $python -m PyInstaller --noconfirm --clean RevolvTranscriber.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed. See the output above." }

$exe = Join-Path $root "dist\Revolv Transcriber\Revolv Transcriber.exe"
if (-not (Test-Path $exe)) { throw "The build finished but $exe is missing." }

$bytes = (Get-ChildItem (Split-Path $exe) -Recurse -File | Measure-Object -Property Length -Sum).Sum
Write-Host ""
Write-Host "Built $exe" -ForegroundColor Green
Write-Host ("Bundle size: {0:N1} GB" -f ($bytes / 1GB)) -ForegroundColor Green
Write-Host ""
Write-Host "Move the whole 'Revolv Transcriber' folder wherever you like, then make a"
Write-Host "shortcut to the .exe. Keep the folder together; the .exe needs _internal."
'''


##############################################################################
# REVOLV_TRANSCRIBER_SPEC  (was legacy/RevolvTranscriber.spec)
##############################################################################

REVOLV_TRANSCRIBER_SPEC = r'''
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Revolv Transcriber.

Built as a onedir bundle. onefile would work but unpacks several gigabytes of
CUDA libraries to a temp folder on every launch, which makes startup unbearable.
"""

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    copy_metadata,
)

datas = []
binaries = []
hiddenimports = []


def take(package):
    """Pull in a package wholesale: modules, data files and shared libraries."""
    global datas, binaries, hiddenimports
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden


# Packages that resolve modules dynamically, ship data files, or both. Missing
# any of these shows up as an ImportError only once the .exe is running.
for package in [
    "whisperx",            # includes assets/pytorch_model.bin, the VAD checkpoint
    "faster_whisper",      # includes assets/silero_vad_v6.onnx
    "ctranslate2",
    "pyannote",
    "pyannote.audio",
    "pyannote.core",
    "pyannote.database",
    "pyannote.pipeline",
    "pyannote.metrics",
    "lightning",
    "lightning_fabric",
    "pytorch_lightning",
    "asteroid_filterbanks",
    "transformers",
    "tokenizers",
    "huggingface_hub",
    "safetensors",
    "torchaudio",
    "onnxruntime",
    "omegaconf",
    "antlr4",
    "librosa",
    "soundfile",
    "soxr",
    "av",
    # PySide6 is deliberately absent: collect_all would drag in every Qt DLL,
    # and binaries ignore the excludes below. PyInstaller's own PySide6 hook
    # follows the actual imports and packs only those modules.
    "einops",
    "sklearn",
    "scipy",
    "pandas",
    "numba",
    "llvmlite",
]:
    try:
        take(package)
    except Exception as exc:  # a package that is not installed is not fatal
        print("spec: skipping {0} ({1})".format(package, exc))

# Several of these read their own version through importlib.metadata at import
# time and raise PackageNotFoundError if the dist-info is missing.
for package in [
    "torch", "torchaudio", "transformers", "tokenizers", "huggingface_hub",
    "whisperx", "faster_whisper", "ctranslate2", "pyannote.audio", "pyannote.core",
    "lightning", "lightning_fabric", "pytorch_lightning", "omegaconf",
    "numpy", "tqdm", "safetensors", "filelock", "packaging", "pyyaml",
    "regex", "requests", "sympy", "networkx", "jinja2", "fsspec", "psutil",
    "scikit-learn", "scipy", "pandas", "soundfile", "librosa", "av",
]:
    try:
        datas += copy_metadata(package)
    except Exception as exc:
        print("spec: no metadata for {0} ({1})".format(package, exc))

# torch's own hook usually gets these, but the CUDA runtime DLLs live in
# torch/lib on Windows and are loaded by name at runtime rather than imported.
try:
    binaries += collect_dynamic_libs("torch")
    datas += collect_data_files("torch", includes=["**/*.json", "**/*.yaml", "version.py"])
except Exception as exc:
    print("spec: torch collection fell back to the default hook ({0})".format(exc))

hiddenimports += [
    "revolv", "revolv.audio", "revolv.config", "revolv.gui",
    "revolv.hardware", "revolv.pipeline", "revolv.theme", "revolv.writers",
    "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
    "sklearn.utils._typedefs", "sklearn.neighbors._partition_nodes",
    "scipy.special.cython_special", "scipy._lib.array_api_compat.numpy.fft",
    "pandas._libs.tslibs.base",
    "transformers.models.wav2vec2",
    "transformers.models.wav2vec2.modeling_wav2vec2",
    "transformers.models.wav2vec2.processing_wav2vec2",
    "transformers.models.whisper",
    "encodings.idna",
]

# gui.py loads the window icon from the bundle root at runtime.
datas += [("revolv.ico", ".")]

excludes = [
    # Broken in this environment and only ever reached through a try/except.
    "torchcodec",
    # Developer tooling that would otherwise be dragged in by the science stack.
    "triton", "tensorboard", "tensorboardX", "wandb", "mlflow",
    "IPython", "ipykernel", "jupyter", "notebook", "nbconvert",
    "sphinx", "docutils",
    "PyQt5", "PyQt6", "PySide2", "wx",
    # The Tk front end is gone; without these its runtime rides along at ~10 MB.
    "tkinter", "tkinterdnd2", "_tkinter",
    # Qt modules this app never touches. PySide6 otherwise packs all of them.
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets", "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "PySide6.QtSql",
    "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtUiTools", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets", "PySide6.Qt3DCore", "PySide6.QtBluetooth",
    "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtSerialPort",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSensors",
    "PySide6.QtStateMachine", "PySide6.QtTextToSpeech", "PySide6.QtSpatialAudio",
    # Nothing under torch is excluded. torch.testing._internal looks like dead
    # test code but is reachable from a normal `import torch.testing`, and
    # dropping it breaks the import chain that pyannote pulls in.
]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["runtime_hook.py"],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Revolv Transcriber",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX corrupts some CUDA DLLs
    console=False,      # windowed app; stdout and stderr go to the log file
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="revolv.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Revolv Transcriber",
)
'''


##############################################################################
# was legacy/runtime_hook.py
##############################################################################

"""Runs inside the frozen app before any of our own code imports.

Sets the environment that this dependency stack expects but cannot arrange for
itself once it is packed into a bundle.
"""

import os

# matplotlib is pulled in by pyannote.metrics. Without a backend chosen it can
# try to start an interactive one and stall a windowed app.
os.environ.setdefault("MPLBACKEND", "Agg")

# Models are cached in the user profile, not beside a possibly read-only .exe.
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Two OpenMP runtimes (torch's and MKL's) can land in one bundle; without this
# the second one to load aborts the process.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")


##############################################################################
# was legacy/make_icon.py
##############################################################################

"""Generate the app icon. Run once; the .ico is then reused by every build."""

from pathlib import Path

from PIL import Image, ImageDraw

BG = (27, 29, 35)
ACCENT = (79, 156, 249)
LIGHT = (230, 232, 238)


def render(size):
    scale = 8
    px = size * scale
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    radius = int(px * 0.22)
    draw.rounded_rectangle([0, 0, px - 1, px - 1], radius=radius, fill=BG)

    # A waveform: bars rising and falling across the middle of the tile.
    heights = [0.18, 0.34, 0.55, 0.82, 0.62, 0.95, 0.48, 0.70, 0.30, 0.16]
    bar_w = px * 0.062
    gap = (px - bar_w * len(heights)) / (len(heights) + 1)
    centre = px / 2
    for index, height in enumerate(heights):
        x = gap + index * (bar_w + gap)
        half = px * 0.36 * height
        colour = ACCENT if index % 2 == 0 else LIGHT
        draw.rounded_rectangle(
            [x, centre - half, x + bar_w, centre + half],
            radius=bar_w / 2, fill=colour,
        )

    return img.resize((size, size), Image.LANCZOS)


def main():
    out = Path(__file__).parent / "revolv.ico"
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [render(s) for s in sizes]
    images[-1].save(out, format="ICO",
                    sizes=[(s, s) for s in sizes], append_images=images[:-1])
    print("wrote", out, out.stat().st_size, "bytes")


if __name__ == "__main__":
    main()


##############################################################################
# was legacy/revolv/__init__.py
##############################################################################

"""Revolv Transcriber - local meeting transcription with diarization and V/A/D emotion."""

APP_NAME = "Revolv Transcriber"
APP_VERSION = "1.0.0"


##############################################################################
# was legacy/revolv/config.py
##############################################################################

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


##############################################################################
# was legacy/revolv/hardware.py
##############################################################################

"""Detect the machine's compute capability and pick pipeline settings to match.

Everything here is deliberately import-light at module level; torch is only
imported inside detect() so the GUI can start instantly and probe in a worker
thread.
"""

import os
from dataclasses import dataclass, field
from typing import List

# GPU tiers, richest first. Each entry is:
#   (minimum free VRAM in GB, whisper model, ctranslate2 compute type,
#    transcription batch size, device for the emotion model)
# The VRAM figures leave headroom for the alignment, diarization and emotion
# models, which sit in memory alongside the ASR model.
GPU_TIERS = [
    (15.0, "large-v3", "float16", 16, "cuda"),
    (11.0, "large-v3", "float16", 12, "cuda"),
    (8.0,  "large-v3", "float16", 8,  "cuda"),
    (6.0,  "large-v3", "int8_float16", 4, "cuda"),
    (4.5,  "medium",   "int8_float16", 4, "cpu"),
    (3.0,  "small",    "int8_float16", 4, "cpu"),
    (2.0,  "base",     "int8_float16", 2, "cpu"),
]

# CPU tiers, richest first: (min RAM GB, min cores, model, batch size)
CPU_TIERS = [
    (24.0, 12, "medium", 8),
    (16.0, 8,  "small",  8),
    (8.0,  4,  "base",   4),
    (0.0,  1,  "tiny",   2),
]

MODEL_CHOICES = ["auto", "large-v3", "large-v2", "medium", "small", "base", "tiny"]


@dataclass
class HardwareProfile:
    device: str = "cpu"
    device_name: str = "CPU"
    vram_gb: float = 0.0
    compute_capability: str = ""
    cpu_count: int = 1
    ram_gb: float = 0.0
    compute_type: str = "int8"
    model_size: str = "base"
    batch_size: int = 4
    emotion_device: str = "cpu"
    diarize_device: str = "cpu"
    cpu_threads: int = 4
    notes: List[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.device == "cuda":
            head = f"{self.device_name}  ({self.vram_gb:.1f} GB VRAM)"
        else:
            head = f"{self.device_name}  ({self.cpu_count} cores, {self.ram_gb:.1f} GB RAM)"
        return f"{head}\nModel {self.model_size} - {self.compute_type} - batch {self.batch_size}"


def _total_ram_gb() -> float:
    try:
        import psutil
        return psutil.virtual_memory().total / 1024 ** 3
    except Exception:
        pass
    try:  # Windows fallback without psutil
        import ctypes

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(MemoryStatusEx)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return status.ullTotalPhys / 1024 ** 3
    except Exception:
        return 8.0


def _cpu_profile(profile: HardwareProfile) -> HardwareProfile:
    for min_ram, min_cores, model, batch in CPU_TIERS:
        if profile.ram_gb >= min_ram and profile.cpu_count >= min_cores:
            profile.model_size = model
            profile.batch_size = batch
            break
    profile.device = "cpu"
    profile.compute_type = "int8"
    profile.emotion_device = "cpu"
    profile.diarize_device = "cpu"
    # Leave a couple of cores for the OS and the UI thread.
    profile.cpu_threads = max(1, min(profile.cpu_count - 2, 16))
    return profile


def detect(device_override: str = "auto", model_override: str = "auto") -> HardwareProfile:
    """Probe the machine and return a tuned pipeline profile."""
    profile = HardwareProfile()
    profile.cpu_count = os.cpu_count() or 1
    profile.ram_gb = _total_ram_gb()

    try:
        import torch
    except Exception as exc:  # pragma: no cover - torch is a hard dependency
        profile.notes.append(f"PyTorch failed to load ({exc}); using CPU defaults.")
        return _cpu_profile(profile)

    try:
        profile.device_name = _cpu_name()
    except Exception:
        pass

    cuda_available = False
    try:
        cuda_available = torch.cuda.is_available()
    except Exception as exc:
        profile.notes.append(f"CUDA probe failed ({exc}).")

    if device_override == "cpu":
        profile.notes.append("Device forced to CPU in settings.")
        cuda_available = False

    if not cuda_available:
        if device_override == "cuda":
            profile.notes.append("CUDA was requested but is unavailable; falling back to CPU.")
        else:
            profile.notes.append("No CUDA GPU detected. Transcription will run on the CPU and will be slow.")
        _cpu_profile(profile)
    else:
        props = torch.cuda.get_device_properties(0)
        profile.device = "cuda"
        profile.device_name = props.name
        profile.vram_gb = props.total_memory / 1024 ** 3
        major, minor = torch.cuda.get_device_capability(0)
        profile.compute_capability = f"{major}.{minor}"
        profile.diarize_device = "cuda"
        profile.cpu_threads = max(1, min(profile.cpu_count - 2, 16))

        for min_vram, model, compute, batch, emotion_device in GPU_TIERS:
            if profile.vram_gb >= min_vram:
                profile.model_size = model
                profile.compute_type = compute
                profile.batch_size = batch
                profile.emotion_device = emotion_device
                break
        else:
            profile.notes.append(
                f"{profile.vram_gb:.1f} GB of VRAM is below the 2 GB minimum; using the CPU instead."
            )
            _cpu_profile(profile)
            profile.device_name = props.name + " (unused)"

        # ctranslate2 needs compute capability 7.0+ for real float16 throughput.
        if profile.device == "cuda" and major < 7:
            profile.compute_type = "int8"
            profile.notes.append(
                f"Compute capability {profile.compute_capability} predates fast float16; using int8."
            )

    if model_override and model_override != "auto":
        profile.model_size = model_override
        profile.notes.append(f"Model size overridden to {model_override} in settings.")

    return profile


def _cpu_name() -> str:
    try:
        import platform
        name = platform.processor() or platform.machine()
        return name or "CPU"
    except Exception:
        return "CPU"


##############################################################################
# was legacy/revolv/audio.py
##############################################################################

"""Decode any container PyAV can open into mono 16 kHz float32 samples.

The original pipeline downmixed by averaging raw frame arrays, which only works
for planar formats; packed formats arrive as a single interleaved row and would
be misread. Routing every frame through an AudioResampler makes the format,
channel layout and sample-rate conversion the decoder's problem.
"""

import numpy as np

TARGET_SR = 16000


class AudioError(RuntimeError):
    pass


def probe_duration(path) -> float:
    """Return the media duration in seconds, or 0.0 if it cannot be determined."""
    import av

    try:
        with av.open(str(path)) as container:
            if container.duration is not None:
                return float(container.duration) / av.time_base
            for stream in container.streams:
                if stream.type == "audio" and stream.duration and stream.time_base:
                    return float(stream.duration * stream.time_base)
    except Exception:
        pass
    return 0.0


def load_audio(path, target_sr: int = TARGET_SR, progress=None, cancel=None) -> np.ndarray:
    """Decode `path` to a mono float32 array in [-1, 1] at `target_sr`.

    `progress` is called with a 0..1 fraction as decoding advances.
    `cancel` is a threading.Event; decoding stops early when it is set.
    """
    import av
    from av.audio.resampler import AudioResampler

    try:
        container = av.open(str(path))
    except Exception as exc:
        raise AudioError(f"Could not open the file: {exc}") from exc

    try:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise AudioError("This file has no audio track.")
        stream.thread_type = "AUTO"

        duration = 0.0
        if container.duration is not None:
            duration = float(container.duration) / av.time_base
        elif stream.duration and stream.time_base:
            duration = float(stream.duration * stream.time_base)

        resampler = AudioResampler(format="flt", layout="mono", rate=target_sr)
        chunks = []
        time_base = stream.time_base

        for frame in container.decode(stream):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
            if progress and duration > 0 and frame.pts is not None and time_base:
                elapsed = float(frame.pts * time_base)
                progress(min(elapsed / duration, 1.0))

        for out in resampler.resample(None):  # flush the resampler's tail
            chunks.append(out.to_ndarray().reshape(-1))
    finally:
        container.close()

    if not chunks:
        raise AudioError("No audio frames could be decoded from this file.")

    audio = np.concatenate(chunks).astype(np.float32, copy=False)
    if progress:
        progress(1.0)

    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak == 0.0:
        raise AudioError("The audio track is completely silent.")
    return audio


class Cancelled(Exception):
    """Raised when the user stops a job mid-flight."""


##############################################################################
# was legacy/revolv/theme.py
##############################################################################

"""Palette and stylesheet for the window.

The brief was calm: muted colour, soft edges, room to breathe. So the neutrals
are warm rather than clinical grey, the accent is a desaturated denim that sits
back instead of shouting, and the layout leans on space rather than boxes and
dividers. Radii run 10px on controls and 16 to 20px on containers.

Every foreground/background pairing below clears WCAG AA (4.5:1). The muted and
subtle text tones are the ones worth watching: subtle is reserved for disabled
states, never for text a reader needs.
"""

from pathlib import Path

LIGHT = {
    "name": "light",

    # Warm neutrals. The canvas is paper rather than white; cards lift off it
    # by being lighter, not by being outlined.
    "canvas": "#F5F4F1",
    "surface": "#FFFFFF",
    "surface_soft": "#FAF9F7",
    "surface_sunken": "#EFEDE9",
    "hover": "#F1EFEB",
    "pressed": "#E8E5E0",
    "border": "#E6E3DD",
    "border_strong": "#D6D2CA",

    "text": "#24231F",         # 15.4:1 on canvas
    "text_muted": "#6A665E",   # 5.1:1 on canvas
    "text_subtle": "#8A857C",  # disabled only

    "accent": "#4A6FA5",       # 5.1:1 with white
    "accent_hover": "#3F5F8C",
    "accent_pressed": "#35507A",
    "accent_fg": "#FFFFFF",
    "accent_text": "#3F6396",
    "accent_soft": "#EDF1F7",
    "accent_border": "#C3D0E4",

    "ok_text": "#37785C",      # 5.3:1 on white
    "ok_soft": "#EAF3EE",
    "bad_text": "#B4544A",     # 4.9:1 on white
    "bad_soft": "#FAEEEC",

    "track": "#E6E3DD",
    "shadow": (0, 0, 0, 26),
}

DARK = {
    "name": "dark",

    "canvas": "#1A1917",
    "surface": "#212020",
    "surface_soft": "#272625",
    "surface_sunken": "#161514",
    "hover": "#2B2A28",
    "pressed": "#333230",
    "border": "#33312E",
    "border_strong": "#45423E",

    "text": "#EDEBE7",
    "text_muted": "#A8A39A",
    "text_subtle": "#7A756D",

    # On a dark ground the fill lightens and the label goes dark.
    "accent": "#7FA3D8",
    "accent_hover": "#96B4E2",
    "accent_pressed": "#6E92C7",
    "accent_fg": "#12192A",
    "accent_text": "#9DBAE6",
    "accent_soft": "#1E2937",
    "accent_border": "#38506F",

    "ok_text": "#6FBF95",
    "ok_soft": "#17251E",
    "bad_text": "#E08A80",
    "bad_soft": "#2A1A18",

    "track": "#33312E",
    "shadow": (0, 0, 0, 90),
}

PALETTES = {"light": LIGHT, "dark": DARK}

FONT_STACK = '"Segoe UI Variable Text", "Segoe UI", -apple-system, sans-serif'
FONT_DISPLAY = '"Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI"'
FONT_MONO = '"Cascadia Mono", "Consolas", monospace'


def get(name):
    return PALETTES.get((name or "light").lower(), LIGHT)


def _glyph(kind, color):
    """Render a chevron or tick to a PNG and return a QSS-safe path.

    Qt stylesheets cannot draw either shape. The zero-size-box border trick
    that works in CSS comes out as a dash here, and there is no tick character
    that renders consistently, so both are painted once and cached on disk.
    """
    import tempfile

    from PySide6 import QtCore, QtGui

    name = "revolv_{0}_{1}.png".format(kind, color.lstrip("#"))
    path = Path(tempfile.gettempdir()) / name
    if not path.exists():
        size = 28
        # QImage rather than QPixmap: a pixmap needs a live QGuiApplication and
        # aborts the process without one, which would make this module unusable
        # before the app starts.
        image = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32)
        image.fill(QtCore.Qt.transparent)

        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        pen = QtGui.QPen(QtGui.QColor(color))
        pen.setWidthF(2.6 if kind == "check" else 2.2)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setPen(pen)

        if kind == "check":
            points = [(8, 14.5), (12.2, 18.5), (20, 10)]
        else:  # chevron
            points = [(9, 12), (14, 17), (19, 12)]
        painter.drawPolyline([QtCore.QPointF(x, y) for x, y in points])
        painter.end()
        image.save(str(path))

    return str(path).replace("\\", "/")


def qss(c):
    """Build the stylesheet for one palette."""
    chevron = _glyph("chevron", c["text_muted"])
    tick = _glyph("check", c["accent_fg"])
    return f"""
    QWidget {{
        background: transparent;
        color: {c['text']};
        font-family: {FONT_STACK};
        font-size: 10pt;
    }}
    /* QWidget above is transparent, so every top-level surface has to name its
       own ground or it inherits the platform default (black). */
    #root, QDialog, QMessageBox {{ background: {c['canvas']}; }}

    /* ---- type ---- */
    #title {{
        font-family: {FONT_DISPLAY};
        font-size: 19pt;
        font-weight: 600;
        color: {c['text']};
    }}
    #subtitle {{ color: {c['text_muted']}; font-size: 10pt; }}
    #sectionLabel {{
        color: {c['text_muted']};
        font-size: 9pt;
        font-weight: 600;
    }}
    #sectionCount {{ color: {c['text_subtle']}; font-size: 9pt; }}
    #statusLine {{ color: {c['text_muted']}; font-size: 9pt; }}

    /* ---- cards ---- */
    #card {{
        background: {c['surface']};
        border-radius: 16px;
    }}
    #pill {{
        background: {c['accent_soft']};
        border-radius: 14px;
    }}
    #pillText {{ color: {c['accent_text']}; font-size: 10pt; }}
    #pillMeta {{ color: {c['accent_text']}; font-size: 9pt; }}

    /* ---- drop zone ---- */
    #dropZone {{
        background: {c['surface']};
        border: 2px dashed {c['border_strong']};
        border-radius: 20px;
    }}
    #dropZone[hot="true"] {{
        background: {c['accent_soft']};
        border: 2px dashed {c['accent']};
    }}
    #dropTitle {{
        font-family: {FONT_DISPLAY};
        font-size: 13pt;
        font-weight: 600;
        color: {c['text']};
    }}
    #dropHint {{ color: {c['text_muted']}; font-size: 9pt; }}

    /* ---- buttons ---- */
    QPushButton {{
        background: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 9px 18px;
        font-size: 10pt;
    }}
    QPushButton:hover {{ background: {c['hover']}; border-color: {c['border_strong']}; }}
    QPushButton:pressed {{ background: {c['pressed']}; }}
    QPushButton:disabled {{ color: {c['text_subtle']}; background: {c['surface_soft']};
                            border-color: {c['border']}; }}

    QPushButton#primary {{
        background: {c['accent']};
        color: {c['accent_fg']};
        border: none;
        border-radius: 12px;
        padding: 13px 26px;
        font-size: 10pt;
        font-weight: 600;
    }}
    QPushButton#primary:hover {{ background: {c['accent_hover']}; }}
    QPushButton#primary:pressed {{ background: {c['accent_pressed']}; }}
    QPushButton#primary:disabled {{ background: {c['surface_sunken']};
                                    color: {c['text_subtle']}; }}

    QPushButton#quiet {{
        background: transparent;
        border: none;
        color: {c['text_muted']};
        padding: 9px 14px;
        border-radius: 10px;
    }}
    QPushButton#quiet:hover {{ background: {c['hover']}; color: {c['text']}; }}
    QPushButton#quiet:disabled {{ color: {c['text_subtle']}; background: transparent; }}

    /* Format chips: selected reads as a soft tinted pill, not a checkbox. */
    QPushButton#chip {{
        background: {c['surface']};
        color: {c['text_muted']};
        border: 1px solid {c['border']};
        border-radius: 16px;
        padding: 8px 16px;
        font-size: 9pt;
    }}
    QPushButton#chip:hover {{ border-color: {c['border_strong']}; color: {c['text']}; }}
    /* Colour is the only thing that changes on check. Switching font weight
       here would re-measure the label and clip it inside the fixed chip. */
    QPushButton#chip:checked {{
        background: {c['accent_soft']};
        border: 1px solid {c['accent_border']};
        color: {c['accent_text']};
    }}

    /* ---- inputs ---- */
    QLineEdit {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 9px 12px;
        selection-background-color: {c['accent_soft']};
        selection-color: {c['accent_text']};
    }}
    QLineEdit:focus {{ border-color: {c['accent']}; }}
    QLineEdit:disabled {{ background: {c['surface_sunken']}; color: {c['text_subtle']}; }}

    QComboBox {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 8px 12px;
        min-width: 120px;
    }}
    QComboBox:focus {{ border-color: {c['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    /* Styling the drop-down hides Qt's built-in arrow, so draw one: a zero-size
       box whose borders form a downward triangle. */
    QComboBox::down-arrow {{
        image: url({chevron});
        width: 16px; height: 16px;
        margin-right: 8px;
    }}
    QComboBox QAbstractItemView {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 4px;
        selection-background-color: {c['accent_soft']};
        selection-color: {c['accent_text']};
        outline: none;
    }}

    QRadioButton, QCheckBox {{ color: {c['text']}; spacing: 9px; padding: 4px 0; }}

    /* Qt adds the border outside the declared width, so the checked state
       shrinks its box by exactly as much as the border grows. Both states end
       up 22px across, and the radius stays at half of that so it reads round. */
    QRadioButton::indicator {{
        width: 18px; height: 18px;
        border: 2px solid {c['border_strong']};
        border-radius: 11px;
        background: {c['surface']};
    }}
    QRadioButton::indicator:checked {{
        width: 12px; height: 12px;
        border: 5px solid {c['accent']};
        border-radius: 11px;
        background: {c['surface']};
    }}
    QRadioButton::indicator:hover {{ border-color: {c['accent']}; }}

    QCheckBox::indicator {{
        width: 18px; height: 18px;
        border: 2px solid {c['border_strong']};
        border-radius: 6px;
        background: {c['surface']};
    }}
    QCheckBox::indicator:checked {{
        border: 2px solid {c['accent']};
        background: {c['accent']};
        image: url({tick});
    }}
    QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}

    /* ---- file rows ---- */
    #row {{ background: {c['surface_soft']}; border-radius: 12px; }}
    #row[state="active"] {{ background: {c['accent_soft']}; }}
    #row[state="done"] {{ background: {c['ok_soft']}; }}
    #row[state="error"] {{ background: {c['bad_soft']}; }}
    #rowName {{ font-size: 10pt; color: {c['text']}; }}
    #rowStatus {{ font-size: 9pt; color: {c['text_muted']}; }}
    #rowStatus[state="done"] {{ color: {c['ok_text']}; }}
    #rowStatus[state="error"] {{ color: {c['bad_text']}; }}
    #rowStatus[state="active"] {{ color: {c['accent_text']}; }}
    #rowPercent {{ font-size: 9pt; color: {c['text_muted']}; }}

    /* ---- progress ---- */
    QProgressBar {{
        background: {c['track']};
        border: none;
        border-radius: 3px;
        height: 6px;
        text-align: center;
        color: transparent;
    }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
    QProgressBar#rowBar {{ height: 4px; border-radius: 2px; }}
    QProgressBar#rowBar::chunk {{ border-radius: 2px; }}

    /* ---- scroll areas ---- */
    QScrollArea, #listHost {{ background: {c['surface']}; border: none;
                              border-radius: 16px; }}
    QScrollBar:vertical {{
        background: transparent; width: 10px; margin: 6px 3px 6px 0;
    }}
    QScrollBar::handle:vertical {{
        background: {c['border_strong']}; border-radius: 4px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {c['text_subtle']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

    /* ---- log ---- */
    QPlainTextEdit#log {{
        background: {c['surface']};
        border: none;
        border-radius: 16px;
        padding: 14px;
        color: {c['text_muted']};
        font-family: {FONT_MONO};
        font-size: 9pt;
        selection-background-color: {c['accent_soft']};
        selection-color: {c['accent_text']};
    }}

    QToolTip {{
        background: {c['text']};
        color: {c['surface']};
        border: none;
        border-radius: 8px;
        padding: 6px 10px;
    }}
    """


##############################################################################
# was legacy/revolv/writers.py
##############################################################################

"""Write a finished transcript out in the formats the user asked for."""

import csv
import json
from pathlib import Path

FORMAT_LABELS = {
    "json": "JSON (full data)",
    "txt": "Text transcript",
    "srt": "Subtitles (.srt)",
    "csv": "Spreadsheet (.csv)",
}
FORMAT_ORDER = ["json", "txt", "srt", "csv"]


def _timestamp(seconds, comma=False):
    seconds = max(float(seconds), 0.0)
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:  # rounding can tip a whole second
        millis = 999
    sep = "," if comma else "."
    return "{0:02d}:{1:02d}:{2:02d}{3}{4:03d}".format(hours, minutes, secs, sep, millis)


def unique_path(path: Path) -> Path:
    """Never clobber an existing output; append (2), (3)... instead."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    counter = 2
    while True:
        candidate = parent / "{0} ({1}){2}".format(stem, counter, suffix)
        if not candidate.exists():
            return candidate
        counter += 1


def write_json(segments, meta, path: Path) -> Path:
    """A bare list of segments, matching what VoiceModel.py produced."""
    path = unique_path(path.with_suffix(".json"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(segments, f, indent=2, ensure_ascii=False)
    return path


def write_txt(segments, meta, path: Path) -> Path:
    path = unique_path(path.with_suffix(".txt"))
    with open(path, "w", encoding="utf-8") as f:
        f.write("Transcript of {0}\n".format(Path(meta.get("source", "")).name))
        f.write("Model {0} on {1} ({2})\n".format(
            meta.get("model", "?"), meta.get("device_name", "?"),
            meta.get("compute_type", "?")))
        f.write("{0} segments".format(meta.get("segments", 0)))
        if meta.get("speakers"):
            f.write(", {0} speakers".format(meta["speakers"]))
        f.write("\n" + "=" * 70 + "\n\n")

        last_speaker = None
        for seg in segments:
            speaker = seg.get("speaker", "UNKNOWN")
            if speaker != last_speaker:
                f.write("\n[{0}] {1}\n".format(_timestamp(seg["start"]), speaker))
                last_speaker = speaker
            f.write(seg.get("text", "") + "\n")
    return path


def write_srt(segments, meta, path: Path) -> Path:
    path = unique_path(path.with_suffix(".srt"))
    with open(path, "w", encoding="utf-8") as f:
        index = 1
        for seg in segments:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            speaker = seg.get("speaker", "")
            if speaker and speaker != "UNKNOWN":
                text = "[{0}] {1}".format(speaker, text)
            f.write("{0}\n{1} --> {2}\n{3}\n\n".format(
                index,
                _timestamp(seg["start"], comma=True),
                _timestamp(seg["end"], comma=True),
                text,
            ))
            index += 1
    return path


def write_csv(segments, meta, path: Path) -> Path:
    path = unique_path(path.with_suffix(".csv"))
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "start", "end", "duration_seconds", "speaker", "text",
            "word_count", "wpm", "valence", "arousal", "dominance",
        ])
        for seg in segments:
            pacing = seg.get("pacing", {})
            emotion = seg.get("emotion", {})
            writer.writerow([
                seg.get("start", ""),
                seg.get("end", ""),
                pacing.get("duration_seconds", ""),
                seg.get("speaker", ""),
                seg.get("text", ""),
                pacing.get("word_count", ""),
                pacing.get("wpm", ""),
                emotion.get("valence", ""),
                emotion.get("arousal", ""),
                emotion.get("dominance", ""),
            ])
    return path


WRITERS = {
    "json": write_json,
    "txt": write_txt,
    "srt": write_srt,
    "csv": write_csv,
}


def write_all(segments, meta, output_dir: Path, stem: str, formats):
    """Write every requested format. Returns the list of paths created."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for fmt in FORMAT_ORDER:
        if fmt in formats:
            written.append(WRITERS[fmt](segments, meta, output_dir / stem))
    return written


##############################################################################
# was legacy/revolv/pipeline.py
##############################################################################

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


##############################################################################
# was legacy/revolv/gui.py
##############################################################################

"""Desktop front end for the transcription pipeline, built on Qt.

Qt rather than Tk because the design calls for rounded containers, soft
shadows, smooth scrolling and real hover states, none of which Tk can draw.
Qt also hands us actual filesystem paths on a drop, where a Tk drop gives a
string that has to be unquoted by hand.
"""

import os
import subprocess
import sys
import traceback
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, Signal

from . import APP_NAME, APP_VERSION, theme
from .config import Settings, is_media_file, log_file
from .hardware import MODEL_CHOICES
from .writers import FORMAT_LABELS, FORMAT_ORDER, write_all

DND_AVAILABLE = True  # Qt handles this natively

# The chips carry the short word; the full description lives in the tooltip so
# the row of formats stays quiet.
CHIP_LABELS = {
    "json": "JSON",
    "txt": "Text",
    "srt": "Subtitles",
    "csv": "Spreadsheet",
}


class Job:
    def __init__(self, path):
        self.path = Path(path)
        self.status = "Queued"
        self.state = "idle"       # idle | active | done | error
        self.percent = 0
        self.outputs = []
        self.row = None


class WaveBadge(QtWidgets.QWidget):
    """A small waveform mark for the drop zone. Drawn, so it stays crisp."""

    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self.colors = palette
        self.setFixedSize(46, 46)

    def set_palette(self, palette):
        self.colors = palette
        self.update()

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QtGui.QColor(self.colors["accent_soft"]))
        painter.drawEllipse(self.rect())

        pen = QtGui.QPen(QtGui.QColor(self.colors["accent"]))
        pen.setWidthF(2.4)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)

        heights = [0.30, 0.58, 0.86, 0.48, 0.70, 0.34]
        centre_y = self.height() / 2
        spacing = 4.4
        start_x = self.width() / 2 - (len(heights) - 1) * spacing / 2
        for index, amount in enumerate(heights):
            half = (self.height() * 0.30) * amount
            x = start_x + index * spacing
            painter.drawLine(QtCore.QPointF(x, centre_y - half),
                             QtCore.QPointF(x, centre_y + half))


class DropZone(QtWidgets.QFrame):
    filesDropped = Signal(list)
    clicked = Signal()

    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setProperty("hot", "false")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(150)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(8)

        self.badge = WaveBadge(palette)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.badge)
        row.addStretch(1)
        layout.addLayout(row)

        self.title = QtWidgets.QLabel("Drop audio or video here")
        self.title.setObjectName("dropTitle")
        self.title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title)

        self.hint = QtWidgets.QLabel(
            "or click to browse    ·    drop a folder to queue everything inside")
        self.hint.setObjectName("dropHint")
        self.hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.hint)

    def set_palette(self, palette):
        self.badge.set_palette(palette)

    def _restyle(self):
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("hot", "true")
            self._restyle()

    def dragLeaveEvent(self, _event):
        self.setProperty("hot", "false")
        self._restyle()

    def dropEvent(self, event):
        self.setProperty("hot", "false")
        self._restyle()
        paths = [url.toLocalFile() for url in event.mimeData().urls()
                 if url.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


class FileRow(QtWidgets.QFrame):
    """One queued file, as a rounded card rather than a table row."""

    activated = Signal()

    def __init__(self, job, parent=None):
        super().__init__(parent)
        self.job = job
        self.setObjectName("row")
        self.setProperty("state", "idle")

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(7)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(12)
        self.name = QtWidgets.QLabel(job.path.name)
        self.name.setObjectName("rowName")
        self.name.setTextInteractionFlags(Qt.NoTextInteraction)
        top.addWidget(self.name, 1)

        self.percent = QtWidgets.QLabel("")
        self.percent.setObjectName("rowPercent")
        top.addWidget(self.percent, 0, Qt.AlignRight)
        outer.addLayout(top)

        self.status = QtWidgets.QLabel("Queued")
        self.status.setObjectName("rowStatus")
        self.status.setProperty("state", "idle")
        outer.addWidget(self.status)

        self.bar = QtWidgets.QProgressBar()
        self.bar.setObjectName("rowBar")
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        self.bar.hide()
        outer.addWidget(self.bar)

    def set_state(self, state, status_text, percent=None):
        self.job.state = state
        self.setProperty("state", state)
        self.status.setProperty("state", state)
        self.status.setText(status_text)

        if percent is None:
            self.percent.setText("")
            self.bar.hide()
        else:
            self.percent.setText("{0}%".format(int(percent * 100)))
            self.bar.setValue(int(percent * 1000))
            self.bar.setVisible(state == "active")

        for widget in (self, self.status):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def mouseDoubleClickEvent(self, _event):
        self.activated.emit()


class Worker(QtCore.QThread):
    """Runs the queue off the UI thread. Signals cross back automatically."""

    log = Signal(str)
    status = Signal(str)
    jobProgress = Signal(int, str, float)
    jobStarted = Signal(int)
    jobDone = Signal(int, list, dict)
    jobFailed = Signal(int, str)
    jobStopped = Signal(int)

    def __init__(self, jobs, indices, profile, settings, output_dir, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self.indices = indices
        self.profile = profile
        self.settings = dict(settings)
        self.output_dir = output_dir
        self._cancel = QtCore.QMutex()
        self._stop = False

    def request_stop(self):
        self._stop = True

    class _Flag:
        """Adapter so the pipeline's `cancel.is_set()` contract still works."""

        def __init__(self, worker):
            self.worker = worker

        def is_set(self):
            return self.worker._stop

    def run(self):
        import time

        from .audio import AudioError, Cancelled
        from .pipeline import Transcriber

        cancel = Worker._Flag(self)
        transcriber = None
        try:
            self.status.emit("Loading models. The first run downloads them, "
                             "which can take a while.")
            transcriber = Transcriber(
                self.profile,
                hf_token=self.settings["hf_token"],
                language=self.settings["language"],
                diarize=self.settings["diarize"],
                emotion=self.settings["emotion"],
                log=self.log.emit,
            )
            transcriber.load_models(progress=self.status.emit, cancel=cancel)

            total = len(self.indices)
            for position, index in enumerate(self.indices, start=1):
                if self._stop:
                    self.jobStopped.emit(index)
                    continue

                job = self.jobs[index]
                self.jobStarted.emit(index)
                self.status.emit("File {0} of {1}  ·  {2}".format(
                    position, total, job.path.name))
                started = time.time()

                def on_progress(stage, overall, message, _index=index):
                    self.jobProgress.emit(_index, message, overall)

                try:
                    segments, meta = transcriber.run(job.path, progress=on_progress,
                                                     cancel=cancel)
                except Cancelled:
                    self.jobStopped.emit(index)
                    break
                except AudioError as exc:
                    self.jobFailed.emit(index, str(exc))
                    self.log.emit("{0}: {1}".format(job.path.name, exc))
                    continue
                except Exception as exc:
                    self.jobFailed.emit(index, "Failed: {0}".format(exc))
                    self.log.emit("{0} failed:\n{1}".format(
                        job.path.name, traceback.format_exc()))
                    continue

                out_dir = Path(self.output_dir) if self.output_dir else job.path.parent
                try:
                    written = write_all(segments, meta, out_dir, job.path.stem,
                                        self.settings["formats"])
                except OSError as exc:
                    self.jobFailed.emit(index, "Could not save: {0}".format(exc))
                    continue

                elapsed = time.time() - started
                speed = (meta["media_seconds"] / elapsed) if elapsed > 0 else 0
                self.jobDone.emit(index, [str(p) for p in written], meta)
                self.log.emit("{0}: {1} segments, {2} speakers, {3:.0f}s "
                              "({4:.1f}x real time)".format(
                                  job.path.name, meta["segments"], meta["speakers"],
                                  elapsed, speed))
                for path in written:
                    self.log.emit("   saved {0}".format(path))

        except Cancelled:
            self.log.emit("Stopped before the models finished loading.")
        except Exception:
            self.log.emit("The run failed:\n{0}".format(traceback.format_exc()))
        finally:
            if transcriber is not None:
                transcriber.close()


class HardwareProbe(QtCore.QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, device_override, model_override, parent=None):
        super().__init__(parent)
        self.device_override = device_override
        self.model_override = model_override

    def run(self):
        try:
            from .hardware import detect
            self.done.emit(detect(self.device_override, self.model_override))
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, initial_files=()):
        super().__init__()
        self.settings = Settings()
        self.colors = theme.get(self.settings["theme"])
        self.profile = None
        self.jobs = []
        self.worker = None
        self.probe = None

        self.setWindowTitle("{0} {1}".format(APP_NAME, APP_VERSION))
        self.resize(1020, 950)
        self.setMinimumSize(880, 680)
        self.setAcceptDrops(True)

        self._build_ui()
        self.apply_theme()
        QtCore.QTimer.singleShot(60, self.detect_hardware)

        if initial_files:
            self.add_paths(initial_files)

    # -- construction ------------------------------------------------------
    def _label(self, text, object_name):
        label = QtWidgets.QLabel(text)
        label.setObjectName(object_name)
        return label

    def _build_ui(self):
        root = QtWidgets.QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        outer = QtWidgets.QVBoxLayout(root)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(18)

        outer.addLayout(self._build_header())
        outer.addWidget(self._build_hardware_pill())
        outer.addWidget(self._build_dropzone())
        outer.addLayout(self._build_files_header())
        outer.addWidget(self._build_list(), 1)
        outer.addLayout(self._build_output_row())
        outer.addLayout(self._build_format_row())
        outer.addLayout(self._build_actions())
        outer.addWidget(self._build_progress())
        outer.addWidget(self.status_line)
        outer.addWidget(self._build_log())

    def _build_header(self):
        row = QtWidgets.QHBoxLayout()
        column = QtWidgets.QVBoxLayout()
        column.setSpacing(2)
        column.addWidget(self._label(APP_NAME, "title"))
        column.addWidget(self._label(
            "Local transcription with speaker labels and tone", "subtitle"))
        row.addLayout(column)
        row.addStretch(1)

        self.settings_button = QtWidgets.QPushButton("Settings")
        self.settings_button.setObjectName("quiet")
        self.settings_button.setCursor(Qt.PointingHandCursor)
        self.settings_button.clicked.connect(self.open_settings)
        row.addWidget(self.settings_button, 0, Qt.AlignTop)
        return row

    def _build_hardware_pill(self):
        self.pill = QtWidgets.QFrame()
        self.pill.setObjectName("pill")
        layout = QtWidgets.QHBoxLayout(self.pill)
        layout.setContentsMargins(18, 13, 18, 13)

        self.hw_text = self._label("Checking what this machine can do…", "pillText")
        layout.addWidget(self.hw_text)
        layout.addStretch(1)
        self.hw_meta = self._label("", "pillMeta")
        layout.addWidget(self.hw_meta)
        return self.pill

    def _build_dropzone(self):
        self.dropzone = DropZone(self.colors)
        self.dropzone.filesDropped.connect(self.add_paths)
        self.dropzone.clicked.connect(self.browse_files)
        return self.dropzone

    def _build_files_header(self):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self._label("Files", "sectionLabel"))
        row.addStretch(1)
        self.files_count = self._label("", "sectionCount")
        row.addWidget(self.files_count)
        return row

    def _build_list(self):
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setObjectName("listHost")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(210)

        holder = QtWidgets.QWidget()
        holder.setObjectName("listHost")
        self.list_layout = QtWidgets.QVBoxLayout(holder)
        self.list_layout.setContentsMargins(12, 12, 12, 12)
        self.list_layout.setSpacing(8)

        self.empty_label = self._label("Nothing queued yet.", "rowStatus")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.list_layout.addWidget(self.empty_label)
        self.list_layout.addStretch(1)

        self.scroll.setWidget(holder)
        # No QGraphicsDropShadowEffect here: applying one to a scroll area stops
        # the viewport clipping its children, and rows spill over the controls
        # below. The card reads fine on depth from its own background.
        return self.scroll

    def _build_output_row(self):
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(self._label("Save to", "sectionLabel"))

        self.beside_radio = QtWidgets.QRadioButton("Beside the original")
        self.folder_radio = QtWidgets.QRadioButton("A folder")
        group = QtWidgets.QButtonGroup(self)
        group.addButton(self.beside_radio)
        group.addButton(self.folder_radio)
        if self.settings["output_dir"]:
            self.folder_radio.setChecked(True)
        else:
            self.beside_radio.setChecked(True)
        self.beside_radio.toggled.connect(self.sync_output_row)
        row.addWidget(self.beside_radio)
        row.addWidget(self.folder_radio)

        self.output_edit = QtWidgets.QLineEdit(self.settings["output_dir"])
        self.output_edit.setPlaceholderText("Choose a folder…")
        row.addWidget(self.output_edit, 1)

        self.output_button = QtWidgets.QPushButton("Choose")
        self.output_button.setCursor(Qt.PointingHandCursor)
        self.output_button.clicked.connect(self.browse_output_dir)
        row.addWidget(self.output_button)

        self.sync_output_row()
        return row

    def _build_format_row(self):
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self._label("Formats", "sectionLabel"))

        self.format_buttons = {}
        for fmt in FORMAT_ORDER:
            button = QtWidgets.QPushButton(CHIP_LABELS[fmt])
            button.setObjectName("chip")
            button.setCheckable(True)
            button.setChecked(fmt in self.settings["formats"])
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(FORMAT_LABELS[fmt])
            self.format_buttons[fmt] = button
            row.addWidget(button)
        row.addStretch(1)
        return row

    def _build_actions(self):
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(10)

        self.start_button = QtWidgets.QPushButton("Start transcribing")
        self.start_button.setObjectName("primary")
        self.start_button.setCursor(Qt.PointingHandCursor)
        self.start_button.clicked.connect(self.start)
        row.addWidget(self.start_button)

        self.stop_button = QtWidgets.QPushButton("Stop")
        self.stop_button.setObjectName("quiet")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        row.addWidget(self.stop_button)

        self.clear_button = QtWidgets.QPushButton("Clear list")
        self.clear_button.setObjectName("quiet")
        self.clear_button.clicked.connect(self.clear_list)
        row.addWidget(self.clear_button)

        row.addStretch(1)

        self.open_button = QtWidgets.QPushButton("Open output folder")
        self.open_button.setCursor(Qt.PointingHandCursor)
        self.open_button.clicked.connect(self.open_output_folder)
        row.addWidget(self.open_button)
        return row

    def _build_progress(self):
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)

        self.status_line = self._label("Add a recording to get started.", "statusLine")
        return self.progress

    def _build_log(self):
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setObjectName("log")
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(104)
        self.log_view.setFrameShape(QtWidgets.QFrame.NoFrame)
        return self.log_view

    # -- theme -------------------------------------------------------------
    def apply_theme(self):
        app = QtWidgets.QApplication.instance()
        app.setStyleSheet(theme.qss(self.colors))
        self.dropzone.set_palette(self.colors)
        self.setStyleSheet("")
        for widget in self.findChildren(QtWidgets.QWidget):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.update()

    def switch_theme(self, name):
        self.colors = theme.get(name)
        self.settings["theme"] = self.colors["name"]
        self.settings.save()
        self.apply_theme()

    # -- hardware ----------------------------------------------------------
    def detect_hardware(self):
        self.probe = HardwareProbe(self.settings["device_override"],
                                   self.settings["model_override"])
        self.probe.done.connect(self._hardware_ready)
        self.probe.failed.connect(
            lambda msg: self.log("Hardware detection failed: {0}".format(msg)))
        self.probe.start()

    def _hardware_ready(self, profile):
        self.profile = profile
        if profile.device == "cuda":
            head = "{0}  ·  {1:.1f} GB of video memory".format(
                profile.device_name, profile.vram_gb)
        else:
            head = "{0}  ·  {1} cores  ·  {2:.0f} GB of memory".format(
                profile.device_name, profile.cpu_count, profile.ram_gb)
        self.hw_text.setText(head)
        self.hw_meta.setText("{0}  ·  {1}  ·  batch {2}".format(
            profile.model_size, profile.compute_type, profile.batch_size))
        self.log("Detected {0}".format(profile.summary().replace("\n", " | ")))
        for note in profile.notes:
            self.log(note)

    # -- files -------------------------------------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls()
                 if url.isLocalFile()]
        if paths:
            self.add_paths(paths)
            event.acceptProposedAction()

    def browse_files(self):
        start = self.settings.get("last_input_dir") or str(Path.home())
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Choose audio or video files",
            start if os.path.isdir(start) else str(Path.home()),
            "Audio and video (*.mkv *.mp4 *.mov *.avi *.webm *.m4v *.wav *.mp3 "
            "*.m4a *.aac *.flac *.ogg *.opus *.wma);;All files (*.*)")
        if paths:
            self.add_paths(paths)

    def add_paths(self, paths):
        found, skipped = [], 0
        for raw in paths:
            path = Path(str(raw))
            if path.is_dir():
                for child in sorted(path.rglob("*")):
                    if child.is_file() and is_media_file(child):
                        found.append(child)
            elif path.is_file():
                if is_media_file(path):
                    found.append(path)
                else:
                    skipped += 1

        existing = {str(job.path).lower() for job in self.jobs}
        added = 0
        for path in found:
            if str(path).lower() in existing:
                continue
            job = Job(path)
            row = FileRow(job)
            row.activated.connect(lambda j=job: self.reveal(
                j.outputs[0] if j.outputs else j.path))
            job.row = row
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)
            self.jobs.append(job)
            existing.add(str(path).lower())
            added += 1

        if added:
            self.settings["last_input_dir"] = str(Path(found[-1]).parent)
            self.settings.save()
            self.log("Added {0} file{1}.".format(added, "" if added == 1 else "s"))
        if skipped:
            self.log("Skipped {0} file{1} that are not audio or video.".format(
                skipped, "" if skipped == 1 else "s"))
        self.refresh_counts()

    def clear_list(self):
        if self.worker and self.worker.isRunning():
            return
        for job in self.jobs:
            job.row.setParent(None)
            job.row.deleteLater()
        self.jobs = []
        self.progress.setValue(0)
        self.refresh_counts()

    def refresh_counts(self):
        self.empty_label.setVisible(not self.jobs)
        if not self.jobs:
            self.files_count.setText("")
            self.status_line.setText("Add a recording to get started.")
            return
        waiting = sum(1 for j in self.jobs if j.state in ("idle", "error"))
        self.files_count.setText("{0} queued  ·  {1} waiting".format(
            len(self.jobs), waiting))
        if not (self.worker and self.worker.isRunning()):
            self.status_line.setText("Ready when you are.")

    # -- output ------------------------------------------------------------
    def sync_output_row(self):
        use_folder = self.folder_radio.isChecked()
        self.output_edit.setEnabled(use_folder)
        self.output_button.setEnabled(use_folder)

    def browse_output_dir(self):
        current = self.output_edit.text().strip()
        start = current if os.path.isdir(current) else str(Path.home())
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Choose where to save transcripts", start)
        if chosen:
            self.output_edit.setText(chosen)
            self.folder_radio.setChecked(True)
            self.sync_output_row()

    def output_dir(self):
        if self.folder_radio.isChecked():
            return self.output_edit.text().strip()
        return ""

    def open_output_folder(self):
        target = None
        for job in reversed(self.jobs):
            if job.outputs:
                target = Path(job.outputs[0]).parent
                break
        if target is None:
            chosen = self.output_dir()
            if chosen:
                target = Path(chosen)
            elif self.jobs:
                target = self.jobs[0].path.parent
        if target is None or not target.exists():
            QtWidgets.QMessageBox.information(
                self, APP_NAME, "There is no output folder to open yet.")
            return
        self.reveal(target)

    def reveal(self, path):
        path = Path(path)
        try:
            if sys.platform.startswith("win"):
                if path.is_dir():
                    os.startfile(str(path))
                else:
                    subprocess.Popen(["explorer", "/select,", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path if path.is_dir() else path.parent)])
            else:
                subprocess.Popen(["xdg-open",
                                  str(path if path.is_dir() else path.parent)])
        except Exception as exc:
            self.log("Could not open {0}: {1}".format(path, exc))

    # -- settings ----------------------------------------------------------
    def open_settings(self):
        SettingsDialog(self).exec()

    def collect_settings(self):
        self.settings["output_dir"] = self.output_dir()
        self.settings["formats"] = [f for f in FORMAT_ORDER
                                    if self.format_buttons[f].isChecked()]
        self.settings.save()

    # -- running -----------------------------------------------------------
    def start(self):
        if self.worker and self.worker.isRunning():
            return
        if self.profile is None:
            QtWidgets.QMessageBox.information(
                self, APP_NAME, "Still checking your hardware. Try again in a moment.")
            return

        indices = [i for i, j in enumerate(self.jobs) if j.state in ("idle", "error")]
        if not indices:
            QtWidgets.QMessageBox.information(
                self, APP_NAME, "Add some audio or video files first.")
            return

        self.collect_settings()
        if not self.settings["formats"]:
            QtWidgets.QMessageBox.information(
                self, APP_NAME, "Pick at least one output format.")
            return

        target = self.output_dir()
        if self.folder_radio.isChecked():
            if not target:
                QtWidgets.QMessageBox.information(
                    self, APP_NAME,
                    "Choose a folder, or switch back to saving beside the original.")
                return
            try:
                Path(target).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                QtWidgets.QMessageBox.critical(
                    self, APP_NAME, "Cannot write to that folder:\n{0}".format(exc))
                return

        for index in indices:
            self.jobs[index].outputs = []
            self.jobs[index].row.set_state("idle", "Queued")

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.clear_button.setEnabled(False)

        self.worker = Worker(self.jobs, indices, self.profile, self.settings, target)
        self.worker.log.connect(self.log)
        self.worker.status.connect(self.status_line.setText)
        self.worker.jobStarted.connect(self._on_job_started)
        self.worker.jobProgress.connect(self._on_job_progress)
        self.worker.jobDone.connect(self._on_job_done)
        self.worker.jobFailed.connect(self._on_job_failed)
        self.worker.jobStopped.connect(self._on_job_stopped)
        self.worker.finished.connect(self._on_all_finished)
        self.worker.start()

    def stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.request_stop()
            self.stop_button.setEnabled(False)
            self.status_line.setText("Stopping after the current step…")
            self.log("Stop requested.")

    def _on_job_started(self, index):
        self.jobs[index].row.set_state("active", "Starting", 0.0)
        self.scroll.ensureWidgetVisible(self.jobs[index].row)

    def _on_job_progress(self, index, message, overall):
        self.jobs[index].row.set_state("active", message, overall)
        self.progress.setValue(int(overall * 1000))

    def _on_job_done(self, index, written, meta):
        job = self.jobs[index]
        job.outputs = written
        summary = "{0} segments".format(meta["segments"])
        if meta.get("speakers"):
            summary += "  ·  {0} speakers".format(meta["speakers"])
        summary += "  ·  double-click to open"
        job.row.set_state("done", summary, 1.0)
        self.progress.setValue(1000)

    def _on_job_failed(self, index, message):
        self.jobs[index].row.set_state("error", message)

    def _on_job_stopped(self, index):
        self.jobs[index].row.set_state("error", "Stopped")

    def _on_all_finished(self):
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.clear_button.setEnabled(True)
        done = sum(1 for j in self.jobs if j.state == "done")
        failed = sum(1 for j in self.jobs if j.state == "error")
        if failed:
            self.status_line.setText(
                "Finished. {0} done, {1} need a look.".format(done, failed))
        else:
            self.status_line.setText(
                "All done. {0} file{1} transcribed.".format(
                    done, "" if done == 1 else "s"))
        self.progress.setValue(0)
        self.refresh_counts()

    # -- misc --------------------------------------------------------------
    def log(self, message):
        import time
        self.log_view.appendPlainText("{0}  {1}".format(
            time.strftime("%H:%M:%S"), message))
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            answer = QtWidgets.QMessageBox.question(
                self, APP_NAME, "A transcription is still running. Quit anyway?")
            if answer != QtWidgets.QMessageBox.Yes:
                event.ignore()
                return
            self.worker.request_stop()
            self.worker.wait(3000)
        self.collect_settings()
        event.accept()


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window_ref = window
        settings = window.settings
        self._original_theme = settings["theme"]

        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(10)

        layout.addWidget(window._label("Appearance", "sectionLabel"))
        theme_row = QtWidgets.QHBoxLayout()
        self.light_radio = QtWidgets.QRadioButton("Light")
        self.dark_radio = QtWidgets.QRadioButton("Dark")
        group = QtWidgets.QButtonGroup(self)
        group.addButton(self.light_radio)
        group.addButton(self.dark_radio)
        (self.dark_radio if settings["theme"] == "dark"
         else self.light_radio).setChecked(True)
        self.light_radio.toggled.connect(self._preview_theme)
        theme_row.addWidget(self.light_radio)
        theme_row.addWidget(self.dark_radio)
        theme_row.addStretch(1)
        layout.addLayout(theme_row)
        layout.addSpacing(8)

        layout.addWidget(window._label(
            "HuggingFace token, needed for speaker labels", "sectionLabel"))
        self.token_edit = QtWidgets.QLineEdit(settings["hf_token"])
        self.token_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        layout.addWidget(self.token_edit)
        hint = window._label(
            "Accept the terms for pyannote/speaker-diarization-3.1 on "
            "huggingface.co first.", "rowStatus")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(8)

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        grid.addWidget(window._label("Language", "sectionLabel"), 0, 0)
        self.language_box = QtWidgets.QComboBox()
        self.language_box.addItems(["auto", "en", "es", "fr", "de", "it", "pt",
                                    "nl", "ja", "zh", "ko", "ru", "uk", "hi", "ar"])
        self.language_box.setCurrentText(settings["language"] or "auto")
        grid.addWidget(self.language_box, 1, 0)

        grid.addWidget(window._label("Whisper model", "sectionLabel"), 0, 1)
        self.model_box = QtWidgets.QComboBox()
        self.model_box.addItems(MODEL_CHOICES)
        self.model_box.setCurrentText(settings["model_override"])
        grid.addWidget(self.model_box, 1, 1)

        grid.addWidget(window._label("Processor", "sectionLabel"), 0, 2)
        self.device_box = QtWidgets.QComboBox()
        self.device_box.addItems(["auto", "cuda", "cpu"])
        self.device_box.setCurrentText(settings["device_override"])
        grid.addWidget(self.device_box, 1, 2)
        layout.addLayout(grid)
        layout.addSpacing(10)

        self.diarize_check = QtWidgets.QCheckBox("Label who is speaking")
        self.diarize_check.setChecked(settings["diarize"])
        layout.addWidget(self.diarize_check)
        self.emotion_check = QtWidgets.QCheckBox(
            "Score valence, arousal and dominance")
        self.emotion_check.setChecked(settings["emotion"])
        layout.addWidget(self.emotion_check)
        layout.addSpacing(14)

        buttons = QtWidgets.QHBoxLayout()
        log_button = QtWidgets.QPushButton("Open log file")
        log_button.setObjectName("quiet")
        log_button.clicked.connect(lambda: window.reveal(log_file()))
        buttons.addWidget(log_button)
        buttons.addStretch(1)

        cancel = QtWidgets.QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)

        save = QtWidgets.QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self.accept)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _preview_theme(self):
        """Switch live so the choice is visible before it is committed."""
        self.window_ref.switch_theme(
            "light" if self.light_radio.isChecked() else "dark")

    def reject(self):
        if self.window_ref.settings["theme"] != self._original_theme:
            self.window_ref.switch_theme(self._original_theme)
        super().reject()

    def accept(self):
        window = self.window_ref
        settings = window.settings
        before = (settings["model_override"], settings["device_override"])

        settings["hf_token"] = self.token_edit.text().strip()
        language = self.language_box.currentText().strip()
        settings["language"] = "" if language == "auto" else language
        settings["model_override"] = self.model_box.currentText()
        settings["device_override"] = self.device_box.currentText()
        settings["diarize"] = self.diarize_check.isChecked()
        settings["emotion"] = self.emotion_check.isChecked()
        settings["theme"] = "light" if self.light_radio.isChecked() else "dark"
        settings.save()

        window.log("Settings saved.")
        if (settings["model_override"], settings["device_override"]) != before:
            window.hw_text.setText("Re-checking what this machine can do…")
            window.hw_meta.setText("")
            window.detect_hardware()
        super().accept()


def launch(initial_files=()):
    app = QtWidgets.QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)

    icon_path = Path(__file__).resolve().parent.parent / "revolv.ico"
    if getattr(sys, "frozen", False):
        icon_path = Path(sys._MEIPASS) / "revolv.ico"
    if icon_path.exists():
        app.setWindowIcon(QtGui.QIcon(str(icon_path)))

    window = MainWindow(initial_files)
    window.show()
    return app.exec()


##############################################################################
# was legacy/main.py
##############################################################################

# The __main__ guard below belonged to the original entry point; running this
# archival file is not supported, see the module docstring.
"""Entry point for Revolv Transcriber.

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
    `"Revolv Transcriber.exe" --selftest [audio file]` walks the whole pipeline
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

        if clip is None:
            say("no audio file given, so stopping after the import and probe checks")
            say("PASS")
            return 0

        transcriber = Transcriber(
            profile, hf_token=settings["hf_token"], language="en",
            diarize=settings["diarize"], emotion=settings["emotion"],
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
                            ["json", "txt", "srt", "csv"])
        for path in written:
            say("wrote {0} ({1} bytes)".format(path, path.stat().st_size))

        if segments:
            say("first line: " + segments[0].get("text", "")[:80])
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
                "Revolv Transcriber failed to start",
                0x10,  # MB_ICONERROR
            )
        except Exception:
            pass
        return 1

    return launch(files) or 0


if __name__ == "__main__":
    sys.exit(main())
