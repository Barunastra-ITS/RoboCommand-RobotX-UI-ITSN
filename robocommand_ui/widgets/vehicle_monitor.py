"""Read-only vehicle telemetry monitor for the Monitoring page.

Shows, per vehicle, exactly what it is sending to RoboCommand: heartbeat
activity (ACTIVE / STALE / OFFLINE with age), robot state, current task,
telemetry (position, speed, heading, attitude, flight phase), sequence number,
the task reports it has sent, and the last command addressed to it. This is
display-only — no editing.
"""

import time

from PyQt5.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout, QFrame, QWidget,
    QScrollArea, QSizePolicy,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor

from robocommand_ui.proto_helper import (
    robot_state_name, vehicle_type_name, rx_task_name, flight_phase_name,
)

STATE_COLORS = {
    "AUTO": "#a6e3a1",
    "MANUAL": "#f9e2af",
    "KILLED": "#f38ba8",
    "UNKNOWN": "#6c7086",
}

# How long before a heartbeat is considered stale. Handbook 3.4.11 = 2 Hz.
STALE_SECONDS = 2.5

REPORT_LABELS = [
    ("safe_passage", "Safe Passage"),
    ("pipeline_survey", "Pipeline Survey"),
    ("resource_delivery", "Resource Delivery"),
    ("docking", "Docking"),
    ("firefighting", "Firefighting"),
    ("incident_ack", "Incident Ack"),
    ("readiness", "Readiness"),
]


