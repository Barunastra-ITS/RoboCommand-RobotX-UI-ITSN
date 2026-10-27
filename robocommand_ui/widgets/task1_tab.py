"""Task 1 tab: the light beacons (``Beacon Light RBX``, ESP8266 over WiFi).

Replaces opening each beacon's web page. Each beacon gets a panel with its
state, read from the beacon every couple of seconds while the tab is shown,
and one button per mode: flashing blue (entry), solid blue (exit), flashing
red / green (starboard / port obstacle) and off (black obstacle).
"""

from typing import Optional

from PyQt5.QtCore import QTimer, pyqtSignal
from PyQt5.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from robocommand_ui import field_devices, theme
from robocommand_ui.widgets.device_host import DeviceHost, readout_style
from robocommand_ui.widgets.device_runner import DeviceRunner
from robocommand_ui.widgets.form import button, caption, heading
from robocommand_ui.widgets.panel import Panel

POLL_MS = 2000
# Physical light colours, the same in light and dark mode
MODE_COLORS = {"flash_blue": "#1976d2", "solid_blue": "#1976d2",
               "flash_red": "#d32f2f", "flash_green": "#388e3c"}
DISABLED_TEXT = "#8a8f98"       # readable on both the light and dark surfaces


def _mode_button(mode: str, text: str, marks: str):
    btn = button(f"{text} · {marks}", "" if mode in MODE_COLORS else "Ghost")
    btn.setMinimumHeight(38)
    if mode in MODE_COLORS:
        btn.setStyleSheet(f"QPushButton {{ background: {MODE_COLORS[mode]}; color: #ffffff;"
                          f" border: 1px solid {MODE_COLORS[mode]}; font-weight: 600; }}"
                          f" QPushButton:disabled {{ background: transparent; color: {DISABLED_TEXT}; }}")
    return btn


class BeaconPanel(Panel):
    log = pyqtSignal(str)

    def __init__(self, number: int, default_host: str, runner: DeviceRunner,
                 settings=None, parent=None):
        super().__init__(f"Beacon {number}", parent)
        self._number = number
        self._runner = runner
        self._busy = False

        self.link = DeviceHost("Address", default_host, settings, f"devices/beacon{number}")
        self.link.changed.connect(lambda _host: self.poll())
        self.body.addWidget(self.link)

        self.body.addWidget(heading("Beacon shows"))
        self.state_label = QLabel("—")
        self.state_label.setStyleSheet(readout_style(theme.TEXT_FAINT))
        self.state_label.setMinimumHeight(34)
        self.body.addWidget(self.state_label)

        self.body.addWidget(heading("Set mode"))
        grid = QGridLayout()
        grid.setSpacing(8)
        self.mode_buttons = {}
        for i, (mode, text, marks) in enumerate(field_devices.BEACON_MODES):
            btn = _mode_button(mode, text, marks)
            btn.clicked.connect(lambda _=False, m=mode: self.set_mode(m))
            self.mode_buttons[mode] = btn
            if mode == "off":
                grid.addWidget(btn, 2, 0, 1, 2)
            else:
                grid.addWidget(btn, i // 2, i % 2)
        self.body.addLayout(grid)
        self.last_label = caption("")
        self.body.addWidget(self.last_label)
        self.body.addStretch()
        self._sync_buttons()

    def poll(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._runner.call(field_devices.beacon_status, self.link.host(),
                          on_done=self._on_status, on_error=self._on_offline)

    def set_mode(self, mode: str) -> None:
        host = self.link.host()
        text = next(f"{t} ({marks})" for m, t, marks in field_devices.BEACON_MODES if m == mode)

        def done(_):
            self.last_label.setText(f"Sent: {text}")
            self.log.emit(f"Beacon {self._number} ({host}) set to {text}")
            self.poll()

        def failed(err: str):
            self.last_label.setText(f"Not sent: {err}")
            self.log.emit(f"[ERROR] Beacon {self._number}: {err}")

        self._runner.call(field_devices.set_beacon, host, mode, on_done=done, on_error=failed)

    def _on_status(self, status: str) -> None:
        self._busy = False
        self._note(self.link.set_online(True))
        self.state_label.setText(status)
        self.state_label.setStyleSheet(readout_style(self._status_color(status)))
        self._sync_buttons()

    def _on_offline(self, err: str) -> None:
        self._busy = False
        self._note(self.link.set_online(False, err))
        self.state_label.setText("—")
        self.state_label.setStyleSheet(readout_style(theme.TEXT_FAINT))
        self._sync_buttons()

    @staticmethod
    def _status_color(status: str) -> str:
        for word, mode in (("BLUE", "flash_blue"), ("RED", "flash_red"), ("GREEN", "flash_green")):
            if word in status:
                return MODE_COLORS[mode]
        return theme.TEXT_MUTED

    def _note(self, line) -> None:
        if line:
            self.log.emit(f"Beacon {self._number} {line}")

    def _sync_buttons(self) -> None:
        for btn in self.mode_buttons.values():
            btn.setEnabled(self.link.online)
            btn.setStatusTip("" if self.link.online else "Beacon is not answering")


class Task1Tab(QWidget):
    log = pyqtSignal(str)

    def __init__(self, settings=None, runner: Optional[DeviceRunner] = None, parent=None):
        super().__init__(parent)
        self.runner = runner or DeviceRunner(self)

        col = QVBoxLayout(self)
        col.setContentsMargins(20, 16, 20, 16)
        col.setSpacing(16)
        col.addWidget(caption(
            "Beacons are on their own WiFi (192.168.0.x). Join it on this host's WiFi; "
            "MQTT stays on the wired course LAN. States refresh every 2 s while this tab is open."))
        row = QHBoxLayout()
        row.setSpacing(16)
        self.beacons = []
        for number, host in enumerate(field_devices.DEFAULT_BEACONS, start=1):
            panel = BeaconPanel(number, host, self.runner, settings)
            panel.log.connect(self.log)
            self.beacons.append(panel)
            row.addWidget(panel, 1)
        col.addLayout(row)
        col.addStretch()

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.poll)

    def poll(self) -> None:
        for panel in self.beacons:
            panel.poll()

    def showEvent(self, event):
        super().showEvent(event)
        self.poll()
        self._timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()
