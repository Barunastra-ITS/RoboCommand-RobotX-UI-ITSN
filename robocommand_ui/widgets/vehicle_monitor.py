"""Per-vehicle telemetry cards for what teams report to the host.

One card per (team_id, vehicle_id) seen on the broker or declared in a
RunDeclaration. Each shows heartbeat activity (ACTIVE / STALE / OFFLINE),
heartbeat rate against the required 2 Hz, robot state, current task,
position, speed/heading, attitude, flight phase, report sequence health, and
task report counts. Read-only; the cards are rebuilt from FleetState.
"""

import time
from typing import Dict, Optional, Tuple

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout,
)

from robocommand_ui.fleet_state import EXPECTED_HB_HZ, FleetState, VehicleTrack
from robocommand_ui.proto_helper import flight_phase_name, robot_state_name, vehicle_type_name

STATE_COLORS = {
    "AUTO": "#a6e3a1",
    "MANUAL": "#f9e2af",
    "KILLED": "#f38ba8",
    "UNKNOWN": "#6c7086",
}
GOOD, WARN, BAD, MUTED = "#a6e3a1", "#f9e2af", "#f38ba8", "#6c7086"

STALE_SECONDS = 2.5          # 2 Hz heartbeats: >2.5 s means several were missed
OFFLINE_SECONDS = 30.0
RATE_TOLERANCE = 0.25        # accept 1.5–2.5 Hz as on-rate

REPORT_LABELS = [
    ("safe_passage", "Safe Passage"),
    ("pipeline_survey", "Pipeline"),
    ("resource_delivery", "Resource Delivery"),
    ("docking", "Docking"),
    ("firefighting", "Firefighting"),
    ("incident_ack", "Incident Ack"),
    ("readiness", "Readiness"),
]


def activity(age: Optional[float]) -> Tuple[str, str]:
    if age is None:
        return "NO DATA", MUTED
    if age <= STALE_SECONDS:
        return "ACTIVE", GOOD
    if age < OFFLINE_SECONDS:
        return f"STALE {age:.0f}s", WARN
    return "OFFLINE", BAD


class MonitorCard(QFrame):
    def __init__(self, team_id: str, vehicle_id: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        header = QHBoxLayout()
        self.name_label = QLabel(f"{team_id} / {vehicle_id}")
        self.name_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #89b4fa;")
        header.addWidget(self.name_label)
        self.type_label = QLabel("---")
        self.type_label.setStyleSheet("font-size: 12px; color: #6c7086; padding: 0 6px;")
        header.addWidget(self.type_label)
        header.addStretch()
        self.status_label = QLabel("NO DATA")
        header.addWidget(self.status_label)
        layout.addLayout(header)

        grid = QGridLayout()
        grid.setSpacing(4)
        names = ["Rate:", "State:", "Task:", "Position:", "Speed / Hdg:",
                 "R/P/Alt/Depth:", "Flight phase:", "Report seq:", "Reports:"]
        self._values: Dict[str, QLabel] = {}
        for row, name in enumerate(names):
            n = QLabel(name)
            n.setStyleSheet("color: #6c7086; font-size: 11px;")
            v = QLabel("---")
            v.setStyleSheet("font-size: 11px;")
            v.setWordWrap(True)
            grid.addWidget(n, row, 0)
            grid.addWidget(v, row, 1)
            self._values[name] = v
        layout.addLayout(grid)
        self._set_border(MUTED)

    def _set(self, name: str, text: str, color: str = "#cdd6f4", bold: bool = False) -> None:
        label = self._values[name]
        label.setText(text)
        weight = "font-weight: bold;" if bold else ""
        label.setStyleSheet(f"font-size: 11px; color: {color}; {weight}")

    def _set_border(self, color: str) -> None:
        self.setStyleSheet(f"""
            MonitorCard {{
                background-color: #1e1e2e;
                border: 2px solid {color};
                border-radius: 8px;
                padding: 8px;
            }}
            QLabel {{ color: #cdd6f4; }}
        """)

    def show_track(self, v: VehicleTrack, now: float) -> None:
        status, color = activity(v.age(now))
        self.status_label.setText(status)
        self.status_label.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {color};")
        self._set_border(color)
        self.type_label.setText(vehicle_type_name(v.vehicle_type))

        rate = v.rate_hz(now)
        on_rate = abs(rate - EXPECTED_HB_HZ) <= EXPECTED_HB_HZ * RATE_TOLERANCE
        self._set("Rate:", f"{rate:.1f} Hz (need {EXPECTED_HB_HZ:.0f} Hz)",
                  GOOD if on_rate else (MUTED if v.last_hb is None else WARN), bold=True)

        seq_text = f"{v.last_seq}"
        problems = []
        if v.seq_missed:
            problems.append(f"{v.seq_missed} missed")
        if v.seq_out_of_order:
            problems.append(f"{v.seq_out_of_order} out of order")
        if v.seq_restarts:
            problems.append(f"{v.seq_restarts} restart(s)")
        if problems:
            seq_text += "  (" + ", ".join(problems) + ")"
        self._set("Report seq:", seq_text, WARN if problems else "#cdd6f4")

        parts = [f"{label} ×{v.reports[key]}" for key, label in REPORT_LABELS if v.reports.get(key)]
        self._set("Reports:", ", ".join(parts) or "none yet")

        hb = v.last_hb
        if hb is None:
            return
        state = robot_state_name(hb.state)
        self._set("State:", state, STATE_COLORS.get(state, "#cdd6f4"), bold=True)
        self._set("Task:", v.current_task)
        self._set("Position:", f"{hb.position.latitude:.6f}, {hb.position.longitude:.6f}")
        self._set("Speed / Hdg:", f"{hb.spd_mps:.2f} m/s  /  {hb.heading_deg:.1f}°")
        self._set("R/P/Alt/Depth:", f"{hb.roll_deg:.1f} / {hb.pitch_deg:.1f} / "
                                    f"{hb.altitude_hae_m:.1f} / {hb.depth_m:.1f} m")
        self._set("Flight phase:", flight_phase_name(hb.flight_phase))


class VehicleMonitorPanel(QGroupBox):
    """Cards for every vehicle the host has heard from."""

    def __init__(self, parent=None):
        super().__init__("Vehicle Telemetry — reported to this host", parent)
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
        """)
        self._cards: Dict[Tuple[str, str], MonitorCard] = {}
        self._stack = QVBoxLayout(self)
        self._stack.setSpacing(6)
        self._empty = QLabel("No vehicles reporting yet.")
        self._empty.setStyleSheet("color: #6c7086; font-style: italic;")
        self._empty.setAlignment(Qt.AlignCenter)
        self._stack.addWidget(self._empty)

    def refresh(self, fleet: FleetState, team_filter: Optional[str] = None,
                now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        tracks = fleet.vehicles_of(team_filter)
        wanted = {v.key for v in tracks}
        for key in list(self._cards):
            if key not in wanted:
                card = self._cards.pop(key)
                self._stack.removeWidget(card)
                card.deleteLater()
        for v in tracks:
            if v.key not in self._cards:
                card = MonitorCard(*v.key)
                self._cards[v.key] = card
                self._stack.addWidget(card)
            self._cards[v.key].show_track(v, now)
        self._empty.setVisible(not tracks)

    def card(self, team_id: str, vehicle_id: str) -> Optional[MonitorCard]:
        return self._cards.get((team_id, vehicle_id))
