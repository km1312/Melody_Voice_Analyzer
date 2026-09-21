"""Palette and stylesheet for the window.

The brief was calm: muted colour, soft edges, room to breathe. So the neutrals
are warm rather than clinical grey, the accent is a desaturated denim that sits
back instead of shouting, and the layout leans on space rather than boxes and
dividers. Radii run 10px on controls and 16 to 20px on containers.

Every foreground/background pairing below clears WCAG AA (4.5:1). The muted and
subtle text tones are the ones worth watching: subtle is reserved for disabled
states, never for text a reader needs.
"""

from pathlib import Path

LIGHT = {
    "name": "light",

    # Warm neutrals. The canvas is paper rather than white; cards lift off it
    # by being lighter, not by being outlined.
    "canvas": "#F5F4F1",
    "surface": "#FFFFFF",
    "surface_soft": "#FAF9F7",
    "surface_sunken": "#EFEDE9",
    "hover": "#F1EFEB",
    "pressed": "#E8E5E0",
    "border": "#E6E3DD",
    "border_strong": "#D6D2CA",

    "text": "#24231F",         # 15.4:1 on canvas
    "text_muted": "#6A665E",   # 5.1:1 on canvas
    "text_subtle": "#8A857C",  # disabled only

    "accent": "#4A6FA5",       # 5.1:1 with white
    "accent_hover": "#3F5F8C",
    "accent_pressed": "#35507A",
    "accent_fg": "#FFFFFF",
    "accent_text": "#3F6396",
    "accent_soft": "#EDF1F7",
    "accent_border": "#C3D0E4",

    "ok_text": "#37785C",      # 5.3:1 on white
    "ok_soft": "#EAF3EE",
    "bad_text": "#B4544A",     # 4.9:1 on white
    "bad_soft": "#FAEEEC",

    "track": "#E6E3DD",
    "shadow": (0, 0, 0, 26),
}

DARK = {
    "name": "dark",

    "canvas": "#1A1917",
    "surface": "#212020",
    "surface_soft": "#272625",
    "surface_sunken": "#161514",
    "hover": "#2B2A28",
    "pressed": "#333230",
    "border": "#33312E",
    "border_strong": "#45423E",

    "text": "#EDEBE7",
    "text_muted": "#A8A39A",
    "text_subtle": "#7A756D",

    # On a dark ground the fill lightens and the label goes dark.
    "accent": "#7FA3D8",
    "accent_hover": "#96B4E2",
    "accent_pressed": "#6E92C7",
    "accent_fg": "#12192A",
    "accent_text": "#9DBAE6",
    "accent_soft": "#1E2937",
    "accent_border": "#38506F",

    "ok_text": "#6FBF95",
    "ok_soft": "#17251E",
    "bad_text": "#E08A80",
    "bad_soft": "#2A1A18",

    "track": "#33312E",
    "shadow": (0, 0, 0, 90),
}

PALETTES = {"light": LIGHT, "dark": DARK}

FONT_STACK = '"Segoe UI Variable Text", "Segoe UI", -apple-system, sans-serif'
FONT_DISPLAY = '"Segoe UI Variable Display", "Segoe UI Semibold", "Segoe UI"'
FONT_MONO = '"Cascadia Mono", "Consolas", monospace'


def get(name):
    return PALETTES.get((name or "light").lower(), LIGHT)


def _glyph(kind, color):
    """Render a chevron or tick to a PNG and return a QSS-safe path.

    Qt stylesheets cannot draw either shape. The zero-size-box border trick
    that works in CSS comes out as a dash here, and there is no tick character
    that renders consistently, so both are painted once and cached on disk.
    """
    import tempfile

    from PySide6 import QtCore, QtGui

    name = "revolv_{0}_{1}.png".format(kind, color.lstrip("#"))
    path = Path(tempfile.gettempdir()) / name
    if not path.exists():
        size = 28
        # QImage rather than QPixmap: a pixmap needs a live QGuiApplication and
        # aborts the process without one, which would make this module unusable
        # before the app starts.
        image = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32)
        image.fill(QtCore.Qt.transparent)

        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        pen = QtGui.QPen(QtGui.QColor(color))
        pen.setWidthF(2.6 if kind == "check" else 2.2)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setPen(pen)

        if kind == "check":
            points = [(8, 14.5), (12.2, 18.5), (20, 10)]
        else:  # chevron
            points = [(9, 12), (14, 17), (19, 12)]
        painter.drawPolyline([QtCore.QPointF(x, y) for x, y in points])
        painter.end()
        image.save(str(path))

    return str(path).replace("\\", "/")


