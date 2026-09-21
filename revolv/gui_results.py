"""The results window (FR-10 to FR-15): transcript, notes, readings, facts.

Layout: the timeline across the top, the transcript on the left, tabs on the
right (Notes / Under the surface / Speakers / How you sounded), the player
bar along the bottom. Everything that plays goes through one `Player`;
everything shown about a reading came out of the verifier, so this module
renders and never judges.

With no `.insights.json` yet, the right side is an Import box: paste or load
a model's reply, and errors come back in plain words (FR-6). A missing media
file disables the play controls with a one-line reason and nothing else
(FR-15).
"""

import json
import traceback
from pathlib import Path

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt, Signal

from . import analysis
from .config import MEDIA_EXTENSIONS
from .interpret import context as context_module
from .interpret import manual_import
from .interpret.verify import PLAY_LEAD_SECONDS
from .player import Player
from .widgets.timeline import TimelineWidget

LIKELIHOOD_LABEL = {
    "roughly even chance": "Roughly even chance",
    "likely": "Likely",
    "very likely": "Very likely",
}
CONFIDENCE_LABEL = {"low": "thin", "moderate": "moderate", "high": "strong"}


def _mmss(ms):
    seconds = max(int(ms / 1000), 0)
    return "{0:02d}:{1:02d}".format(seconds // 60, seconds % 60)


def find_media(out_dir, stem):
    for suffix in sorted(MEDIA_EXTENSIONS):
        candidate = Path(out_dir) / (stem + suffix)
        if candidate.exists():
            return candidate
    return None


def latest_insights(out_dir, stem):
    candidates = sorted(Path(out_dir).glob(stem + ".insights*.json"),
                        key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def questions_asked(report):
    counts = {}
    for turn in report.get("turns") or []:
        if (turn.get("text") or "").strip().endswith("?"):
            counts[turn["speaker"]] = counts.get(turn["speaker"], 0) + 1
    return counts


def speaker_facts(report):
    """FR-13: measured facts only, per speaker, no scores of any kind."""
    speakers = report.get("speakers") or {}
    overlap = report.get("overlap") or {}
    floor = overlap.get("floor_taking_by_speaker") or {}
    backchannels = {}
    for event in report.get("overlap_events") or []:
        if event.get("kind") == "backchannel" and event.get("by"):
            backchannels[event["by"]] = backchannels.get(event["by"], 0) + 1
    questions = questions_asked(report)
    facts = {}
    for name, entry in speakers.items():
        facts[name] = {
            "talk_share": entry.get("talk_share"),
            "turns": entry.get("turns", 0),
            "median_reply": entry.get("median_reply_latency"),
            "articulation_wpm": entry.get("articulation_wpm"),
            "floor_takes": floor.get(name, 0),
            "backchannels": backchannels.get(name, 0),
            "questions_asked": questions.get(name, 0),
        }
    return facts


class ResultsData:
    """Everything the window shows, loaded from the files beside a run."""

    def __init__(self, out_dir, stem, media_path=None):
        self.out_dir = Path(out_dir)
        self.stem = stem
        self.problems = []

        json_path = self.out_dir / (stem + ".json")
        self.segments = None
        if json_path.exists():
            try:
                with open(json_path, encoding="utf-8") as f:
                    self.segments = json.load(f)
            except (OSError, json.JSONDecodeError) as exc:
                self.problems.append("Could not read {0}: {1}".format(
                    json_path.name, exc))

        analysis_path = self.out_dir / (stem + ".analysis.json")
        self.report = None
        if analysis_path.exists():
            try:
                with open(analysis_path, encoding="utf-8") as f:
                    self.report = json.load(f)
            except (OSError, json.JSONDecodeError) as exc:
                self.problems.append("Could not read {0}: {1}".format(
                    analysis_path.name, exc))
        if self.report is None and self.segments is not None:
            self.report = analysis.analyse(self.segments, {})
        if self.report is None:
            self.problems.append(
                "No transcript files for {0} were found here.".format(stem))

        self.context_path = self.out_dir / (stem + ".context.json")
        self.context = context_module.load(self.context_path)
        self.insights_path = latest_insights(self.out_dir, stem)
        self.insights = None
        if self.insights_path is not None:
            try:
                with open(self.insights_path, encoding="utf-8") as f:
                    self.insights = json.load(f)
            except (OSError, json.JSONDecodeError) as exc:
                self.problems.append("Could not read {0}: {1}".format(
                    self.insights_path.name, exc))

        self.media_path = Path(media_path) if media_path else \
            find_media(self.out_dir, stem)

    @property
    def names(self):
        return self.context.get("speaker_names") or {}

    def display_name(self, label):
        return self.names.get(label, label)

    def meta_for_import(self):
        media_seconds = ((self.report.get("summary") or {})
                         .get("media_seconds"))
        return {
            "source": str(self.media_path or (self.out_dir / self.stem)),
            "media_seconds": media_seconds,
            "analysis": self.report,
            "numbers_file": (self.out_dir
                             / (self.stem + ".analysis.json")).exists(),
        }


class InsightCard(QtWidgets.QFrame):
    """One reading (FR-11): claim, likelihood words, evidence chips,
    alternatives in the open, a follow-up and a play button. No numbers."""

    playRequested = Signal(int, int)
    feedback = Signal(str, str, str)   # insight_key, kind, bad_reason

    def __init__(self, insight, data, parent=None):
        super().__init__(parent)
        self.setObjectName("insightCard")
        self.insight = insight

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(7)

        head = QtWidgets.QHBoxLayout()
        claim = QtWidgets.QLabel(insight.get("claim", ""))
        claim.setObjectName("cardClaim")
        claim.setWordWrap(True)
        head.addWidget(claim, 1)
        play = QtWidgets.QPushButton("Play")
        play.setObjectName("quiet")
        play.setCursor(Qt.PointingHandCursor)
        audio_range = insight.get("audio_range") or {}
        play.clicked.connect(lambda: self.playRequested.emit(
            audio_range.get("start_ms", 0), audio_range.get("end_ms", 0)))
        self.play_button = play
        head.addWidget(play, 0, Qt.AlignTop)
        layout.addLayout(head)

        weight = QtWidgets.QLabel("{0} · evidence is {1}".format(
            LIKELIHOOD_LABEL.get(insight.get("likelihood"),
                                 insight.get("likelihood", "")),
            CONFIDENCE_LABEL.get(insight.get("evidence_confidence"),
                                 insight.get("evidence_confidence", ""))))
        weight.setObjectName("cardMeta")
        layout.addWidget(weight)

        chips = QtWidgets.QVBoxLayout()
        chips.setSpacing(4)
        for item in insight.get("evidence") or []:
            quote = (item.get("quote") or "").strip()
            body = '"{0}"'.format(quote) if quote else \
                (item.get("description") or "")
            turn = item.get("turn_id", "")
            chip = QtWidgets.QLabel("{0} · {1} · {2}".format(
                item.get("channel", ""), turn, body))
            chip.setObjectName("evidenceChip")
            chip.setWordWrap(True)
            chips.addLayout(self._row(chip))
        layout.addLayout(chips)

        alternatives = insight.get("alternatives") or []
        if alternatives:
            alt = QtWidgets.QLabel("Could instead be: " +
                                   "; or ".join(alternatives) + ".")
            alt.setObjectName("cardAlternatives")
            alt.setWordWrap(True)
            layout.addWidget(alt)

        if insight.get("follow_up"):
            follow = QtWidgets.QLabel("Worth asking: " + insight["follow_up"])
            follow.setObjectName("cardFollowUp")
            follow.setWordWrap(True)
            layout.addWidget(follow)

        self.feedback_row = QtWidgets.QHBoxLayout()
        self.feedback_row.setSpacing(6)
        layout.addLayout(self.feedback_row)

    def _row(self, widget):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(widget)
        row.addStretch(1)
        return row


class ResultsWindow(QtWidgets.QWidget):
    """The window a finished row opens."""

    def __init__(self, out_dir, stem, media_path=None, settings=None,
                 store=None, player=None, parent=None):
        super().__init__(parent, Qt.Window)
        self.setObjectName("root")
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle("Results - {0}".format(stem))
        self.resize(1080, 720)

        self.settings = settings or {}
        self.store = store
        self.data = ResultsData(out_dir, stem, media_path)
        self.subtext = bool(self.settings.get("subtext_enabled", True))
        self._syncing = False

        if player is not None:
            self.player = player
        elif self.data.media_path is not None:
            self.player = Player(str(self.data.media_path), parent=self)
            self.player.load()
        else:
            self.player = Player(parent=self)  # unavailable, with reason
        self.player.stateChanged.connect(self._player_state)
        self.player.positionChanged.connect(self._follow_position)

        from . import theme
        self.colors = theme.get(self.settings.get("theme", "light"))

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 14)
        outer.setSpacing(10)

        self.timeline = TimelineWidget(self.colors)
        self.timeline.rangeClicked.connect(self._timeline_clicked)
        outer.addWidget(self.timeline)

        split = QtWidgets.QSplitter()
        split.setChildrenCollapsible(False)
        self.transcript = QtWidgets.QListWidget()
        self.transcript.setObjectName("transcript")
        self.transcript.setWordWrap(True)
        self.transcript.itemClicked.connect(self._turn_clicked)
        split.addWidget(self.transcript)

        self.tabs = QtWidgets.QTabWidget()
        split.addWidget(self.tabs)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 4)
        outer.addWidget(split, 1)

        bar = QtWidgets.QHBoxLayout()
        self.stop_button = QtWidgets.QPushButton("Stop")
        self.stop_button.setObjectName("quiet")
        self.stop_button.clicked.connect(self.player.stop)
        bar.addWidget(self.stop_button)
        self.position_label = QtWidgets.QLabel("")
        self.position_label.setObjectName("statusLine")
        bar.addWidget(self.position_label)
        bar.addStretch(1)
        self.player_note = QtWidgets.QLabel("")
        self.player_note.setObjectName("statusLine")
        bar.addWidget(self.player_note)
        outer.addLayout(bar)

        self._build_content()
        self._player_state(self.player.state)

        if self.store is not None and self.data.insights is not None:
            self._record_in_store()
            QtCore.QTimer.singleShot(300, self._ask_outcomes)

    # -- construction --------------------------------------------------------
    def _build_content(self):
        self._fill_transcript()
        report = self.data.report
        insights = (self.data.insights or {}).get("insights") or []
        self.timeline.set_data(report, insights,
                               names=self.data.names, subtext=self.subtext)

        self.tabs.clear()
        if self.data.insights is None:
            self.tabs.addTab(self._build_import_tab(), "Import")
        else:
            self.tabs.addTab(self._build_notes_tab(), "Notes")
            if self.subtext:
                self.tabs.addTab(self._build_subtext_tab(),
                                 "Under the surface")
        self.tabs.addTab(self._build_speakers_tab(), "Speakers")
        self.coaching_tab_index = self.tabs.addTab(
            self._build_coaching_tab(), "How you sounded")

    def _fill_transcript(self):
        self.transcript.clear()
        for turn in self.data.report.get("turns") or []:
            label = self.data.display_name(turn["speaker"])
            item = QtWidgets.QListWidgetItem("[{0}] {1}: {2}".format(
                _mmss(float(turn["start"]) * 1000), label,
                turn.get("text", "")))
            item.setData(Qt.UserRole, turn["index"])
            self.transcript.addItem(item)

    def _build_import_tab(self):
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setSpacing(8)
        intro = QtWidgets.QLabel(
            "No reading of this call yet. Send the files in the .prompt "
            "folder to a model (README.txt in there says how), then paste "
            "its JSON reply here.")
        intro.setWordWrap(True)
        intro.setObjectName("rowStatus")
        layout.addWidget(intro)
        self.import_edit = QtWidgets.QPlainTextEdit()
        self.import_edit.setObjectName("dictionary")
        self.import_edit.setPlaceholderText("Paste the model's JSON reply…")
        layout.addWidget(self.import_edit, 1)
        self.import_problems = QtWidgets.QLabel("")
        self.import_problems.setObjectName("rowStatus")
        self.import_problems.setWordWrap(True)
        layout.addWidget(self.import_problems)
        row = QtWidgets.QHBoxLayout()
        load = QtWidgets.QPushButton("Load a file…")
        load.setObjectName("quiet")
        load.clicked.connect(self._load_response_file)
        row.addWidget(load)
        row.addStretch(1)
        import_button = QtWidgets.QPushButton("Import")
        import_button.setObjectName("primary")
        import_button.clicked.connect(self._import_pasted)
        row.addWidget(import_button)
        layout.addLayout(row)
        return page

    def _build_notes_tab(self):
        browser = QtWidgets.QTextBrowser()
        browser.setObjectName("notesView")
        browser.setOpenLinks(False)
        browser.anchorClicked.connect(self._notes_link)
        browser.setHtml(self._notes_html())
        return browser

    def _notes_html(self):
        document = self.data.insights
        notes = document.get("notes") or {}
        names = self.data.names
        turn_starts = {t["index"]: float(t["start"]) * 1000
                      for t in self.data.report.get("turns") or []}

        def link(turn_ids):
            for tid in turn_ids or []:
                index = int(tid[1:]) - 1
                if index in turn_starts:
                    return ' <a href="turn:{0}">({1})</a>'.format(
                        tid, _mmss(turn_starts[index]))
            return ""

        parts = []
        if notes.get("summary"):
            parts.append("<p>{0}</p>".format(notes["summary"]))
        sections = [("Decisions", notes.get("decisions"), "text"),
                    ("Action items", notes.get("action_items"), "task"),
                    ("Open questions", notes.get("open_questions"), "text"),
                    ("Key numbers", notes.get("key_numbers"), "text")]
        for title, lines, key in sections:
            if not lines:
                continue
            parts.append("<h3>{0}</h3><ul>".format(title))
            for line in lines:
                if key == "task":
                    owner = names.get(line.get("owner", ""),
                                      line.get("owner", ""))
                    due = line.get("due") or ""
                    text = "{0}{1}{2}".format(
                        owner + ": " if owner else "", line.get("task", ""),
                        " — due " + due if due else "")
                else:
                    text = line.get("text", "")
                parts.append("<li>{0}{1}</li>".format(
                    text, link(line.get("turn_ids"))))
            parts.append("</ul>")
        so_what = document.get("so_what") or []
        if so_what:
            parts.append("<h3>Next</h3><ul>")
            for step in so_what:
                parts.append("<li>{0}</li>".format(step.get("text", "")))
            parts.append("</ul>")
        return "".join(parts) or "<p>Nothing here yet.</p>"

    def _build_subtext_tab(self):
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        holder = QtWidgets.QWidget()
        holder.setObjectName("listHost")
        layout = QtWidgets.QVBoxLayout(holder)
        layout.setSpacing(10)

        document = self.data.insights
        insights = document.get("insights") or []
        by_speaker = {}
        for insight in insights:
            by_speaker.setdefault(insight.get("speaker"), []).append(insight)

        speakers = [s.get("label") for s in document.get("speakers") or []]
        for label in speakers:
            if label not in by_speaker:
                by_speaker.setdefault(label, [])
        self.cards = []
        for label in sorted(by_speaker, key=lambda l: -(len(by_speaker[l]))):
            header = QtWidgets.QLabel(self.data.display_name(label))
            header.setObjectName("sectionLabel")
            layout.addWidget(header)
            cares = next((s.get("cares_about") for s in
                          document.get("speakers") or []
                          if s.get("label") == label), None)
            for care in cares or []:
                note = QtWidgets.QLabel("Seemed to care about {0}: {1}".format(
                    care.get("topic_id", ""), care.get("why", "")))
                note.setObjectName("rowStatus")
                note.setWordWrap(True)
                layout.addWidget(note)
            if not by_speaker[label]:
                nothing = QtWidgets.QLabel("Nothing notable.")
                nothing.setObjectName("rowStatus")
                layout.addWidget(nothing)
                continue
            for insight in by_speaker[label]:
                card = InsightCard(insight, self.data)
                card.playRequested.connect(self._play_range)
                if not self.player.available:
                    card.play_button.setEnabled(False)
                if self.store is not None:
                    self._attach_feedback(card)
                layout.addWidget(card)
                self.cards.append(card)
        if not insights and not speakers:
            layout.addWidget(QtWidgets.QLabel("Nothing notable on this call."))
        layout.addStretch(1)
        scroll.setWidget(holder)
        return scroll

    def _build_speakers_tab(self):
        page = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(page)
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(16)
        facts = speaker_facts(self.data.report)
        headers = ["", "Talk time", "Turns", "Median reply", "Articulation",
                   "Floor-takes", "Backchannels", "Questions"]
        for column, text in enumerate(headers):
            label = QtWidgets.QLabel(text)
            label.setObjectName("sectionLabel")
            grid.addWidget(label, 0, column)
        ordered = sorted(facts, key=lambda n: -(facts[n]["talk_share"] or 0))
        for row, name in enumerate(ordered, start=1):
            entry = facts[name]
            grid.addWidget(QtWidgets.QLabel(self.data.display_name(name)),
                           row, 0)
            share = QtWidgets.QProgressBar()
            share.setRange(0, 100)
            share.setValue(int((entry["talk_share"] or 0) * 100))
            share.setFormat("{0:.0f}%".format((entry["talk_share"] or 0) * 100))
            share.setTextVisible(False)
            share.setFixedHeight(6)
            share.setToolTip("{0:.0f}% of the talking".format(
                (entry["talk_share"] or 0) * 100))
            grid.addWidget(share, row, 1)
            values = [
                str(entry["turns"]),
                "{0:.2f}s".format(entry["median_reply"])
                if entry["median_reply"] is not None else "-",
                "{0:.0f} wpm".format(entry["articulation_wpm"] or 0),
                str(entry["floor_takes"]),
                str(entry["backchannels"]),
                str(entry["questions_asked"]),
            ]
            for column, value in enumerate(values, start=2):
                grid.addWidget(QtWidgets.QLabel(value), row, column)
        grid.setRowStretch(len(ordered) + 1, 1)
        return page

    def _build_coaching_tab(self):
        from .gui_coaching import CoachingTab

        return CoachingTab(self.data, self.store, self.settings,
                           player=self.player, colors=self.colors)

    # -- feedback ------------------------------------------------------------
    def _attach_feedback(self, card):
        from .gui_feedback import attach_feedback_buttons

        attach_feedback_buttons(card, self.store, self.data)

    def _record_in_store(self):
        from .gui_feedback import _call_id

        call_id = _call_id(self.data)
        summary = (self.data.report.get("summary") or {})
        self.store.record_call(
            call_id, media_seconds=summary.get("media_seconds"),
            me_label=self.data.context.get("me"),
            source_path=self.data.media_path
            or (self.data.out_dir / self.data.stem))
        self.store.record_insights(self.data.insights, call_id)

    def _ask_outcomes(self):
        from .gui_feedback import ask_pending_outcomes

        try:
            ask_pending_outcomes(self, self.store, self.data)
        except Exception:
            pass

    # -- playback ------------------------------------------------------------
    def _play_range(self, start_ms, end_ms):
        self.player.play(start_ms, end_ms)

    def _timeline_clicked(self, start_ms, end_ms, _mark):
        self._play_range(start_ms, end_ms)

    def _turn_clicked(self, item):
        if self._syncing:
            return
        index = item.data(Qt.UserRole)
        turn = self.data.report["turns"][index]
        begin = max(int(float(turn["start"]) * 1000
                        - PLAY_LEAD_SECONDS * 1000), 0)
        self._play_range(begin, int(float(turn["end"]) * 1000))

    def _notes_link(self, url):
        target = url.toString()
        if not target.startswith("turn:"):
            return
        index = int(target[5:].lstrip("T")) - 1
        self.select_turn(index, play=True)

    def select_turn(self, index, play=False):
        self._syncing = True
        try:
            self.transcript.setCurrentRow(index)
            self.transcript.scrollToItem(self.transcript.item(index),
                                         QtWidgets.QAbstractItemView.PositionAtCenter)
        finally:
            self._syncing = False
        if play:
            turn = self.data.report["turns"][index]
            begin = max(int(float(turn["start"]) * 1000
                            - PLAY_LEAD_SECONDS * 1000), 0)
            self._play_range(begin, int(float(turn["end"]) * 1000))

    def turn_index_at(self, position_ms):
        seconds = position_ms / 1000.0
        turns = self.data.report.get("turns") or []
        current = None
        for turn in turns:
            if float(turn["start"]) <= seconds:
                current = turn["index"]
            else:
                break
        return current

    def _follow_position(self, position_ms):
        self.position_label.setText(_mmss(position_ms))
        index = self.turn_index_at(position_ms)
        if index is not None and index != self.transcript.currentRow():
            self._syncing = True
            try:
                self.transcript.setCurrentRow(index)
                self.transcript.scrollToItem(
                    self.transcript.item(index),
                    QtWidgets.QAbstractItemView.PositionAtCenter)
            finally:
                self._syncing = False

    def _player_state(self, state):
        available = state in ("ready", "playing")
        self.stop_button.setEnabled(available)
        if state == "unavailable":
            reason = self.player.unavailable_reason or \
                "The recording is not here any more."
            self.player_note.setText("Playback off: " + reason)
        elif state == "loading":
            self.player_note.setText("Decoding the recording…")
        else:
            self.player_note.setText("")
        for card in getattr(self, "cards", []):
            card.play_button.setEnabled(available)

    # -- import --------------------------------------------------------------
    def _load_response_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose the model's reply", str(self.data.out_dir),
            "JSON or text (*.json *.txt);;All files (*.*)")
        if path:
            self.import_edit.setPlainText(
                Path(path).read_text(encoding="utf-8", errors="replace"))

    def _import_pasted(self):
        text = self.import_edit.toPlainText().strip()
        if not text:
            self.import_problems.setText("Paste the model's JSON reply first.")
            return
        if self.data.segments is None:
            self.import_problems.setText(
                "The {0}.json transcript is missing, so quotes cannot be "
                "checked. Keep the JSON format on.".format(self.data.stem))
            return
        try:
            result = manual_import.import_response(
                self.data.segments, self.data.meta_for_import(),
                self.data.out_dir, self.data.stem, text,
                context=self.data.context,
                max_per_call=int(self.settings.get("max_insights_per_call", 8)),
                max_per_speaker=int(
                    self.settings.get("max_insights_per_speaker", 3)))
        except Exception:
            self.import_problems.setText(
                "The import failed unexpectedly:\n"
                + traceback.format_exc(limit=1))
            return
        if result.problems:
            self.import_problems.setText("\n".join(result.problems[:6]))
            return
        self.data = ResultsData(self.data.out_dir, self.data.stem,
                                self.data.media_path)
        self._build_content()
        self.tabs.setCurrentIndex(0)
        if self.store is not None and self.data.insights is not None:
            self._record_in_store()

    def closeEvent(self, event):
        if self.player.parent() is self:
            self.player.close()
        super().closeEvent(event)
