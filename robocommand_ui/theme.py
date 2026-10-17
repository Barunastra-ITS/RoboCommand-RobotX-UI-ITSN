"""Design tokens and the global stylesheet for the host console.

Two palettes share one set of token names: **light** (the default, for a
sunlit course tent) and **dark** (the nala2-report OCS monitor look, so the
host and the team GCS read as one system). Panels are 12 px surfaces with a
dot title and a mono topic tag, tabs are pills, and status colours turn into
solid chips for terminal states (ok / warn / fault). Vehicle-type colours
are the OCS ones (USV green, UAV blue, UUV violet).

Every widget takes its colours from here. ``set_mode`` swaps the module
tokens; ``apply`` restyles the running app, and ``resolve`` maps a colour
captured from the other palette (an import-time table, an inline style) to
the current one, so nothing needs rebuilding.
"""

import re
from typing import Dict, Iterable

from PyQt5.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt5.QtWidgets import QApplication

LIGHT, DARK = "light", "dark"
DEFAULT_MODE = LIGHT

# Token -> colour. Two tokens may share a colour only if they share it in
# both palettes (``resolve`` relies on that; tests check it).
PALETTES: Dict[str, Dict[str, str]] = {
    DARK: {
        # surfaces
        "BG": "#0f1115", "BG_ALT": "#12141a", "SURFACE": "#1a1d24", "SURFACE_2": "#15181e",
        "SURFACE_3": "#232833", "WELL": "#0c0e12",
        "BORDER": "#2d313a", "BORDER_SOFT": "#232630", "BORDER_STRONG": "#3a4049",
        # text
        "TEXT": "#d5dae2", "TEXT_STRONG": "#f2f4f7", "TEXT_MUTED": "#98a1ae",
        "TEXT_FAINT": "#7d8794",
        # semantic
        "ACCENT": "#7ba3cf", "ACCENT_HOVER": "#8fb4dd", "SELECTION": "#2c4a6e",
        "ON_SELECTION": "#fefefe",
        "OK": "#6fa96d", "WARN": "#d2a13f", "FAULT": "#cf5f56",
        # solid fills for terminal states: (fill, text on it)
        "OK_FILL": "#3e7a46", "ON_OK": "#f0faf1", "WARN_FILL": "#b3862f", "ON_WARN": "#1c1406",
        "FAULT_FILL": "#a94a42", "ON_FAULT": "#fdf2f0", "NEUTRAL_FILL": "#3a404a",
        "ON_NEUTRAL": "#e8ecf1", "PRIMARY_HOVER": "#4a8c53",
        "UUV": "#a58ccb",
        # map
        "MAP_WATER": "#0b0d11", "MAP_GRID": "#1b1e25", "MAP_BOUNDARY": "#f4f6f8",
        "MAP_GEOFENCE": "#d2a13e", "MAP_PIN": "#e8b04b", "MAP_DIM": "#0f1116",
    },
    LIGHT: {
        "BG": "#eef1f5", "BG_ALT": "#f7f9fb", "SURFACE": "#ffffff", "SURFACE_2": "#f5f7fa",
        "SURFACE_3": "#e8edf3", "WELL": "#fbfcfd",
        "BORDER": "#d3dae3", "BORDER_SOFT": "#e2e7ed", "BORDER_STRONG": "#b4bfcc",
        "TEXT": "#1d2633", "TEXT_STRONG": "#0b1220", "TEXT_MUTED": "#4a5565",
        "TEXT_FAINT": "#667080",
        "ACCENT": "#2563c9", "ACCENT_HOVER": "#1d4fa8", "SELECTION": "#d6e4f8",
        "ON_SELECTION": "#0b1221",
        "OK": "#2c7a3a", "WARN": "#9a6300", "FAULT": "#b8382c",
        "OK_FILL": "#2f8a40", "ON_OK": "#fdfffd", "WARN_FILL": "#e0a536", "ON_WARN": "#231703",
        "FAULT_FILL": "#c43d30", "ON_FAULT": "#fffefe", "NEUTRAL_FILL": "#dfe4ea",
        "ON_NEUTRAL": "#1d2634", "PRIMARY_HOVER": "#26773a",
        "UUV": "#7652b8",
        "MAP_WATER": "#e4eaf0", "MAP_GRID": "#cdd6e0", "MAP_BOUNDARY": "#fbfcfe",
        "MAP_GEOFENCE": "#c98a12", "MAP_PIN": "#e09a1f", "MAP_DIM": "#0f1117",
    },
}
# Same colour as another token in both palettes
ALIASES = {"INFO": "ACCENT", "IDLE": "TEXT_FAINT", "PRIMARY": "OK_FILL", "ON_PRIMARY": "ON_OK",
           "USV": "OK", "UAV": "ACCENT", "TYPE_UNKNOWN": "TEXT_MUTED"}

