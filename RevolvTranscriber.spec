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
    "crisperwhisper",      # verbatim pass (CrisperWhisper 2.0, transformers backend)
    "penn",                # pitch tracker; ships its config and assets
    "torbi",               # PENN's Viterbi decoder, a compiled extension
    "torchutil",
    "yapecs",
    "accelerate",
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
    "crisperwhisper", "penn", "torbi", "accelerate",
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
    "revolv", "revolv.analysis", "revolv.asr", "revolv.audio", "revolv.config",
    "revolv.gui", "revolv.hardware", "revolv.pipeline", "revolv.prosody",
    "revolv.stance", "revolv.theme", "revolv.verbatim", "revolv.writers",
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
# The trained stance head is data, read by revolv/stance.py from revolv/assets.
datas += [("revolv/assets/stance_head.npz", "revolv/assets")]

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
