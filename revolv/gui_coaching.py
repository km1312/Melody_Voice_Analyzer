"""The "How you sounded" tab (FR-16 to FR-19): me-speaker only, ever.

Numbers on this tab describe the user to the user, against their own stored
history, and nothing here renders for any other speaker: the tab checks the
me label once at construction and shows only the how-to note without it.
"""

import datetime
import json
import re
import traceback
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from . import coaching
from .interpret import schema as schema_module
from .interpret.verify import banned_wording
from .store import call_id_for
from .writers import unique_path


class RingWidget(QtWidgets.QWidget):
    """The single composite ring (FR-17). Drawn, no gauge library."""

    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self.colors = palette
        self.percentile = None
        self.setFixedSize(96, 96)

    def set_percentile(self, percentile):
        self.percentile = percentile
        self.update()

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = self.rect().adjusted(8, 8, -8, -8)
        pen = QtGui.QPen(QtGui.QColor(self.colors["track"]), 8)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 0, 360 * 16)
        if self.percentile is not None:
            pen.setColor(QtGui.QColor(self.colors["accent"]))
            painter.setPen(pen)
            sweep = int(360 * 16 * (self.percentile / 100.0))
            painter.drawArc(rect, 90 * 16, -sweep)
            painter.setPen(QtGui.QColor(self.colors["text"]))
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "{0:.0f}%".format(self.percentile))


