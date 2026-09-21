"""Interpretation-layer self-checks for `--selftest` (M11.2).

Everything runs on synthetic data built right here, in a temp folder, with
no models and no network: the net guard, a pack build, the verifier's core
guarantees and the store. A windowed bundle has no console, so failures
must surface as log lines and a nonzero exit rather than a traceback box.
"""

import json
import shutil
import tempfile
from pathlib import Path


def _segments():
    """Two speakers, 13 scored turns each, wordy enough for baselines."""
    segments = []
    cursor = 1.0
    text = ("the plan for the quarter looks steady and the team agrees "
            "on the numbers again").split()
    for index in range(26):
        speaker = "SPEAKER_00" if index % 2 == 0 else "SPEAKER_01"
        start = cursor + (6.0 if index == 21 else 0.5)
        words = []
        t = start
        for w_index, word in enumerate(text):
            item = {"word": word, "start": round(t, 2),
                    "end": round(t + 0.3, 2)}
            if index == 21 and w_index in (3, 7, 11):
                item = {"word": "um", "start": round(t, 2),
                        "end": round(t + 0.3, 2), "kind": "filler"}
            words.append(item)
            t += 0.36
        segments.append({
            "start": start, "end": round(t, 2), "speaker": speaker,
            "text": " ".join(w["word"] for w in words), "words": words,
            "pacing": {"word_count": len(words),
                       "duration_seconds": round(t - start, 2),
                       "wpm": 160.0},
            "emotion": {"arousal": 0.2 if index == 21 else
                        0.45 + (index % 5) * 0.005,
                        "valence": 0.5, "dominance": 0.5,
                        "measured_over": [start, round(t, 2)]},
        })
        cursor = t
    return segments


def run(say):
    """Returns True when every check passed; `say` gets one line each."""
    from . import analysis, netguard, safelog
    from .interpret import verify as verify_module
    from .interpret import view as view_module
    from .interpret.pack import build_pack
    from .store import Store

    ok = True

    def check(name, passed, detail=""):
        nonlocal ok
        ok = ok and passed
        say("interpret {0}: {1}{2}".format(
            name, "ok" if passed else "FAILED",
            " ({0})".format(detail) if detail else ""))

    # Net guard: loopback passes, a LAN literal does not.
    try:
        netguard.assert_loopback("http://127.0.0.1:8080/v1")
        blocked = False
        try:
            netguard.assert_loopback("http://192.168.1.10:8080/v1")
        except netguard.EgressError:
            blocked = True
        check("netguard", blocked)
    except Exception as exc:
        check("netguard", False, str(exc))

    # Safe logging refuses prose.
    try:
        safelog.log_event("selftest", turns=26)
        refused = False
        try:
            safelog.log_event("selftest", note="free text with spaces")
        except safelog.UnsafeLogValue:
            refused = True
        check("safelog", refused)
    except Exception as exc:
        check("safelog", False, str(exc))

    temp = Path(tempfile.mkdtemp(prefix="melody_selfcheck_"))
    try:
        segments = _segments()
        meta = {"source": str(temp / "check.wav"), "media_seconds": 320.0,
                "segments": len(segments), "speakers": 2}
        meta["analysis"] = analysis.analyse(segments, meta)
        report = meta["analysis"]

        # Pack build: files complete, no open slots in the filled ones.
        try:
            pack_dir = build_pack(segments, dict(meta, numbers_file=False),
                                  temp, "check")
            names = {p.name for p in pack_dir.iterdir()}
            wanted = {"system.txt", "single_pass.txt", "view.txt",
                      "pack.json", "README.txt"}
            filled = all("{{" not in (pack_dir / n).read_text(
                encoding="utf-8") for n in ("system.txt", "single_pass.txt"))
            check("pack", wanted <= names and filled)
        except Exception as exc:
            check("pack", False, str(exc))

        # Verifier: a real quote survives, an invented one does not.
        try:
            view = view_module.build(report, segments, meta)
            moment = next((m for m, entry in view.moments.items()
                           if view.turns[entry["turn_id"]]["speaker"]
                           == "SPEAKER_01"), None)
            tid = view.moments[moment]["turn_id"] if moment else "T022"
            quote = " ".join(view.turns[tid]["text"].split()[:6])
            reading = {
                "layer": "unsaid", "speaker": "SPEAKER_01",
                "claim": "May be worth checking.",
                "likelihood": "roughly even chance",
                "evidence_confidence": "low",
                "evidence": [
                    {"turn_id": tid, "quote": quote, "channel": "lexical",
                     "moment_ids": [], "description": "wording"},
                    {"turn_id": tid, "quote": "", "channel": "timing",
                     "moment_ids": [], "description": "slow reply"}],
                "alternatives": ["Thinking time"],
                "follow_up": "Worth asking?"}
            bad = dict(reading,
                       evidence=[dict(reading["evidence"][0],
                                      quote="the purple elephant")]
                       + [reading["evidence"][1]])
            draft = {"topics": [], "notes": {
                "summary": "", "decisions": [], "action_items": [],
                "open_questions": [], "key_numbers": []},
                "speakers": [], "insights": [reading, bad]}
            result = verify_module.verify(draft, view, report)
            check("verifier",
                  len(result.kept) == 1
                  and result.dropped_by_reason.get("quote_mismatch") == 1)
        except Exception as exc:
            check("verifier", False, str(exc))

        # The store opens, takes a row, exports, closes.
        try:
            store = Store(temp / "melody.db")
            store.record_call("selfcheck")
            store.add_feedback("k", "selfcheck", "r", "useful")
            store.export_csv(temp / "export.csv")
            store.close()
            header = (temp / "export.csv").read_text(
                encoding="utf-8").splitlines()[0]
            check("store", "layer" in header and "claim" not in header)
        except Exception as exc:
            check("store", False, str(exc))
    finally:
        shutil.rmtree(temp, ignore_errors=True)

    return ok
