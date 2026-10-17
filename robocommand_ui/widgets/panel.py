"""Shared building blocks: titled panel and status chip (OCS monitor style)."""

from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from robocommand_ui import theme


CHIP_SLACK_PX = 26


class Panel(QFrame):
    """Rounded surface with a "● Title  tag" row and a body layout.

    ``self.body`` is the layout to add content to; ``self.actions`` holds
    controls shown at the right of the title row. ``set_meta`` fills the mono
    tag beside the title (a topic, a count, a state). ``dot`` colours the
    marker before the title, as the OCS does per message direction.
    """

    def __init__(self, title: str, parent=None, body_margins=(16, 4, 16, 16),
                 dot: str = theme.ACCENT):
        super().__init__(parent)
        self.setObjectName("Panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QWidget()
        row = QHBoxLayout(head)
        row.setContentsMargins(16, 12, 12, 8)
        row.setSpacing(8)
        self.dot_label = QLabel("●")
        self.dot_label.setObjectName("PanelDot")
        self.set_dot(dot)
        row.addWidget(self.dot_label)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("PanelTitle")
        row.addWidget(self.title_label)
        self.meta_label = QLabel("")
        self.meta_label.setObjectName("PanelMeta")
        row.addWidget(self.meta_label)
        row.addStretch()
        self.actions = QHBoxLayout()
        self.actions.setSpacing(6)
        row.addLayout(self.actions)
        outer.addWidget(head)

        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(*body_margins)
        self.body.setSpacing(8)
        outer.addWidget(body, 1)

    def set_meta(self, text: str) -> None:
        self.meta_label.setText(text)

    def set_dot(self, color: str) -> None:
        self.dot_label.setStyleSheet(f"color: {theme.resolve(color)};")


def make_chip(text: str = "", color: str = theme.TEXT_MUTED) -> QLabel:
    chip = QLabel(text)
    chip.setProperty("chip", True)
    chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)     # pill-sized in any row
    set_chip(chip, text, color)
    return chip


def set_chip(chip: QLabel, text: str, color: str) -> None:
    """Solid chip for ok / warn / fault, outlined in ``color`` otherwise."""
    chip.setText(text)
    chip.setStyleSheet(theme.chip_style(color))
    # Fallback-font glyphs (●) can outrun the size hint: measure with the chip's own
    # (polished, 11 px bold) font and leave room for its padding and border
    chip.ensurePolished()
    chip.setMinimumWidth(chip.fontMetrics().horizontalAdvance(text) + CHIP_SLACK_PX)
