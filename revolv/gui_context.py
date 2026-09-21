"""The context window: everything optional, nothing required (FR-1 to FR-4).

Opened from a finished file row. Meeting type, a one-line goal, names per
diarized speaker, free notes, the consent line, and "Which one is you?",
which plays a three-second sample of each speaker so the user can mark
themselves with one click. Like the settings popover, choices apply when the
window closes: closing saves `<name>.context.json` beside the outputs.
"""

import json
from pathlib import Path

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt, Signal

from .interpret import context as context_module

# "Which one is you?" (FR-2): only speakers with this much talk get a sample.
MIN_SAMPLE_SPEECH_SECONDS = 5.0
SAMPLE_SECONDS = 3.0
SAMPLE_LEAD_SECONDS = 1.0


def _touched_by_overlap(turn, events):
    start, end = float(turn["start"]), float(turn["end"])
    for event in events or []:
        if float(event["start"]) < end and start < float(event["end"]):
            return True
    return False


def me_sample_ranges(report):
    """Per speaker, the (start_ms, end_ms) of their sample clip.

    The longest turn of theirs that no overlap event touches, played for
    three seconds starting one second in, so the sample is one voice and not
    the turn's opening breath.
    """
    events = report.get("overlap_events") or []
    ranges = {}
    for label, entry in (report.get("speakers") or {}).items():
        if (entry.get("speech_seconds") or 0) < MIN_SAMPLE_SPEECH_SECONDS:
            continue
        candidates = [t for t in report["turns"] if t["speaker"] == label
                      and not _touched_by_overlap(t, events)]
        if not candidates:
            continue
        turn = max(candidates, key=lambda t: t.get("speech_seconds") or 0)
        begin = float(turn["start"]) + SAMPLE_LEAD_SECONDS
        end = min(begin + SAMPLE_SECONDS, float(turn["end"]))
        if end <= begin:
            begin, end = float(turn["start"]), min(
                float(turn["start"]) + SAMPLE_SECONDS, float(turn["end"]))
        ranges[label] = (round(begin * 1000), round(end * 1000))
    return ranges


def speakers_by_talk_share(report):
    speakers = report.get("speakers") or {}
    return sorted(speakers, key=lambda n: -(speakers[n].get("talk_share") or 0))


