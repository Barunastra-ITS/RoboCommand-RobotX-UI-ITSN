"""Pre-run declaration panel for configuring and sending RunDeclaration."""

from PyQt5.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QCheckBox, QTextEdit, QGridLayout, QFrame,
)
from PyQt5.QtCore import pyqtSignal, Qt

from robocommand_ui.proto_helper import TIER_STR_MAP, common_pb2


def _warn(parent, title, text):
    """Modal dialogs would block the OCS (handbook 3.4.13), so log to the panel."""
    parent._status_label.setText(f"{title}: {text}")
    parent._status_label.setStyleSheet("color: #f38ba8; font-weight: bold;")


class RunDeclarationPanel(QGroupBox):
    send_declaration = pyqtSignal(list, int, int, int, int, list)

    def __init__(self, parent=None):
        super().__init__("Pre-Run Declaration (RxRequest)", parent)
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
            QLineEdit, QComboBox {
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 3px 6px;
            }
            QPushButton {
                background-color: #89b4fa;
                color: #11111b;
                font-weight: bold;
                border-radius: 4px;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background-color: #74c7ec;
            }
            QPushButton:disabled {
                background-color: #45475a;
                color: #6c7086;
            }
        """)

        layout = QVBoxLayout(self)

        # Vehicle IDs
        vlayout = QHBoxLayout()
        vlayout.addWidget(QLabel("Vehicle IDs:"))
        self.vehicles_input = QLineEdit("USV1, UUV1, UAV1")
        self.vehicles_input.setPlaceholderText("USV1, UUV1, UAV1")
        vlayout.addWidget(self.vehicles_input)
        layout.addLayout(vlayout)

        # Task tiers
        grid = QGridLayout()
        grid.setSpacing(4)
        tier_choices = ["TIER_NONE", "TIER_CORE", "TIER_ADVANCED", "TIER_DISRUPTIVE"]
        self.task_combos = {}

        tasks = [
            ("Task 1 (Safe Passage):", "task1"),
            ("Task 2 (Infra Survey):", "task2"),
            ("Task 3 (Coord. Logistics):", "task3"),
            ("Task 4 (Dynamic Incident):", "task4"),
        ]
        for i, (label_text, key) in enumerate(tasks):
            grid.addWidget(QLabel(label_text), i, 0)
            combo = QComboBox()
            combo.addItems(tier_choices)
            combo.setCurrentText("TIER_NONE")
            self.task_combos[key] = combo
            grid.addWidget(combo, i, 1)

        layout.addLayout(grid)

        # UAV Geofence
        geo_layout = QVBoxLayout()
        geo_layout.addWidget(QLabel("UAV Geofence (lat,lng per line; first==last):"))
        self.geofence_input = QTextEdit()
        self.geofence_input.setMaximumHeight(80)
        self.geofence_input.setPlaceholderText(
            "1.280329, 103.8556869\n1.2804716, 103.8554529\n1.2808993, 103.8557337\n"
            "1.2807567, 103.8559743\n1.280329, 103.8556869"
        )
        self.geofence_input.setStyleSheet(
            "background-color: #313244; color: #cdd6f4; border: 1px solid #45475a; border-radius: 4px;"
        )
        geo_layout.addWidget(self.geofence_input)
        layout.addLayout(geo_layout)

        # Send button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.send_btn = QPushButton("Send RunDeclaration")
        self.send_btn.clicked.connect(self._on_send)
        btn_layout.addWidget(self.send_btn)
        layout.addLayout(btn_layout)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #6c7086; font-style: italic;")
        layout.addWidget(self._status_label)

    def _parse_geofence(self) -> list:
        text = self.geofence_input.toPlainText().strip()
        if not text:
            return []
        points = []
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) != 2:
                raise ValueError(f"Invalid geofence point: {line}")
            points.append((float(parts[0].strip()), float(parts[1].strip())))
        return points

    def _on_send(self):
        vehicles_text = self.vehicles_input.text().strip()
        if not vehicles_text:
            _warn(self, "Error", "Enter at least one vehicle ID.")
            return
        vehicle_ids = [v.strip() for v in vehicles_text.split(",") if v.strip()]

        tiers = {}
        for key, combo in self.task_combos.items():
            tier_name = combo.currentText()
            tiers[key] = TIER_STR_MAP.get(tier_name, common_pb2.TIER_NONE)

        try:
            geofence = self._parse_geofence()
        except ValueError as e:
            _warn(self, "Geofence Error", str(e))
            return

        has_uav = any("UAV" in vid.upper() for vid in vehicle_ids)
        if has_uav and len(geofence) < 4:
            _warn(self, "Geofence Required",
                  "UAV is declared but geofence has fewer than 4 points.")
            return

        self.send_declaration.emit(
            vehicle_ids,
            tiers["task1"],
            tiers["task2"],
            tiers["task3"],
            tiers["task4"],
            geofence,
        )
        self._status_label.setText(f"Sent RunDeclaration with vehicles: {vehicle_ids}")
        self._status_label.setStyleSheet("color: #6c7086; font-style: italic;")

    def set_enabled(self, enabled: bool):
        self.send_btn.setEnabled(enabled)