# Current-mode tokens (declared for readers and linters; ``_load`` fills them)
BG = BG_ALT = SURFACE = SURFACE_2 = SURFACE_3 = WELL = ""
BORDER = BORDER_SOFT = BORDER_STRONG = TEXT = TEXT_STRONG = TEXT_MUTED = ""
TEXT_FAINT = ACCENT = ACCENT_HOVER = SELECTION = ON_SELECTION = OK = ""
WARN = FAULT = OK_FILL = ON_OK = WARN_FILL = ON_WARN = ""
FAULT_FILL = ON_FAULT = NEUTRAL_FILL = ON_NEUTRAL = PRIMARY_HOVER = UUV = ""
MAP_WATER = MAP_GRID = MAP_BOUNDARY = MAP_GEOFENCE = MAP_PIN = MAP_DIM = ""
INFO = IDLE = PRIMARY = ON_PRIMARY = USV = UAV = ""
TYPE_UNKNOWN = ""

_mode = DEFAULT_MODE
SOLID: Dict[str, tuple] = {}
TYPE_COLORS: Dict[str, str] = {}
NEUTRAL_SOLID = ("", "")


def token(name: str, mode: str = "") -> str:
    palette = PALETTES[mode or _mode]
    return palette[ALIASES.get(name, name)]


def _load(mode: str) -> None:
    """Point the module tokens (BG, TEXT, OK, ...) at ``mode``'s palette."""
    global _mode, NEUTRAL_SOLID
    _mode = mode
    names = set(PALETTES[mode]) | set(ALIASES)
    g = globals()
    for name in names:
        g[name] = token(name)
    SOLID.clear()                       # tone -> (fill, text); kept as the same dict object
    SOLID.update({g["OK"]: (g["OK_FILL"], g["ON_OK"]),
                  g["WARN"]: (g["WARN_FILL"], g["ON_WARN"]),
                  g["FAULT"]: (g["FAULT_FILL"], g["ON_FAULT"])})
    NEUTRAL_SOLID = (g["NEUTRAL_FILL"], g["ON_NEUTRAL"])
    TYPE_COLORS.clear()
    TYPE_COLORS.update({"USV": g["USV"], "UAV": g["UAV"], "UUV": g["UUV"]})


def mode() -> str:
    return _mode


def _colour_index() -> Dict[str, str]:
    """Any palette's colour -> token name."""
    index = {}
    for palette in PALETTES.values():
        for name, colour in palette.items():
            index.setdefault(colour.lower(), name)
    return index


_INDEX = _colour_index()
_HEX = re.compile(r"#[0-9a-fA-F]{6}\b")


def resolve(colour: str) -> str:
    """A token colour from either palette, in the current palette (others unchanged)."""
    name = _INDEX.get(colour.lower())
    return PALETTES[_mode][name] if name else colour


def resolve_style(style: str) -> str:
    """Every token colour in a stylesheet, in the current palette."""
    return _HEX.sub(lambda m: resolve(m.group(0)), style)


