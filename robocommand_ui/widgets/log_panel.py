"""Message log with filtering. Colour carries meaning: fault, warning, command."""

import datetime
import html

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QComboBox, QPushButton, QTextEdit

from robocommand_ui import theme
from robocommand_ui.widgets.panel import Panel

FILTERS = ["All", "Problems", "RxCourse", "RxRequest", "RxCommand", "RxReport", "Connection"]
MAX_MESSAGES = 5000


def _is_problem(entry: str) -> bool:
    return any(tag in entry for tag in ("[ERROR]", "[REJECT]", "[WARN]", "Error"))


class LogPanel(Panel):
    def __init__(self, parent=None):
        super().__init__("Log", parent, body_margins=(0, 0, 0, 0))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(FILTERS)
        self.filter_combo.setCursor(Qt.PointingHandCursor)
        self.filter_combo.setToolTip("Show only matching log lines")
        self.filter_combo.currentIndexChanged.connect(self._apply_filter)
        self.actions.addWidget(self.filter_combo)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("Ghost")
        self.clear_btn.setCursor(Qt.PointingHandCursor)
        self.clear_btn.clicked.connect(self._clear)
        self.actions.addWidget(self.clear_btn)

        self.log_view = QTextEdit()
        self.log_view.setObjectName("Log")
        self.log_view.setReadOnly(True)
        self.log_view.document().setMaximumBlockCount(MAX_MESSAGES)
        self.body.addWidget(self.log_view)

        self._all_messages = []
        self._problems = 0
        self._update_meta()

    def append_log(self, text: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        entry = f"[{ts}] {text}"
        self._all_messages.append(entry)
        if len(self._all_messages) > MAX_MESSAGES:
            self._all_messages = self._all_messages[-MAX_MESSAGES:]
        if _is_problem(entry):
            self._problems += 1
        if self._matches_filter(entry, self.filter_combo.currentText()):
            self._render(entry)
        self._update_meta()

    def _update_meta(self):
        meta = f"{len(self._all_messages)} lines"
        if self._problems:
            meta += f"  ·  {self._problems} problems"
        self.set_meta(meta)

    def _render(self, entry: str):
        self.log_view.append(f'<span style="color:{self._color_for_entry(entry)}">'
                             f'{html.escape(entry)}</span>')

    @staticmethod
    def _matches_filter(entry: str, filt: str) -> bool:
        if filt == "All":
            return True
        if filt == "Problems":
            return _is_problem(entry)
        if filt == "Connection":
            return "Connect" in entry or "Disconnect" in entry or "Monitoring" in entry
        return f"[{filt}]" in entry

    @staticmethod
    def _color_for_entry(entry: str) -> str:
        if "[ERROR]" in entry or "[REJECT]" in entry or "Error" in entry:
            return theme.FAULT
        if "[WARN]" in entry:
            return theme.WARN
        if "[RxCommand]" in entry or "RunStart" in entry:
            return theme.INFO
        if "Connect" in entry or "Monitoring" in entry or "New vehicle" in entry:
            return theme.TEXT
        return theme.TEXT_MUTED

    def _apply_filter(self):
        self.log_view.clear()
        filt = self.filter_combo.currentText()
        for entry in self._all_messages:
            if self._matches_filter(entry, filt):
                self._render(entry)

    def _clear(self):
        self._all_messages.clear()
        self._problems = 0
        self.log_view.clear()
        self._update_meta()
