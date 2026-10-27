"""Per-vehicle telemetry cards for what teams report to the host.

One card per (team_id, vehicle_id) seen on the broker or declared in a
RunDeclaration. The left edge and status chip carry heartbeat health
(ACTIVE / STALE / OFFLINE / NO DATA); three large readouts show speed,
heading and heartbeat rate against the required 2 Hz; the detail grid shows
state, task, position, attitude, flight phase, sequence health and task
report counts. Read-only; rebuilt from FleetState on every refresh.
"""

import time
from typing import Dict, Optional, Tuple

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from robocommand_ui import theme
from robocommand_ui.fleet_state import (
    EXPECTED_HB_HZ, OFFLINE_SECONDS, STALE_SECONDS, FleetState, VehicleTrack,
)
from robocommand_ui.proto_helper import flight_phase_name, robot_state_name, vehicle_type_name
from robocommand_ui.widgets.panel import Panel, make_chip, set_chip

STATE_COLORS = {
    "AUTO": theme.OK,
    "MANUAL": theme.WARN,
    "KILLED": theme.FAULT,
    "UNKNOWN": theme.IDLE,
}
RATE_TOLERANCE = 0.25        # accept 1.5–2.5 Hz as on-rate

REPORT_LABELS = [
    ("safe_passage", "Safe Passage"),
    ("pipeline_survey", "Pipeline"),
    ("resource_delivery", "Delivery"),
    ("docking", "Docking"),
    ("firefighting", "Firefighting"),
    ("incident_ack", "Incident Ack"),
    ("readiness", "Readiness"),
]

# (field, row, column, full width)
DETAIL_LAYOUT = [
    ("State", 0, 0, False), ("Task", 0, 1, False),
    ("Position", 1, 0, True),
    ("Alt / Depth", 2, 0, False), ("Flight", 2, 1, False),
    ("Roll / Pitch", 3, 0, False), ("Report seq", 3, 1, False),
    ("Reports", 4, 0, True),
    ("Registration", 5, 0, True),      # UAV only: Heartbeat.uav_registration (CAAS)
]


def activity(age: Optional[float]) -> Tuple[str, str]:
    if age is None:
        return "NO DATA", theme.IDLE
    if age <= STALE_SECONDS:
        return "ACTIVE", theme.OK
    if age < OFFLINE_SECONDS:
        return f"STALE {age:.0f}s", theme.WARN
    return "OFFLINE", theme.FAULT


