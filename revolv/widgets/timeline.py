"""The per-speaker timeline (FR-12): one lane per baselined speaker.

Ticks are the report's moments, coloured by feature family; hollow gaps mark
silences of two seconds or more; pins sit where a kept reading cites its
first turn. Clicking anything plays from 1.5 s before the turn to its end.

All the arithmetic lives in module functions (`build_marks`, `time_to_x`,
`x_to_time`, `TimelineWidget.hit_test`) so the maths is testable offscreen
without painting a pixel (M5.4).
"""

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, Signal

from ..interpret.verify import PLAY_LEAD_SECONDS

# The family map, one table (PRD M5.3).
FEATURE_FAMILY = {
    "articulation": "pace",
    "f0_range": "pitch",
    "terminal_rise": "pitch",
    "arousal": "energy",
    "loudness_sd": "energy",
    "mismatch": "energy",
    "medial_fillers": "hesitation",
    "certainty": "hesitation",
}
FAMILIES = ("pace", "pitch", "energy", "hesitation", "silence")

# Palette keys per family; the widget resolves them against theme.get().
FAMILY_COLOR_KEYS = {
    "pace": "accent",
    "pitch": "ok_text",
    "energy": "bad_text",
    "hesitation": "accent_text",
    "silence": "text_subtle",
}

SILENCE_MARK_SECONDS = 2.0

LANE_HEIGHT = 26
LANE_GAP = 6
LABEL_WIDTH = 96
TICK_WIDTH = 3
PIN_RADIUS = 5


def time_to_x(ms, total_ms, width):
    if total_ms <= 0:
        return 0.0
    return width * (ms / total_ms)


def x_to_time(x, total_ms, width):
    if width <= 0:
        return 0
    return int(total_ms * (x / width))


def moment_family(moment):
    for item in moment.get("evidence") or []:
        family = FEATURE_FAMILY.get(item.get("feature"))
        if family:
            return family
    return "silence"  # pause-only moments


def build_marks(report, insights=None, subtext=True):
    """(lanes, marks): lanes are baselined speakers by talk share; marks are
    plain dicts the widget draws and the tests assert on."""
    speakers = report.get("speakers") or {}
    lanes = [name for name in sorted(
        speakers, key=lambda n: -(speakers[n].get("talk_share") or 0))
        if (speakers[name].get("baseline_turns") or 0) > 0]
    lane_of = {name: i for i, name in enumerate(lanes)}
    turns = report.get("turns") or []
    marks = []

    for moment in report.get("moments") or []:
        turn = turns[moment["turn"]]
        lane = lane_of.get(moment["speaker"])
        if lane is None:
            continue
        marks.append({
            "kind": "tick",
            "lane": lane,
            "family": moment_family(moment),
            "start_ms": round(float(turn["start"]) * 1000),
            "end_ms": round(float(turn["end"]) * 1000),
            "turn_index": moment["turn"],
        })

    previous_end = None
    for turn in turns:
        start = float(turn["start"])
        if previous_end is not None and \
                start - previous_end >= SILENCE_MARK_SECONDS:
            marks.append({
                "kind": "silence",
                "lane": None,
                "family": "silence",
                "start_ms": round(previous_end * 1000),
                "end_ms": round(start * 1000),
                "turn_index": turn["index"],
            })
        previous_end = float(turn["end"])

    if subtext:
        for insight in insights or []:
            evidence = insight.get("evidence") or []
            if not evidence:
                continue
            lane = lane_of.get(insight.get("speaker"))
            if lane is None:
                continue
            audio_range = insight.get("audio_range") or {}
            marks.append({
                "kind": "pin",
                "lane": lane,
                "family": None,
                "start_ms": audio_range.get("start_ms", 0),
                "end_ms": audio_range.get("end_ms", 0),
                "insight_id": insight.get("id"),
                "key": insight.get("key"),
            })
    return lanes, marks


