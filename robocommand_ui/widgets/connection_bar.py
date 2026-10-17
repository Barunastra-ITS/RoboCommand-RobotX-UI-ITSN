"""Broker selection and connection status, shown in the header.

On the course host itself (e.g. 192.168.65.2) use "This host"; the course
presets let the same monitor watch a course broker from another machine.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QIntValidator
from PyQt5.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QPushButton, QWidget

from robocommand_ui import theme
from robocommand_ui.courses import MQTT_PORT, course_hosts
from robocommand_ui.widgets.panel import make_chip, set_chip

LOCAL_PRESET = "This host (localhost)"
COURSE_PRESETS = {LOCAL_PRESET: ("localhost", MQTT_PORT)}
COURSE_PRESETS.update({f"{c.name} ({c.host})": (c.host, MQTT_PORT) for c in course_hosts()})


class ConnectionBar(QWidget):
    connect_requested = pyqtSignal(str, int)
    disconnect_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(COURSE_PRESETS))
        self.preset_combo.setCurrentText(LOCAL_PRESET)
        self.preset_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.preset_combo.setMinimumWidth(170)
        self.preset_combo.setCursor(Qt.PointingHandCursor)
        self.preset_combo.setToolTip("Broker to monitor")
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        lay.addWidget(self.preset_combo)

        self.host_input = QLineEdit("localhost")
        self.host_input.setFixedWidth(120)
        self.host_input.setToolTip("Broker address")
        self.host_input.setFont(theme.mono_font(9.5))
        lay.addWidget(self.host_input)

        self.port_input = QLineEdit(str(MQTT_PORT))
        self.port_input.setFixedWidth(56)
        self.port_input.setValidator(QIntValidator(1, 65535, self))
        self.port_input.setToolTip("Broker port")
        self.port_input.setFont(theme.mono_font(9.5))
        lay.addWidget(self.port_input)

        self.toggle_btn = QPushButton("Connect")
        self.toggle_btn.setObjectName("Primary")
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.setMinimumWidth(96)
        self.toggle_btn.clicked.connect(self._on_toggle_clicked)
        lay.addWidget(self.toggle_btn)

        self.status_label = make_chip("● Broker disconnected", theme.FAULT)
        self.status_label.setToolTip(
            "This monitor's own connection to the MQTT broker.\n"
            "Each team's GCS link is shown in the Teams panel (from its heartbeats).")
        lay.addWidget(self.status_label)

        self._connected = False

    def _on_preset_changed(self, index: int):
        host, port = COURSE_PRESETS[self.preset_combo.currentText()]
        self.host_input.setText(host)
        self.port_input.setText(str(port))

    def _on_toggle_clicked(self):
        if self._connected:
            self.disconnect_requested.emit()
            return
        host = self.host_input.text().strip() or "localhost"
        try:
            port = int(self.port_input.text().strip())
        except ValueError:
            set_chip(self.status_label, "● Invalid port", theme.FAULT)
            return
        set_chip(self.status_label, "● Connecting…", theme.WARN)
        self.connect_requested.emit(host, port)

    def _restyle(self, name: str):
        self.toggle_btn.setObjectName(name)
        self.toggle_btn.style().unpolish(self.toggle_btn)
        self.toggle_btn.style().polish(self.toggle_btn)

    def set_connected(self, is_connected: bool):
        self._connected = is_connected
        for w in (self.host_input, self.port_input, self.preset_combo):
            w.setEnabled(not is_connected)
        if is_connected:
            self.toggle_btn.setText("Disconnect")
            self._restyle("Danger")
            set_chip(self.status_label, "● Broker connected", theme.OK)
        else:
            self.toggle_btn.setText("Connect")
            self._restyle("Primary")
            set_chip(self.status_label, "● Broker disconnected", theme.FAULT)

    def set_error(self, err_msg: str):
        self.set_connected(False)
        set_chip(self.status_label, "● Broker error", theme.FAULT)
        self.status_label.setToolTip(err_msg)
