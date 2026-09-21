# Audit delta — 2026-09-21

Milestone A of `docs/MELODY_PRD.md`, run on the owner's machine
(`D:\Kaden\Python\Revolv`, branch `interpret-phase1` from `main` at 1a469b1).
This file records only what differed from section 1 of the PRD; everything not
listed here matched the code as described.

## Selftest

`.\.venv\Scripts\python.exe main.py --selftest` (no clip): **PASS**.
torch 2.11.0+cu128, CUDA available, NVIDIA GeForce RTX 5060 Ti, 15.9 GB VRAM,
profile large-v3 / float16 / batch 16. Two pre-existing warnings, both already
known: triton is absent (flop counting only) and torchcodec's DLLs do not load
(the pipeline deliberately feeds pyannote in-memory waveforms to avoid it).

## Deltas against PRD section 1

1. **Working tree was clean.** The eight files the PRD saw as modified from a
   non-Windows mount show no change here; `git status` reports only the
   untracked `MELODY_PRD.md` and `docs/`. Line endings in the worktree are LF
   everywhere except `revolv/prosody.py` and `revolv/stance.py` (CRLF), which
   this build does not touch. New files are written LF.
2. **The PRD exists twice**, at the repo root and as `docs/MELODY_PRD.md`,
   byte-identical. The `docs/` copy is committed as the working spec; the root
   copy is left untracked for the owner to keep or remove.
3. **Python is 3.13.14** as stated; `pytest`, `jsonschema`, `send2trash` and
   `sounddevice` are absent from `.venv` as stated, and `PyYAML`, `nltk`,
   `requests`, `psutil` and `av` are present.
4. Everything else in the section 1 table was verified by reading
   `README.md`, `revolv/analysis.py`, `revolv/writers.py`, `revolv/gui.py`,
   `revolv/config.py`, `revolv/pipeline.py`, `revolv/prosody.py`,
   `revolv/audio.py`, `revolv/hardware.py`, `revolv/theme.py` and `main.py`
   on 2026-09-21 and matched: entry points, signatures, the `.analysis.json`
   travelling only with `md`+`json`, 0-based turn indexes, per-turn moments,
   the absence of any interpretation code, and the log already carrying source
   file names (D10).

## Milestone plan

The milestone list in PRD section 9 is adopted unchanged, sizes included, with
one note: the parts of M9 and M10 that need a running local model server, and
the parts of M5 that need eyes on a screen, are built and covered by tests
with a fake provider / offscreen Qt, and their on-hardware confirmation is
left on the release checklist for the owner.

## Owner go-ahead

The task brief for this build said to proceed and flag open points at the end
rather than stop, so the go-ahead the PRD asks for here is taken from that
brief. The section 12 decisions are recorded in `docs/DECISIONS.md` with the
PRD's own recommendations adopted; each is flagged for the owner's review.
