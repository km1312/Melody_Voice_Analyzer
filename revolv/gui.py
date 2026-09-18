"""Desktop front end for the transcription pipeline, built on Qt.

Qt rather than Tk because the design calls for rounded containers, soft
shadows, smooth scrolling and real hover states, none of which Tk can draw.
Qt also hands us actual filesystem paths on a drop, where a Tk drop gives a
string that has to be unquoted by hand.
"""

import os
import subprocess
import sys
import traceback
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, Signal

from . import APP_NAME, APP_VERSION, theme
from .config import Settings, is_media_file, log_file
from .hardware import MODEL_CHOICES
from .writers import FORMAT_LABELS, FORMAT_ORDER, write_all

DND_AVAILABLE = True  # Qt handles this natively

# The chips carry the short word; the full description lives in the tooltip so
# the row of formats stays quiet.
CHIP_LABELS = {
    "json": "JSON",
    "md": "Analysis",
    "txt": "Text",
    "srt": "Subtitles",
    "csv": "Spreadsheet",
}

# The two outputs a reader needs: the analysis view for a model, and the JSON
# the analysis can be re-run from. The rest are conveniences for people and
# other programs, so their chips are drawn smaller and marked optional.
RECOMMENDED_FORMATS = ("md", "json")


def split_terms(text):
    """Dictionary terms from free text: one per line or comma-separated,
    trimmed, empties dropped, duplicates removed in order of first appearance."""
    seen = set()
    terms = []
    for line in (text or "").replace(",", "\n").splitlines():
        term = line.strip()
        if term and term not in seen:
            seen.add(term)
            terms.append(term)
    return terms


class Job:
    def __init__(self, path):
        self.path = Path(path)
        self.status = "Queued"
        self.state = "idle"       # idle | active | done | error
        self.percent = 0
        self.outputs = []
        self.row = None


class WaveBadge(QtWidgets.QWidget):
    """A small waveform mark for the drop zone. Drawn, so it stays crisp."""

    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self.colors = palette
        self.setFixedSize(46, 46)

    def set_palette(self, palette):
        self.colors = palette
        self.update()

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QtGui.QColor(self.colors["accent_soft"]))
        painter.drawEllipse(self.rect())

        pen = QtGui.QPen(QtGui.QColor(self.colors["accent"]))
        pen.setWidthF(2.4)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)

        heights = [0.30, 0.58, 0.86, 0.48, 0.70, 0.34]
        centre_y = self.height() / 2
        spacing = 4.4
        start_x = self.width() / 2 - (len(heights) - 1) * spacing / 2
        for index, amount in enumerate(heights):
            half = (self.height() * 0.30) * amount
            x = start_x + index * spacing
            painter.drawLine(QtCore.QPointF(x, centre_y - half),
                             QtCore.QPointF(x, centre_y + half))


