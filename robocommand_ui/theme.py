"""Design tokens and the global stylesheet for the host console.

Matches the nala2-report OCS monitor (``qtui.py``) so the host and the team
GCS read as one system: neutral graphite surfaces, 12 px panels with a dot
title and a mono topic tag, pill tabs, and muted status colours that turn
into solid chips for terminal states (ok / warn / fault). Vehicle-type
colours are the OCS ones (USV green, UAV blue, UUV violet). Every widget
takes its colours from here; none hardcode their own palette.
"""

from typing import Iterable

from PyQt5.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt5.QtWidgets import QApplication

# ---- surfaces (OCS dark palette) ------------------------------------------
BG = "#0f1115"            # window
BG_ALT = "#12141a"
SURFACE = "#1a1d24"       # panels
SURFACE_2 = "#15181e"     # cards, inputs
SURFACE_3 = "#232833"     # hover
WELL = "#0c0e12"          # logs, tables, map wells
BORDER = "#2d313a"
BORDER_SOFT = "#232630"
BORDER_STRONG = "#3a4049"

# ---- text -----------------------------------------------------------------
TEXT = "#d5dae2"
TEXT_STRONG = "#f2f4f7"
TEXT_MUTED = "#98a1ae"
TEXT_FAINT = "#7d8794"

# ---- semantic -------------------------------------------------------------
ACCENT = "#7ba3cf"        # focus, links, selection
ACCENT_HOVER = "#8fb4dd"
SELECTION = "#2c4a6e"
OK = "#6fa96d"
WARN = "#d2a13f"
FAULT = "#cf5f56"
INFO = "#7ba3cf"
IDLE = "#7d8794"

# Solid chip / primary-button fills for terminal states: tone -> (fill, text)
SOLID = {
    OK: ("#3e7a46", "#f0faf1"),
    WARN: ("#b3862f", "#1c1406"),
    FAULT: ("#a94a42", "#fdf2f0"),
}
NEUTRAL_SOLID = ("#3a4049", "#e8ecf1")
PRIMARY, ON_PRIMARY = SOLID[OK]
PRIMARY_HOVER = "#4a8c53"

# ---- vehicle types (not status) -------------------------------------------
TYPE_COLORS = {
    "USV": "#6fa96d",
    "UAV": "#7ba3cf",
    "UUV": "#a58ccb",
}
TYPE_UNKNOWN = "#98a1ae"

# ---- map ------------------------------------------------------------------
MAP_WATER = WELL
MAP_GRID = "#1b1e25"
MAP_GRID_LABEL = "#4a5160"
MAP_BOUNDARY = "#f2f4f7"
MAP_GEOFENCE = "#d2a13f"
MAP_PIN = "#e8b04b"

# ---- metrics --------------------------------------------------------------
RADIUS_SM = 6
RADIUS = 8
RADIUS_LG = 12
RADIUS_PILL = 10
SPACE = 8                 # base unit; dense dashboard rhythm is 4/8/12/16

UI_FONTS = ("Inter", "Roboto", "IBM Plex Sans", "Noto Sans", "Liberation Sans",
            "DejaVu Sans", "Arial")
MONO_FONTS = ("JetBrains Mono", "Fira Code", "Cascadia Mono", "Liberation Mono",
              "Noto Sans Mono", "DejaVu Sans Mono")


def _first_installed(candidates: Iterable[str], fallback: str) -> str:
    installed = {name.lower(): name for name in QFontDatabase().families()}
    for name in candidates:
        if name.lower() in installed:
            return installed[name.lower()]
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


def chip_style(color: str) -> str:
    """OCS chip: solid fill for ok / warn / fault, outline in the tone otherwise."""
    if color in SOLID:
        fill, text = SOLID[color]
        return f"color: {text}; background: {fill}; border: 1px solid {fill};"
    return f"color: {color}; background: transparent; border: 1px solid {BORDER};"


def _family(name: str) -> str:
    return f'"{name}"'


