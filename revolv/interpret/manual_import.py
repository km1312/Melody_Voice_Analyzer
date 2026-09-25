"""Turn a model's reply into `.insights.json` and `.notes.md` (FR-6, FR-9).

One code path serves the Import box, the CLI and the runner: parse and
schema-check the reply, run the verifier, assemble the insights document of
PRD 7.3 with its run record, and write both files through `unique_path` so a
second run sits beside the first rather than over it.
"""

import datetime
import json
import secrets
from pathlib import Path

from .. import safelog
from ..writers import unique_path
from . import verify as verify_module
from . import view as view_module
from .context import default_context
from .pack import prompt_sha256, _read_template

SCHEMA_VERSION = "1.0"


class ImportResult:
    def __init__(self, problems=(), insights_path=None, notes_path=None,
                 document=None):
        self.problems = list(problems)
        self.insights_path = insights_path
        self.notes_path = notes_path
        self.document = document

    @property
    def kept(self):
        return len((self.document or {}).get("insights") or [])

    @property
    def dropped(self):
        return len((self.document or {}).get("dropped") or [])


def new_run_id():
    stamp = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    return "{0}_{1}".format(stamp, secrets.token_hex(2))


def run_record(provider="manual", model="", mode="single_pass", params=None,
               seconds=0.0, tokens_in=None, tokens_out=None, context=None):
    version = _read_template("brief.md")[0]
    return {
        "run_id": new_run_id(),
        "provider": provider,
        "model": model,
        "mode": mode,
        "prompt_version": version,
        "prompt_sha256": prompt_sha256(context),
        "params": params or {},
        "seconds": round(seconds, 2),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }


def assemble_document(result, view, meta, context, run):
    """The PRD 7.3 insights document from a VerifyResult."""
    report = meta.get("analysis") or {}
    source_path = Path(meta.get("source", ""))
    return {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "media": source_path.name,
            "media_seconds": meta.get("media_seconds"),
            "segments_json": source_path.stem + ".json",
            "analysis_json": source_path.stem + ".analysis.json",
            "prosody": any(t.get("prosody")
                           for t in report.get("turns") or []),
        },
        "run": run,
        "context": context or {},
        "topics": result.topics,
        "notes": result.notes,
        "speakers": result.speakers,
        "insights": result.kept,
        "so_what": result.so_what,
        "dropped": result.dropped,
        "verifier": result.summary(),
    }


def _mmss(ms):
    seconds = max(int(ms / 1000), 0)
    return "{0:02d}:{1:02d}".format(seconds // 60, seconds % 60)


def _named(label, names):
    return names.get(label, label)


def render_notes_md(document, view, context=None):
    """The Notes tab as Markdown, for pasting elsewhere (FR-10)."""
    names = (context or {}).get("speaker_names") or {}
    notes = document.get("notes") or {}

    def stamp(turn_ids):
        for tid in turn_ids or []:
            turn = view.turns.get(tid)
            if turn:
                return " ({0})".format(_mmss(turn["start_ms"]))
        return ""

    out = ["# Notes - {0}".format(
        Path(document["source"].get("media") or "recording").stem), ""]
    if notes.get("summary"):
        out.extend([notes["summary"], ""])
    sections = [
        ("Decisions", notes.get("decisions"), "text"),
        ("Action items", notes.get("action_items"), "task"),
        ("Open questions", notes.get("open_questions"), "text"),
        ("Key numbers", notes.get("key_numbers"), "text"),
    ]
    for title, lines, key in sections:
        if not lines:
            continue
        out.append("## {0}".format(title))
        for line in lines:
            if key == "task":
                owner = _named(line.get("owner", ""), names)
                due = line.get("due") or ""
                item = "- [ ] {0}{1}{2}{3}".format(
                    owner + ": " if owner else "",
                    line.get("task", ""),
                    " - due {0}".format(due) if due else "",
                    stamp(line.get("turn_ids")))
            else:
                item = "- {0}{1}".format(line.get("text", ""),
                                         stamp(line.get("turn_ids")))
            out.append(item)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def import_response(segments, meta, out_dir, stem, response_text,
                    context=None, run=None, log=None,
                    max_per_call=8, max_per_speaker=3):
    """Verify `response_text` and write the two files. Never overwrites."""
    context = context if context is not None else default_context()
    report = meta.get("analysis")
    if not report:
        return ImportResult(problems=[
            "There is no analysis for this recording, so the response "
            "cannot be checked against it."])

    view = view_module.build(report, segments, meta)
    draft, problems = verify_module.parse_response(response_text)
    if problems:
        return ImportResult(problems=problems)

    result = verify_module.verify(draft, view, report, context=context,
                                  max_per_call=max_per_call,
                                  max_per_speaker=max_per_speaker)
    if run is None:
        run = run_record(context=context)
    document = assemble_document(result, view, meta, context, run)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    insights_path = unique_path(out_dir / (stem + ".insights.json"))
    with open(insights_path, "w", encoding="utf-8") as f:
        json.dump(document, f, indent=2, ensure_ascii=False)
    notes_path = unique_path(out_dir / (stem + ".notes.md"))
    with open(notes_path, "w", encoding="utf-8") as f:
        f.write(render_notes_md(document, view, context))

    summary = result.summary()
    safelog.log_event("insights_written", emit=log,
                      run=run["run_id"], proposed=summary["proposed"],
                      kept=summary["kept"],
                      dropped=len(document["dropped"]))
    return ImportResult(insights_path=insights_path, notes_path=notes_path,
                        document=document)