class DropZone(QtWidgets.QFrame):
    filesDropped = Signal(list)
    clicked = Signal()

    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setProperty("hot", "false")
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(150)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(8)

        self.badge = WaveBadge(palette)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.badge)
        row.addStretch(1)
        layout.addLayout(row)

        self.title = QtWidgets.QLabel("Drop audio or video here")
        self.title.setObjectName("dropTitle")
        self.title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title)

        self.hint = QtWidgets.QLabel(
            "or click to browse    ·    drop a folder to queue everything inside")
        self.hint.setObjectName("dropHint")
        self.hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.hint)

    def set_palette(self, palette):
        self.badge.set_palette(palette)

    def _restyle(self):
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("hot", "true")
            self._restyle()

    def dragLeaveEvent(self, _event):
        self.setProperty("hot", "false")
        self._restyle()

    def dropEvent(self, event):
        self.setProperty("hot", "false")
        self._restyle()
        paths = [url.toLocalFile() for url in event.mimeData().urls()
                 if url.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


class FileRow(QtWidgets.QFrame):
    """One queued file, as a rounded card rather than a table row."""

    activated = Signal()

    def __init__(self, job, parent=None):
        super().__init__(parent)
        self.job = job
        self.setObjectName("row")
        self.setProperty("state", "idle")

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(7)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(12)
        self.name = QtWidgets.QLabel(job.path.name)
        self.name.setObjectName("rowName")
        self.name.setTextInteractionFlags(Qt.NoTextInteraction)
        top.addWidget(self.name, 1)

        self.percent = QtWidgets.QLabel("")
        self.percent.setObjectName("rowPercent")
        top.addWidget(self.percent, 0, Qt.AlignRight)
        outer.addLayout(top)

        self.status = QtWidgets.QLabel("Queued")
        self.status.setObjectName("rowStatus")
        self.status.setProperty("state", "idle")
        outer.addWidget(self.status)

        self.bar = QtWidgets.QProgressBar()
        self.bar.setObjectName("rowBar")
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        self.bar.hide()
        outer.addWidget(self.bar)

    def set_state(self, state, status_text, percent=None):
        self.job.state = state
        self.setProperty("state", state)
        self.status.setProperty("state", state)
        self.status.setText(status_text)

        if percent is None:
            self.percent.setText("")
            self.bar.hide()
        else:
            self.percent.setText("{0}%".format(int(percent * 100)))
            self.bar.setValue(int(percent * 1000))
            self.bar.setVisible(state == "active")

        for widget in (self, self.status):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def mouseDoubleClickEvent(self, _event):
        self.activated.emit()


class Worker(QtCore.QThread):
    """Runs the queue off the UI thread. Signals cross back automatically."""

    log = Signal(str)
    status = Signal(str)
    jobProgress = Signal(int, str, float)
    jobStarted = Signal(int)
    jobDone = Signal(int, list, dict)
    jobFailed = Signal(int, str)
    jobStopped = Signal(int)

    def __init__(self, jobs, indices, profile, settings, output_dir, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self.indices = indices
        self.profile = profile
        self.settings = dict(settings)
        self.output_dir = output_dir
        self._cancel = QtCore.QMutex()
        self._stop = False

    def request_stop(self):
        self._stop = True

    class _Flag:
        """Adapter so the pipeline's `cancel.is_set()` contract still works."""

        def __init__(self, worker):
            self.worker = worker

        def is_set(self):
            return self.worker._stop

    def run(self):
        import time

        from .audio import AudioError, Cancelled
        from .pipeline import Transcriber

        cancel = Worker._Flag(self)
        transcriber = None
        try:
            self.status.emit("Loading models. The first run downloads them, "
                             "which can take a while.")
            transcriber = Transcriber(
                self.profile,
                hf_token=self.settings["hf_token"],
                language=self.settings["language"],
                diarize=self.settings["diarize"],
                emotion=self.settings["emotion"],
                backend=self.settings.get("asr_backend"),
                model_override=self.settings.get("model_override", "auto"),
                vocabulary=self.settings.get("vocabulary", ""),
                prosody=self.settings.get("prosody", True),
                analyse=self.settings.get("analysis", True),
                verbatim=self.settings.get("verbatim", True),
                stance=self.settings.get("stance", True),
                log=self.log.emit,
            )
            transcriber.load_models(progress=self.status.emit, cancel=cancel)

            total = len(self.indices)
            for position, index in enumerate(self.indices, start=1):
                if self._stop:
                    self.jobStopped.emit(index)
                    continue

                job = self.jobs[index]
                self.jobStarted.emit(index)
                self.status.emit("File {0} of {1}  ·  {2}".format(
                    position, total, job.path.name))
                started = time.time()

                def on_progress(stage, overall, message, _index=index):
                    self.jobProgress.emit(_index, message, overall)

                try:
                    segments, meta = transcriber.run(job.path, progress=on_progress,
                                                     cancel=cancel)
                except Cancelled:
                    self.jobStopped.emit(index)
                    break
                except AudioError as exc:
                    self.jobFailed.emit(index, str(exc))
                    self.log.emit("{0}: {1}".format(job.path.name, exc))
                    continue
                except Exception as exc:
                    self.jobFailed.emit(index, "Failed: {0}".format(exc))
                    self.log.emit("{0} failed:\n{1}".format(
                        job.path.name, traceback.format_exc()))
                    continue

                out_dir = Path(self.output_dir) if self.output_dir else job.path.parent
                try:
                    written = write_all(segments, meta, out_dir, job.path.stem,
                                        self.settings["formats"])
                except OSError as exc:
                    self.jobFailed.emit(index, "Could not save: {0}".format(exc))
                    continue

                elapsed = time.time() - started
                speed = (meta["media_seconds"] / elapsed) if elapsed > 0 else 0
                self.jobDone.emit(index, [str(p) for p in written], meta)
                self.log.emit("{0}: {1} segments, {2} speakers, {3:.0f}s "
                              "({4:.1f}x real time)".format(
                                  job.path.name, meta["segments"], meta["speakers"],
                                  elapsed, speed))
                for path in written:
                    self.log.emit("   saved {0}".format(path))

        except Cancelled:
            self.log.emit("Stopped before the models finished loading.")
        except Exception:
            self.log.emit("The run failed:\n{0}".format(traceback.format_exc()))
        finally:
            if transcriber is not None:
                transcriber.close()


class HardwareProbe(QtCore.QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, device_override, model_override, parent=None):
        super().__init__(parent)
        self.device_override = device_override
        self.model_override = model_override

    def run(self):
        try:
            from .hardware import detect
            self.done.emit(detect(self.device_override, self.model_override))
        except Exception as exc:
            self.failed.emit(str(exc))


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, initial_files=()):
        super().__init__()
        self.settings = Settings()
        self.colors = theme.get(self.settings["theme"])
        self.profile = None
        self.jobs = []
        self.worker = None
        self.probe = None

        self.setWindowTitle("{0} {1}".format(APP_NAME, APP_VERSION))
        self.resize(1020, 950)
        self.setMinimumSize(880, 680)
        self.setAcceptDrops(True)

        self._build_ui()
        self.apply_theme()
        QtCore.QTimer.singleShot(60, self.detect_hardware)

        if initial_files:
            self.add_paths(initial_files)

    # -- construction ------------------------------------------------------
    def _label(self, text, object_name):
        label = QtWidgets.QLabel(text)
        label.setObjectName(object_name)
        return label

    def _build_ui(self):
        root = QtWidgets.QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        outer = QtWidgets.QVBoxLayout(root)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(18)

        outer.addLayout(self._build_header())
        outer.addWidget(self._build_hardware_pill())
        outer.addWidget(self._build_dropzone())
        outer.addLayout(self._build_files_header())
        outer.addWidget(self._build_list(), 1)
        outer.addLayout(self._build_output_row())
        outer.addLayout(self._build_format_row())
        outer.addLayout(self._build_actions())
        outer.addWidget(self._build_progress())
        outer.addWidget(self.status_line)
        outer.addWidget(self._build_log())

    def _build_header(self):
        row = QtWidgets.QHBoxLayout()
        column = QtWidgets.QVBoxLayout()
        column.setSpacing(2)
        column.addWidget(self._label(APP_NAME, "title"))
        column.addWidget(self._label(
            "Local transcription with speaker labels and tone", "subtitle"))
        row.addLayout(column)
        row.addStretch(1)

        self.dictionary_button = QtWidgets.QPushButton("Dictionary")
        self.dictionary_button.setObjectName("quiet")
        self.dictionary_button.setCursor(Qt.PointingHandCursor)
        self.dictionary_button.setToolTip(
            "Names and jargon the recordings contain, so they are spelled the "
            "way you write them")
        self.dictionary_button.clicked.connect(self.open_dictionary)
        row.addWidget(self.dictionary_button, 0, Qt.AlignTop)

        self.settings_button = QtWidgets.QPushButton("Settings")
        self.settings_button.setObjectName("quiet")
        self.settings_button.setCursor(Qt.PointingHandCursor)
        self.settings_button.clicked.connect(self.open_settings)
        row.addWidget(self.settings_button, 0, Qt.AlignTop)
        return row

    def _build_hardware_pill(self):
        self.pill = QtWidgets.QFrame()
        self.pill.setObjectName("pill")
        layout = QtWidgets.QHBoxLayout(self.pill)
        layout.setContentsMargins(18, 13, 18, 13)

        self.hw_text = self._label("Checking what this machine can do…", "pillText")
        layout.addWidget(self.hw_text)
        layout.addStretch(1)
        self.hw_meta = self._label("", "pillMeta")
        layout.addWidget(self.hw_meta)
        return self.pill

    def _build_dropzone(self):
        self.dropzone = DropZone(self.colors)
        self.dropzone.filesDropped.connect(self.add_paths)
        self.dropzone.clicked.connect(self.browse_files)
        return self.dropzone

    def _build_files_header(self):
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(self._label("Files", "sectionLabel"))
        row.addStretch(1)
        self.files_count = self._label("", "sectionCount")
        row.addWidget(self.files_count)
        # Clear list sits with the list it clears, at the top right of it,
        # rather than among the run controls underneath.
        self.clear_button = QtWidgets.QPushButton("Clear list")
        self.clear_button.setObjectName("quiet")
        self.clear_button.setCursor(Qt.PointingHandCursor)
        self.clear_button.clicked.connect(self.clear_list)
        row.addWidget(self.clear_button)
        return row

    def _build_list(self):
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setObjectName("listHost")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setMinimumHeight(210)

        holder = QtWidgets.QWidget()
        holder.setObjectName("listHost")
        self.list_layout = QtWidgets.QVBoxLayout(holder)
        self.list_layout.setContentsMargins(12, 12, 12, 12)
        self.list_layout.setSpacing(8)

        self.empty_label = self._label("Nothing queued yet.", "rowStatus")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.list_layout.addWidget(self.empty_label)
        self.list_layout.addStretch(1)

        self.scroll.setWidget(holder)
        # No QGraphicsDropShadowEffect here: applying one to a scroll area stops
        # the viewport clipping its children, and rows spill over the controls
        # below. The card reads fine on depth from its own background.
        return self.scroll

    def _build_output_row(self):
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(self._label("Save to", "sectionLabel"))

        self.beside_radio = QtWidgets.QRadioButton("Beside the original")
        self.folder_radio = QtWidgets.QRadioButton("A folder")
        group = QtWidgets.QButtonGroup(self)
        group.addButton(self.beside_radio)
        group.addButton(self.folder_radio)
        if self.settings["output_dir"]:
            self.folder_radio.setChecked(True)
        else:
            self.beside_radio.setChecked(True)
        self.beside_radio.toggled.connect(self.sync_output_row)
        row.addWidget(self.beside_radio)
        row.addWidget(self.folder_radio)

        self.output_edit = QtWidgets.QLineEdit(self.settings["output_dir"])
        self.output_edit.setPlaceholderText("Choose a folder…")
        row.addWidget(self.output_edit, 1)

        self.output_button = QtWidgets.QPushButton("Choose")
        self.output_button.setCursor(Qt.PointingHandCursor)
        self.output_button.clicked.connect(self.browse_output_dir)
        row.addWidget(self.output_button)

        self.sync_output_row()
        return row

    def _build_format_row(self):
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self._label("Formats", "sectionLabel"))

        self.format_buttons = {}
        for fmt in RECOMMENDED_FORMATS:
            row.addWidget(self._format_chip(fmt, "chip"))
        divider = self._label("optional", "sectionCount")
        divider.setToolTip("Not needed for an AI reading of the call. The "
                           "Analysis file already holds the full transcript.")
        row.addSpacing(8)
        row.addWidget(divider)
        for fmt in FORMAT_ORDER:
            if fmt not in RECOMMENDED_FORMATS:
                row.addWidget(self._format_chip(fmt, "chipMinor"))
        row.addStretch(1)
        return row

    def _format_chip(self, fmt, object_name):
        button = QtWidgets.QPushButton(CHIP_LABELS[fmt])
        button.setObjectName(object_name)
        button.setCheckable(True)
        button.setChecked(fmt in self.settings["formats"])
        button.setCursor(Qt.PointingHandCursor)
        tip = FORMAT_LABELS[fmt]
        if fmt not in RECOMMENDED_FORMATS:
            tip += ". Optional: not needed for an AI reading of the call."
        button.setToolTip(tip)
        self.format_buttons[fmt] = button
        return button

    def _build_actions(self):
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(10)

        self.start_button = QtWidgets.QPushButton("Start transcribing")
        self.start_button.setObjectName("primary")
        self.start_button.setCursor(Qt.PointingHandCursor)
        self.start_button.clicked.connect(self.start)
        row.addWidget(self.start_button)

        self.stop_button = QtWidgets.QPushButton("Stop")
        self.stop_button.setObjectName("quiet")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        row.addWidget(self.stop_button)

        row.addStretch(1)

        self.open_button = QtWidgets.QPushButton("Open output folder")
        self.open_button.setCursor(Qt.PointingHandCursor)
        self.open_button.clicked.connect(self.open_output_folder)
        row.addWidget(self.open_button)
        return row

    def _build_progress(self):
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)

        self.status_line = self._label("Add a recording to get started.", "statusLine")
        return self.progress

    def _build_log(self):
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setObjectName("log")
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(104)
        self.log_view.setFrameShape(QtWidgets.QFrame.NoFrame)
        return self.log_view

    # -- theme -------------------------------------------------------------
    def apply_theme(self):
        app = QtWidgets.QApplication.instance()
        app.setStyleSheet(theme.qss(self.colors))
        self.dropzone.set_palette(self.colors)
        self.setStyleSheet("")
        for widget in self.findChildren(QtWidgets.QWidget):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.update()

    def switch_theme(self, name):
        self.colors = theme.get(name)
        self.settings["theme"] = self.colors["name"]
        self.settings.save()
        self.apply_theme()

    # -- hardware ----------------------------------------------------------
    def detect_hardware(self):
        self.probe = HardwareProbe(self.settings["device_override"],
                                   self.settings["model_override"])
        self.probe.done.connect(self._hardware_ready)
        self.probe.failed.connect(
            lambda msg: self.log("Hardware detection failed: {0}".format(msg)))
        self.probe.start()

    def _hardware_ready(self, profile):
        self.profile = profile
        if profile.device == "cuda":
            head = "{0}  ·  {1:.1f} GB of video memory".format(
                profile.device_name, profile.vram_gb)
        else:
            head = "{0}  ·  {1} cores  ·  {2:.0f} GB of memory".format(
                profile.device_name, profile.cpu_count, profile.ram_gb)
        self.hw_text.setText(head)
        self.hw_meta.setText("{0}  ·  {1}  ·  batch {2}".format(
            profile.model_size, profile.compute_type, profile.batch_size))
        self.log("Detected {0}".format(profile.summary().replace("\n", " | ")))
        for note in profile.notes:
            self.log(note)

    # -- files -------------------------------------------------------------
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls()
                 if url.isLocalFile()]
        if paths:
            self.add_paths(paths)
            event.acceptProposedAction()

    def browse_files(self):
        start = self.settings.get("last_input_dir") or str(Path.home())
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Choose audio or video files",
            start if os.path.isdir(start) else str(Path.home()),
            "Audio and video (*.mkv *.mp4 *.mov *.avi *.webm *.m4v *.wav *.mp3 "
            "*.m4a *.aac *.flac *.ogg *.opus *.wma);;All files (*.*)")
        if paths:
            self.add_paths(paths)

    def add_paths(self, paths):
        found, skipped = [], 0
        for raw in paths:
            path = Path(str(raw))
            if path.is_dir():
                for child in sorted(path.rglob("*")):
                    if child.is_file() and is_media_file(child):
                        found.append(child)
            elif path.is_file():
                if is_media_file(path):
                    found.append(path)
                else:
                    skipped += 1

        existing = {str(job.path).lower() for job in self.jobs}
        added = 0
        for path in found:
            if str(path).lower() in existing:
                continue
            job = Job(path)
            row = FileRow(job)
            row.activated.connect(lambda j=job: self.reveal(
                j.outputs[0] if j.outputs else j.path))
            job.row = row
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)
            self.jobs.append(job)
            existing.add(str(path).lower())
            added += 1

        if added:
            self.settings["last_input_dir"] = str(Path(found[-1]).parent)
            self.settings.save()
            self.log("Added {0} file{1}.".format(added, "" if added == 1 else "s"))
        if skipped:
            self.log("Skipped {0} file{1} that are not audio or video.".format(
                skipped, "" if skipped == 1 else "s"))
        self.refresh_counts()

    def clear_list(self):
        if self.worker and self.worker.isRunning():
            return
        for job in self.jobs:
            job.row.setParent(None)
            job.row.deleteLater()
        self.jobs = []
        self.progress.setValue(0)
        self.refresh_counts()

    def refresh_counts(self):
        self.empty_label.setVisible(not self.jobs)
        if not self.jobs:
            self.files_count.setText("")
            self.status_line.setText("Add a recording to get started.")
            return
        waiting = sum(1 for j in self.jobs if j.state in ("idle", "error"))
        self.files_count.setText("{0} queued  ·  {1} waiting".format(
            len(self.jobs), waiting))
        if not (self.worker and self.worker.isRunning()):
            self.status_line.setText("Ready when you are.")

    # -- output ------------------------------------------------------------
    def sync_output_row(self):
        use_folder = self.folder_radio.isChecked()
        self.output_edit.setEnabled(use_folder)
        self.output_button.setEnabled(use_folder)

    def browse_output_dir(self):
        current = self.output_edit.text().strip()
        start = current if os.path.isdir(current) else str(Path.home())
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Choose where to save transcripts", start)
        if chosen:
            self.output_edit.setText(chosen)
            self.folder_radio.setChecked(True)
            self.sync_output_row()

    def output_dir(self):
        if self.folder_radio.isChecked():
            return self.output_edit.text().strip()
        return ""

    def open_output_folder(self):
        target = None
        for job in reversed(self.jobs):
            if job.outputs:
                target = Path(job.outputs[0]).parent
                break
        if target is None:
            chosen = self.output_dir()
            if chosen:
                target = Path(chosen)
            elif self.jobs:
                target = self.jobs[0].path.parent
        if target is None or not target.exists():
            QtWidgets.QMessageBox.information(
                self, APP_NAME, "There is no output folder to open yet.")
            return
        self.reveal(target)

    def reveal(self, path):
        path = Path(path)
        try:
            if sys.platform.startswith("win"):
                if path.is_dir():
                    os.startfile(str(path))
                else:
                    subprocess.Popen(["explorer", "/select,", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path if path.is_dir() else path.parent)])
            else:
                subprocess.Popen(["xdg-open",
                                  str(path if path.is_dir() else path.parent)])
        except Exception as exc:
            self.log("Could not open {0}: {1}".format(path, exc))

    # -- settings ----------------------------------------------------------
    def open_settings(self):
        SettingsDialog(self).exec()

    def open_dictionary(self):
        DictionaryDialog(self).exec()

    def collect_settings(self):
        self.settings["output_dir"] = self.output_dir()
        self.settings["formats"] = [f for f in FORMAT_ORDER
                                    if self.format_buttons[f].isChecked()]
        self.settings.save()

    # -- running -----------------------------------------------------------
    def start(self):
        if self.worker and self.worker.isRunning():
            return
        if self.profile is None:
            QtWidgets.QMessageBox.information(
                self, APP_NAME, "Still checking your hardware. Try again in a moment.")
            return

        indices = [i for i, j in enumerate(self.jobs) if j.state in ("idle", "error")]
        if not indices:
            QtWidgets.QMessageBox.information(
                self, APP_NAME, "Add some audio or video files first.")
            return

        self.collect_settings()
        if not self.settings["formats"]:
            QtWidgets.QMessageBox.information(
                self, APP_NAME, "Pick at least one output format.")
            return

        target = self.output_dir()
        if self.folder_radio.isChecked():
            if not target:
                QtWidgets.QMessageBox.information(
                    self, APP_NAME,
                    "Choose a folder, or switch back to saving beside the original.")
                return
            try:
                Path(target).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                QtWidgets.QMessageBox.critical(
                    self, APP_NAME, "Cannot write to that folder:\n{0}".format(exc))
                return

        for index in indices:
            self.jobs[index].outputs = []
            self.jobs[index].row.set_state("idle", "Queued")

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.clear_button.setEnabled(False)

        self.worker = Worker(self.jobs, indices, self.profile, self.settings, target)
        self.worker.log.connect(self.log)
        self.worker.status.connect(self.status_line.setText)
        self.worker.jobStarted.connect(self._on_job_started)
        self.worker.jobProgress.connect(self._on_job_progress)
        self.worker.jobDone.connect(self._on_job_done)
        self.worker.jobFailed.connect(self._on_job_failed)
        self.worker.jobStopped.connect(self._on_job_stopped)
        self.worker.finished.connect(self._on_all_finished)
        self.worker.start()

    def stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.request_stop()
            self.stop_button.setEnabled(False)
            self.status_line.setText("Stopping after the current step…")
            self.log("Stop requested.")

    def _on_job_started(self, index):
        self.jobs[index].row.set_state("active", "Starting", 0.0)
        self.scroll.ensureWidgetVisible(self.jobs[index].row)

    def _on_job_progress(self, index, message, overall):
        self.jobs[index].row.set_state("active", message, overall)
        self.progress.setValue(int(overall * 1000))

    def _on_job_done(self, index, written, meta):
        job = self.jobs[index]
        job.outputs = written
        summary = "{0} segments".format(meta["segments"])
        if meta.get("speakers"):
            summary += "  ·  {0} speakers".format(meta["speakers"])
        summary += "  ·  double-click to open"
        job.row.set_state("done", summary, 1.0)
        self.progress.setValue(1000)

    def _on_job_failed(self, index, message):
        self.jobs[index].row.set_state("error", message)

    def _on_job_stopped(self, index):
        self.jobs[index].row.set_state("error", "Stopped")

    def _on_all_finished(self):
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.clear_button.setEnabled(True)
        done = sum(1 for j in self.jobs if j.state == "done")
        failed = sum(1 for j in self.jobs if j.state == "error")
        if failed:
            self.status_line.setText(
                "Finished. {0} done, {1} need a look.".format(done, failed))
        else:
            self.status_line.setText(
                "All done. {0} file{1} transcribed.".format(
                    done, "" if done == 1 else "s"))
        self.progress.setValue(0)
        self.refresh_counts()

    # -- misc --------------------------------------------------------------
    def log(self, message):
        import time
        self.log_view.appendPlainText("{0}  {1}".format(
            time.strftime("%H:%M:%S"), message))
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            answer = QtWidgets.QMessageBox.question(
                self, APP_NAME, "A transcription is still running. Quit anyway?")
            if answer != QtWidgets.QMessageBox.Yes:
                event.ignore()
                return
            self.worker.request_stop()
            self.worker.wait(3000)
        self.collect_settings()
        event.accept()


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window_ref = window
        settings = window.settings
        self._original_theme = settings["theme"]

        self.setWindowTitle("Settings")
        self.setMinimumWidth(560)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(10)

        layout.addWidget(window._label("Appearance", "sectionLabel"))
        theme_row = QtWidgets.QHBoxLayout()
        self.light_radio = QtWidgets.QRadioButton("Light")
        self.dark_radio = QtWidgets.QRadioButton("Dark")
        group = QtWidgets.QButtonGroup(self)
        group.addButton(self.light_radio)
        group.addButton(self.dark_radio)
        (self.dark_radio if settings["theme"] == "dark"
         else self.light_radio).setChecked(True)
        self.light_radio.toggled.connect(self._preview_theme)
        theme_row.addWidget(self.light_radio)
        theme_row.addWidget(self.dark_radio)
        theme_row.addStretch(1)
        layout.addLayout(theme_row)
        layout.addSpacing(8)

        layout.addWidget(window._label(
            "HuggingFace token, needed for speaker labels", "sectionLabel"))
        self.token_edit = QtWidgets.QLineEdit(settings["hf_token"])
        self.token_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        layout.addWidget(self.token_edit)
        hint = window._label(
            "Accept the terms for pyannote/speaker-diarization-community-1 and "
            "pyannote/segmentation-3.0 on huggingface.co first.", "rowStatus")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addSpacing(8)

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        grid.addWidget(window._label("Language", "sectionLabel"), 0, 0)
        self.language_box = QtWidgets.QComboBox()
        self.language_box.addItems(["auto", "en", "es", "fr", "de", "it", "pt",
                                    "nl", "ja", "zh", "ko", "ru", "uk", "hi", "ar"])
        self.language_box.setCurrentText(settings["language"] or "auto")
        grid.addWidget(self.language_box, 1, 0)

        grid.addWidget(window._label("Whisper model", "sectionLabel"), 0, 1)
        self.model_box = QtWidgets.QComboBox()
        self.model_box.addItems(MODEL_CHOICES)
        self.model_box.setCurrentText(settings["model_override"])
        grid.addWidget(self.model_box, 1, 1)

        grid.addWidget(window._label("Processor", "sectionLabel"), 0, 2)
        self.device_box = QtWidgets.QComboBox()
        self.device_box.addItems(["auto", "cuda", "cpu"])
        self.device_box.setCurrentText(settings["device_override"])
        grid.addWidget(self.device_box, 1, 2)
        layout.addLayout(grid)
        layout.addSpacing(10)

        self.diarize_check = QtWidgets.QCheckBox("Label who is speaking")
        self.diarize_check.setChecked(settings["diarize"])
        layout.addWidget(self.diarize_check)
        self.emotion_check = QtWidgets.QCheckBox("Score emotion once per turn")
        self.emotion_check.setToolTip(
            "Arousal is reported. Valence and dominance are recorded in the .json "
            "but not presented as evidence.")
        self.emotion_check.setChecked(settings["emotion"])
        layout.addWidget(self.emotion_check)
        self.verbatim_check = QtWidgets.QCheckBox(
            "Keep fillers, cut-offs and repetitions")
        self.verbatim_check.setToolTip(
            "The CrisperWhisper 2.0 verbatim pass. Needs a CUDA GPU and takes "
            "about three quarters of the run time.")
        self.verbatim_check.setChecked(settings.get("verbatim", True))
        layout.addWidget(self.verbatim_check)
        self.stance_check = QtWidgets.QCheckBox(
            "Read stance with the learned head")
        self.stance_check.setChecked(settings.get("stance", True))
        layout.addWidget(self.stance_check)
        self.prosody_check = QtWidgets.QCheckBox(
            "Measure pitch and loudness per turn")
        self.prosody_check.setChecked(settings.get("prosody", True))
        layout.addWidget(self.prosody_check)
        self.analysis_check = QtWidgets.QCheckBox(
            "Derive turns, baselines and moments")
        self.analysis_check.setToolTip(
            "Needed for the Analysis (.md) format and its .analysis.json.")
        self.analysis_check.setChecked(settings.get("analysis", True))
        layout.addWidget(self.analysis_check)
        layout.addSpacing(8)

        dictionary_row = QtWidgets.QHBoxLayout()
        dictionary_row.addWidget(window._label("Dictionary", "sectionLabel"))
        dictionary_button = QtWidgets.QPushButton("Edit names and jargon")
        dictionary_button.setObjectName("quiet")
        dictionary_button.setCursor(Qt.PointingHandCursor)
        dictionary_button.clicked.connect(lambda: DictionaryDialog(window).exec())
        dictionary_row.addWidget(dictionary_button)
        dictionary_row.addStretch(1)
        layout.addLayout(dictionary_row)
        layout.addSpacing(14)

        buttons = QtWidgets.QHBoxLayout()
        log_button = QtWidgets.QPushButton("Open log file")
        log_button.setObjectName("quiet")
        log_button.clicked.connect(lambda: window.reveal(log_file()))
        buttons.addWidget(log_button)
        buttons.addStretch(1)

        cancel = QtWidgets.QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)

        save = QtWidgets.QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self.accept)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _preview_theme(self):
        """Switch live so the choice is visible before it is committed."""
        self.window_ref.switch_theme(
            "light" if self.light_radio.isChecked() else "dark")

    def reject(self):
        if self.window_ref.settings["theme"] != self._original_theme:
            self.window_ref.switch_theme(self._original_theme)
        super().reject()

    def accept(self):
        window = self.window_ref
        settings = window.settings
        before = (settings["model_override"], settings["device_override"])

        settings["hf_token"] = self.token_edit.text().strip()
        language = self.language_box.currentText().strip()
        settings["language"] = "" if language == "auto" else language
        settings["model_override"] = self.model_box.currentText()
        settings["device_override"] = self.device_box.currentText()
        settings["diarize"] = self.diarize_check.isChecked()
        settings["emotion"] = self.emotion_check.isChecked()
        settings["verbatim"] = self.verbatim_check.isChecked()
        settings["stance"] = self.stance_check.isChecked()
        settings["prosody"] = self.prosody_check.isChecked()
        settings["analysis"] = self.analysis_check.isChecked()
        settings["theme"] = "light" if self.light_radio.isChecked() else "dark"
        settings.save()

        window.log("Settings saved.")
        if (settings["model_override"], settings["device_override"]) != before:
            window.hw_text.setText("Re-checking what this machine can do…")
            window.hw_meta.setText("")
            window.detect_hardware()
        super().accept()


