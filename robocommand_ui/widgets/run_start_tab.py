"""Run start tab: teams that declared a run, and the button that starts it.

Replaces ``rc run-start --team … --declaration-seq … --run-id …``. Each team
whose GCS sent a RunDeclaration is listed; pick one and press **Allow start**.
The declaration seq comes from the declaration itself, so it always matches.

**End run** closes an ACTIVE run on this host (the protocol has no run-end
message): the run log is saved and the team shows ENDED until its GCS sends
a new RunDeclaration, which then appears here as DECLARED.
"""

import time
from typing import List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QTableWidget,
    QTableWidgetItem, QWidget,
)

from robocommand_ui import theme
from robocommand_ui.fleet_state import STALE_SECONDS, FleetState, TeamState
from robocommand_ui.proto_helper import task_tier_name
from robocommand_ui.widgets.form import button, caption, int_spin
from robocommand_ui.widgets.panel import Panel
from robocommand_ui.widgets.teams_panel import RUN_COLORS

COLUMNS = ["Team", "State", "Decl seq", "Vehicles", "Live", "Tiers T1–T4", "Run ID"]
STATE_ORDER = {"DECLARED": 0, "DECL MISMATCH": 1, "ACTIVE": 2, "ENDED": 3}
NEW_RUN_HINT = ("Waiting for the team's new RunDeclaration. nala2-report GCS: "
                "ros2 service call /nala2_report/new_run std_srvs/srv/Trigger")
MAX_RUN_ID = 1_000_000


def requesting_teams(fleet: FleetState) -> List[TeamState]:
    """Teams that declared a run: waiting ones first, then the rest by name."""
    teams = [t for t in fleet.teams.values()
             if t.declaration_seq is not None or t.run_id is not None or t.ended]
    return sorted(teams, key=lambda t: (STATE_ORDER.get(t.run_state, 3), t.team_id))


