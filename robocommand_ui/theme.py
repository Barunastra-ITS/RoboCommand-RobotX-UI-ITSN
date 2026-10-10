"""Design tokens and the global stylesheet for the host monitor.

Mission-control dark: slate surfaces, one green accent, and status colours
used only for meaning (ok / warn / fault). Vehicle-type colours are kept
distinct from status colours so a UAV is never mistaken for a warning.
Every widget takes its colours from here; none hardcode their own palette.
"""

from typing import Iterable

from PyQt5.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt5.QtWidgets import QApplication

# ---- surfaces -------------------------------------------------------------
BG = "#0B1120"            # window
SURFACE = "#111A2E"       # panels
SURFACE_2 = "#16213A"     # cards, inputs
SURFACE_3 = "#1E2A45"     # hover
BORDER = "#24324F"
BORDER_STRONG = "#334566"

# ---- text -----------------------------------------------------------------
TEXT = "#E2E8F0"
TEXT_MUTED = "#94A3B8"
TEXT_FAINT = "#64748B"

# ---- semantic -------------------------------------------------------------
ACCENT = "#22C55E"        # primary action, connected
ACCENT_HOVER = "#4ADE80"
ON_ACCENT = "#052E16"
OK = "#22C55E"
WARN = "#F59E0B"
FAULT = "#EF4444"
INFO = "#38BDF8"
IDLE = "#64748B"

# ---- vehicle types (not status) -------------------------------------------
TYPE_COLORS = {
    "USV": "#38BDF8",     # sky
    "UUV": "#A78BFA",     # violet
    "UAV": "#F472B6",     # pink
}
TYPE_UNKNOWN = "#94A3B8"

# ---- map ------------------------------------------------------------------
MAP_WATER = "#0A1628"
MAP_GRID = "#13233D"
MAP_GRID_LABEL = "#3B5275"
MAP_BOUNDARY = "#CBD5E1"
MAP_GEOFENCE = "#2DD4BF"

# ---- metrics --------------------------------------------------------------
RADIUS = 8
RADIUS_SM = 5
SPACE = 8                 # base unit; dense dashboard rhythm is 4/8/12/16

UI_FONTS = ("Inter", "Fira Sans", "IBM Plex Sans", "Noto Sans", "Ubuntu", "Cantarell", "DejaVu Sans")
MONO_FONTS = ("Fira Code", "FiraCode Nerd Font", "JetBrains Mono", "IBM Plex Mono",
              "Noto Sans Mono", "DejaVu Sans Mono")


def _first_installed(candidates: Iterable[str], fallback: str) -> str:
    installed = set(QFontDatabase().families())
    for name in candidates:
        if name in installed:
            return name
    return fallback


_ui_family = None
_mono_family = None


def ui_family() -> str:
    global _ui_family
    if _ui_family is None:
        _ui_family = _first_installed(UI_FONTS, QFont().defaultFamily())
    return _ui_family


def mono_family() -> str:
    global _mono_family
    if _mono_family is None:
        _mono_family = _first_installed(MONO_FONTS, "monospace")
    return _mono_family


def ui_font(pt: float = 10, weight: int = QFont.Normal) -> QFont:
    f = QFont(ui_family())
    f.setPointSizeF(pt)
    f.setWeight(weight)
    return f


def mono_font(pt: float = 10, weight: int = QFont.Normal) -> QFont:
    f = QFont(mono_family())
    f.setPointSizeF(pt)
    f.setWeight(weight)
    f.setStyleHint(QFont.Monospace)
    return f


def qcolor(hex_color: str, alpha: int = 255) -> QColor:
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c


def type_color(type_name: str) -> str:
    return TYPE_COLORS.get(type_name, TYPE_UNKNOWN)


