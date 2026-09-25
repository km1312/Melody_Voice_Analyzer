"""Gold labels: a template, and a small CLI to label moments listening.

    python -m bench.gold <call_dir>

walks the call's moments, shows each preview, optionally plays the turn
(when call audio sits beside the files as call.wav/mp3/...), and records
real / not_real / unknown into gold.json, alongside the owner's hand list
of action items.
"""

import json
import sys
from pathlib import Path

TEMPLATE = {
    "action_items": [
        {"task": "what the owner wrote down themselves",
         "turn_ids": ["T000"]},
    ],
    "readings": [
        {"turn_ids": ["T000"], "label": "real",
         "note": "labels are real, not_real or unknown"},
    ],
    "moments": [],
}


def write_template(call_dir):
    path = Path(call_dir) / "gold.json"
    if not path.exists():
        with open(path, "w", encoding="utf-8") as f:
            json.dump(TEMPLATE, f, indent=2)
    return path


def _player_for(call_dir):
    from revolv.config import MEDIA_EXTENSIONS
    from revolv.player import Player

    for suffix in sorted(MEDIA_EXTENSIONS):
        media = Path(call_dir) / ("call" + suffix)
        if media.exists():
            player = Player(str(media))
            player.load_sync()
            return player if player.available else None
    return None


def label_moments(call_dir, ask=input, say=print):
    call_dir = Path(call_dir)
    with open(call_dir / "call.analysis.json", encoding="utf-8") as f:
        report = json.load(f)
    path = write_template(call_dir)
    with open(path, encoding="utf-8") as f:
        gold = json.load(f)
    done = {tuple(m.get("turn_ids", [])) for m in gold.get("moments") or []}

    player = _player_for(call_dir)
    for position, moment in enumerate(report.get("moments") or [], 1):
        tid = "T{0:03d}".format(moment["turn"] + 1)
        if (tid,) in done:
            continue
        turn = report["turns"][moment["turn"]]
        say("\n[{0}] {1} {2}".format(tid, moment["speaker"],
                                     "; ".join(moment["observations"])))
        say('    "{0}..."'.format(moment.get("preview", "")))
        while True:
            answer = ask("real / not_real / unknown / play / quit? ") \
                .strip().lower()
            if answer == "play" and player is not None:
                player.play(int(float(turn["start"]) * 1000) - 1500,
                            int(float(turn["end"]) * 1000))
                continue
            if answer == "quit":
                _save(path, gold)
                return gold
            if answer in ("real", "not_real", "unknown"):
                gold.setdefault("moments", []).append(
                    {"turn_ids": [tid], "label": answer})
                break
    _save(path, gold)
    return gold


def _save(path, gold):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(gold, f, indent=2)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    label_moments(sys.argv[1])
