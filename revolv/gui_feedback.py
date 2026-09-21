"""Feedback controls on insight cards, and the deferred outcome ask.

One click each, undoable by clicking again (FR-20). Bad evidence opens a
small menu of the four reasons. Everything lands in the local store and
nothing but enums travels: the claim text stays in the insights file.
"""

from PySide6 import QtWidgets
from PySide6.QtCore import Qt

from .store import BAD_REASONS, call_id_for

BAD_REASON_LABELS = {
    "wrong_speaker": "Wrong speaker",
    "wrong_quote": "Wrong quote",
    "wrong_moment": "Wrong moment",
    "other": "Other",
}


def _call_id(data):
    source = data.media_path or (data.out_dir / data.stem)
    return call_id_for(source)


def attach_feedback_buttons(card, store, data):
    """Add Useful / Not useful / Bad evidence to a card's feedback row."""
    insight = card.insight
    key = insight.get("key") or insight.get("id") or ""
    call_id = _call_id(data)
    run_id = ((data.insights or {}).get("run") or {}).get("run_id")
    store.record_call(call_id, source_path=data.media_path
                      or (data.out_dir / data.stem))

    existing = store.feedback_for(call_id).get(key)

    buttons = {}

    def refresh(selected_kind):
        for kind, button in buttons.items():
            button.setChecked(kind == selected_kind)

    def toggle(kind, bad_reason=None):
        current = store.feedback_for(call_id).get(key)
        if current is not None and current[0] == kind and bad_reason is None:
            store.undo_feedback(key, call_id)   # one click, undoable
            refresh(None)
            return
        store.add_feedback(key, call_id, run_id, kind, bad_reason)
        refresh(kind)

    for kind, label in (("useful", "Useful"), ("not_useful", "Not useful")):
        button = QtWidgets.QPushButton(label)
        button.setObjectName("feedback")
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(lambda _=False, k=kind: toggle(k))
        buttons[kind] = button
        card.feedback_row.addWidget(button)

    bad = QtWidgets.QPushButton("Bad evidence")
    bad.setObjectName("feedback")
    bad.setCheckable(True)
    bad.setCursor(Qt.PointingHandCursor)
    menu = QtWidgets.QMenu(bad)
    for reason in BAD_REASONS:
        action = menu.addAction(BAD_REASON_LABELS[reason])
        action.triggered.connect(
            lambda _=False, r=reason: toggle("bad_evidence", r))
    bad.setMenu(menu)
    buttons["bad_evidence"] = bad
    card.feedback_row.addWidget(bad)
    card.feedback_row.addStretch(1)

    if existing is not None:
        refresh(existing[0])
    card.feedback_buttons = buttons
    return buttons


class OutcomeDialog(QtWidgets.QDialog):
    """'Did this turn out to be real?' for one reading (FR-21)."""

    def __init__(self, claim, parent=None):
        super().__init__(parent)
        self.setWindowTitle("A reading from last week")
        self.answer = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 20)
        layout.setSpacing(12)
        lead = QtWidgets.QLabel("A while ago Melody suggested:")
        lead.setObjectName("sectionLabel")
        layout.addWidget(lead)
        text = QtWidgets.QLabel('"{0}"'.format(claim))
        text.setWordWrap(True)
        layout.addWidget(text)
        question = QtWidgets.QLabel("Did this turn out to be real?")
        layout.addWidget(question)
        row = QtWidgets.QHBoxLayout()
        for label, answer in (("Yes", "yes"), ("No", "no"),
                              ("Still don't know", "unknown")):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(
                lambda _=False, a=answer: self._pick(a))
            row.addWidget(button)
        layout.addLayout(row)

    def _pick(self, answer):
        self.answer = answer
        self.accept()


def ask_pending_outcomes(parent, store, data, limit=2):
    """On opening results: ask about this call's readings that have come of
    age (seven days, FR-21), one dialog each, marking asked-at so nothing is
    asked twice in a week. The same-named-person trigger passes other calls'
    ids to `pending_outcomes(call_ids=...)` when a caller knows the names."""
    call_id = _call_id(data)
    due = [d for d in store.pending_outcomes()
           if d["call_id"] == call_id]
    if not due:
        return 0
    claims = {i.get("key"): i.get("claim", "")
              for i in (data.insights or {}).get("insights") or []}
    asked = 0
    for item in due[:limit]:
        claim = claims.get(item["insight_key"])
        if not claim:
            continue
        store.mark_asked(item["insight_key"], call_id)
        dialog = OutcomeDialog(claim, parent)
        dialog.exec()
        if dialog.answer:
            store.answer_outcome(item["insight_key"], call_id, dialog.answer)
        asked += 1
    return asked
