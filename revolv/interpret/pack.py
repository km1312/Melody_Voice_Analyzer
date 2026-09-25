"""Build the prompt pack: `<name>.prompt/`, ready for any model (FR-5).

The pack is the product's model-agnostic seam. Everything a model needs is
written to disk as plain text — the shared brief with the context and lens
filled in, the numbered view, the single-pass prompt for hand use, the pass
templates for a runner, and the JSON Schemas for every reply shape — so the
same recording can be read by a local server, a frontier model in a browser
tab, or the benchmark harness, and the verifier treats them all alike.

Slot filling fails loudly: an unknown slot in a template, a slot the caller
did not fill, or a filled template with `{{` left in it is a bug, never
something to paper over.
"""

import hashlib
import json
import re
from pathlib import Path

from .. import safelog
from ..writers import unique_path
from . import schema as schema_module
from . import view as view_module
from .context import (MEETING_TYPE_KEYS, MEETING_TYPE_LABELS, default_context)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

_SLOT = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
_VERSION_LINE = re.compile(r"^# version: (?P<version>\S+)\n")

# Slots deliberately left open in the templates a runner fills later.
PASS_TEMPLATE_SLOTS = {
    "pass_b": {"PASS_A_JSON"},
    "pass_c": {"PASS_B_JSON", "PASS_A_OBSERVATIONS_JSON"},
    "pass_d": {"PASS_A_FACTS_AND_TOPICS_JSON",
               "PASS_C_KEPT_WITH_OBSERVATIONS_JSON"},
}

README_TEXT = """How to use this prompt pack by hand

1. Open your model tool. If it has a system or custom-instruction field,
   paste system.txt there; otherwise paste system.txt first, as the start
   of your message.
2. Paste single_pass.txt as the message.
3. Copy the model's whole JSON reply into Melody's Import box (or run
   `python -m revolv.interpret import <name>.json <reply.json>`).

Melody then checks every quote, id and claim in code before anything is
shown; a reply that fails the checks is explained in plain words.

Privacy: pasting these files into a cloud tool sends the transcript off
this machine, under that tool's terms. Only do that for calls marked
cloud_ok in their context file, and prefer an API console under commercial
terms over a consumer chat plan.

The pass_*.txt files are for running the four-pass version by hand or from
a script: A then B then C then D, pasting the earlier pass's JSON into the
marked slot. The single pass is the default and gives the same guarantees;
schemas/ holds the JSON Schema for every reply shape.
"""


class PackError(RuntimeError):
    """A template and its slots disagree; the pack must not be written."""


def _read_template(name):
    """(version, text-without-version-line) for a prompt file."""
    path = PROMPTS_DIR / name
    raw = path.read_text(encoding="utf-8")
    match = _VERSION_LINE.match(raw)
    if not match:
        raise PackError("{0} has no '# version:' line".format(name))
    return match.group("version"), raw[match.end():]


def fill(template, slots, leave=frozenset()):
    """Fill `{{SLOT}}`s. Every provided slot must exist; every slot in the
    template must be provided or listed in `leave`."""
    present = set(_SLOT.findall(template))
    unknown = set(slots) - present
    if unknown:
        raise PackError("Slots not in template: {0}".format(sorted(unknown)))
    missing = present - set(slots) - set(leave)
    if missing:
        raise PackError("Unfilled slots: {0}".format(sorted(missing)))

    def replace(match):
        name = match.group(1)
        return slots[name] if name in slots else match.group(0)

    return _SLOT.sub(replace, template)


def _not_given(value, fallback):
    value = (value or "").strip() if isinstance(value, str) else value
    return value if value else fallback


def render_context_block(context, template=None, guessed=None):
    context = context or default_context()
    if template is None:
        _, template = _read_template("context_block.md")
    names = context.get("speaker_names") or {}
    parts = []
    names_line = ", ".join("{0} is {1}".format(label, name)
                           for label, name in sorted(names.items()))
    if names_line:
        parts.append(names_line)
    # Transcript-derived guesses travel as guesses, never as facts: only for
    # labels the user left unnamed, and worded so the model treats them the
    # way the brief treats every other unproven thing.
    from ..names import merge_with_context

    for label, guess in sorted(merge_with_context(guessed or {},
                                                  names).items()):
        parts.append("{0} may be {1} (guessed from the transcript, "
                     "unconfirmed)".format(label, guess["name"]))
    topics = context.get("important_topics") or []
    return fill(template, {
        "MEETING_TYPE_LABEL": MEETING_TYPE_LABELS.get(
            context.get("meeting_type", "other"), "Other"),
        "GOAL_OR_NOT_GIVEN": _not_given(context.get("goal"), "not given"),
        "ME_LABEL_OR_NOT_IDENTIFIED": _not_given(context.get("me"),
                                                 "not identified"),
        "NAMES_OR_NONE": _not_given("; ".join(parts), "none"),
        "TOPICS_OR_NONE": _not_given(", ".join(topics), "none"),
        "NOTES_OR_NONE": _not_given(context.get("notes"), "none"),
    })


