"""Shared building blocks: titled panel and status chip."""

from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from robocommand_ui import theme


class Panel(QFrame):
    """Rounded surface with an uppercase title row and a body layout.

    ``self.body`` is the layout to add content to; ``self.actions`` holds
    controls shown at the right of the title row.
    """

    def __init__(self, title: str, parent=None, body_margins=(12, 4, 12, 12)):
        super().__init__(parent)
        self.setObjectName("Panel")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QWidget()
        row = QHBoxLayout(head)
        row.setContentsMargins(12, 10, 8, 6)
        row.setSpacing(8)
        self.title_label = QLabel(title.upper())
        self.title_label.setObjectName("PanelTitle")
        row.addWidget(self.title_label)
        self.meta_label = QLabel("")
        self.meta_label.setObjectName("PanelMeta")
        row.addWidget(self.meta_label)
        row.addStretch()
        self.actions = QHBoxLayout()
        self.actions.setSpacing(4)
        row.addLayout(self.actions)
        outer.addWidget(head)

        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(*body_margins)
        self.body.setSpacing(8)
        outer.addWidget(body, 1)

    def set_meta(self, text: str) -> None:
        self.meta_label.setText(text)


def make_chip(text: str = "", color: str = theme.TEXT_MUTED) -> QLabel:
    chip = QLabel(text)
    chip.setProperty("chip", True)
    set_chip(chip, text, color)
    return chip


def set_chip(chip: QLabel, text: str, color: str) -> None:
    """Chip with a tinted fill and border in ``color`` (status meaning only)."""
    chip.setText(text)
    c = theme.qcolor(color)
    chip.setStyleSheet(
        f"color: {color}; background: rgba({c.red()}, {c.green()}, {c.blue()}, 0.12);"
        f"border: 1px solid rgba({c.red()}, {c.green()}, {c.blue()}, 0.45);")
