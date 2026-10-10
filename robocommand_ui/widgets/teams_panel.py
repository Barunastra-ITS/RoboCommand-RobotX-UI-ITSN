"""Per-team run status as seen by the RoboCommand host.

One row per team on the broker: run state (IDLE / DECLARED / ACTIVE / DECL
MISMATCH), declaration seq, declared vs reporting vehicles, task tiers,
run_id, and the latest request/command sequence numbers.
"""

import time
from typing import Optional

from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QGroupBox, QHeaderView, QTableWidget, QTableWidgetItem, QVBoxLayout

from robocommand_ui.fleet_state import FleetState
from robocommand_ui.proto_helper import task_tier_name
from robocommand_ui.widgets.vehicle_monitor import STALE_SECONDS

RUN_COLORS = {
    "IDLE": "#6c7086",
    "DECLARED": "#f9e2af",
    "ACTIVE": "#a6e3a1",
    "DECL MISMATCH": "#f38ba8",
}
COLUMNS = ["Team", "Run", "Decl seq", "Vehicles (live/declared)", "Tiers T1-T4",
           "run_id", "Req seq", "Cmd seq"]


class TeamsPanel(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Teams on this course", parent)
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 6px;
                margin-top: 8px;
                padding: 12px 8px 8px 8px;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
            QTableWidget { background-color: #1e1e2e; color: #cdd6f4; gridline-color: #45475a; }
            QHeaderView::section {
                background-color: #313244; color: #cdd6f4; font-weight: bold;
                border: 1px solid #45475a;
            }
        """)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setMaximumHeight(150)
        layout.addWidget(self.table)

    def refresh(self, fleet: FleetState, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        team_ids = fleet.team_ids()
        self.table.setRowCount(len(team_ids))
        for row, tid in enumerate(team_ids):
            team = fleet.teams[tid]
            tracks = fleet.vehicles_of(tid)
            live = sum(1 for v in tracks
                       if v.age(now) is not None and v.age(now) <= STALE_SECONDS)
            declared = len(team.declared_vehicles)
            tiers = "/".join(task_tier_name(t) for t in team.tiers) if team.declaration_seq else "---"
            values = [
                tid,
                team.run_state,
                "---" if team.declaration_seq is None else str(team.declaration_seq),
                f"{live}/{declared}" if declared else f"{live}/-",
                tiers,
                "---" if team.run_id is None else str(team.run_id),
                str(team.last_request_seq),
                str(team.last_command_seq),
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col == 1:
                    item.setForeground(QColor(RUN_COLORS.get(text, "#cdd6f4")))
                self.table.setItem(row, col, item)

    def row_text(self, team_id: str) -> Optional[list]:
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).text() == team_id:
                return [self.table.item(row, c).text() for c in range(self.table.columnCount())]
        return None
