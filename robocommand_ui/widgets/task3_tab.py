"""Task 3 tab: the docking bays (``RBX_1``, ESP32 over WiFi).

Replaces the dock controller's web page. Each bay shows the water it has
collected against the target, the flow and the controller state, read every
second while the tab is shown. Starting a tier turns the bay's LED red and
resets its litres; at the target it goes green for 5 s, then Advanced flashes
colour 1 and Disruptive flashes colour 1 / colour 2 for 60 s. Stop turns the
LED off. The target and the flow calibration apply to both bays.
"""

from typing import Optional

from PyQt5.QtCore import QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QColorDialog, QComboBox, QGridLayout, QHBoxLayout, QLabel, QSizePolicy,
    QVBoxLayout, QWidget,
)

from robocommand_ui import field_devices, theme
from robocommand_ui.field_devices import ALL_BAYS, BayStatus, DockStatus
from robocommand_ui.widgets.device_host import DeviceHost, readout_style
from robocommand_ui.widgets.device_runner import DeviceRunner
from robocommand_ui.widgets.form import button, caption, heading, number_spin
from robocommand_ui.widgets.panel import Panel, make_chip, set_chip

POLL_MS = 1000
TARGET_INPUT_L = 0.25           # what the Target field starts at
TARGET_STEP_L = 0.05
DEFAULT_CALIBRATION = 4.90
BAY_SIDES = {1: "left", 2: "right"}


def _state_color(state: str) -> str:
    if state.startswith("FIREFIGHTING"):
        return theme.WARN
    if state.startswith("SUCCESS"):
        return theme.OK
    if state.startswith(("ADV", "DISRUPT")):
        return theme.INFO
    return theme.IDLE


def _color_combo() -> QComboBox:
    combo = QComboBox()
    combo.addItems(list(field_devices.DOCK_COLORS))
    return combo