class TimelineWidget(QtWidgets.QWidget):
    """Draws the lanes; clicks come back as (start_ms, end_ms, payload)."""

    rangeClicked = Signal(int, int, dict)

    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self.colors = palette
        self.lanes = []
        self.marks = []
        self.total_ms = 1
        self.names = {}
        self.setMinimumHeight(LANE_HEIGHT + LANE_GAP)
        self.setCursor(Qt.PointingHandCursor)

    def set_palette(self, palette):
        self.colors = palette
        self.update()

    def set_data(self, report, insights=None, names=None, subtext=True):
        self.lanes, self.marks = build_marks(report, insights,
                                             subtext=subtext)
        media = (report.get("summary") or {}).get("media_seconds") or 0
        last_turn = max((float(t["end"]) for t in report.get("turns") or []),
                        default=0.0)
        self.total_ms = max(int(max(media, last_turn) * 1000), 1)
        self.names = names or {}
        height = len(self.lanes) * (LANE_HEIGHT + LANE_GAP) + LANE_GAP
        self.setMinimumHeight(max(height, LANE_HEIGHT + LANE_GAP))
        self.update()

    # -- geometry -----------------------------------------------------------
    def _track_width(self):
        return max(self.width() - LABEL_WIDTH, 1)

    def _lane_top(self, lane):
        return LANE_GAP + lane * (LANE_HEIGHT + LANE_GAP)

    def mark_rect(self, mark):
        """Where a mark is drawn, in widget coordinates."""
        width = self._track_width()
        x0 = LABEL_WIDTH + time_to_x(mark["start_ms"], self.total_ms, width)
        x1 = LABEL_WIDTH + time_to_x(mark["end_ms"], self.total_ms, width)
        if mark["kind"] == "silence":
            top = 0
            height = self.height()
            return QtCore.QRectF(x0, top, max(x1 - x0, 1.5), height)
        top = self._lane_top(mark["lane"])
        if mark["kind"] == "pin":
            centre = (x0 + x1) / 2
            return QtCore.QRectF(centre - PIN_RADIUS, top - 2,
                                 PIN_RADIUS * 2, PIN_RADIUS * 2)
        return QtCore.QRectF(x0, top + 3, max(x1 - x0, TICK_WIDTH),
                             LANE_HEIGHT - 6)

    def hit_test(self, x, y):
        """The topmost mark under (x, y), pins first, else None."""
        point = QtCore.QPointF(x, y)
        for mark in self.marks:
            if mark["kind"] == "pin" and \
                    self.mark_rect(mark).adjusted(-2, -2, 2, 2).contains(point):
                return mark
        for mark in self.marks:
            if mark["kind"] != "pin" and \
                    self.mark_rect(mark).adjusted(-2, 0, 2, 0).contains(point):
                return mark
        return None

    # -- interaction ---------------------------------------------------------
    def mouseReleaseEvent(self, event):
        mark = self.hit_test(event.position().x(), event.position().y())
        if mark is None:
            return
        lead = int(PLAY_LEAD_SECONDS * 1000)
        if mark["kind"] == "pin":
            begin, end = mark["start_ms"], mark["end_ms"]
        else:
            begin = max(mark["start_ms"] - lead, 0)
            end = mark["end_ms"]
        self.rangeClicked.emit(begin, end, mark)

    # -- painting ------------------------------------------------------------
    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        colors = self.colors

        for lane, name in enumerate(self.lanes):
            top = self._lane_top(lane)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QtGui.QColor(colors["surface_sunken"]))
            painter.drawRoundedRect(
                QtCore.QRectF(LABEL_WIDTH, top, self._track_width(),
                              LANE_HEIGHT), 6, 6)
            painter.setPen(QtGui.QColor(colors["text_muted"]))
            painter.drawText(
                QtCore.QRectF(0, top, LABEL_WIDTH - 8, LANE_HEIGHT),
                Qt.AlignRight | Qt.AlignVCenter,
                self.names.get(name, name))

        for mark in self.marks:
            if mark["kind"] != "silence":
                continue
            painter.setPen(Qt.NoPen)
            colour = QtGui.QColor(colors["text_subtle"])
            colour.setAlpha(60)
            painter.setBrush(colour)
            painter.drawRect(self.mark_rect(mark))

        for mark in self.marks:
            if mark["kind"] != "tick":
                continue
            key = FAMILY_COLOR_KEYS.get(mark["family"], "accent")
            painter.setPen(Qt.NoPen)
            painter.setBrush(QtGui.QColor(colors[key]))
            painter.drawRoundedRect(self.mark_rect(mark), 2, 2)

        for mark in self.marks:
            if mark["kind"] != "pin":
                continue
            painter.setPen(QtGui.QPen(QtGui.QColor(colors["surface"]), 1.5))
            painter.setBrush(QtGui.QColor(colors["accent"]))
            painter.drawEllipse(self.mark_rect(mark))
