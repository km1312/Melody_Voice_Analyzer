"""The local store: feedback, outcomes, self labels, the me-baseline (7.5).

One SQLite file beside settings.json. Everything in it is deliberately
content-free: layers, channels, likelihood words, enum answers, numeric
features, dates, ids and file paths — never a quote, a claim, a name or a
goal. That is what makes the CSV export shareable as evaluation data
(FR-23) without shipping a word of any call.

`insight_meta` carries one row per kept reading so usefulness can be sliced
by layer, channel, model and prompt version later. The `source_path` column
on `calls` is the one addition to the PRD 7.5 schema: it lets the deferred
outcome check find a call's insights file again without holding any content
(a path is the user's own label for their own file, per D10).
"""

import csv
import datetime
import hashlib
import json
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

FEEDBACK_KINDS = ("useful", "not_useful", "bad_evidence")
BAD_REASONS = ("wrong_speaker", "wrong_quote", "wrong_moment", "other")
OUTCOME_ANSWERS = ("yes", "no", "unknown")
SELF_ANSWERS = ("yes", "no", "not_sure")

OUTCOME_DELAY_DAYS = 7
OUTCOME_REASK_DAYS = 7

EXPORT_COLUMNS = ["layer", "channels", "likelihood", "evidence_confidence",
                  "provider", "model", "prompt_version", "feedback",
                  "bad_reason", "outcome"]

