"""Task 4 tab: Dynamic Incident Response commands, grouped by tier.

Replaces ``rc assistance-request`` / ``readiness-confirm`` (Core),
``keep-out-zone`` / ``all-clear`` (Advanced) and ``moving-object-alert``
(Disruptive). Every command goes to the selected team with the next seq.
Every panel can be edited, but only the send buttons of the team's declared
Task 4 tier work: each tier has its own command chain (§3.4.12), so a team
that declared Advanced gets keep-out zones and all-clears, not assistance
requests or moving objects.
The history below matches each command with the team's IncidentAck and
ReadinessReport, and fills in the Readiness confirm for you.

The **Incident map** beside it shows the course, the team's vehicles and the
objects it reported. Its centre crosshair is where commands go: pan the map
and the position fields of every tier follow it (typing a position, or
**Centre**, moves the map there). Each tier's command is drawn as it would be
sent (the declared tier's labelled, the others faint): the assistance point,
the keep-out zone at its radius (dashed red), and the moving object with its
keep-out radius (dashed yellow) and heading; when the two rings fall on the
same line (same place and radius), it alternates red and yellow dashes.
"""

import time
from typing import Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from robocommand_ui import commands, theme
from robocommand_ui.fleet_state import STALE_SECONDS, FleetState
from robocommand_ui.incident_log import IncidentLog
from robocommand_ui.proto_helper import common_pb2, task_tier_name, vehicle_type_name
from robocommand_ui.widgets.form import (
    LatLngField, button, caption, heading, int_spin, number_spin, type_combo, with_unit,
)
from robocommand_ui.widgets.course_map import CourseMapWidget
from robocommand_ui.widgets.panel import Panel, make_chip, set_chip
from robocommand_ui.widgets.task4_map import IncidentMapCanvas, Preview

TIER_LEVELS = (common_pb2.TIER_CORE, common_pb2.TIER_ADVANCED, common_pb2.TIER_DISRUPTIVE)
HISTORY_COLUMNS = ["Seq", "Time", "Command", "Details", "Team answer"]
MAX_SEQ = 2_147_483_647          # QSpinBox is a signed 32-bit int
STATUS_COLORS = {"SENT": theme.TEXT_MUTED, "WAITING ACK": theme.WARN, "CONFIRMED": theme.OK}


def _form() -> QFormLayout:
    form = QFormLayout()
    form.setHorizontalSpacing(10)
    form.setVerticalSpacing(6)
    form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    return form