class ContextWindow(QtWidgets.QWidget):
    """One recording's context. All fields optional; saved on close."""

    saved = Signal(dict)
    topicsChanged = Signal(list)

    def __init__(self, context_path, report, player=None, parent=None,
                 topics=None):
        super().__init__(parent, Qt.Window)
        self.setObjectName("root")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle("Context")
        self.setMinimumWidth(520)

        self.context_path = Path(context_path)
        self.report = report
        self.player = player
        self.context = context_module.load(self.context_path)
        self._original = json.dumps(self.context, sort_keys=True)
        self._sample_ranges = me_sample_ranges(report)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 20)
        layout.setSpacing(10)

        layout.addWidget(self._section("Meeting type"))
        self.type_box = QtWidgets.QComboBox()
        for key, label in context_module.MEETING_TYPES:
            self.type_box.addItem(label, key)
        index = self.type_box.findData(self.context.get("meeting_type", "other"))
        self.type_box.setCurrentIndex(max(index, 0))
        layout.addWidget(self.type_box)

        layout.addWidget(self._section("Your goal for this call, in one line"))
        self.goal_edit = QtWidgets.QLineEdit(self.context.get("goal", ""))
        self.goal_edit.setPlaceholderText("Optional")
        layout.addWidget(self.goal_edit)

        layout.addWidget(self._section("Speakers — names, and which one is you"))
        self.name_edits = {}
        self.me_group = QtWidgets.QButtonGroup(self)
        self.me_group.setExclusive(True)
        self.me_buttons = {}
        names = self.context.get("speaker_names") or {}
        for label in speakers_by_talk_share(report):
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(10)
            tag = QtWidgets.QLabel(label)
            tag.setObjectName("rowStatus")
            tag.setMinimumWidth(110)
            row.addWidget(tag)
            edit = QtWidgets.QLineEdit(names.get(label, ""))
            edit.setPlaceholderText("Name (optional)")
            self.name_edits[label] = edit
            row.addWidget(edit, 1)
            if label in self._sample_ranges:
                play = QtWidgets.QPushButton("Play")
                play.setObjectName("quiet")
                play.setCursor(Qt.PointingHandCursor)
                play.setToolTip("Play three seconds of this speaker")
                play.clicked.connect(
                    lambda _=False, l=label: self.play_sample(l))
                row.addWidget(play)
                me = QtWidgets.QRadioButton("This is me")
                self.me_group.addButton(me)
                self.me_buttons[label] = me
                if self.context.get("me") == label:
                    me.setChecked(True)
                row.addWidget(me)
            layout.addLayout(row)

        clear_row = QtWidgets.QHBoxLayout()
        clear_me = QtWidgets.QPushButton("Not sure which is me")
        clear_me.setObjectName("quiet")
        clear_me.setCursor(Qt.PointingHandCursor)
        clear_me.clicked.connect(self.clear_me)
        clear_row.addWidget(clear_me)
        clear_row.addStretch(1)
        layout.addLayout(clear_row)

        self.topics_label = self._section("Topics — tap what matters to re-rank")
        self.topics_label.hide()
        layout.addWidget(self.topics_label)
        self.topics_row = QtWidgets.QHBoxLayout()
        self.topics_row.setSpacing(8)
        layout.addLayout(self.topics_row)
        self.topic_chips = {}
        if topics:
            self.set_topics(topics)

        layout.addWidget(self._section("Notes"))
        self.notes_edit = QtWidgets.QPlainTextEdit()
        self.notes_edit.setObjectName("dictionary")
        self.notes_edit.setPlaceholderText(
            "Anything the reading should know. Optional.")
        self.notes_edit.setPlainText(self.context.get("notes", ""))
        self.notes_edit.setFixedHeight(90)
        layout.addWidget(self.notes_edit)

        layout.addWidget(self._section(
            "Everyone on this recording knew it was being recorded"))
        consent_row = QtWidgets.QHBoxLayout()
        self.consent_buttons = {}
        consent_group = QtWidgets.QButtonGroup(self)
        for key, label in (("yes", "Yes"), ("no", "No"),
                           ("not_sure", "Not sure")):
            radio = QtWidgets.QRadioButton(label)
            consent_group.addButton(radio)
            self.consent_buttons[key] = radio
            consent_row.addWidget(radio)
        consent_row.addStretch(1)
        answer = (self.context.get("consent") or {}).get(
            "all_parties_knew", "not_sure")
        self.consent_buttons.get(answer, self.consent_buttons["not_sure"]) \
            .setChecked(True)
        layout.addLayout(consent_row)

        self.cloud_check = QtWidgets.QCheckBox(
            "May be sent to a cloud model for benchmarking")
        self.cloud_check.setToolTip(
            "Off by default. Nothing leaves this machine either way in "
            "normal use; this only unlocks the benchmark harness's remote "
            "and hand-paste routes for this recording.")
        self.cloud_check.setChecked(
            bool((self.context.get("consent") or {}).get("cloud_ok", False)))
        layout.addWidget(self.cloud_check)

        foot = QtWidgets.QHBoxLayout()
        foot.addWidget(self._section("Everything here is optional. "
                                     "Closing this window saves it."))
        foot.addStretch(1)
        layout.addLayout(foot)

    def _section(self, text):
        label = QtWidgets.QLabel(text)
        label.setObjectName("sectionLabel")
        return label

    # -- me-speaker samples --------------------------------------------------
    def play_sample(self, label):
        if self.player is None or not self.player.available:
            return
        begin, end = self._sample_ranges[label]
        self.player.play(begin, end)

    def clear_me(self):
        button = self.me_group.checkedButton()
        if button is not None:
            # Exclusive groups cannot uncheck; lift exclusivity for a moment.
            self.me_group.setExclusive(False)
            button.setChecked(False)
            self.me_group.setExclusive(True)

    # -- topics (FR-3) -------------------------------------------------------
    def set_topics(self, topics):
        """Render detected topics as checkable chips once insights exist."""
        for chip in self.topic_chips.values():
            chip.setParent(None)
            chip.deleteLater()
        self.topic_chips = {}
        important = set(self.context.get("important_topics") or [])
        for topic in topics:
            chip = QtWidgets.QPushButton(topic.get("label") or topic["id"])
            chip.setObjectName("chip")
            chip.setCheckable(True)
            chip.setChecked(topic["id"] in important)
            chip.setCursor(Qt.PointingHandCursor)
            chip.toggled.connect(self._topics_toggled)
            self.topic_chips[topic["id"]] = chip
            self.topics_row.addWidget(chip)
        self.topics_label.setVisible(bool(topics))

    def _topics_toggled(self, _checked):
        self.topicsChanged.emit(self.important_topics())

    def important_topics(self):
        return [tid for tid, chip in self.topic_chips.items()
                if chip.isChecked()]

    # -- persistence ---------------------------------------------------------
    def collect(self):
        me = None
        for label, button in self.me_buttons.items():
            if button.isChecked():
                me = label
        consent = "not_sure"
        for key, button in self.consent_buttons.items():
            if button.isChecked():
                consent = key
        names = {label: edit.text().strip()
                 for label, edit in self.name_edits.items()
                 if edit.text().strip()}
        context = dict(self.context)
        context.update({
            "meeting_type": self.type_box.currentData(),
            "goal": self.goal_edit.text().strip(),
            "me": me,
            "speaker_names": names,
            "important_topics": (self.important_topics() if self.topic_chips
                                 else self.context.get("important_topics", [])),
            "notes": self.notes_edit.toPlainText().strip(),
            "consent": {"all_parties_knew": consent,
                        "cloud_ok": self.cloud_check.isChecked()},
        })
        return context

    def save(self):
        context = self.collect()
        problems = context_module.save(context, self.context_path)
        if not problems:
            self.context = context
            # Emit only on a real change, so closing an untouched window
            # does not trigger a pack rebuild.
            now = json.dumps(context_module.merged(context), sort_keys=True)
            if now != self._original:
                self._original = now
                self.saved.emit(context)
        return problems

    def closeEvent(self, event):
        self.save()
        super().closeEvent(event)
