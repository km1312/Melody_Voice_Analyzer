# Decisions (PRD section 12)

The build brief said to proceed on best judgement and flag open points at
the end rather than stop, so each decision below adopts the PRD's own
recommendation. **Every row is standing for the owner's review**; changing
one later is cheap, and the "Where it lives" column says what to touch.

| ID | Decision taken | Why | Where it lives |
| --- | --- | --- | --- |
| D1 | **A** — the loopback-only runner ships in Phase 1 | It is local, passes the offline tests, and lets the harness run unattended | `interpret/runner.py`, `providers/openai_compat.py`, `InterpretWorker` in `gui.py` |
| D2 | **Single pass** by default | Until the harness shows multi-pass is more faithful on the default local model | `interpret_mode` in `config.DEFAULTS`; both modes implemented |
| D3 | **Deferred** — no product name chosen | Trademark and domain checks are the owner's call; nothing in the code blocks a rename | `APP_NAME` in `revolv/__init__.py` is the one string |
| D4 | **Advisory** consent line; `cloud_ok` blocking for egress | Matches PR-11; the harness refuses remote/manual-cloud cells without it | `gui_context.py`, `bench/run.py::cloud_blocked` |
| D5 | **8 calls** before the ring | Revisit once self labels accumulate | `me_baseline_min_calls` in `config.DEFAULTS` |
| D6 | **3 per speaker, 8 per call** | Fewer, better readings | `max_insights_per_*` in `config.DEFAULTS`; verifier rule 9 |
| D7 | **Approved list only**: `pytest`, `jsonschema`, `send2trash`, `sounddevice` (D9-A) | Pinned in `requirements-dev.txt`, added to `build.ps1` and the spec | `requirements-dev.txt` |
| D8 | **Rebuild and re-import** for topic re-rank | Keeps FR-3 working in manual mode; a context save with changes rebuilds the pack | `MainWindow._context_saved` |
| D9 | **A** — PyAV decode + `sounddevice` | Smaller bundle, one module owns it, the same decoder writes and reads clips | `revolv/player.py`, `revolv/retention.py` |
| D10 | **Leave as is** — the window log keeps file names | A file name is the user's own label for their own file; PR-4 binds new code only | `safelog.py` guards everything new |

## Deviations from the PRD worth knowing about

1. **`calls.source_path` column** was added to the store schema (7.5 lists
   no such column). It holds a file path — the user's own label, no call
   content — and exists so the deferred outcome check can find a call's
   insights file again. Documented in `store.py`.
2. **The same-named-person outcome trigger (FR-21)** is implemented in the
   store (`pending_outcomes(call_ids=...)`) but not yet wired in the UI:
   the store deliberately holds no names, so the wiring needs the caller to
   compare context files. The seven-day trigger is fully wired.
3. **A second pack build lands at `call (2).prompt`**, not
   `call.prompt (2)`: `unique_path` reads `.prompt` as the suffix. Same
   guarantee, different spelling; the PRD's own conflict note 6 predicted
   the pattern for `.insights.json` and this is the directory analogue.
4. **`apply_offline_env` sets the HF offline flags only once the model
   cache exists** (PR-2's "default on once the cache is complete"),
   detected as a non-empty `models--*` glob in the hub cache. Telemetry is
   off unconditionally.
5. **`no_timing`/`clean` ablations suppress silence lines through a
   renderer override** (`bench/variants.py::render_overrides`) rather than
   by shifting timestamps: shifted turns would no longer match their
   segments and the view's consistency check would refuse them.
6. **The coaching reply** is stored as `<name>.coaching.json` (gitignored,
   removed by delete-derived). The PRD named no file for it.
7. **Speaker facts got their own "Speakers" tab** in the results window;
   the PRD listed the facts (FR-13) without naming their home.
8. **`docs/providers/` checklist template** was seeded now (Phase 2 prep,
   P2-6); no adapter is enabled by it.