def stylesheet() -> str:
    ui, mono = _family(ui_family()), _family(mono_family())
    fault_fill = SOLID[FAULT][0]
    return f"""
    * {{ font-family: {ui}; font-size: 13px; color: {TEXT}; }}
    QMainWindow, QWidget#Root {{ background: {BG}; }}
    QWidget {{ background: transparent; }}
    QToolTip {{ background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER};
                padding: 5px 8px; border-radius: {RADIUS_SM}px; }}

    /* header + footer */
    QFrame#Header {{ background: {SURFACE}; border: none; border-bottom: 1px solid {BORDER}; }}
    QLabel#Brand {{ font-size: 17px; font-weight: 700; color: {TEXT_STRONG}; }}
    QLabel#BrandSub {{ color: {TEXT_MUTED}; font-size: 12px; }}
    QLabel#Clock {{ font-family: {mono}; font-size: 17px; font-weight: 600; color: {TEXT}; }}
    QLabel#ClockDate {{ color: {TEXT_FAINT}; font-size: 11px; }}
    QStatusBar {{ background: {SURFACE}; color: {TEXT_FAINT}; border-top: 1px solid {BORDER};
                  font-size: 11px; font-weight: 600; }}
    QStatusBar QLabel {{ color: {TEXT_FAINT}; font-size: 11px; font-weight: 600; }}

    /* panels */
    QFrame#Panel {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS_LG}px; }}
    QLabel#PanelTitle {{ color: {TEXT_STRONG}; font-size: 14px; font-weight: 700; }}
    QLabel#PanelMeta {{ color: {TEXT_FAINT}; font-family: {mono}; font-size: 11px; }}
    QLabel#PanelDot {{ font-size: 10px; }}
    QFrame#Card {{ background: {SURFACE_2}; border: 1px solid {BORDER_SOFT}; border-radius: {RADIUS}px; }}
    QLabel#Muted {{ color: {TEXT_MUTED}; }}
    QLabel#Faint {{ color: {TEXT_FAINT}; font-size: 12px; }}
    QLabel#Mono {{ font-family: {mono}; }}
    QLabel#Empty {{ color: {TEXT_MUTED}; font-size: 12px; font-weight: 700; padding: 18px;
                    border: 1px dashed {BORDER}; border-radius: {RADIUS}px; }}
    QLabel#FormHeading {{ color: {TEXT_MUTED}; font-size: 11px; font-weight: 700; padding-top: 6px; }}

    /* chips */
    QLabel[chip="true"] {{ border-radius: {RADIUS_PILL}px; padding: 2px 9px; font-size: 11px;
                           font-weight: 700; }}

    /* tabs */
    QTabWidget::pane {{ background: {BG}; border: none; top: -1px; }}
    QTabBar {{ background: {SURFACE}; qproperty-drawBase: 0; }}
    QTabBar::tab {{ background: transparent; color: {TEXT_MUTED}; border: 1px solid transparent;
                    border-radius: {RADIUS}px; padding: 7px 15px; margin: 3px;
                    font-size: 12px; font-weight: 700; }}
    QTabBar::tab:hover {{ background: {SURFACE_3}; color: {TEXT}; }}
    QTabBar::tab:selected {{ color: {TEXT_STRONG}; background: {BG}; border: 1px solid {BORDER}; }}

    /* inputs */
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
        background: {WELL}; border: 1px solid {BORDER_SOFT}; border-radius: {RADIUS_SM}px;
        padding: 4px 8px; min-height: 20px; selection-background-color: {SELECTION}; }}
    QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{ border-color: {BORDER}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
    QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
        color: {TEXT_FAINT}; background: {SURFACE_2}; }}
    QComboBox::drop-down {{ border: none; width: 18px; }}
    QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {BORDER};
                                   selection-background-color: {SELECTION}; outline: 0; padding: 4px; }}
    QSpinBox::up-button, QSpinBox::down-button,
    QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 14px; border: none; }}
    QCheckBox {{ spacing: 6px; }}
    QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {BORDER};
                            border-radius: 4px; background: {WELL}; }}
    QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

    /* buttons */
    QPushButton {{ background: {SURFACE_2}; color: {TEXT}; border: 1px solid {BORDER};
                   border-radius: {RADIUS}px; padding: 5px 12px; font-size: 12px; font-weight: 700; }}
    QPushButton:hover {{ background: {SURFACE_3}; border-color: {ACCENT}; }}
    QPushButton:pressed {{ background: {SURFACE}; }}
    QPushButton:focus {{ border-color: {ACCENT}; }}
    QPushButton:disabled {{ color: {TEXT_FAINT}; background: {SURFACE_2}; border-color: {BORDER_SOFT}; }}
    QPushButton#Primary {{ background: {PRIMARY}; color: {ON_PRIMARY}; border: 1px solid {PRIMARY}; }}
    QPushButton#Primary:hover {{ background: {PRIMARY_HOVER}; border-color: {PRIMARY_HOVER}; }}
    QPushButton#Primary:disabled {{ color: {TEXT_FAINT}; background: {SURFACE_2}; border-color: {BORDER_SOFT}; }}
    QPushButton#Danger {{ background: transparent; color: {FAULT}; border: 1px solid {FAULT}; }}
    QPushButton#Danger:hover {{ background: {fault_fill}; color: {SOLID[FAULT][1]}; }}
    QPushButton#Ghost {{ background: {SURFACE_2}; color: {TEXT_MUTED}; border: 1px solid {BORDER};
                         padding: 4px 12px; font-size: 11px; }}
    QPushButton#Ghost:hover {{ color: {TEXT}; background: {SURFACE_3}; border-color: {ACCENT}; }}
    QPushButton#Ghost:checked {{ color: {TEXT_STRONG}; border-color: {ACCENT}; }}

    /* tables */
    QTableWidget {{ background: {WELL}; border: 1px solid {BORDER_SOFT}; border-radius: {RADIUS}px;
                    gridline-color: transparent; selection-background-color: {SELECTION};
                    alternate-background-color: {BG_ALT}; outline: none; }}
    QTableWidget::item {{ padding: 4px 6px; border-bottom: 1px solid {BORDER_SOFT}; }}
    QTableWidget::item:selected {{ background: {SELECTION}; color: #ffffff; }}
    QHeaderView::section {{ background: {SURFACE}; color: {TEXT_MUTED}; border: none;
                            border-bottom: 1px solid {BORDER}; padding: 5px 6px;
                            font-size: 11px; font-weight: 700; }}
    QTableCornerButton::section {{ background: {SURFACE}; border: none;
                                   border-bottom: 1px solid {BORDER}; }}

    /* log */
    QTextEdit#Log {{ background: {WELL}; border: 1px solid {BORDER_SOFT}; border-radius: {RADIUS}px;
                     font-family: {mono}; font-size: 12px; color: {TEXT}; padding: 6px 8px; }}

    /* scrolling + splitters */
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px 2px 2px 0; }}
    QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: {TEXT_FAINT}; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0 2px 2px 2px; }}
    QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px; min-width: 28px; }}
    QScrollBar::handle:horizontal:hover {{ background: {TEXT_FAINT}; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        width: 0; height: 0; background: transparent; }}
    QSplitter::handle {{ background: {BG}; }}
    QSplitter::handle:hover {{ background: {BORDER}; }}
    """


def apply(app: QApplication) -> None:
    """Apply palette + stylesheet so popups and native bits are dark too."""
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in (
        (QPalette.Window, BG), (QPalette.WindowText, TEXT), (QPalette.Base, WELL),
        (QPalette.AlternateBase, BG_ALT), (QPalette.Text, TEXT), (QPalette.Button, SURFACE_2),
        (QPalette.ButtonText, TEXT), (QPalette.Highlight, SELECTION),
        (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, SURFACE),
        (QPalette.ToolTipText, TEXT), (QPalette.PlaceholderText, TEXT_FAINT),
    ):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setFont(ui_font(10))
    app.setStyleSheet(stylesheet())