_load(DEFAULT_MODE)

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
    c = QColor(resolve(hex_color))
    c.setAlpha(alpha)
    return c


def type_color(type_name: str) -> str:
    return TYPE_COLORS.get(type_name, TYPE_UNKNOWN)


def set_mode(new_mode: str) -> None:
    """Switch palette. Call ``apply`` afterwards to restyle a running app."""
    if new_mode not in PALETTES:
        raise ValueError(f"unknown theme mode '{new_mode}' (choose {', '.join(PALETTES)})")
    _load(new_mode)


def chip_style(color: str) -> str:
    """OCS chip: solid fill for ok / warn / fault, outline in the tone otherwise."""
    color = resolve(color)
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
    QFrame#Divider {{ background: {BORDER}; }}
    QLabel#Unit {{ color: {TEXT_MUTED}; font-family: {mono}; font-size: 12px; }}

    /* chips */
    QLabel[chip="true"] {{ border-radius: {RADIUS_PILL}px; padding: 2px 9px; font-size: 11px;
                           font-weight: 700; }}

    /* tabs */
    QTabWidget::pane {{ background: {BG}; border: none; top: -1px; }}
    QTabBar {{ background: {SURFACE}; qproperty-drawBase: 0; }}
    QWidget#TabCorner {{ background: {SURFACE}; }}
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
    QListWidget {{ background: {WELL}; border: 1px solid {BORDER_SOFT}; border-radius: {RADIUS}px;
                   outline: none; padding: 4px; }}
    QListWidget::item {{ padding: 7px 8px; border-radius: {RADIUS_SM}px; color: {TEXT}; }}
    QListWidget::item:hover {{ background: {SURFACE_3}; }}
    QListWidget::item:selected {{ background: {SELECTION}; color: {ON_SELECTION}; }}
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
    QPushButton#Danger:disabled {{ color: {TEXT_FAINT}; border-color: {BORDER_SOFT}; background: transparent; }}
    QPushButton#Ghost {{ background: {SURFACE_2}; color: {TEXT_MUTED}; border: 1px solid {BORDER};
                         padding: 4px 12px; font-size: 12px; }}
    QPushButton#Ghost:hover {{ color: {TEXT}; background: {SURFACE_3}; border-color: {ACCENT}; }}
    QPushButton#Ghost:checked {{ color: {TEXT_STRONG}; border-color: {ACCENT}; }}
    QPushButton#Ghost:disabled {{ color: {TEXT_FAINT}; border-color: {BORDER_SOFT}; background: transparent; }}

    /* tables */
    QTableWidget {{ background: {WELL}; border: 1px solid {BORDER_SOFT}; border-radius: {RADIUS}px;
                    gridline-color: transparent; selection-background-color: {SELECTION};
                    alternate-background-color: {BG_ALT}; outline: none; }}
    QTableWidget::item {{ padding: 4px 6px; border-bottom: 1px solid {BORDER_SOFT}; }}
    QTableWidget::item:selected {{ background: {SELECTION}; color: {ON_SELECTION}; }}
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
    """Apply palette + stylesheet (popups and native bits follow), then restyle
    widgets that already exist: their inline colours and their painting."""
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in (
        (QPalette.Window, BG), (QPalette.WindowText, TEXT), (QPalette.Base, WELL),
        (QPalette.AlternateBase, BG_ALT), (QPalette.Text, TEXT), (QPalette.Button, SURFACE_2),
        (QPalette.ButtonText, TEXT), (QPalette.Highlight, SELECTION),
        (QPalette.HighlightedText, ON_SELECTION), (QPalette.ToolTipBase, SURFACE),
        (QPalette.ToolTipText, TEXT), (QPalette.PlaceholderText, TEXT_FAINT),
    ):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setFont(ui_font(10))
    app.setStyleSheet(stylesheet())
    for w in app.allWidgets():
        style = w.styleSheet()
        if style:
            new = resolve_style(style)
            if new != style:
                w.setStyleSheet(new)
        w.update()