_TABLES = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS calls (
    call_id TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,
    media_seconds REAL,
    me_label TEXT,
    source_path TEXT
);
CREATE TABLE IF NOT EXISTS insight_feedback (
    insight_key TEXT NOT NULL,
    call_id TEXT NOT NULL,
    run_id TEXT,
    kind TEXT NOT NULL,
    bad_reason TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outcomes (
    insight_key TEXT NOT NULL,
    call_id TEXT NOT NULL,
    asked_at TEXT,
    answer TEXT,
    answered_at TEXT,
    PRIMARY KEY (insight_key, call_id)
);
CREATE TABLE IF NOT EXISTS self_labels (
    call_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    answer TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (call_id, turn_id)
);
CREATE TABLE IF NOT EXISTS me_baseline (
    call_id TEXT PRIMARY KEY,
    call_date TEXT NOT NULL,
    features_json TEXT NOT NULL,
    minutes_spoken REAL
);
CREATE TABLE IF NOT EXISTS insight_meta (
    insight_key TEXT NOT NULL,
    call_id TEXT NOT NULL,
    run_id TEXT,
    layer TEXT,
    channels TEXT,
    likelihood TEXT,
    evidence_confidence TEXT,
    provider TEXT,
    model TEXT,
    prompt_version TEXT,
    PRIMARY KEY (insight_key, call_id, run_id)
);
"""


def call_id_for(source_path):
    """sha1 of the source path and its size (0 when the file is gone)."""
    path = Path(source_path)
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    raw = "{0}|{1}".format(str(path), size)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, path=None):
        if path is None:
            from .config import app_data_dir

            path = app_data_dir() / "melody.db"
        self.path = Path(path)
        self.db = sqlite3.connect(str(self.path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_TABLES)
        row = self.db.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            self.db.execute("INSERT INTO schema_version VALUES (?)",
                            (SCHEMA_VERSION,))
        self.db.commit()

    def close(self):
        self.db.close()

    # -- calls ---------------------------------------------------------------
    def record_call(self, call_id, media_seconds=None, me_label=None,
                    source_path=None):
        self.db.execute(
            "INSERT INTO calls (call_id, first_seen, media_seconds, me_label,"
            " source_path) VALUES (?, ?, ?, ?, ?) ON CONFLICT(call_id) DO "
            "UPDATE SET media_seconds=COALESCE(excluded.media_seconds, "
            "media_seconds), me_label=COALESCE(excluded.me_label, me_label), "
            "source_path=COALESCE(excluded.source_path, source_path)",
            (call_id, _now(), media_seconds, me_label,
             str(source_path) if source_path else None))
        self.db.commit()

    def call(self, call_id):
        return self.db.execute("SELECT * FROM calls WHERE call_id=?",
                               (call_id,)).fetchone()

    # -- feedback (FR-20) ----------------------------------------------------
    def add_feedback(self, insight_key, call_id, run_id, kind,
                     bad_reason=None):
        if kind not in FEEDBACK_KINDS:
            raise ValueError("unknown feedback kind {0!r}".format(kind))
        if bad_reason is not None and bad_reason not in BAD_REASONS:
            raise ValueError("unknown bad_evidence reason {0!r}".format(
                bad_reason))
        self.db.execute(
            "DELETE FROM insight_feedback WHERE insight_key=? AND call_id=?",
            (insight_key, call_id))
        self.db.execute(
            "INSERT INTO insight_feedback VALUES (?, ?, ?, ?, ?, ?)",
            (insight_key, call_id, run_id, kind, bad_reason, _now()))
        self.db.commit()

    def undo_feedback(self, insight_key, call_id):
        self.db.execute(
            "DELETE FROM insight_feedback WHERE insight_key=? AND call_id=?",
            (insight_key, call_id))
        self.db.commit()

    def feedback_for(self, call_id):
        rows = self.db.execute(
            "SELECT insight_key, kind, bad_reason FROM insight_feedback "
            "WHERE call_id=?", (call_id,)).fetchall()
        return {r["insight_key"]: (r["kind"], r["bad_reason"]) for r in rows}

    # -- insight meta --------------------------------------------------------
    def record_insights(self, document, call_id):
        run = document.get("run") or {}
        for insight in document.get("insights") or []:
            self.db.execute(
                "INSERT OR REPLACE INTO insight_meta VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (insight.get("key"), call_id, run.get("run_id"),
                 insight.get("layer"),
                 ",".join(insight.get("channels") or []),
                 insight.get("likelihood"),
                 insight.get("evidence_confidence"),
                 run.get("provider"), run.get("model"),
                 run.get("prompt_version")))
        self.db.commit()

    # -- outcomes (FR-21) ----------------------------------------------------
    def pending_outcomes(self, call_ids=None, now=None):
        """Readings due an outcome question: old enough (or explicitly named
        through `call_ids`, the same-person trigger), unanswered, and not
        asked within the last week."""
        now = now or datetime.datetime.now()
        cutoff_age = (now - datetime.timedelta(days=OUTCOME_DELAY_DAYS)) \
            .isoformat(timespec="seconds")
        cutoff_ask = (now - datetime.timedelta(days=OUTCOME_REASK_DAYS)) \
            .isoformat(timespec="seconds")
        rows = self.db.execute(
            "SELECT m.insight_key, m.call_id, c.source_path, o.asked_at "
            "FROM insight_meta m JOIN calls c ON c.call_id = m.call_id "
            "LEFT JOIN outcomes o ON o.insight_key = m.insight_key "
            "AND o.call_id = m.call_id WHERE o.answer IS NULL").fetchall()
        due = []
        for row in rows:
            call = self.call(row["call_id"])
            triggered = (call["first_seen"] <= cutoff_age
                         or (call_ids and row["call_id"] in call_ids))
            asked_recently = (row["asked_at"] is not None
                              and row["asked_at"] > cutoff_ask)
            if triggered and not asked_recently:
                due.append({"insight_key": row["insight_key"],
                            "call_id": row["call_id"],
                            "source_path": row["source_path"]})
        return due

    def mark_asked(self, insight_key, call_id, now=None):
        asked = (now or datetime.datetime.now()).isoformat(timespec="seconds")
        self.db.execute(
            "INSERT INTO outcomes (insight_key, call_id, asked_at) VALUES "
            "(?, ?, ?) ON CONFLICT(insight_key, call_id) DO UPDATE SET "
            "asked_at=excluded.asked_at", (insight_key, call_id, asked))
        self.db.commit()

    def answer_outcome(self, insight_key, call_id, answer):
        if answer not in OUTCOME_ANSWERS:
            raise ValueError("unknown outcome answer {0!r}".format(answer))
        self.db.execute(
            "INSERT INTO outcomes (insight_key, call_id, asked_at, answer, "
            "answered_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(insight_key, "
            "call_id) DO UPDATE SET answer=excluded.answer, "
            "answered_at=excluded.answered_at",
            (insight_key, call_id, _now(), answer, _now()))
        self.db.commit()

    # -- self labels (FR-22) -------------------------------------------------
    def add_self_label(self, call_id, turn_id, answer):
        if answer not in SELF_ANSWERS:
            raise ValueError("unknown self-label answer {0!r}".format(answer))
        self.db.execute(
            "INSERT OR REPLACE INTO self_labels VALUES (?, ?, ?, ?)",
            (call_id, turn_id, answer, _now()))
        self.db.commit()

    def self_labels_for(self, call_id):
        rows = self.db.execute(
            "SELECT turn_id, answer FROM self_labels WHERE call_id=?",
            (call_id,)).fetchall()
        return {r["turn_id"]: r["answer"] for r in rows}

    # -- the me-baseline (FR-19, PR-10) --------------------------------------
    def add_me_baseline(self, call_id, call_date, features, minutes_spoken):
        for value in features.values():
            if value is not None and not isinstance(value, (int, float)):
                raise ValueError("me_baseline stores numeric features only")
        self.db.execute(
            "INSERT OR REPLACE INTO me_baseline VALUES (?, ?, ?, ?)",
            (call_id, call_date, json.dumps(features), minutes_spoken))
        self.db.commit()

    def me_baseline_rows(self, exclude_call=None):
        rows = self.db.execute(
            "SELECT call_id, call_date, features_json, minutes_spoken "
            "FROM me_baseline ORDER BY call_date").fetchall()
        return [{"call_id": r["call_id"], "call_date": r["call_date"],
                 "features": json.loads(r["features_json"]),
                 "minutes_spoken": r["minutes_spoken"]}
                for r in rows if r["call_id"] != exclude_call]

    def reset_me_baseline(self):
        self.db.execute("DELETE FROM me_baseline")
        self.db.commit()

    # -- export (FR-23) ------------------------------------------------------
    def export_csv(self, path):
        """Content-free rows only: a column whitelist, nothing free-text."""
        rows = self.db.execute(
            "SELECT m.layer, m.channels, m.likelihood, m.evidence_confidence,"
            " m.provider, m.model, m.prompt_version, f.kind AS feedback, "
            "f.bad_reason, o.answer AS outcome FROM insight_meta m "
            "LEFT JOIN insight_feedback f ON f.insight_key = m.insight_key "
            "AND f.call_id = m.call_id "
            "LEFT JOIN outcomes o ON o.insight_key = m.insight_key "
            "AND o.call_id = m.call_id").fetchall()
        path = Path(path)
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(EXPORT_COLUMNS)
            for row in rows:
                writer.writerow([row[c] if row[c] is not None else ""
                                 for c in EXPORT_COLUMNS])
        return path

    # -- delete everything derived (FR-26) -----------------------------------
    def delete_call(self, call_id):
        for table in ("insight_feedback", "outcomes", "self_labels",
                      "me_baseline", "insight_meta", "calls"):
            self.db.execute(
                "DELETE FROM {0} WHERE call_id=?".format(table), (call_id,))
        self.db.commit()
