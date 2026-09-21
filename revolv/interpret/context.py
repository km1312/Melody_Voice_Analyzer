"""The per-recording context file: `<name>.context.json`.

Everything in it is optional by design (product principle 6: designed for an
empty notes pane). An untouched context window still yields a valid file,
and interpretation runs with every field empty.

This is the one derived file that is edited in place rather than written
through `unique_path`, so `save` keeps the previous version as a `.bak`
first. Validation returns plain-words errors, never exceptions, because the
window shows them to a person.
"""

import json
import shutil
from pathlib import Path

SCHEMA_VERSION = "1.0"

MEETING_TYPES = [
    ("investor_pitch", "Investor pitch"),
    ("sales_discovery", "Sales discovery"),
    ("negotiation", "Negotiation"),
    ("one_on_one", "One-on-one"),
    ("job_interview", "Job interview"),
    ("user_research", "User research"),
    ("team_decision", "Team decision"),
    ("other", "Other"),
]
MEETING_TYPE_KEYS = [key for key, _ in MEETING_TYPES]
MEETING_TYPE_LABELS = dict(MEETING_TYPES)

CONSENT_ANSWERS = ("yes", "no", "not_sure")


def default_context():
    return {
        "schema_version": SCHEMA_VERSION,
        "meeting_type": "other",
        "goal": "",
        "me": None,
        "speaker_names": {},
        "important_topics": [],
        "notes": "",
        "consent": {"all_parties_knew": "not_sure", "cloud_ok": False},
    }


def validate(context):
    """Plain-words problems with `context`, or an empty list."""
    problems = []
    if not isinstance(context, dict):
        return ["The context file is not a JSON object."]
    meeting = context.get("meeting_type", "other")
    if meeting not in MEETING_TYPE_KEYS:
        problems.append(
            "Unknown meeting type {0!r}; expected one of {1}.".format(
                meeting, ", ".join(MEETING_TYPE_KEYS)))
    if not isinstance(context.get("goal", ""), str):
        problems.append("The goal must be text.")
    me = context.get("me")
    if me is not None and not isinstance(me, str):
        problems.append("'me' must be a speaker label or null.")
    names = context.get("speaker_names", {})
    if not isinstance(names, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in names.items()):
        problems.append("Speaker names must map labels to names.")
    topics = context.get("important_topics", [])
    if not isinstance(topics, list) or not all(
            isinstance(t, str) for t in topics):
        problems.append("Important topics must be a list of topic ids.")
    if not isinstance(context.get("notes", ""), str):
        problems.append("Notes must be text.")
    consent = context.get("consent", {})
    if not isinstance(consent, dict):
        problems.append("Consent must be an object.")
    else:
        answer = consent.get("all_parties_knew", "not_sure")
        if answer not in CONSENT_ANSWERS:
            problems.append(
                "The consent answer must be one of yes, no or not_sure.")
        if not isinstance(consent.get("cloud_ok", False), bool):
            problems.append("cloud_ok must be true or false.")
    return problems


def merged(stored):
    """`stored` over the defaults, keeping unknown keys out."""
    base = default_context()
    if not isinstance(stored, dict):
        return base
    for key in list(base):
        if key not in stored:
            continue
        if key == "consent" and isinstance(stored[key], dict):
            base["consent"].update({
                k: stored[key][k] for k in ("all_parties_knew", "cloud_ok")
                if k in stored[key]})
        else:
            base[key] = stored[key]
    base["schema_version"] = SCHEMA_VERSION
    return base


def context_path(json_path) -> Path:
    """`call.json` (or `call.mp4`) -> `call.context.json` beside it."""
    path = Path(json_path)
    return path.with_name(path.stem + ".context.json")


def load(path):
    """The context at `path`, merged over defaults. Missing file: defaults."""
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as f:
            stored = json.load(f)
    except FileNotFoundError:
        return default_context()
    except (json.JSONDecodeError, OSError):
        return default_context()
    return merged(stored)


def save(context, path):
    """Validate and write `context`; keep the previous file as `.bak`.

    Returns the list of validation problems; nothing is written unless it is
    empty.
    """
    problems = validate(context)
    if problems:
        return problems
    path = Path(path)
    if path.exists():
        try:
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        except OSError:
            pass
    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged(context), f, indent=2, ensure_ascii=False)
    return []
