"""Message log viewer with filtering."""

from PyQt5.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QLabel, QComboBox,
)
from PyQt5.QtCore import Qt


class LogPanel(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Message Log", parent)
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 6px;
                margin-top: 8px;
                padding: 12px 8px 8px 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
            }
            QTextEdit {
                background-color: #11111b;
                color: #a6adc8;
                border: 1px solid #45475a;
                border-radius: 4px;
                font-family: monospace;
                font-size: 11px;
            }
            QPushButton {
                background-color: #313244;
                color: #cdd6f4;
                border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background-color: #45475a;
            }
        """)
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["All", "RxCourse", "RxCommand", "RxReport", "RxRequest", "Error", "Connection"])
        self.filter_combo.currentIndexChanged.connect(self._apply_filter)
        toolbar.addWidget(QLabel("Filter:"))
        toolbar.addWidget(self.filter_combo)
        toolbar.addStretch()

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self._clear)
        toolbar.addWidget(self.clear_btn)

        self.count_label = QLabel("0 messages")
        self.count_label.setStyleSheet("color: #6c7086;")
        toolbar.addWidget(self.count_label)

        layout.addLayout(toolbar)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)

        self._all_messages = []
        self._max_messages = 5000

    def append_log(self, text: str):
        import datetime
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        entry = f"[{ts}] {text}"
        self._all_messages.append(entry)
        if len(self._all_messages) > self._max_messages:
            self._all_messages = self._all_messages[-self._max_messages:]

        current_filter = self.filter_combo.currentText()
        if self._matches_filter(entry, current_filter):
            color = self._color_for_entry(entry)
            self.log_view.append(f'<span style="color:{color}">{entry}</span>')

        self.count_label.setText(f"{len(self._all_messages)} messages")

    def _matches_filter(self, entry: str, filt: str) -> bool:
        if filt == "All":
            return True
        if filt == "Error":
            return "[ERROR]" in entry or "Error" in entry
        if filt == "Connection":
            return "Connect" in entry or "Disconnect" in entry
        return f"[{filt}]" in entry

    def _color_for_entry(self, entry: str) -> str:
        if "[ERROR]" in entry or "Error" in entry:
            return "#f38ba8"
        if "[RxCourse]" in entry:
            return "#89b4fa"
        if "[RxCommand]" in entry:
            return "#f9e2af"
        if "[RxReport]" in entry or "Report" in entry:
            return "#a6e3a1"
        if "[RxRequest]" in entry or "Request" in entry:
            return "#cba6f7"
        if "Connect" in entry:
            return "#94e2d5"
        return "#a6adc8"

    def _apply_filter(self):
        self.log_view.clear()
        filt = self.filter_combo.currentText()
        for entry in self._all_messages:
            if self._matches_filter(entry, filt):
                color = self._color_for_entry(entry)
                self.log_view.append(f'<span style="color:{color}">{entry}</span>')

    def _clear(self):
        self._all_messages.clear()
        self.log_view.clear()
        self.count_label.setText("0 messages")
