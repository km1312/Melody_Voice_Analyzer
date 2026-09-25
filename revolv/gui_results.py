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
import re
import time
import traceback
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
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


# Fix list #1: after the user scrolls or clicks, playback stops steering the
# transcript for this long.
FOLLOW_HOLDOFF_SECONDS = 2.0

_EVENT_BRACKETS = re.compile(r"\[[^\]]*\]")
_PAUSE_MARKS = re.compile(r"\(\.\.\.\d+(?:\.\d+)?s\)")
_SENTENCE_END = re.compile(r"(?<=[.!?])")


def questions_asked(report):
    """Questions asked per speaker: sentences ending in `?` inside each
    turn, not just turns that end with one (fix list #8)."""
    counts = {}
    for turn in report.get("turns") or []:
        text = _PAUSE_MARKS.sub(" ", _EVENT_BRACKETS.sub(" ",
                                                         turn.get("text") or ""))
        asked = sum(1 for sentence in _SENTENCE_END.split(text)
                    if sentence.strip().endswith("?"))
        if asked:
            counts[turn["speaker"]] = counts.get(turn["speaker"], 0) + asked
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
        turns = entry.get("turns", 0)
        speech = entry.get("speech_seconds") or 0.0
        facts[name] = {
            "talk_share": entry.get("talk_share"),
            "turns": turns,
            "avg_turn_seconds": round(speech / turns, 1) if turns else None,
            "median_reply": entry.get("median_reply_latency"),
            "articulation_wpm": entry.get("articulation_wpm"),
            "floor_takes": floor.get(name, 0),
            "backchannels": backchannels.get(name, 0),
            "questions_asked": questions.get(name, 0),
        }
    return facts


# What each Speakers-tab column measures, for the header's (i) marks. Plain
# words, no verdicts: these describe the arithmetic, not the person.
METRIC_DESCRIPTIONS = {
    "Talk time": "This speaker's share of all the speech in the recording.",
    "Turns": "Stretches of talk by one person. A silence of two seconds or "
             "more ends a turn even when the same person continues.",
    "Avg turn": "Average speech per turn, in seconds: how long this person "
                "tends to hold the floor at a stretch.",
    "Median reply": "The typical silence before this speaker answers "
                    "someone else. Counted only where the floor actually "
                    "changed hands, so it is about replying, not pausing.",
    "Articulation": "Words per minute while actually producing words. "
                    "Pauses inside a turn are excluded, so speaking slowly "
                    "and stopping to think read differently.",
    "Floor-takes": "Times this speaker started while someone else was "
                   "talking and kept going past the overlap - taking the "
                   "floor rather than acknowledging. Classified from the "
                   "diarization with the NaturalTurn rule.",
    "Backchannels": "Short acknowledgements - \"right\", \"mm-hm\" - "
                    "spoken entirely inside someone else's turn. Listening "
                    "noises, not interruptions.",
    "Questions asked": "Sentences ending in a question mark, wherever in "
                       "the turn they fall.",
}


def _speaker_runs(words, default_speaker):
    """Consecutive words grouped by their word-level speaker."""
    runs = []
    for word in words:
        speaker = word.get("speaker", default_speaker)
        if runs and runs[-1][0] == speaker:
            runs[-1][1].append(word)
        else:
            runs.append((speaker, [word]))
    return runs


