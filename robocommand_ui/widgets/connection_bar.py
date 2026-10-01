"""Connection Bar widget for RoboCommand network selection and status."""

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QFrame, QStyle
)
from PyQt5.QtCore import pyqtSignal, Qt

COURSE_PRESETS = {
    "Course Alpha": ("192.168.65.2", 1883),
    "Course Bravo": ("192.168.66.2", 1883),
    "Course Charlie": ("192.168.67.2", 1883),
    "Course Delta": ("192.168.68.2", 1883),
    "Team Village Demo": ("localhost", 1883),
}


class ConnectionBar(QFrame):
    connect_requested = pyqtSignal(str, int, str)
    disconnect_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("""
            ConnectionBar {
                background-color: #1e1e2e;
                border-bottom: 2px solid #313244;
                padding: 6px;
            }
            QLabel {
                color: #cdd6f4;
                font-weight: bold;
            }
            QLineEdit, QComboBox {
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QPushButton#connectBtn {
                background-color: #a6e3a1;
                color: #11111b;
                font-weight: bold;
                border-radius: 4px;
                padding: 6px 14px;
            }
            QPushButton#connectBtn:hover {
                background-color: #94e2d5;
            }
            QPushButton#disconnectBtn {
                background-color: #f38ba8;
                color: #11111b;
                font-weight: bold;
                border-radius: 4px;
                padding: 6px 14px;
            }
            QPushButton#disconnectBtn:hover {
                background-color: #eba0ac;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(10)

        # Preset selector
        layout.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(COURSE_PRESETS.keys()))
        self.preset_combo.setCurrentText("Team Village Demo")
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        layout.addWidget(self.preset_combo)

        # Host
        layout.addWidget(QLabel("Host:"))
        self.host_input = QLineEdit("localhost")
        self.host_input.setFixedWidth(130)
        layout.addWidget(self.host_input)

        # Port
        layout.addWidget(QLabel("Port:"))
        self.port_input = QLineEdit("1883")
        self.port_input.setFixedWidth(60)
        layout.addWidget(self.port_input)

        # Team ID
        layout.addWidget(QLabel("Team ID:"))
        self.team_input = QLineEdit("ITSN")
        self.team_input.setFixedWidth(80)
        layout.addWidget(self.team_input)

        # Connect / Disconnect button
        self.toggle_btn = QPushButton("Connect")
        self.toggle_btn.setObjectName("connectBtn")
        self.toggle_btn.clicked.connect(self._on_toggle_clicked)
        layout.addWidget(self.toggle_btn)

        # Status badge
        self.status_label = QLabel("● Disconnected")
        self.status_label.setStyleSheet("color: #f38ba8; font-weight: bold; padding-left: 10px;")
        layout.addWidget(self.status_label)

        layout.addStretch()
        self._connected = False

    def _on_preset_changed(self, index: int):
        preset_name = self.preset_combo.currentText()
        if preset_name in COURSE_PRESETS:
            host, port = COURSE_PRESETS[preset_name]
            self.host_input.setText(host)
            self.port_input.setText(str(port))

    def _on_toggle_clicked(self):
        if not self._connected:
            host = self.host_input.text().strip() or "localhost"
            try:
                port = int(self.port_input.text().strip())
            except ValueError:
                self.status_label.setText("● Invalid port")
                self.status_label.setStyleSheet(
                    "color: #f38ba8; font-weight: bold; padding-left: 10px;")
                return
            team = self.team_input.text().strip() or "ITSN"
            if not team.replace("_", "").replace("-", "").isalnum():
                self.status_label.setText("● Invalid team_id")
                self.status_label.setStyleSheet(
                    "color: #f38ba8; font-weight: bold; padding-left: 10px;")
                return
            self.status_label.setText("● Connecting...")
            self.status_label.setStyleSheet(
                "color: #f9e2af; font-weight: bold; padding-left: 10px;")
            self.connect_requested.emit(host, port, team)
        else:
            self.disconnect_requested.emit()

    def set_connected(self, is_connected: bool):
        self._connected = is_connected
        if is_connected:
            self.toggle_btn.setText("Disconnect")
            self.toggle_btn.setObjectName("disconnectBtn")
            self.toggle_btn.setStyle(self.toggle_btn.style())
            self.status_label.setText("● Connected")
            self.status_label.setStyleSheet("color: #a6e3a1; font-weight: bold; padding-left: 10px;")
            self.host_input.setEnabled(False)
            self.port_input.setEnabled(False)
            self.team_input.setEnabled(False)
            self.preset_combo.setEnabled(False)
        else:
            self.toggle_btn.setText("Connect")
            self.toggle_btn.setObjectName("connectBtn")
            self.toggle_btn.setStyle(self.toggle_btn.style())
            self.status_label.setText("● Disconnected")
            self.status_label.setStyleSheet("color: #f38ba8; font-weight: bold; padding-left: 10px;")
            self.host_input.setEnabled(True)
            self.port_input.setEnabled(True)
            self.team_input.setEnabled(True)
            self.preset_combo.setEnabled(True)

    def set_error(self, err_msg: str):
        self._connected = False
        self.set_connected(False)
        self.status_label.setText(f"● Error: {err_msg}")
        self.status_label.setStyleSheet("color: #f38ba8; font-weight: bold; padding-left: 10px;")