class BayPanel(Panel):
    command = pyqtSignal(str, object, tuple)        # description, fn, args after host

    def __init__(self, bay: int, parent=None):
        super().__init__(f"Bay {bay} · {BAY_SIDES[bay]}", parent)
        self.bay = bay
        self._target = TARGET_INPUT_L
        self._litres: Optional[float] = None

        top = QHBoxLayout()
        self.litres_label = QLabel("—")
        self.litres_label.setStyleSheet(readout_style(theme.TEXT, 26))
        top.addWidget(self.litres_label)
        top.addStretch()
        self.state_chip = make_chip("—", theme.IDLE)
        top.addWidget(self.state_chip)
        self.body.addLayout(top)
        self.flow_label = caption("")
        self.body.addWidget(self.flow_label)

        self.body.addLayout(self._build_start())

        self.body.addWidget(heading("Test and stop"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.force_btn = button("Force success", "Ghost", "Count the target as reached (testing)")
        self.force_btn.clicked.connect(
            lambda: self.command.emit(f"Bay {bay} force success",
                                      field_devices.dock_force_success, (bay,)))
        row.addWidget(self.force_btn)
        self.color_btn = button("Manual colour…", "Ghost", "Fill the LED (only while stopped)")
        self.color_btn.clicked.connect(self._pick_color)
        row.addWidget(self.color_btn)
        self.stop_btn = button("Stop", "Danger", "LED off, litres reset")
        self.stop_btn.clicked.connect(
            lambda: self.command.emit(f"Bay {bay} stop", field_devices.dock_stop, (bay,)))
        row.addWidget(self.stop_btn)
        self.body.addLayout(row)
        self.body.addStretch()

    def _build_start(self) -> QGridLayout:
        """One column per tier, each with only the colours that tier flashes."""
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        self.adv_color = _color_combo()
        self.adv_color.setToolTip("Flashed 1 s on / 1 s off for 60 s after the target")
        self.disrupt_color1 = _color_combo()
        self.disrupt_color2 = _color_combo()
        self.disrupt_color2.setCurrentText("blue")
        for combo in (self.disrupt_color1, self.disrupt_color2):
            combo.setToolTip("Code after the target: colour 1, off, colour 2, off (1 s each) for 60 s")
        columns = {
            "core": [caption("Green 5 s at the target, then off")],
            "adv": [self._labelled("Colour", self.adv_color)],
            "disrupt": [self._labelled("Colour 1", self.disrupt_color1),
                        self._labelled("Colour 2", self.disrupt_color2)],
        }
        self.start_buttons = {}
        for col, (tier, name) in enumerate(field_devices.DOCK_TIERS.items()):
            grid.addWidget(heading(name), 0, col)
            for row, widget in enumerate(columns[tier], start=1):
                grid.addWidget(widget, row, col)
            btn = button(f"Start {name}", "Primary", f"Start {name}: LED red until the target")
            btn.clicked.connect(lambda _=False, t=tier: self._start(t))
            self.start_buttons[tier] = btn
            grid.addWidget(btn, 3, col)
            grid.setColumnStretch(col, 1)
        grid.setRowStretch(2, 1)
        return grid

    @staticmethod
    def _labelled(text: str, combo: QComboBox) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(QLabel(text))
        row.addWidget(combo, 1)
        return box

    def controls(self):
        return [*self.start_buttons.values(), self.force_btn, self.color_btn, self.stop_btn]

    def set_target(self, litres: float) -> None:
        self._target = litres
        self._show_litres()

    def _show_litres(self) -> None:
        if self._litres is not None:
            self.litres_label.setText(f"{self._litres:.2f} / {self._target:.2f} L")

    def show_status(self, status: BayStatus) -> None:
        self._litres = status.litres
        self._show_litres()
        self.flow_label.setText(f"Flow {status.flow_lpm:.2f} L/min")
        set_chip(self.state_chip, status.state, _state_color(status.state))

    def show_offline(self) -> None:
        self._litres = None
        self.litres_label.setText("—")
        self.flow_label.setText("")
        set_chip(self.state_chip, "—", theme.IDLE)

    def _start(self, tier: str) -> None:
        if tier == "adv":
            c1 = c2 = self.adv_color.currentText()
            detail = f" ({c1})"
        elif tier == "disrupt":
            c1, c2 = self.disrupt_color1.currentText(), self.disrupt_color2.currentText()
            detail = f" ({c1} / {c2})"
        else:
            c1 = c2 = "red"             # Core flashes nothing; the firmware ignores them
            detail = ""
        self.command.emit(f"Bay {self.bay} start {field_devices.DOCK_TIERS[tier]}{detail}",
                          field_devices.dock_start, (self.bay, tier, c1, c2))

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(parent=self, title=f"Bay {self.bay} LED colour")
        if color.isValid():
            rgb = (color.red(), color.green(), color.blue())
            self.command.emit(f"Bay {self.bay} colour {color.name()}",
                              field_devices.dock_set_color, (self.bay, rgb))


class Task3Tab(QWidget):
    log = pyqtSignal(str)

    def __init__(self, settings=None, runner: Optional[DeviceRunner] = None, parent=None):
        super().__init__(parent)
        self.runner = runner or DeviceRunner(self)
        self._busy = False
        self._target_sent = False       # the Target field goes to the ESP on each connect

        col = QVBoxLayout(self)
        col.setContentsMargins(20, 16, 20, 16)
        col.setSpacing(16)
        self.link = DeviceHost("Dock controller", field_devices.DEFAULT_DOCK, settings,
                               "devices/dock")
        self.link.changed.connect(lambda _host: self._relink())
        col.addWidget(self.link)
        col.addWidget(caption(
            "The dock is on its own WiFi (192.168.0.x). Join it on this host's WiFi; "
            "MQTT stays on the wired course LAN. Bays refresh every second while this tab is open."))

        row = QHBoxLayout()
        row.setSpacing(16)
        self.bays = []
        for bay in field_devices.BAYS:
            panel = BayPanel(bay)
            panel.command.connect(self.send)
            self.bays.append(panel)
            row.addWidget(panel, 1)
        col.addLayout(row)
        col.addWidget(self._build_settings())
        col.addStretch()

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self.poll)
        self._sync_controls()

    def _build_settings(self) -> Panel:
        panel = Panel("Both bays")
        panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(QLabel("Target"))
        self.target_spin = number_spin(0.01, 1000.0, TARGET_INPUT_L, 2)
        self.target_spin.setSingleStep(TARGET_STEP_L)
        self.target_spin.valueChanged.connect(self._show_target)
        row.addWidget(self.target_spin)
        row.addWidget(QLabel("L"))
        self.target_btn = button("Set", "Ghost", "Litres each bay must collect (lost on ESP reboot)")
        self.target_btn.clicked.connect(self._set_target)
        row.addWidget(self.target_btn)
        row.addSpacing(24)
        row.addWidget(QLabel("Flow calibration"))
        self.calib_spin = number_spin(0.1, 1000.0, DEFAULT_CALIBRATION, 2)
        self.calib_spin.setToolTip("Sensor pulses per (L/min); the ESP keeps it across reboots")
        row.addWidget(self.calib_spin)
        self.calib_btn = button("Save", "Ghost", "Store the calibration on the ESP")
        self.calib_btn.clicked.connect(
            lambda: self.send(f"Flow calibration {self.calib_spin.value():.2f}",
                              field_devices.dock_set_calibration, (self.calib_spin.value(),)))
        row.addWidget(self.calib_btn)
        self.calib_label = caption("")
        row.addWidget(self.calib_label)
        row.addStretch()
        self.stop_all_btn = button("Stop both bays", "Danger", "Both LEDs off, litres reset")
        self.stop_all_btn.clicked.connect(
            lambda: self.send("Stop both bays", field_devices.dock_stop, (ALL_BAYS,)))
        row.addWidget(self.stop_all_btn)
        panel.body.addLayout(row)
        return panel

    # ---------- polling ----------
    def poll(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.runner.call(field_devices.dock_status, self.link.host(),
                         on_done=self._on_status, on_error=self._on_offline)

    def _relink(self) -> None:
        self._target_sent = False
        self.poll()

    def _on_status(self, status: DockStatus) -> None:
        self._busy = False
        self._note(self.link.set_online(True))
        if not self._target_sent:
            self._target_sent = True
            self._set_target()
        for panel, bay in zip(self.bays, status.bays):
            panel.show_status(bay)
        self.calib_label.setText(f"(ESP has {status.calibration:.2f})")
        self._sync_controls()

    def _on_offline(self, err: str) -> None:
        self._busy = False
        self._target_sent = False
        self._note(self.link.set_online(False, err))
        for panel in self.bays:
            panel.show_offline()
        self.calib_label.setText("")
        self._sync_controls()

    def _show_target(self, litres: float) -> None:
        """The bay readouts follow the Target field as it is typed, before Set."""
        for panel in self.bays:
            panel.set_target(litres)

    def _note(self, line) -> None:
        if line:
            self.log.emit(f"Dock {line}")

    def _sync_controls(self) -> None:
        online = self.link.online
        controls = [c for p in self.bays for c in p.controls()]
        controls += [self.target_btn, self.calib_btn, self.stop_all_btn]
        for widget in controls:
            widget.setEnabled(online)
            widget.setStatusTip("" if online else "Dock controller is not answering")

    # ---------- commands ----------
    def send(self, what: str, fn, args: tuple = ()) -> None:
        host = self.link.host()

        def done(_):
            self.log.emit(f"Dock ({host}): {what}")
            self.poll()

        def failed(err: str):
            self.log.emit(f"[ERROR] Dock: {what} not done: {err}")

        self.runner.call(fn, host, *args, on_done=done, on_error=failed)

    def _set_target(self) -> None:
        litres = self.target_spin.value()

        def done(_):
            self.log.emit(f"Dock ({self.link.host()}): target {litres:.2f} L")

        self.runner.call(field_devices.dock_set_target, self.link.host(), litres, on_done=done,
                         on_error=lambda err: self.log.emit(f"[ERROR] Dock: target not set: {err}"))

    def showEvent(self, event):
        super().showEvent(event)
        self.poll()
        self._timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()