class CoachingTab(QtWidgets.QWidget):
    def __init__(self, data, store, settings, player=None, colors=None,
                 parent=None):
        super().__init__(parent)
        self.data = data
        self.store = store
        self.settings = settings or {}
        self.player = player
        self.colors = colors or {}
        self.me = (data.context or {}).get("me")
        self.me_confirmed = bool(self.me)
        self.me_guess = None
        if not self.me:
            # Derive a probable me from the name guesses and the recording's
            # own title — enough to show the delivery table, not enough to
            # write history (a wrong me would quietly poison every later
            # comparison, so storage and the ring wait for confirmation).
            from .names import guess_me

            names_map = {label: guess["name"]
                         for label, guess in (data.guessed_names or {}).items()}
            names_map.update({label: name
                              for label, name in (data.names or {}).items()
                              if (name or "").strip()})
            source_name = (data.media_path.name if data.media_path
                           else data.stem)
            self.me_guess = guess_me(data.report, names_map, source_name)
            if self.me_guess:
                self.me = self.me_guess["label"]
        self.call_id = call_id_for(data.media_path
                                   or (data.out_dir / data.stem))

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)

        if not self.me:
            note = QtWidgets.QLabel(
                "Mark which speaker is you in the Context window and this "
                "tab will compare this call with your own past ones.")
            note.setWordWrap(True)
            note.setObjectName("rowStatus")
            layout.addWidget(note)
            layout.addStretch(1)
            return

        self.features = coaching.compute_features(data.report, self.me)
        if self.me_confirmed:
            self._store_baseline()
        history = [] if store is None else \
            store.me_baseline_rows(exclude_call=self.call_id)
        self.usual = coaching.usual_features(history)
        min_calls = int(self.settings.get("me_baseline_min_calls", 8))
        self.result = coaching.composite(self.features, history,
                                         min_calls=min_calls)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        holder = QtWidgets.QWidget()
        holder.setObjectName("listHost")
        body = QtWidgets.QVBoxLayout(holder)
        body.setSpacing(12)

        if not self.me_confirmed:
            # A guessed me is a preview: the table below is live, but
            # nothing is stored and no ring shows until the one-click
            # confirmation in Context.
            banner = QtWidgets.QLabel(
                "Guessing this is you: {0}. {1} is named in the "
                "recording's title, so the other main speaker is probably "
                "you. Confirm it in the Context window to start your "
                "history and the ring.".format(
                    self.data.display_name(self.me),
                    self.me_guess["counterpart_name"] or "The other person"))
            banner.setWordWrap(True)
            banner.setObjectName("rowStatus")
            body.addWidget(banner)

        # The ring, or the building note (FR-17) — confirmed me only.
        if self.me_confirmed:
            ring_row = QtWidgets.QHBoxLayout()
            if self.result.get("percentile") is not None:
                ring = RingWidget(self.colors)
                ring.set_percentile(self.result["percentile"])
                ring_row.addWidget(ring)
                ring_note = QtWidgets.QLabel(
                    "Steadier than {0:.0f}% of your past {1} calls.\n"
                    "Experimental: this composite has not yet been checked "
                    "against how you actually felt.".format(
                        self.result["percentile"], self.result["n"]))
            else:
                ring_note = QtWidgets.QLabel(
                    "Building your baseline, {0} of {1} calls.".format(
                        self.result.get("n", 0), min_calls))
            ring_note.setWordWrap(True)
            ring_note.setObjectName("rowStatus")
            ring_row.addWidget(ring_note, 1)
            body.addLayout(ring_row)

        body.addWidget(self._section("This call against your usual"))
        body.addLayout(self._feature_grid())

        contrast = coaching.topic_contrast(
            data.report, self.me,
            (data.insights or {}).get("topics") or [])
        if contrast:
            body.addWidget(self._section("By topic"))
            for kind, label in (("most_assured", "Most assured on"),
                                ("least_assured", "Least assured on")):
                entry = contrast[kind]
                row = QtWidgets.QHBoxLayout()
                text = QtWidgets.QLabel("{0}: {1}".format(label,
                                                          entry["label"]))
                row.addWidget(text)
                play = QtWidgets.QPushButton("Play")
                play.setObjectName("quiet")
                play.setCursor(Qt.PointingHandCursor)
                play.clicked.connect(
                    lambda _=False, i=entry["turn_index"]: self._play_turn(i))
                row.addWidget(play)
                row.addStretch(1)
                body.addLayout(row)

        # Model coaching, self labels and the history reset all assume the
        # me-label is right, so they wait for the confirmed one.
        if self.me_confirmed:
            self.coaching_view = QtWidgets.QVBoxLayout()
            body.addWidget(self._section(
                "A colleague's read (from your model)"))
            body.addLayout(self.coaching_view)
            self._show_coaching_file()

            self.coach_edit = QtWidgets.QPlainTextEdit()
            self.coach_edit.setObjectName("dictionary")
            self.coach_edit.setPlaceholderText(
                "Paste the reply to coaching.txt from the prompt pack…")
            self.coach_edit.setFixedHeight(64)
            body.addWidget(self.coach_edit)
            coach_row = QtWidgets.QHBoxLayout()
            self.coach_problems = QtWidgets.QLabel("")
            self.coach_problems.setObjectName("rowStatus")
            coach_row.addWidget(self.coach_problems, 1)
            import_button = QtWidgets.QPushButton("Import coaching")
            import_button.setObjectName("quiet")
            import_button.clicked.connect(self._import_coaching)
            coach_row.addWidget(import_button)
            body.addLayout(coach_row)

            # Self labels (FR-22): the user's own ground truth.
            moments = [m for m in data.report.get("moments") or []
                       if m["speaker"] == self.me]
            if moments:
                body.addWidget(self._section(
                    "Your moments - were you actually unsure here?"))
                stored = {} if store is None else \
                    store.self_labels_for(self.call_id)
                for moment in moments[:8]:
                    body.addLayout(self._self_label_row(moment, stored))

            reset_row = QtWidgets.QHBoxLayout()
            reset_row.addStretch(1)
            reset = QtWidgets.QPushButton("Reset my baseline")
            reset.setObjectName("quiet")
            reset.clicked.connect(self._reset_baseline)
            reset_row.addWidget(reset)
            body.addLayout(reset_row)

        body.addStretch(1)
        scroll.setWidget(holder)
        layout.addWidget(scroll)

    # -- pieces --------------------------------------------------------------
    def _section(self, text):
        label = QtWidgets.QLabel(text)
        label.setObjectName("sectionLabel")
        return label

    def _feature_grid(self):
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        headers = ["", "This call", "Usual", "Steadier when"]
        for column, text in enumerate(headers):
            label = QtWidgets.QLabel(text)
            label.setObjectName("sectionCount")
            grid.addWidget(label, 0, column)
        self.feature_rows = {}
        for row, (name, direction) in enumerate(coaching.DIRECTIONS.items(),
                                                start=1):
            grid.addWidget(QtWidgets.QLabel(coaching.FEATURE_LABELS[name]),
                           row, 0)
            value = self.features.get(name)
            usual = self.usual.get(name)
            this_label = QtWidgets.QLabel(coaching.format_value(name, value))
            grid.addWidget(this_label, row, 1)
            grid.addWidget(QtWidgets.QLabel(
                "-" if usual is None else coaching.format_value(name, usual)),
                row, 2)
            # The static direction always shows (fix list #6); the
            # comparison joins it once there is history to compare with.
            trend = coaching.DIRECTION_TEXT[direction]
            if direction != "report" and value is not None \
                    and usual is not None:
                if coaching.steadier(name, value, usual):
                    trend += "  ·  steadier than usual"
                elif value == usual:
                    trend += "  ·  as usual"
                else:
                    trend += "  ·  less steady than usual"
            trend_label = QtWidgets.QLabel(trend)
            trend_label.setObjectName("sectionCount")
            grid.addWidget(trend_label, row, 3)
            self.feature_rows[name] = (this_label, trend_label)
        return grid

    def _self_label_row(self, moment, stored):
        row = QtWidgets.QHBoxLayout()
        turn = self.data.report["turns"][moment["turn"]]
        tid = "T{0:03d}".format(moment["turn"] + 1)
        seconds = int(float(turn["start"]))
        text = QtWidgets.QLabel("{0:02d}:{1:02d} - {2}".format(
            seconds // 60, seconds % 60,
            "; ".join(moment.get("observations") or [])))
        text.setWordWrap(True)
        row.addWidget(text, 1)
        play = QtWidgets.QPushButton("Play")
        play.setObjectName("quiet")
        play.clicked.connect(
            lambda _=False, i=moment["turn"]: self._play_turn(i))
        row.addWidget(play)
        group = QtWidgets.QButtonGroup(self)
        for label, answer in (("Yes", "yes"), ("No", "no"),
                              ("Not sure", "not_sure")):
            button = QtWidgets.QPushButton(label)
            button.setObjectName("feedback")
            button.setCheckable(True)
            button.setChecked(stored.get(tid) == answer)
            group.addButton(button)
            button.clicked.connect(
                lambda _=False, t=tid, a=answer: self._self_label(t, a))
            row.addWidget(button)
        return row

    # -- behaviour -----------------------------------------------------------
    def _call_date(self):
        """The recording's date, not the day Results was opened (fix #9):
        a YYYY-MM-DD in the file name wins (the app's own recordings carry
        one), then the media file's modification time, then the .json's,
        and today only when nothing else exists."""
        match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", self.data.stem)
        if match:
            try:
                return datetime.date.fromisoformat(match.group(1)).isoformat()
            except ValueError:
                pass
        candidates = [self.data.media_path,
                      self.data.out_dir / (self.data.stem + ".json")]
        for candidate in candidates:
            if candidate is not None and Path(candidate).exists():
                return datetime.date.fromtimestamp(
                    Path(candidate).stat().st_mtime).isoformat()
        return datetime.date.today().isoformat()

    def _store_baseline(self):
        if self.store is None:
            return
        try:
            minutes = sum(t.get("speech_seconds") or 0
                          for t in self.data.report.get("turns") or []
                          if t["speaker"] == self.me) / 60.0
            self.store.record_call(self.call_id, me_label=self.me,
                                   source_path=self.data.media_path)
            self.store.add_me_baseline(
                self.call_id, self._call_date(),
                coaching.baseline_row(self.features), round(minutes, 2))
        except Exception:
            traceback.print_exc()

    def _self_label(self, turn_id, answer):
        if self.store is not None:
            self.store.add_self_label(self.call_id, turn_id, answer)

    def _play_turn(self, index):
        if self.player is None or not getattr(self.player, "available",
                                              False):
            return
        turn = self.data.report["turns"][index]
        begin = max(int(float(turn["start"]) * 1000) - 1500, 0)
        self.player.play(begin, int(float(turn["end"]) * 1000))

    def _reset_baseline(self):
        if self.store is None:
            return
        answer = QtWidgets.QMessageBox.question(
            self, "Reset baseline",
            "Forget every stored delivery measurement from your past calls? "
            "Recordings and transcripts are untouched.")
        if answer == QtWidgets.QMessageBox.Yes:
            self.store.reset_me_baseline()

    # -- the coaching reply --------------------------------------------------
    def coaching_path(self):
        return self.data.out_dir / (self.data.stem + ".coaching.json")

    def _show_coaching_file(self):
        candidates = sorted(self.data.out_dir.glob(
            self.data.stem + ".coaching*.json"))
        if not candidates:
            hint = QtWidgets.QLabel(
                "The prompt pack contains coaching.txt; paste your model's "
                "reply below for three concrete observations.")
            hint.setWordWrap(True)
            hint.setObjectName("rowStatus")
            self.coaching_view.addWidget(hint)
            return
        try:
            reply = json.loads(candidates[-1].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if reply.get("nothing_to_report"):
            self.coaching_view.addWidget(QtWidgets.QLabel(
                "Nothing differed enough from your usual to mention."))
        for item in reply.get("observations") or []:
            line = QtWidgets.QLabel("• {0}  Try: {1}".format(
                item.get("text", ""), item.get("try", "")))
            line.setWordWrap(True)
            self.coaching_view.addWidget(line)

    def _import_coaching(self):
        text = self.coach_edit.toPlainText().strip()
        if not text:
            return
        from .interpret.verify import strip_response

        try:
            reply = json.loads(strip_response(text))
        except ValueError as exc:
            self.coach_problems.setText("Not valid JSON: {0}".format(exc))
            return
        problems = schema_module.problems(reply, schema_module.COACHING)
        if problems:
            self.coach_problems.setText(problems[0])
            return
        kept = []
        for item in reply.get("observations") or []:
            if banned_wording(item.get("text", "")) or \
                    banned_wording(item.get("try", "")):
                continue
            tid = item.get("turn_id")
            if tid:
                index = int(tid[1:]) - 1
                turns = self.data.report.get("turns") or []
                if not (0 <= index < len(turns)) or \
                        turns[index]["speaker"] != self.me:
                    item = dict(item)
                    item.pop("turn_id", None)
            kept.append(item)
        reply["observations"] = kept
        path = unique_path(self.coaching_path())
        with open(path, "w", encoding="utf-8") as f:
            json.dump(reply, f, indent=2, ensure_ascii=False)
        self.coach_problems.setText("Saved.")
        while self.coaching_view.count():
            item = self.coaching_view.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._show_coaching_file()