def lens_for(meeting_type):
    key = meeting_type if meeting_type in MEETING_TYPE_KEYS else "other"
    return _read_template("lenses/{0}.md".format(key))[1].strip()


def build_system_prompt(context, guessed=None):
    version, brief = _read_template("brief.md")
    lens = lens_for((context or {}).get("meeting_type", "other"))
    return version, fill(brief, {
        "CONTEXT_BLOCK": render_context_block(context,
                                              guessed=guessed).strip(),
        "LENS_BLOCK": lens,
    })


def prompt_sha256(context=None):
    """Hash over P0, the pass files, the single pass and the lens used, so a
    run record pins exactly what the model was told."""
    hasher = hashlib.sha256()
    for name in ("brief.md", "context_block.md", "pass_a.md", "pass_b.md",
                 "pass_c.md", "pass_d.md", "single_pass.md", "coaching.md"):
        hasher.update(_read_template(name)[1].encode("utf-8"))
    lens_key = (context or {}).get("meeting_type", "other")
    hasher.update(lens_for(lens_key).encode("utf-8"))
    return hasher.hexdigest()


def _sha256_file(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def build_pack(segments, meta, out_dir, stem, context=None, source_paths=(),
               log=None, coaching_slots=None, vocabulary=()):
    """Write `<out_dir>/<stem>.prompt/` and return its path.

    `meta` must carry `analysis`; `source_paths` are the pipeline files whose
    hashes go into pack.json; `coaching_slots` (from `coaching.py`, when a
    me-speaker is set) adds coaching.txt.
    """
    report = meta.get("analysis")
    if not report:
        raise PackError("meta carries no analysis; the pack needs the report")
    context = context or default_context()

    view = view_module.build(report, segments, meta)
    from ..names import guess_speaker_names

    try:
        guessed = guess_speaker_names(report.get("turns") or [], vocabulary)
    except Exception:
        guessed = {}
    version, system_text = build_system_prompt(context, guessed=guessed)
    view_slots = {"NUMBERED_VIEW": view.text}

    files = {"README.txt": README_TEXT,
             "system.txt": system_text,
             "view.txt": view.text}
    _, single = _read_template("single_pass.md")
    files["single_pass.txt"] = fill(single, view_slots)
    _, pass_a = _read_template("pass_a.md")
    files["pass_a.txt"] = fill(pass_a, view_slots)
    for name in ("pass_b", "pass_c", "pass_d"):
        _, template = _read_template(name + ".md")
        leave = PASS_TEMPLATE_SLOTS[name]
        slots = {k: v for k, v in view_slots.items()
                 if k in _SLOT.findall(template)}
        files[name + ".template.txt"] = fill(template, slots, leave=leave)
    if coaching_slots:
        _, coaching = _read_template("coaching.md")
        files["coaching.txt"] = fill(coaching, coaching_slots)

    prosody_present = any(t.get("prosody") for t in report.get("turns") or [])
    token_estimate = (len(system_text) + len(files["single_pass.txt"])) // 4
    pack_meta = {
        "prompt_version": version,
        "prompt_sha256": prompt_sha256(context),
        "meeting_type": context.get("meeting_type", "other"),
        "token_estimate": token_estimate,
        "prosody": bool(prosody_present),
        "sources": {Path(p).name: _sha256_file(p) for p in source_paths
                    if Path(p).exists()},
    }

    pack_dir = unique_path(Path(out_dir) / "{0}.prompt".format(stem))
    pack_dir.mkdir(parents=True)
    (pack_dir / "schemas").mkdir()
    for name, text in files.items():
        with open(pack_dir / name, "w", encoding="utf-8") as f:
            f.write(text)
    for name, schema in schema_module.SCHEMAS.items():
        with open(pack_dir / "schemas" / (name + ".json"), "w",
                  encoding="utf-8") as f:
            json.dump(schema, f, indent=2)
    with open(pack_dir / "pack.json", "w", encoding="utf-8") as f:
        json.dump(pack_meta, f, indent=2)

    safelog.log_event("pack_built", emit=log,
                      turns=len(view.turns), moments=len(view.moments),
                      tokens=token_estimate, prosody=bool(prosody_present),
                      version=version)
    return pack_dir