class Readout(QWidget):
    """Large monospace value with a small caption."""

    def __init__(self, caption: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.value = QLabel("—")
        self.value.setFont(theme.mono_font(15, 600))
        lay.addWidget(self.value)
        cap = QLabel(caption.upper())
        cap.setObjectName("PanelMeta")
        lay.addWidget(cap)

    def set(self, text: str, color: str = theme.TEXT) -> None:
        self.value.setText(text)
        self.value.setStyleSheet(f"color: {theme.resolve(color)};")


class MonitorCard(QFrame):
    def __init__(self, team_id: str, vehicle_id: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 12, 10)
        lay.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.name_label = QLabel(f"{team_id} / {vehicle_id}")
        self.name_label.setFont(theme.ui_font(11, 700))
        head.addWidget(self.name_label)
        self.type_chip = make_chip("—", theme.TYPE_UNKNOWN)
        head.addWidget(self.type_chip)
        head.addStretch()
        self.status_label = make_chip("NO DATA", theme.IDLE)
        head.addWidget(self.status_label)
        lay.addLayout(head)

        readouts = QHBoxLayout()
        readouts.setSpacing(18)
        self.speed = Readout("speed m/s")
        self.heading = Readout("heading")
        self.rate = Readout(f"rate · need {EXPECTED_HB_HZ:.0f} Hz")
        for r in (self.speed, self.heading, self.rate):
            readouts.addWidget(r)
        readouts.addStretch()
        lay.addLayout(readouts)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(3)
        self._values: Dict[str, QLabel] = {}
        for name, row, col, full in DETAIL_LAYOUT:
            n = QLabel(name)
            n.setObjectName("Faint")
            v = QLabel("—")
            v.setFont(theme.mono_font(9))
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(n, row, col * 2)
            grid.addWidget(v, row, col * 2 + 1, 1, 3 if full else 1)
            self._values[name] = v
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        lay.addLayout(grid)
        self._set_edge(theme.IDLE)

    def _set_edge(self, color: str) -> None:
        self.setStyleSheet(
            f"QFrame#Card {{ background: {theme.SURFACE_2}; border: 1px solid {theme.BORDER};"
            f" border-left: 3px solid {theme.resolve(color)}; border-radius: {theme.RADIUS_SM}px; }}")

    def _set(self, name: str, text: str, color: str = theme.TEXT) -> None:
        label = self._values[name]
        label.setText(text)
        label.setStyleSheet(f"color: {theme.resolve(color)};")

    def show_track(self, v: VehicleTrack, now: float) -> None:
        status, color = activity(v.age(now))
        set_chip(self.status_label, status, color)
        self._set_edge(color)
        type_name = vehicle_type_name(v.vehicle_type)
        set_chip(self.type_chip, type_name, theme.type_color(type_name))

        rate = v.rate_hz(now)
        on_rate = abs(rate - EXPECTED_HB_HZ) <= EXPECTED_HB_HZ * RATE_TOLERANCE
        self.rate.set(f"{rate:.1f} Hz", theme.OK if on_rate else (
            theme.IDLE if v.last_hb is None else theme.WARN))

        problems = []
        if v.seq_missed:
            problems.append(f"{v.seq_missed} missed")
        if v.seq_out_of_order:
            problems.append(f"{v.seq_out_of_order} dropped")
        if v.seq_restarts:
            problems.append(f"{v.seq_restarts} restart")
        seq = str(v.last_seq) + (f"  ({', '.join(problems)})" if problems else "")
        self._set("Report seq", seq, theme.WARN if problems else theme.TEXT)

        parts = [f"{label} ×{v.reports[key]}" for key, label in REPORT_LABELS if v.reports.get(key)]
        self._set("Reports", ", ".join(parts) or "none yet",
                  theme.TEXT if parts else theme.TEXT_FAINT)

        hb = v.last_hb
        if hb is None:
            return
        self.speed.set(f"{hb.spd_mps:.2f}")
        self.heading.set(f"{hb.heading_deg:05.1f}°")
        state = robot_state_name(hb.state)
        self._set("State", state, STATE_COLORS.get(state, theme.TEXT))
        self._set("Task", v.current_task)
        self._set("Position", f"{hb.position.latitude:.6f}, {hb.position.longitude:.6f}")
        self._set("Alt / Depth", f"{hb.altitude_hae_m:.1f} / {hb.depth_m:.1f} m")
        self._set("Roll / Pitch", f"{hb.roll_deg:.1f}° / {hb.pitch_deg:.1f}°")
        self._set("Flight", flight_phase_name(hb.flight_phase))
        if vehicle_type_name(v.vehicle_type) == "UAV":
            self._set("Registration", hb.uav_registration or "— (team has one UAV)",
                      theme.TEXT if hb.uav_registration else theme.TEXT_FAINT)


class VehicleMonitorPanel(Panel):
    """Cards for every vehicle the host has heard from."""

    def __init__(self, parent=None):
        super().__init__("Vehicles", parent)
        self._cards: Dict[Tuple[str, str], MonitorCard] = {}
        self._empty = QLabel("No vehicles")
        self._empty.setObjectName("Empty")
        self._empty.setAlignment(Qt.AlignCenter)
        self.body.addWidget(self._empty)

    def refresh(self, fleet: FleetState, team_filter: Optional[str] = None,
                now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        tracks = fleet.vehicles_of(team_filter)
        wanted = {v.key for v in tracks}
        for key in list(self._cards):
            if key not in wanted:
                card = self._cards.pop(key)
                self.body.removeWidget(card)
                card.deleteLater()
        for v in tracks:
            if v.key not in self._cards:
                card = MonitorCard(*v.key)
                self._cards[v.key] = card
                self.body.addWidget(card)
            self._cards[v.key].show_track(v, now)
        self._empty.setVisible(not tracks)
        live = sum(1 for v in tracks if v.age(now) is not None and v.age(now) <= STALE_SECONDS)
        self.set_meta(f"{live} live / {len(tracks)}" if tracks else "")

    def card(self, team_id: str, vehicle_id: str) -> Optional[MonitorCard]:
        return self._cards.get((team_id, vehicle_id))
