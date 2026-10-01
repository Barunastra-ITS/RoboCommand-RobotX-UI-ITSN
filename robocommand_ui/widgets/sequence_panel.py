"""Sequence number display and run state indicator."""

from PyQt5.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout, QFrame,
)
from PyQt5.QtCore import Qt

from robocommand_ui.sequence_tracker import SequenceTracker


class SequencePanel(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Sequence Numbers & Run State", parent)
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
            QLabel { color: #cdd6f4; }
        """)

        layout = QVBoxLayout(self)

        grid = QGridLayout()
        grid.setSpacing(4)

        grid.addWidget(self._header("Request Seq:"), 0, 0)
        self.request_seq_label = QLabel("0")
        self.request_seq_label.setStyleSheet("font-weight: bold; color: #cba6f7;")
        grid.addWidget(self.request_seq_label, 0, 1)

        grid.addWidget(self._header("Last RxCommand Seq:"), 1, 0)
        self.command_seq_label = QLabel("0")
        self.command_seq_label.setStyleSheet("font-weight: bold; color: #f9e2af;")
        grid.addWidget(self.command_seq_label, 1, 1)

        grid.addWidget(self._header("Vehicle Report Seqs:"), 2, 0)
        self.vehicle_seqs_label = QLabel("---")
        self.vehicle_seqs_label.setStyleSheet("font-size: 11px; color: #a6e3a1;")
        self.vehicle_seqs_label.setWordWrap(True)
        grid.addWidget(self.vehicle_seqs_label, 2, 1)

        layout.addLayout(grid)

        self.run_state_label = QLabel("Run State: IDLE")
        self.run_state_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #6c7086; margin-top: 6px;")
        layout.addWidget(self.run_state_label)

    def _header(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #6c7086; font-size: 11px;")
        return lbl

    def update_from_tracker(self, tracker: SequenceTracker):
        self.request_seq_label.setText(str(tracker.get_request_seq()))
        self.command_seq_label.setText(str(tracker.get_last_rx_command_seq()))
        vseqs = tracker.get_all_vehicle_seqs()
        if vseqs:
            parts = [f"{vid}={seq}" for vid, seq in sorted(vseqs.items())]
            self.vehicle_seqs_label.setText(" | ".join(parts))
        else:
            self.vehicle_seqs_label.setText("---")

    def set_run_state(self, state: str, run_id=None):
        if state == "ACTIVE":
            text = f"Run State: ACTIVE (run_id={run_id})" if run_id else "Run State: ACTIVE"
            self.run_state_label.setText(text)
            self.run_state_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #a6e3a1; margin-top: 6px;")
        elif state == "DECLARED":
            self.run_state_label.setText("Run State: DECLARED (awaiting RunStart)")
            self.run_state_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #f9e2af; margin-top: 6px;")
        else:
            self.run_state_label.setText("Run State: IDLE")
            self.run_state_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #6c7086; margin-top: 6px;")