class Task4Tab(QWidget):
    command_requested = pyqtSignal(str, object, str)    # team_id, (body name, msg), summary

    def __init__(self, parent=None):
        super().__init__(parent)
        self._connected = False
        self._declared_tier = None      # team's Task 4 tier, None when not declared / not seen
        self._filled_readiness = None
        self._send_buttons = []

        col = QVBoxLayout(self)
        col.setContentsMargins(20, 16, 20, 16)
        col.setSpacing(16)
        col.addLayout(self._build_target_row())
        tiers = QHBoxLayout()
        tiers.setSpacing(16)
        self.core = self._build_core()
        self.advanced = self._build_advanced()
        self.disruptive = self._build_disruptive()
        self._tier_panels = (self.core, self.advanced, self.disruptive)
        for panel in self._tier_panels:
            tiers.addWidget(panel, 1)
        col.addLayout(tiers)
        bottom = QHBoxLayout()
        bottom.setSpacing(16)
        bottom.addWidget(self._build_history(), 2)
        bottom.addWidget(self._build_map(), 3)
        col.addLayout(bottom, 1)
        self._connect_previews()
        self._sync_buttons()

    # ---------- builders ----------
    def _build_target_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(16)
        label = QLabel("Team")
        label.setObjectName("FormHeading")
        row.addWidget(label)
        self.team_combo = QComboBox()
        self.team_combo.setMinimumWidth(140)
        self.team_combo.setCursor(Qt.PointingHandCursor)
        self.team_combo.setToolTip("Team that receives the Task 4 commands")
        self.team_combo.currentIndexChanged.connect(self._sync_buttons)
        row.addWidget(self.team_combo)
        self.run_chip = make_chip("NO TEAM", theme.IDLE)
        row.addWidget(self.run_chip)
        self.tier_chip = make_chip("TASK 4 —", theme.IDLE)
        self.tier_chip.setToolTip("Task 4 tier the team declared")
        row.addWidget(self.tier_chip)
        self.live_label = caption("")
        row.addWidget(self.live_label, 1)
        self.seq_label = caption("")
        self.seq_label.setFont(theme.mono_font(9.5))
        row.addWidget(self.seq_label)
        return row

    def _send_button(self, text: str, handler, level: int) -> QWidget:
        """A send button of one tier: it works only when that tier is the declared one."""
        btn = button(text, "Primary")
        btn.clicked.connect(handler)
        self._send_buttons.append((btn, level))
        return btn

    def _build_core(self) -> Panel:
        panel = Panel("Core · assistance")
        panel.body.addWidget(heading("Assistance request"))
        form = _form()
        self.assist_type = type_combo()
        form.addRow("Vehicle type", self.assist_type)
        self.assist_pos = LatLngField()
        form.addRow("Go to", self.assist_pos)
        panel.body.addLayout(form)
        panel.body.addWidget(self._send_button("Send assistance request", self._send_assist,
                                                common_pb2.TIER_CORE))

        panel.body.addWidget(heading("Readiness confirm"))
        form = _form()
        self.confirm_vehicle = QComboBox()
        self.confirm_vehicle.setEditable(True)
        form.addRow("Vehicle ID", self.confirm_vehicle)
        self.confirm_seq = int_spin(1, MAX_SEQ, 1)
        self.confirm_seq.setToolTip("RxReport.seq of the ReadinessReport (R), not the command seq")
        form.addRow("Report seq R", self.confirm_seq)
        panel.body.addLayout(form)
        self.confirm_hint = caption("")
        panel.body.addWidget(self.confirm_hint)
        panel.body.addWidget(self._send_button("Send readiness confirm", self._send_confirm,
                                                common_pb2.TIER_CORE))
        panel.body.addStretch()
        return panel

    def _build_advanced(self) -> Panel:
        panel = Panel("Advanced · keep-out")
        panel.body.addWidget(heading("Keep-out zone"))
        form = _form()
        self.koz_type = type_combo()
        form.addRow("Vehicle type", self.koz_type)
        self.koz_pos = LatLngField()
        form.addRow("Centre", self.koz_pos)
        self.koz_radius = number_spin(1.0, 500.0, 15.0, 1)
        form.addRow("Radius", with_unit(self.koz_radius, "m"))
        panel.body.addLayout(form)
        panel.body.addWidget(self._send_button("Send keep-out zone", self._send_koz,
                                                common_pb2.TIER_ADVANCED))

        panel.body.addWidget(heading("All clear"))
        form = _form()
        self.clear_type = type_combo()
        form.addRow("Vehicle type", self.clear_type)
        panel.body.addLayout(form)
        panel.body.addWidget(self._send_button("Send all clear", self._send_all_clear,
                                                common_pb2.TIER_ADVANCED))
        panel.body.addStretch()
        return panel

    def _build_disruptive(self) -> Panel:
        panel = Panel("Disruptive · moving object")
        panel.body.addWidget(heading("Moving object alert"))
        form = _form()
        self.mo_pos = LatLngField()
        form.addRow("Object at", self.mo_pos)
        self.mo_heading = number_spin(0.0, 359.9, 0.0, 1)
        self.mo_heading.setWrapping(True)
        form.addRow("Heading", with_unit(self.mo_heading, "°"))
        self.mo_speed = number_spin(0.0, 20.0, 1.0, 2)
        form.addRow("Speed", with_unit(self.mo_speed, "m/s"))
        self.mo_radius = number_spin(0.5, 100.0, commands.DEFAULT_MOVING_KEEP_OUT_M, 1)
        self.mo_radius.setToolTip("Keep-out radius: affected vehicles must stay beyond this "
                                  "distance from the object (MovingObjectAlert.keep_out_radius_m)")
        form.addRow("Keep out", with_unit(self.mo_radius, "m"))
        affected = QHBoxLayout()
        affected.setSpacing(16)
        self.mo_types = {}
        for name in commands.VEHICLE_TYPES:
            box = QCheckBox(name)
            box.setChecked(name in ("USV", "UUV"))
            box.setCursor(Qt.PointingHandCursor)
            self.mo_types[name] = box
            affected.addWidget(box)
        affected.addStretch()
        form.addRow("Affects", affected)
        panel.body.addLayout(form)
        panel.body.addWidget(self._send_button("Send moving object alert", self._send_moving,
                                                common_pb2.TIER_DISRUPTIVE))
        panel.body.addStretch()
        return panel

    def _build_history(self) -> Panel:
        panel = Panel("Sent commands")
        self.history = QTableWidget(0, len(HISTORY_COLUMNS))
        self.history.setHorizontalHeaderLabels(HISTORY_COLUMNS)
        header = self.history.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.history.verticalHeader().setVisible(False)
        self.history.setEditTriggers(QTableWidget.NoEditTriggers)
        self.history.setSelectionMode(QAbstractItemView.NoSelection)
        self.history.setShowGrid(False)
        self.history.setMinimumHeight(140)
        panel.body.addWidget(self.history)
        return panel

    def _build_map(self) -> CourseMapWidget:
        self.map = IncidentMapCanvas()
        self.map_panel = CourseMapWidget(title="Incident map", canvas=self.map, clearable=False)
        self.map_panel.set_meta("pan to place · crosshair = position")
        self.map.center_changed.connect(self._on_map_center)
        return self.map_panel

    def _connect_previews(self) -> None:
        for field in self._position_fields():
            field.edited.connect(self._on_field_edited)
        for spin in (self.koz_radius, self.mo_radius, self.mo_heading, self.mo_speed):
            spin.valueChanged.connect(self._update_previews)
        for combo in (self.assist_type, self.koz_type):
            combo.currentTextChanged.connect(self._update_previews)
        for box in self.mo_types.values():
            box.toggled.connect(self._update_previews)

    def _position_fields(self):
        return (self.assist_pos, self.koz_pos, self.mo_pos)

    # ---------- map ----------
    def _on_map_center(self, lat: float, lng: float) -> None:
        """The map was panned: every tier's position follows its centre."""
        for field in self._position_fields():
            field.follow((lat, lng))
        self._update_previews()

    def _on_field_edited(self, lat: float, lng: float) -> None:
        """A position was typed (or set to the course centre): bring the map there."""
        self.map.set_center_latlng(lat, lng)
        self._update_previews()

    def previews(self):
        """Every tier's command as it would be sent; the declared tier's (or all, when
        none is declared) active, the others faint."""
        declared = self._declared_tier if self._declared_tier in TIER_LEVELS else None
        mo_radius, koz_radius = self.mo_radius.value(), self.koz_radius.value()
        types = "/".join(n for n, box in self.mo_types.items() if box.isChecked()) or "none"
        out = [
            Preview(self.assist_pos.value(), f"ASSIST {self.assist_type.currentText()}",
                    theme.INFO, active=declared in (None, common_pb2.TIER_CORE)),
            Preview(self.koz_pos.value(), f"KEEP-OUT {koz_radius:g} m · {self.koz_type.currentText()}",
                    theme.FAULT, radius_m=koz_radius,
                    active=declared in (None, common_pb2.TIER_ADVANCED)),
            Preview(self.mo_pos.value(), f"MOVING · {mo_radius:g} m · {types}", theme.WARN,
                    radius_m=mo_radius, heading_deg=self.mo_heading.value(),
                    speed_mps=self.mo_speed.value(),
                    active=declared in (None, common_pb2.TIER_DISRUPTIVE)),
        ]
        return out

    def _update_previews(self, *_args) -> None:
        if hasattr(self, "map"):
            self.map.set_previews(self.previews())

    # ---------- inputs from the window ----------
    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self._sync_buttons()

    def set_course(self, ring, center, course=None) -> None:
        """Course boundary for the position fields; ``course`` (RxCourse) for the map."""
        for field in self._position_fields():
            field.set_course(ring, center)
        if course is not None:
            self.map_panel.set_course(course)
        self._update_previews()

    def selected_team(self) -> Optional[str]:
        return self.team_combo.currentText() or None

    def refresh(self, fleet: FleetState, incidents: IncidentLog, next_seq,
                now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        self._sync_teams(fleet)
        team_id = self.selected_team()
        team = fleet.teams.get(team_id) if team_id else None
        self._show_team(fleet, team, now)
        self.seq_label.setText(f"next seq {next_seq(team_id)}" if team_id else "")
        self._fill_readiness(incidents, team_id)
        self._show_history(incidents, team_id)
        self.map_panel.show_fleet(fleet, team_id, now)

    def _sync_teams(self, fleet: FleetState) -> None:
        teams = fleet.team_ids()
        known = [self.team_combo.itemText(i) for i in range(self.team_combo.count())]
        if known == teams:
            return
        current = self.team_combo.currentText()
        self.team_combo.blockSignals(True)
        self.team_combo.clear()
        self.team_combo.addItems(teams)
        active = [t for t in teams if fleet.teams[t].run_state == "ACTIVE"]
        pick = current if current in teams else (active[0] if active else (teams[0] if teams else ""))
        self.team_combo.setCurrentText(pick)
        self.team_combo.blockSignals(False)
        self._sync_buttons()

    def _show_team(self, fleet: FleetState, team, now: float) -> None:
        if team is None:
            set_chip(self.run_chip, "NO TEAM", theme.IDLE)
            set_chip(self.tier_chip, "TASK 4 —", theme.IDLE)
            self.live_label.setText("No team on the broker yet.")
            self._declared_tier = None
            for panel in self._tier_panels:
                panel.set_meta("")
            self._sync_buttons()
            return
        state = team.run_state
        set_chip(self.run_chip, state, theme.OK if state == "ACTIVE" else theme.WARN)
        declared = team.tiers[3] if team.declaration_seq is not None else None
        tier = task_tier_name(declared) if declared is not None else "NOT DECLARED"
        set_chip(self.tier_chip, f"TASK 4 {tier}",
                 theme.INFO if declared is not None and declared >= common_pb2.TIER_CORE
                 else theme.IDLE)
        live = [f"{v.vehicle_id} {vehicle_type_name(v.vehicle_type)}"
                for v in fleet.vehicles_of(team.team_id)
                if v.age(now) is not None and v.age(now) <= STALE_SECONDS]
        self.live_label.setText("Live: " + (", ".join(live) if live else "none"))
        self._declared_tier = declared
        for panel, level in zip(self._tier_panels, TIER_LEVELS):
            panel.set_meta("declared" if declared == level else
                           f"not declared (Task 4 is {tier})")
        self._sync_buttons()
        vehicles = team.declared_vehicles or [v.vehicle_id for v in fleet.vehicles_of(team.team_id)]
        known = [self.confirm_vehicle.itemText(i) for i in range(self.confirm_vehicle.count())]
        if known != vehicles:
            text = self.confirm_vehicle.currentText()
            self.confirm_vehicle.clear()
            self.confirm_vehicle.addItems(vehicles)
            self.confirm_vehicle.setCurrentText(text or (vehicles[0] if vehicles else ""))

    def _fill_readiness(self, incidents: IncidentLog, team_id: Optional[str]) -> None:
        pending = incidents.pending_readiness(team_id) if team_id else None
        if pending is None:
            return
        key = (pending.team_id, pending.seq, pending.readiness)
        if key == self._filled_readiness:
            return
        self._filled_readiness = key
        vehicle, report_seq = pending.readiness
        self.confirm_vehicle.setCurrentText(vehicle)
        self.confirm_seq.setValue(report_seq)
        self.confirm_hint.setText(f"{vehicle} is ready for request seq={pending.seq}: "
                                  f"confirm report seq R={report_seq}.")
        self.confirm_hint.setStyleSheet(f"color: {theme.OK};")

    def _show_history(self, incidents: IncidentLog, team_id: Optional[str]) -> None:
        entries = incidents.entries(team_id)
        self.history.setRowCount(len(entries))
        for row, e in enumerate(entries):
            status = e.status
            values = [str(e.seq), time.strftime("%H:%M:%S", time.localtime(e.sent_at)),
                      e.kind, e.summary, status]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setFont(theme.mono_font(9.5))
                if col == 4:
                    fallback = theme.INFO if status.startswith("READY") else theme.OK
                    item.setForeground(theme.qcolor(STATUS_COLORS.get(status, fallback)))
                self.history.setItem(row, col, item)

    def _sync_buttons(self) -> None:
        """Every panel stays editable; send buttons work only when connected, for the
        declared tier."""
        for btn, level in self._send_buttons:
            reason = self._send_blocked(level)
            btn.setEnabled(not reason)
            btn.setToolTip(reason)
            btn.setStatusTip(reason)
        self._update_previews()

    def _send_blocked(self, level: int) -> str:
        """Why a send button of this tier can't send; empty when it can."""
        if not self._connected:
            return "Connect to the broker first"
        if not self.selected_team():
            return "No team selected"
        if self._declared_tier != level:
            return "Not this team's declared Task 4 tier (or its declaration was not seen)"
        return ""

    # ---------- senders ----------
    def _emit(self, body, summary: str) -> None:
        team_id = self.selected_team()
        if team_id:
            self.command_requested.emit(team_id, body, summary)

    @staticmethod
    def _where(field: LatLngField) -> str:
        lat, lng = field.value()
        return f"{lat:.9f}, {lng:.9f}"

    def _send_assist(self) -> None:
        vtype = self.assist_type.currentText()
        self._emit(commands.assistance_request(self.assist_pos.value(), vtype),
                   f"{vtype} to {self._where(self.assist_pos)}")

    def _send_confirm(self) -> None:
        vehicle = self.confirm_vehicle.currentText().strip()
        if vehicle:
            seq = self.confirm_seq.value()
            self._emit(commands.readiness_confirm(seq, vehicle), f"{vehicle} report seq R={seq}")

    def _send_koz(self) -> None:
        vtype, radius = self.koz_type.currentText(), self.koz_radius.value()
        self._emit(commands.keep_out_zone(self.koz_pos.value(), radius, vtype),
                   f"{vtype} r={radius:.1f} m at {self._where(self.koz_pos)}")

    def _send_all_clear(self) -> None:
        vtype = self.clear_type.currentText()
        self._emit(commands.all_clear(vtype), vtype)

    def _send_moving(self) -> None:
        types = [name for name, box in self.mo_types.items() if box.isChecked()]
        if not types:
            self.mo_types["USV"].setFocus()
            return
        heading_deg, speed = self.mo_heading.value(), self.mo_speed.value()
        radius = self.mo_radius.value()
        self._emit(commands.moving_object_alert(self.mo_pos.value(), heading_deg, speed, types,
                                                radius),
                   f"{'/'.join(types)} · {heading_deg:.0f}° {speed:.1f} m/s r={radius:.1f} m at "
                   f"{self._where(self.mo_pos)}")