class DictionaryDialog(QtWidgets.QDialog):
    """Names and jargon the recordings contain, one per line.

    Whisper spells a name it has never seen by sound, so on one call the same
    person came out as Chom, Chon, Chong, John and Sean, and a product as "my
    cloth". The list goes to the Whisper pass as hotwords, which biases
    decoding toward these spellings. It is stored comma-separated in
    settings["vocabulary"] and applied when the models load, so it takes
    effect on the next Start.
    """

    def __init__(self, window):
        super().__init__(window)
        self.window_ref = window
        self.setWindowTitle("Dictionary")
        self.setMinimumSize(480, 440)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(10)

        layout.addWidget(window._label("Names and jargon, one per line", "sectionLabel"))
        hint = window._label(
            "People, companies and products the recordings mention. Whisper "
            "spells an unfamiliar name by sound, so one person can come out five "
            "different ways in a single call; a name written here is spelled "
            "this way instead. Applied the next time you press Start.",
            "rowStatus")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.editor = QtWidgets.QPlainTextEdit()
        self.editor.setObjectName("dictionary")
        self.editor.setPlaceholderText("Acme Robotics\nOpenRouter\nESG\nTypeform")
        self.editor.setPlainText("\n".join(split_terms(window.settings.get("vocabulary", ""))))
        layout.addWidget(self.editor, 1)

        self.count = window._label("", "sectionCount")
        layout.addWidget(self.count)
        self.editor.textChanged.connect(self._refresh_count)
        self._refresh_count()

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        cancel = QtWidgets.QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = QtWidgets.QPushButton("Save")
        save.setObjectName("primary")
        save.clicked.connect(self.accept)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def terms(self):
        return split_terms(self.editor.toPlainText())

    def _refresh_count(self):
        count = len(self.terms())
        self.count.setText("{0} term{1}".format(count, "" if count == 1 else "s")
                           if count else "No terms yet")

    def accept(self):
        terms = self.terms()
        settings = self.window_ref.settings
        settings["vocabulary"] = ", ".join(terms)
        settings.save()
        self.window_ref.log("Dictionary saved: {0} term{1}.".format(
            len(terms), "" if len(terms) == 1 else "s"))
        super().accept()


def launch(initial_files=()):
    app = QtWidgets.QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)

    icon_path = Path(__file__).resolve().parent.parent / "revolv.ico"
    if getattr(sys, "frozen", False):
        icon_path = Path(sys._MEIPASS) / "revolv.ico"
    if icon_path.exists():
        app.setWindowIcon(QtGui.QIcon(str(icon_path)))

    window = MainWindow(initial_files)
    window.show()
    return app.exec()