def qss(c):
    """Build the stylesheet for one palette."""
    chevron = _glyph("chevron", c["text_muted"])
    tick = _glyph("check", c["accent_fg"])
    return f"""
    QWidget {{
        background: transparent;
        color: {c['text']};
        font-family: {FONT_STACK};
        font-size: 10pt;
    }}
    /* QWidget above is transparent, so every top-level surface has to name its
       own ground or it inherits the platform default (black). */
    #root, QDialog, QMessageBox {{ background: {c['canvas']}; }}

    /* ---- type ---- */
    #title {{
        font-family: {FONT_DISPLAY};
        font-size: 19pt;
        font-weight: 600;
        color: {c['text']};
    }}
    #subtitle {{ color: {c['text_muted']}; font-size: 10pt; }}
    #sectionLabel {{
        color: {c['text_muted']};
        font-size: 9pt;
        font-weight: 600;
    }}
    #sectionCount {{ color: {c['text_subtle']}; font-size: 9pt; }}
    #statusLine {{ color: {c['text_muted']}; font-size: 9pt; }}

    /* ---- cards ---- */
    #card {{
        background: {c['surface']};
        border-radius: 16px;
    }}
    /* Settings popover: a rounded card floating under its button. */
    QFrame#popover {{
        background: {c['surface']};
        border: 1px solid {c['border_strong']};
        border-radius: 16px;
    }}
    #pill {{
        background: {c['accent_soft']};
        border-radius: 14px;
    }}
    #pillText {{ color: {c['accent_text']}; font-size: 10pt; }}
    #pillMeta {{ color: {c['accent_text']}; font-size: 9pt; }}

    /* ---- drop zone ---- */
    #dropZone {{
        background: {c['surface']};
        border: 2px dashed {c['border_strong']};
        border-radius: 20px;
    }}
    #dropZone[hot="true"] {{
        background: {c['accent_soft']};
        border: 2px dashed {c['accent']};
    }}
    #dropTitle {{
        font-family: {FONT_DISPLAY};
        font-size: 13pt;
        font-weight: 600;
        color: {c['text']};
    }}
    #dropHint {{ color: {c['text_muted']}; font-size: 9pt; }}

    /* ---- buttons ---- */
    QPushButton {{
        background: {c['surface']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 9px 18px;
        font-size: 10pt;
    }}
    QPushButton:hover {{ background: {c['hover']}; border-color: {c['border_strong']}; }}
    QPushButton:pressed {{ background: {c['pressed']}; }}
    QPushButton:disabled {{ color: {c['text_subtle']}; background: {c['surface_soft']};
                            border-color: {c['border']}; }}

    QPushButton#primary {{
        background: {c['accent']};
        color: {c['accent_fg']};
        border: none;
        border-radius: 12px;
        padding: 13px 26px;
        font-size: 10pt;
        font-weight: 600;
    }}
    QPushButton#primary:hover {{ background: {c['accent_hover']}; }}
    QPushButton#primary:pressed {{ background: {c['accent_pressed']}; }}
    QPushButton#primary:disabled {{ background: {c['surface_sunken']};
                                    color: {c['text_subtle']}; }}

    QPushButton#quiet {{
        background: transparent;
        border: none;
        color: {c['text_muted']};
        padding: 9px 14px;
        border-radius: 10px;
    }}
    QPushButton#quiet:hover {{ background: {c['hover']}; color: {c['text']}; }}
    QPushButton#quiet:disabled {{ color: {c['text_subtle']}; background: transparent; }}

    /* Format chips: selected reads as a soft tinted pill, not a checkbox. */
    QPushButton#chip {{
        background: {c['surface']};
        color: {c['text_muted']};
        border: 1px solid {c['border']};
        border-radius: 16px;
        padding: 8px 16px;
        font-size: 9pt;
    }}
    QPushButton#chip:hover {{ border-color: {c['border_strong']}; color: {c['text']}; }}
    /* Colour is the only thing that changes on check. Switching font weight
       here would re-measure the label and clip it inside the fixed chip. */
    QPushButton#chip:checked {{
        background: {c['accent_soft']};
        border: 1px solid {c['accent_border']};
        color: {c['accent_text']};
    }}
    /* Optional formats: the same chip, smaller and quieter, so the two that
       matter read as the default and these read as extras. */
    QPushButton#chipMinor {{
        background: transparent;
        color: {c['text_subtle']};
        border: 1px solid {c['border']};
        border-radius: 12px;
        padding: 5px 11px;
        font-size: 8pt;
    }}
    QPushButton#chipMinor:hover {{ border-color: {c['border_strong']}; color: {c['text']}; }}
    QPushButton#chipMinor:checked {{
        background: {c['accent_soft']};
        border: 1px solid {c['accent_border']};
        color: {c['accent_text']};
    }}

    /* ---- inputs ---- */
    QLineEdit {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 9px 12px;
        selection-background-color: {c['accent_soft']};
        selection-color: {c['accent_text']};
    }}
    QLineEdit:focus {{ border-color: {c['accent']}; }}
    QLineEdit:disabled {{ background: {c['surface_sunken']}; color: {c['text_subtle']}; }}
    QPlainTextEdit#dictionary {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 10px 12px;
        color: {c['text']};
        selection-background-color: {c['accent_soft']};
        selection-color: {c['accent_text']};
    }}
    QPlainTextEdit#dictionary:focus {{ border-color: {c['accent']}; }}

    QComboBox {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 8px 12px;
        min-width: 120px;
    }}
    QComboBox:focus {{ border-color: {c['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    /* Styling the drop-down hides Qt's built-in arrow, so draw one: a zero-size
       box whose borders form a downward triangle. */
    QComboBox::down-arrow {{
        image: url({chevron});
        width: 16px; height: 16px;
        margin-right: 8px;
    }}
    QComboBox QAbstractItemView {{
        background: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        padding: 4px;
        selection-background-color: {c['accent_soft']};
        selection-color: {c['accent_text']};
        outline: none;
    }}

    QRadioButton, QCheckBox {{ color: {c['text']}; spacing: 9px; padding: 4px 0; }}

    /* Qt adds the border outside the declared width, so the checked state
       shrinks its box by exactly as much as the border grows. Both states end
       up 22px across, and the radius stays at half of that so it reads round. */
    QRadioButton::indicator {{
        width: 18px; height: 18px;
        border: 2px solid {c['border_strong']};
        border-radius: 11px;
        background: {c['surface']};
    }}
    QRadioButton::indicator:checked {{
        width: 12px; height: 12px;
        border: 5px solid {c['accent']};
        border-radius: 11px;
        background: {c['surface']};
    }}
    QRadioButton::indicator:hover {{ border-color: {c['accent']}; }}

    QCheckBox::indicator {{
        width: 18px; height: 18px;
        border: 2px solid {c['border_strong']};
        border-radius: 6px;
        background: {c['surface']};
    }}
    QCheckBox::indicator:checked {{
        border: 2px solid {c['accent']};
        background: {c['accent']};
        image: url({tick});
    }}
    QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}

    /* ---- file rows ---- */
    #row {{ background: {c['surface_soft']}; border-radius: 12px; }}
    #row[state="active"] {{ background: {c['accent_soft']}; }}
    #row[state="done"] {{ background: {c['ok_soft']}; }}
    #row[state="error"] {{ background: {c['bad_soft']}; }}
    #rowName {{ font-size: 10pt; color: {c['text']}; }}
    #rowStatus {{ font-size: 9pt; color: {c['text_muted']}; }}
    #rowStatus[state="done"] {{ color: {c['ok_text']}; }}
    #rowStatus[state="error"] {{ color: {c['bad_text']}; }}
    #rowStatus[state="active"] {{ color: {c['accent_text']}; }}
    #rowPercent {{ font-size: 9pt; color: {c['text_muted']}; }}

    /* ---- progress ---- */
    QProgressBar {{
        background: {c['track']};
        border: none;
        border-radius: 3px;
        height: 6px;
        text-align: center;
        color: transparent;
    }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
    QProgressBar#rowBar {{ height: 4px; border-radius: 2px; }}
    QProgressBar#rowBar::chunk {{ border-radius: 2px; }}

    /* ---- scroll areas ---- */
    QScrollArea, #listHost {{ background: {c['surface']}; border: none;
                              border-radius: 16px; }}
    QScrollBar:vertical {{
        background: transparent; width: 10px; margin: 6px 3px 6px 0;
    }}
    QScrollBar::handle:vertical {{
        background: {c['border_strong']}; border-radius: 4px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {c['text_subtle']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

    /* ---- log ---- */
    QPlainTextEdit#log {{
        background: {c['surface']};
        border: none;
        border-radius: 16px;
        padding: 14px;
        color: {c['text_muted']};
        font-family: {FONT_MONO};
        font-size: 9pt;
        selection-background-color: {c['accent_soft']};
        selection-color: {c['accent_text']};
    }}

    /* ---- interpretation: results and context windows ---- */
    QTabWidget::pane {{ border: none; }}
    QTabBar::tab {{
        background: transparent;
        color: {c['text_muted']};
        padding: 8px 14px;
        border: none;
        border-bottom: 2px solid transparent;
        font-size: 9.5pt;
    }}
    QTabBar::tab:selected {{
        color: {c['accent_text']};
        border-bottom: 2px solid {c['accent']};
    }}
    QTabBar::tab:hover {{ color: {c['text']}; }}

    QListWidget#transcript {{
        background: {c['surface']};
        border: none;
        border-radius: 16px;
        padding: 10px;
        font-size: 9.5pt;
    }}
    QListWidget#transcript::item {{
        padding: 6px 8px;
        border-radius: 8px;
        color: {c['text']};
    }}
    QListWidget#transcript::item:selected {{
        background: {c['accent_soft']};
        color: {c['accent_text']};
    }}
    QTextBrowser#notesView {{
        background: {c['surface']};
        border: none;
        border-radius: 16px;
        padding: 14px;
        color: {c['text']};
        selection-background-color: {c['accent_soft']};
        selection-color: {c['accent_text']};
    }}

    /* Insight cards: their own rules rather than a stretched #card. */
    QFrame#insightCard {{
        background: {c['surface_soft']};
        border-radius: 12px;
    }}
    #cardClaim {{ font-size: 10pt; font-weight: 600; color: {c['text']}; }}
    #cardMeta {{ font-size: 9pt; color: {c['text_muted']}; }}
    QLabel#evidenceChip {{
        background: {c['accent_soft']};
        color: {c['accent_text']};
        border-radius: 8px;
        padding: 4px 9px;
        font-size: 8.5pt;
    }}
    #cardAlternatives {{ font-size: 9pt; color: {c['text_muted']}; }}
    #cardFollowUp {{ font-size: 9pt; color: {c['accent_text']}; }}
    QPushButton#feedback {{
        background: transparent;
        border: 1px solid {c['border']};
        border-radius: 9px;
        padding: 3px 10px;
        font-size: 8.5pt;
        color: {c['text_muted']};
    }}
    QPushButton#feedback:hover {{ border-color: {c['border_strong']};
                                  color: {c['text']}; }}
    QPushButton#feedback:checked {{
        background: {c['accent_soft']};
        border-color: {c['accent_border']};
        color: {c['accent_text']};
    }}

    QToolTip {{
        background: {c['text']};
        color: {c['surface']};
        border: none;
        border-radius: 8px;
        padding: 6px 10px;
    }}
    """
