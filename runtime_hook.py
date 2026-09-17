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