def stylesheet() -> str:
    ui, mono = ui_family(), mono_family()
    return f"""
    * {{ font-family: "{ui}"; font-size: 10pt; color: {TEXT}; }}
    QMainWindow, QWidget#Root {{ background: {BG}; }}
    QWidget {{ background: transparent; }}
    QToolTip {{ background: {SURFACE_2}; color: {TEXT}; border: 1px solid {BORDER_STRONG};
                padding: 4px 6px; border-radius: {RADIUS_SM}px; }}

    /* header */
    QFrame#Header {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
    QLabel#Brand {{ font-weight: 700; letter-spacing: 2px; font-size: 10pt; color: {TEXT}; }}
    QLabel#BrandSub {{ color: {TEXT_FAINT}; font-size: 9pt; }}

    /* panels */
    QFrame#Panel {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS}px; }}
    QLabel#PanelTitle {{ color: {TEXT_MUTED}; font-size: 8pt; font-weight: 700; letter-spacing: 1.5px; }}
    QLabel#PanelMeta {{ color: {TEXT_FAINT}; font-size: 8pt; }}
    QLabel#Muted {{ color: {TEXT_MUTED}; }}
    QLabel#Faint {{ color: {TEXT_FAINT}; font-size: 9pt; }}
    QLabel#Mono {{ font-family: "{mono}"; }}
    QLabel#Empty {{ color: {TEXT_FAINT}; padding: 18px; }}

    /* chips */
    QLabel[chip="true"] {{ border-radius: 10px; padding: 2px 9px; font-size: 8pt; font-weight: 700;
                           letter-spacing: 0.5px; background: {SURFACE_2}; border: 1px solid {BORDER}; }}

    /* inputs */
    QLineEdit, QComboBox {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: {RADIUS_SM}px;
                            padding: 4px 8px; min-height: 20px; selection-background-color: {SURFACE_3}; }}
    QLineEdit:hover, QComboBox:hover {{ border-color: {BORDER_STRONG}; }}
    QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {TEXT_FAINT}; background: {SURFACE}; }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{ background: {SURFACE_2}; border: 1px solid {BORDER_STRONG};
                                   selection-background-color: {SURFACE_3}; outline: 0; padding: 4px; }}

    /* buttons */
    QPushButton {{ background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: {RADIUS_SM}px;
                   padding: 5px 12px; font-weight: 600; }}
    QPushButton:hover {{ background: {SURFACE_3}; border-color: {BORDER_STRONG}; }}
    QPushButton:pressed {{ background: {BORDER}; }}
    QPushButton:focus {{ border-color: {ACCENT}; }}
    QPushButton#Primary {{ background: {ACCENT}; color: {ON_ACCENT}; border: 1px solid {ACCENT}; }}
    QPushButton#Primary:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
    QPushButton#Danger {{ background: transparent; color: {FAULT}; border: 1px solid {FAULT}; }}
    QPushButton#Danger:hover {{ background: rgba(239, 68, 68, 0.12); }}
    QPushButton#Ghost {{ background: transparent; border: none; color: {TEXT_MUTED}; padding: 3px 8px; }}
    QPushButton#Ghost:hover {{ color: {TEXT}; background: {SURFACE_2}; }}
    QPushButton#Ghost:checked {{ color: {TEXT}; }}

    /* tables */
    QTableWidget {{ background: transparent; border: none; gridline-color: transparent;
                    selection-background-color: {SURFACE_3}; alternate-background-color: {SURFACE_2}; }}
    QTableWidget::item {{ padding: 4px 6px; border-bottom: 1px solid {BORDER}; }}
    QHeaderView::section {{ background: transparent; color: {TEXT_FAINT}; border: none;
                            border-bottom: 1px solid {BORDER}; padding: 4px 6px;
                            font-size: 8pt; font-weight: 700; }}

    /* log */
    QTextEdit#Log {{ background: {BG}; border: none; font-family: "{mono}"; font-size: 9pt;
                     color: {TEXT_MUTED}; padding: 6px; }}

    /* scrolling + splitters */
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {BORDER_STRONG}; border-radius: 3px; min-height: 24px; }}
    QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {BORDER_STRONG}; border-radius: 3px; min-width: 24px; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        width: 0; height: 0; background: transparent; }}
    QSplitter::handle {{ background: {BG}; }}
    QSplitter::handle:hover {{ background: {BORDER}; }}
    QStatusBar {{ background: {SURFACE}; color: {TEXT_FAINT}; border-top: 1px solid {BORDER}; }}
    """


def apply(app: QApplication) -> None:
    """Apply palette + stylesheet so popups and native bits are dark too."""
    pal = QPalette()
    for role, color in (
        (QPalette.Window, BG), (QPalette.WindowText, TEXT), (QPalette.Base, SURFACE_2),
        (QPalette.AlternateBase, SURFACE), (QPalette.Text, TEXT), (QPalette.Button, SURFACE_2),
        (QPalette.ButtonText, TEXT), (QPalette.Highlight, SURFACE_3),
        (QPalette.HighlightedText, TEXT), (QPalette.ToolTipBase, SURFACE_2),
        (QPalette.ToolTipText, TEXT), (QPalette.PlaceholderText, TEXT_FAINT),
    ):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setFont(ui_font(10))
    app.setStyleSheet(stylesheet())
