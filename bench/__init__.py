"""The benchmark harness (PRD section 10).

Runs providers, prompt versions and input variants over a fixed set of
calls and reports the same metrics every time. Nothing here is a second
implementation: packs come from `revolv.interpret.pack`, completions from
the app's providers, and every response goes through `revolv.interpret
.verify` before it counts.

Calls, raw outputs and reports live outside git, under %MELODY_BENCH_DIR%.
Reports carry ids and numbers only; raw outputs (which contain call text)
stay in the runs folder.
"""

import os
from pathlib import Path


def bench_dir():
    root = os.environ.get("MELODY_BENCH_DIR")
    if not root:
        raise SystemExit(
            "Set MELODY_BENCH_DIR to a folder outside the repository; it "
            "will hold calls/, runs/ and reports/.")
    return Path(root)