class RunStartTab(QWidget):
    start_requested = pyqtSignal(str, int, int)     # team_id, declaration_seq, run_id
    end_requested = pyqtSignal(str)                 # team_id
    reset_requested = pyqtSignal(str)               # team_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._teams = {}
        self._connected = False
        self._run_id_for = None         # (team, declaration seq) the run id was suggested for

        row = QHBoxLayout(self)
        row.setContentsMargins(20, 16, 20, 16)
        row.setSpacing(16)
        row.addWidget(self._build_list(), 3)
        row.addWidget(self._build_action(), 2)
        self._sync_action()

    def _build_list(self) -> Panel:
        panel = Panel("Run start requests")
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        self.table.itemSelectionChanged.connect(self._sync_action)
        panel.body.addWidget(self.table, 1)
        self.empty = QLabel("No team has declared a run yet.\n"
                            "A team appears here when its GCS sends a RunDeclaration.")
        self.empty.setObjectName("Empty")
        self.empty.setAlignment(Qt.AlignCenter)
        panel.body.addWidget(self.empty, 1)
        return panel

    def _build_action(self) -> Panel:
        panel = Panel("Allow start")
        self.selected_label = QLabel("Select a team from the list")
        self.selected_label.setObjectName("FormHeading")
        panel.body.addWidget(self.selected_label)
        self.detail = caption("")
        panel.body.addWidget(self.detail)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        self.run_id = int_spin(1, MAX_RUN_ID, 1)
        self.run_id.setToolTip("Run number the GCS records (RunStart.run_id)")
        form.addRow("Run ID", self.run_id)
        panel.body.addLayout(form)

        self.start_btn = button("Allow start", "Primary",
                                "Send RunStart with this team's declaration seq")
        self.start_btn.setMinimumHeight(36)
        self.start_btn.clicked.connect(self._on_start)
        panel.body.addWidget(self.start_btn)
        self.end_btn = button("End run", "Danger",
                              "End this team's run on the host: save the run log and wait "
                              "for the team's next RunDeclaration")
        self.end_btn.clicked.connect(self._on_end)
        panel.body.addWidget(self.end_btn)
        panel.body.addWidget(caption(
            "Check before starting: vehicles LIVE, tiers as briefed, and the UAV geofence "
            "inside the course on the Map tab."))
        panel.body.addStretch()
        self.reset_btn = button("Reset run ID && seq", "Ghost",
                                "Suggest Run ID 1 and restart this team's command seq at 1")
        self.reset_btn.clicked.connect(self._on_reset)
        panel.body.addWidget(self.reset_btn)
        panel.body.addWidget(caption(
            "Only between runs (DECLARED or ENDED): the GCS drops a repeated seq as a duplicate "
            "until the team declares a new run."))
        return panel

    # ---------- state ----------
    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self._sync_action()

    def selected_team(self) -> Optional[str]:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return item.text() if item else None

    def select_team(self, team_id: str) -> None:
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).text() == team_id:
                self.table.selectRow(row)
                return

    def refresh(self, fleet: FleetState, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        selected = self.selected_team()
        teams = requesting_teams(fleet)
        self._teams = {t.team_id: t for t in teams}

        self.table.blockSignals(True)
        self.table.setRowCount(len(teams))
        for row, team in enumerate(teams):
            tracks = fleet.vehicles_of(team.team_id)
            live = sum(1 for v in tracks if v.age(now) is not None and v.age(now) <= STALE_SECONDS)
            values = [
                team.team_id,
                team.run_state,
                "—" if team.declaration_seq is None else str(team.declaration_seq),
                ", ".join(team.declared_vehicles) or "—",
                f"{live}/{len(team.declared_vehicles) or len(tracks)}",
                " ".join(task_tier_name(t)[:3] for t in team.tiers),
                "—" if team.run_id is None else str(team.run_id),
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setFont(theme.ui_font(10, 700) if col in (0, 1) else theme.mono_font(9.5))
                if col == 1:
                    item.setForeground(theme.qcolor(RUN_COLORS.get(text, theme.TEXT)))
                self.table.setItem(row, col, item)
        self.table.clearSelection()
        if selected in self._teams:
            self.select_team(selected)
        elif selected is None and teams and teams[0].run_state == "DECLARED":
            self.select_team(teams[0].team_id)      # the team waiting to start
        self.table.blockSignals(False)

        self.table.setVisible(bool(teams))
        self.empty.setVisible(not teams)
        self._sync_action()

    def _sync_action(self) -> None:
        team_id = self.selected_team()
        team = self._teams.get(team_id) if team_id else None
        if team is None:
            self.selected_label.setText("Select a team from the list")
            self.detail.setText("")
            self.start_btn.setEnabled(False)
            self.end_btn.setEnabled(False)
            self.reset_btn.setEnabled(False)
            self._run_id_for = None
            return
        key = (team_id, team.declaration_seq, team.last_run_id)     # new team, run request or end
        if key != self._run_id_for:
            self.run_id.setValue((team.run_id or team.last_run_id or 0) + 1)
            self._run_id_for = key
        state = team.run_state
        self.end_btn.setEnabled(team.run_id is not None)
        self.reset_btn.setEnabled(team.run_id is None)
        if state == "ENDED":
            self.selected_label.setText(f"{team_id} · ENDED (run {team.last_run_id})")
            self.detail.setText(NEW_RUN_HINT)
            self.start_btn.setText("Allow start")
            self.start_btn.setEnabled(False)
            return
        self.selected_label.setText(f"{team_id} · {state}")
        self.detail.setText(
            f"Declaration seq {team.declaration_seq}  ·  vehicles "
            f"{', '.join(team.declared_vehicles) or '—'}"
            + ("" if self._connected else "\nConnect to the broker to send."))
        self.start_btn.setText("Restart run" if state == "ACTIVE" else "Allow start")
        self.start_btn.setEnabled(self._connected and team.declaration_seq is not None)

    def _on_reset(self) -> None:
        team_id = self.selected_team()
        if team_id:
            self.reset_requested.emit(team_id)
            self._run_id_for = None         # re-suggest the Run ID from the reset counters

    def _on_end(self) -> None:
        team_id = self.selected_team()
        if team_id:
            self.end_requested.emit(team_id)

    def _on_start(self) -> None:
        team_id = self.selected_team()
        team = self._teams.get(team_id) if team_id else None
        if team is not None and team.declaration_seq is not None:
            self.start_requested.emit(team_id, team.declaration_seq, self.run_id.value())