class MonitorCard(QFrame):
    def __init__(self, vehicle_id, parent=None):
        super().__init__(parent)
        self.vehicle_id = vehicle_id
        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setStyleSheet("""
            MonitorCard {
                background-color: #1e1e2e;
                border: 2px solid #45475a;
                border-radius: 8px;
                padding: 8px;
            }
            QLabel { color: #cdd6f4; }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        # Header row: name + type + status
        header = QHBoxLayout()
        self.name_label = QLabel(vehicle_id)
        self.name_label.setStyleSheet("font-size: 15px; font-weight: bold; color: #89b4fa;")
        header.addWidget(self.name_label)
        self.type_label = QLabel("---")
        self.type_label.setStyleSheet("font-size: 12px; color: #6c7086; padding: 0 6px;")
        header.addWidget(self.type_label)
        header.addStretch()
        self.status_label = QLabel("OFFLINE")
        self.status_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #6c7086;")
        header.addWidget(self.status_label)
        layout.addLayout(header)

        grid = QGridLayout()
        grid.setSpacing(4)
        self.heartbeat_label = self._field(grid, 0, "Heartbeat:", "---")
        self.state_label = self._field(grid, 1, "State:", "---")
        self.task_label = self._field(grid, 2, "Task:", "---")
        self.pos_label = self._field(grid, 3, "Position:", "---")
        self.speed_label = self._field(grid, 4, "Speed / Hdg:", "---")
        self.attitude_label = self._field(grid, 5, "R/P/Alt/Depth:", "---")
        self.flight_label = self._field(grid, 6, "Flight phase:", "---")
        self.seq_label = self._field(grid, 7, "Report seq:", "---")
        layout.addLayout(grid)

        self.reports_label = self._field_row(layout, "Reports sent:")
        self.command_label = self._field_row(layout, "Last command:")

        self._hb_time = 0.0

    def _field(self, grid, row, name, default):
        n = QLabel(name)
        n.setStyleSheet("color: #6c7086; font-size: 11px;")
        v = QLabel(default)
        v.setStyleSheet("font-size: 11px;")
        grid.addWidget(n, row, 0)
        grid.addWidget(v, row, 1)
        return v

    def _field_row(self, layout, name):
        row = QHBoxLayout()
        n = QLabel(name)
        n.setStyleSheet("color: #6c7086; font-size: 11px; font-weight: bold;")
        v = QLabel("---")
        v.setStyleSheet("font-size: 11px; color: #cdd6f4;")
        v.setWordWrap(True)
        row.addWidget(n)
        row.addWidget(v, 1)
        layout.addLayout(row)
        return v

    def set_type(self, vtype):
        self.type_label.setText(vehicle_type_name(vtype))

    def set_heartbeat(self, hb, seq, is_fresh):
        state = robot_state_name(hb.state)
        self.heartbeat_label.setText(
            "ACTIVE" if is_fresh else f"STALE {time.time() - self._hb_time:.1f}s ago")
        color = STATE_COLORS.get(state, "#cdd6f4")
        self.state_label.setText(state)
        self.state_label.setStyleSheet(f"font-size: 11px; font-weight: bold; color: {color};")
        self.task_label.setText(rx_task_name(hb.current_task))
        self.pos_label.setText(f"{hb.position.latitude:.6f}, {hb.position.longitude:.6f}")
        self.speed_label.setText(f"{hb.spd_mps:.2f} m/s  /  {hb.heading_deg:.1f}°")
        self.attitude_label.setText(
            f"{hb.roll_deg:.1f} / {hb.pitch_deg:.1f} / {hb.altitude_hae_m:.1f} / "
            f"{hb.depth_m:.1f} m")
        self.flight_label.setText(flight_phase_name(hb.flight_phase))
        self.seq_label.setText(str(seq))

    def set_reports(self, counts: dict):
        if not counts:
            self.reports_label.setText("none yet")
            return
        parts = [f"{label} ×{counts[key]}" for key, label in REPORT_LABELS if counts.get(key)]
        self.reports_label.setText(", ".join(parts) or "none yet")

    def set_command(self, text):
        self.command_label.setText(text or "---")

    def set_status(self, text, color):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {color};")
        self.setStyleSheet(f"""
            MonitorCard {{
                background-color: #1e1e2e;
                border: 2px solid {color};
                border-radius: 8px;
                padding: 8px;
            }}
            QLabel {{ color: #cdd6f4; }}
        """)

    def set_age(self, age_s):
        self._hb_time = time.time() - age_s
        if age_s <= STALE_SECONDS:
            self.set_status("ACTIVE", "#a6e3a1")
        elif age_s < 60.0:
            self.set_status(f"STALE {age_s:.0f}s", "#f9e2af")
        else:
            self.set_status("OFFLINE", "#f38ba8")


class VehicleMonitorPanel(QGroupBox):
    """Read-only monitor of what each vehicle is sending."""

    def __init__(self, parent=None):
        super().__init__("Vehicle Telemetry — what the vehicles are sending", parent)
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
        self._veh = {}
        self._cards = {}
        self._stack = QVBoxLayout(self)
        self._stack.setSpacing(6)
        self._empty = QLabel("No vehicles reporting yet.")
        self._empty.setStyleSheet("color: #6c7086; font-style: italic;")
        self._empty.setAlignment(Qt.AlignCenter)
        self._stack.addWidget(self._empty)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(500)

    # --- recording (called by the main window) ---
    def record_heartbeat(self, vehicle_id, hb, seq):
        v = self._ensure(vehicle_id)
        v["type"] = hb.vehicle_type
        v["last_hb"] = hb
        v["hb_time"] = time.time()
        v["seq"] = seq
        card = self._ensure_card(vehicle_id)
        card.set_type(hb.vehicle_type)
        card.set_heartbeat(hb, seq, is_fresh=True)
        self._refresh()

    def record_report(self, vehicle_id, report_key):
        v = self._ensure(vehicle_id)
        v["reports"][report_key] = v["reports"].get(report_key, 0) + 1
        card = self._ensure_card(vehicle_id)
        card.set_reports(v["reports"])

    def record_command(self, vehicle_ids, text):
        for vid in vehicle_ids:
            v = self._ensure(vid)
            v["last_cmd"] = text
            card = self._ensure_card(vid)
            card.set_command(text)

    def all_vehicle_ids(self):
        return list(self._veh.keys())

    def vehicle_ids_of_type(self, vtype):
        return [vid for vid, v in self._veh.items() if v["type"] == vtype]

    def clear(self):
        self._veh = {}
        self._cards = {}
        self._empty.show()
        for card in self._cards.values():
            self._stack.removeWidget(card)
            card.deleteLater()
        self._cards = {}

    # --- internals ---
    def _ensure(self, vid):
        if vid not in self._veh:
            self._veh[vid] = {
                "type": 0, "last_hb": None, "hb_time": 0.0,
                "seq": 0, "reports": {}, "last_cmd": None,
            }
        return self._veh[vid]

    def _ensure_card(self, vid):
        if vid not in self._cards:
            self._empty.hide()
            card = MonitorCard(vid)
            self._cards[vid] = card
            self._stack.addWidget(card)
        return self._cards[vid]

    def _refresh(self):
        for vid, v in self._veh.items():
            card = self._cards.get(vid)
            if card is None:
                continue
            if v["last_hb"] is None:
                card.set_status("NO DATA", "#6c7086")
                continue
            age = time.time() - v["hb_time"]
            card.set_age(age)
            card.set_heartbeat(v["last_hb"], v["seq"], is_fresh=age <= STALE_SECONDS)
            card.set_reports(v["reports"])
            card.set_command(v["last_cmd"])