class ResultsData:
    """Everything the window shows, loaded from the files beside a run."""

    def __init__(self, out_dir, stem, media_path=None, vocabulary=""):
        self.out_dir = Path(out_dir)
        self.stem = stem
        self.problems = []
        self._turn_words = None
        self.vocabulary = [t.strip() for t in (vocabulary or "").split(",")
                           if t.strip()]

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

        # Names the transcript itself suggests, shown with a question mark
        # until confirmed in the Context window. A typed name always wins.
        from .names import guess_speaker_names, merge_with_context

        guesses = {}
        if self.report is not None:
            try:
                guesses = guess_speaker_names(self.report.get("turns") or [],
                                              self.vocabulary)
            except Exception:
                guesses = {}
        self.guessed_names = merge_with_context(
            guesses, (self.context or {}).get("speaker_names"))

    def turn_words(self):
        """Words per turn index, rebuilt from the segments the same way the
        analysis built its turns; empty without segments. This is what lets
        the transcript show word-level speakers (fix list #4)."""
        if self._turn_words is None:
            self._turn_words = {}
            if self.segments is not None and self.report is not None:
                try:
                    rebuilt = analysis.build_turns(
                        analysis.split_segments_by_speaker(self.segments))
                    if len(rebuilt) == len(self.report.get("turns") or []):
                        self._turn_words = {
                            t["index"]: [w for s in t["segments"]
                                         for w in (s.get("words") or [])]
                            for t in rebuilt}
                except Exception:
                    self._turn_words = {}
        return self._turn_words

    def reload_context(self):
        self.context = context_module.load(self.context_path)

    @property
    def names(self):
        return self.context.get("speaker_names") or {}

    def display_name(self, label):
        """A typed name as itself; a guessed one marked with '?'; else the
        raw label. The mark is the honesty: a guess reads as a guess."""
        name = self.names.get(label)
        if name:
            return name
        guess = self.guessed_names.get(label)
        if guess:
            return guess["name"] + "?"
        return label

    def apply_names(self, text):
        """SPEAKER_NN tokens inside model text, rendered as display names."""
        return re.sub(r"\bSPEAKER_\d+\b",
                      lambda m: self.display_name(m.group(0)), text or "")

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
        claim = QtWidgets.QLabel(data.apply_names(insight.get("claim", "")))
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
            alt = QtWidgets.QLabel(data.apply_names(
                "Could instead be: " + "; or ".join(alternatives) + "."))
            alt.setObjectName("cardAlternatives")
            alt.setWordWrap(True)
            layout.addWidget(alt)

        if insight.get("follow_up"):
            follow = QtWidgets.QLabel(
                data.apply_names("Worth asking: " + insight["follow_up"]))
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
        self.data = ResultsData(out_dir, stem, media_path,
                                vocabulary=(settings or {}).get("vocabulary",
                                                                ""))
        self.subtext = bool(self.settings.get("subtext_enabled", True))
        self._syncing = False

        if player is not None:
            self.player = player
        else:
            from .retention import player_for

            # The source when it exists; the kept clips when it does not.
            self.player = player_for(self.data.out_dir, stem,
                                     self.data.media_path, parent=self)
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
        outer.addLayout(self._build_timeline_legend())

        split = QtWidgets.QSplitter()
        split.setChildrenCollapsible(False)
        self.transcript = QtWidgets.QListWidget()
        self.transcript.setObjectName("transcript")
        self.transcript.setWordWrap(True)
        # Wrapped item heights must follow the viewport on resize, and long
        # turns must never elide (fix list #7).
        self.transcript.setResizeMode(QtWidgets.QListView.Adjust)
        self.transcript.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.transcript.setTextElideMode(Qt.ElideNone)
        self.transcript.setUniformItemSizes(False)
        self.transcript.itemClicked.connect(self._turn_clicked)
        # Playback follows the transcript with a marker, never the selection,
        # and backs off while the user is scrolling or clicking (fix #1).
        self._playing_row = None
        self._user_touch = 0.0
        self._auto_scrolling = False
        self.transcript.itemPressed.connect(self._note_user_touch)
        self.transcript.verticalScrollBar().valueChanged.connect(
            self._note_user_touch)
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
        self.remove_source_button = QtWidgets.QPushButton(
            "Remove source recording…")
        self.remove_source_button.setObjectName("quiet")
        self.remove_source_button.setToolTip(
            "Sends the recording to the Recycle Bin after a confirm. "
            "Nothing else is touched.")
        self.remove_source_button.setEnabled(
            self.data.media_path is not None
            and Path(self.data.media_path).exists())
        self.remove_source_button.clicked.connect(self._remove_source)
        bar.addWidget(self.remove_source_button)
        self.delete_derived_button = QtWidgets.QPushButton(
            "Delete everything derived…")
        self.delete_derived_button.setObjectName("quiet")
        self.delete_derived_button.setToolTip(
            "Context, prompt packs, insights, notes, clips and this call's "
            "feedback. The recording and transcript stay.")
        self.delete_derived_button.clicked.connect(self._delete_derived)
        bar.addWidget(self.delete_derived_button)
        outer.addLayout(bar)

        self._build_content()
        self._player_state(self.player.state)

        if self.store is not None and self.data.insights is not None:
            self._record_in_store()
            QtCore.QTimer.singleShot(300, self._ask_outcomes)

    # -- construction --------------------------------------------------------
    def _build_timeline_legend(self):
        """One swatch and word per family, so the colours mean something
        without hovering (fix list #3)."""
        from .widgets.timeline import FAMILY_COLOR_KEYS, FAMILY_LABELS

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(6)

        def add(color, text, radius=3):
            box = QtWidgets.QLabel()
            box.setFixedSize(10, 10)
            box.setStyleSheet("background: {0}; border-radius: {1}px;"
                              .format(color, radius))
            row.addWidget(box)
            label = QtWidgets.QLabel(text)
            label.setObjectName("sectionCount")
            row.addWidget(label)
            row.addSpacing(10)

        for family, text in FAMILY_LABELS.items():
            add(self.colors[FAMILY_COLOR_KEYS[family]], text)
        grey = QtGui.QColor(self.colors["text_subtle"])
        add("rgba({0}, {1}, {2}, 0.35)".format(grey.red(), grey.green(),
                                               grey.blue()),
            "silence ≥ 2 s")
        add(self.colors["accent"], "reading", radius=5)
        row.addStretch(1)
        return row

    def _build_content(self):
        self._fill_transcript()
        report = self.data.report
        insights = (self.data.insights or {}).get("insights") or []
        self.timeline.set_data(report, insights,
                               names={label: self.data.display_name(label)
                                      for label in report.get("speakers")
                                      or {}},
                               subtext=self.subtext)

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
        self._playing_row = None
        for turn in self.data.report.get("turns") or []:
            label = self.data.display_name(turn["speaker"])
            item = QtWidgets.QListWidgetItem("[{0}] {1}: {2}".format(
                _mmss(float(turn["start"]) * 1000), label,
                self._turn_line_text(turn)))
            item.setData(Qt.UserRole, turn["index"])
            self.transcript.addItem(item)

    def _turn_line_text(self, turn):
        """The turn's words, with another speaker's interjections shown
        inline as `[Name: yeah]` instead of silently folded in (fix #4).
        The `.md` stays per-turn on purpose; this is display only."""
        words = self.data.turn_words().get(turn["index"])
        if not words:
            return turn.get("text", "")
        pieces = []
        for speaker, run in _speaker_runs(words, turn["speaker"]):
            text = " ".join((w.get("word") or "").strip()
                            for w in run).strip()
            if not text:
                continue
            if speaker != turn["speaker"]:
                pieces.append("[{0}: {1}]".format(
                    self.data.display_name(speaker), text))
            else:
                pieces.append(text)
        return " ".join(pieces) or turn.get("text", "")

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
            parts.append("<p>{0}</p>".format(
                self.data.apply_names(notes["summary"])))
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
                    owner = self.data.apply_names(line.get("owner", ""))
                    due = line.get("due") or ""
                    text = "{0}{1}{2}".format(
                        owner + ": " if owner else "", line.get("task", ""),
                        " — due " + due if due else "")
                else:
                    text = line.get("text", "")
                parts.append("<li>{0}{1}</li>".format(
                    self.data.apply_names(text),
                    link(line.get("turn_ids"))))
            parts.append("</ul>")
        so_what = document.get("so_what") or []
        if so_what:
            parts.append("<h3>Next</h3><ul>")
            for step in so_what:
                parts.append("<li>{0}</li>".format(
                    self.data.apply_names(step.get("text", ""))))
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

    def _metric_header(self, text):
        """A column header with its (i) mark: hover explains the metric."""
        holder = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        label = QtWidgets.QLabel(text)
        label.setObjectName("sectionLabel")
        row.addWidget(label)
        tip = METRIC_DESCRIPTIONS.get(text)
        if tip:
            label.setToolTip(tip)
            info = QtWidgets.QLabel("ⓘ")
            info.setObjectName("sectionCount")
            info.setToolTip(tip)
            info.setCursor(Qt.WhatsThisCursor)
            row.addWidget(info)
        row.addStretch(1)
        return holder

    def _build_speakers_tab(self):
        page = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(page)
        grid.setVerticalSpacing(8)
        grid.setHorizontalSpacing(16)
        facts = speaker_facts(self.data.report)
        headers = ["", "Talk time", "Turns", "Avg turn", "Median reply",
                   "Articulation", "Floor-takes", "Backchannels",
                   "Questions asked"]
        for column, text in enumerate(headers):
            grid.addWidget(self._metric_header(text), 0, column)
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
                "{0:.1f} s".format(entry["avg_turn_seconds"])
                if entry["avg_turn_seconds"] is not None else "-",
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
        self._user_touch = time.monotonic()
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

    def _note_user_touch(self, *_args):
        if not self._auto_scrolling:
            self._user_touch = time.monotonic()

    def _set_playing_row(self, index):
        """Mark the playing turn without touching the selection, so a click
        elsewhere is never fought over (fix list #1)."""
        if index == self._playing_row:
            return
        if self._playing_row is not None:
            old = self.transcript.item(self._playing_row)
            if old is not None:
                old.setData(Qt.BackgroundRole, None)
        self._playing_row = index
        item = self.transcript.item(index) if index is not None else None
        if item is None:
            return
        item.setData(Qt.BackgroundRole,
                     QtGui.QBrush(QtGui.QColor(self.colors["accent_soft"])))
        recently_touched = (time.monotonic() - self._user_touch
                            < FOLLOW_HOLDOFF_SECONDS)
        visible = self.transcript.visualItemRect(item).intersects(
            self.transcript.viewport().rect())
        if not visible and not recently_touched:
            self._auto_scrolling = True
            try:
                self.transcript.scrollToItem(
                    item, QtWidgets.QAbstractItemView.PositionAtCenter)
            finally:
                self._auto_scrolling = False

    def _follow_position(self, position_ms):
        self.position_label.setText(_mmss(position_ms))
        index = self.turn_index_at(position_ms)
        if index is not None:
            self._set_playing_row(index)

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

    # -- context updates (fix list #2) ---------------------------------------
    def reload_context(self):
        """Re-read `<name>.context.json` and re-render everything that shows
        a name. Called by the main window whenever the Context window saves,
        so both windows can be open at once and stay in step."""
        import_text = None
        if hasattr(self, "import_edit"):
            try:
                import_text = self.import_edit.toPlainText()
            except RuntimeError:
                import_text = None  # widget already deleted with its tab
        current_tab = self.tabs.currentIndex()
        self.data = ResultsData(self.data.out_dir, self.data.stem,
                                self.data.media_path,
                                vocabulary=self.settings.get("vocabulary",
                                                             ""))
        self._build_content()
        if import_text and hasattr(self, "import_edit"):
            self.import_edit.setPlainText(import_text)
        if 0 <= current_tab < self.tabs.count():
            self.tabs.setCurrentIndex(current_tab)

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
                                self.data.media_path,
                                vocabulary=self.settings.get("vocabulary",
                                                             ""))
        self._build_content()
        self.tabs.setCurrentIndex(0)
        if self.store is not None and self.data.insights is not None:
            self._record_in_store()
        if self.settings.get("retention") == "clips":
            self._export_clips()

    def _export_clips(self):
        from .retention import export_clips

        try:
            samples = None
            rate = 16000
            if getattr(self.player, "samples", None) is not None \
                    and len(self.player.samples):
                samples, rate = self.player.samples, self.player.sample_rate
            if samples is None and (self.data.media_path is None
                                    or not Path(self.data.media_path).exists()):
                return
            export_clips(self.data.insights, self.data.out_dir,
                         self.data.stem, samples=samples, sample_rate=rate,
                         media_path=self.data.media_path)
        except Exception:
            self.player_note.setText("Could not write the flagged clips.")

    def _remove_source(self):
        from .retention import remove_source

        answer = QtWidgets.QMessageBox.question(
            self, "Remove source recording",
            "Send {0} to the Recycle Bin? Transcripts, notes and readings "
            "stay; playback will use the kept clips, if any.".format(
                Path(self.data.media_path).name))
        if answer != QtWidgets.QMessageBox.Yes:
            return
        try:
            remove_source(self.data.media_path)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self, "Remove source recording",
                "Could not remove it: {0}".format(exc))
            return
        self.remove_source_button.setEnabled(False)
        self.player.stop()
        self.player._unavailable("The recording was moved to the Recycle "
                                 "Bin.")

    def _delete_derived(self):
        from .gui_feedback import _call_id
        from .retention import delete_derived

        answer = QtWidgets.QMessageBox.question(
            self, "Delete everything derived",
            "Delete this call's context, prompt packs, readings, notes, "
            "clips and feedback? The recording and the transcript files "
            "stay.")
        if answer != QtWidgets.QMessageBox.Yes:
            return
        delete_derived(self.data.out_dir, self.data.stem, store=self.store,
                       call_id=_call_id(self.data))
        self.close()

    def closeEvent(self, event):
        # Walking away silences playback: the player is usually shared with
        # the main window (so its decoded audio survives a reopen), which is
        # exactly why closing this window must stop it explicitly rather
        # than rely on ownership.
        try:
            self.player.stop()
        except Exception:
            pass
        if self.player.parent() is self:
            self.player.close()
        super().closeEvent(event)
